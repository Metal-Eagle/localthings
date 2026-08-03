"""Config flow for Local Things integration."""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import re
import selectors
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CLIENTHELLO_PROBE_RETRIES,
    CLIENTHELLO_PROBE_TIMEOUT_S,
    CONF_BYPASS_REMOTE_CONTROL,
    CONF_CA_CERT_PEM,
    CONF_CA_KEY_PEM,
    CONF_DEVICE_TYPE,
    CONF_FINISH_TIME_HYSTERESIS_MINUTES,
    CONF_HOST,
    CONF_LEAF_CERT_PEM,
    CONF_LEAF_KEY_PEM,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_PORT,
    CONF_SERIAL,
    DEFAULT_FINISH_TIME_HYSTERESIS_MINUTES,
    DOMAIN,
    LIVENESS_PROBE_TIMEOUT_S,
    PREFERRED_PROBE_PORTS,
    PROBE_GET_TIMEOUT_S,
    PROBE_MAX_WORKERS,
    PROBE_PORT_RANGE,
)

_TEXT = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
_MULTILINE = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True))
_HYSTERESIS_MINUTES = NumberSelector(
    NumberSelectorConfig(
        min=0,
        max=30,
        step=1,
        mode=NumberSelectorMode.BOX,
    )
)

_LOGGER = logging.getLogger(__name__)

_SAMSUNG_CLOUD_HOST = "connect-v2.samsungiotcloud.com"


class CannotConnect(Exception):
    pass


class InvalidCA(Exception):
    pass


def _fetch_samsung_uuid() -> str:
    """Connect to Samsung's cloud gateway and extract the UUID from its TLS cert.

    Verification is disabled because Samsung's chain contains a self-signed cert.
    We only need to read the UUID from the cert subject, not verify its trust.
    """
    from cryptography import x509 as _x509

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection((_SAMSUNG_CLOUD_HOST, 443), timeout=15) as raw,
        ctx.wrap_socket(raw, server_hostname=_SAMSUNG_CLOUD_HOST) as tls,
    ):
        der = tls.getpeercert(binary_form=True)
    if der is None:
        raise RuntimeError(f"No certificate received from {_SAMSUNG_CLOUD_HOST}")
    cert = _x509.load_der_x509_certificate(der)
    for attr in cert.subject:
        if attr.oid == _x509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME and isinstance(attr.value, str):
            m = re.search(r"uuid:([0-9a-f-]+)", attr.value, re.IGNORECASE)
            if m:
                return m.group(1)
    raise RuntimeError(f"UUID not found in {_SAMSUNG_CLOUD_HOST} certificate subject")


def _mint_leaf_cert(ca_cert_pem: str, ca_key_pem: str, uuid: str) -> tuple[str, str]:
    """Mint a fresh RSA-2048 leaf cert signed by the CA.

    Returns (fullchain_pem, leaf_key_pem) where fullchain_pem is the leaf cert
    followed by the full CA PEM, suitable for use_certificate_chain_file.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    from cryptography.x509.oid import NameOID

    m = re.search(
        r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)",
        ca_cert_pem,
        re.DOTALL,
    )
    if not m:
        raise InvalidCA("No certificate found in CA cert PEM")
    try:
        ca_cert = x509.load_pem_x509_certificate(m.group(1).encode())
        ca_key = serialization.load_pem_private_key(ca_key_pem.encode(), password=None)
    except Exception as exc:
        raise InvalidCA(f"Failed to load CA credentials: {exc}") from exc
    if not isinstance(
        ca_key,
        (
            _rsa.RSAPrivateKey,
            ec.EllipticCurvePrivateKey,
            ed25519.Ed25519PrivateKey,
            ed448.Ed448PrivateKey,
            dsa.DSAPrivateKey,
        ),
    ):
        raise InvalidCA(f"CA key is not a signing key (got {type(ca_key).__name__})")

    leaf_key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)

    now = datetime.datetime.now(datetime.UTC)
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COUNTRY_NAME, "KR"),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Samsung Electronics"),
                    x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, f"uuid:{uuid}"),
                    x509.NameAttribute(NameOID.COMMON_NAME, f"urn:uuid:{uuid}"),
                ]
            )
        )
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=10 * 365))
        .sign(ca_key, hashes.SHA256())
    )

    leaf_cert_pem = leaf_cert.public_bytes(serialization.Encoding.PEM).decode()
    leaf_key_pem = leaf_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    # Ensure a newline separates the leaf and CA blocks regardless of
    # whether the user's pasted CA PEM had a trailing newline.
    fullchain_pem = leaf_cert_pem.rstrip("\n") + "\n" + ca_cert_pem
    if not fullchain_pem.endswith("\n"):
        fullchain_pem += "\n"
    return fullchain_pem, leaf_key_pem


def _order_candidates(ports: list[int]) -> list[int]:
    """Order live ports so the historically known DTLS ports are tried first."""
    preferred = [p for p in PREFERRED_PROBE_PORTS if p in ports]
    rest = sorted(p for p in ports if p not in PREFERRED_PROBE_PORTS)
    return preferred + rest


def _find_live_ports(host: str, ports: list[int], timeout: float) -> list[int]:
    """Fast UDP liveness sweep to narrow the range before the DTLS handshake.

    UDP is connectionless, but a *connected* UDP socket surfaces the ICMP
    port-unreachable that a closed port returns as ECONNREFUSED on its next
    recv. So we send one probe datagram per port and watch for that error:

      * ECONNREFUSED       -> port is closed (device actively rejected it)
      * silence / any data -> port may be live (open|filtered); a candidate

    This is the in-process equivalent of ``nmap -sU``: it lets us take a
    nine-port range down to the one or two ports actually worth a full DTLS
    handshake + /device/0 GET, and bounds the total wait to ``timeout``
    instead of stalling on every dead port when a firewall swallows the ICMP
    replies.
    """
    sockets: dict[int, socket.socket] = {}
    sel = selectors.DefaultSelector()
    # A single byte is enough to provoke an ICMP port-unreach from a closed
    # port; a real DTLS ClientHello is unnecessary just to test for life.
    probe = b"\x00"
    try:
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            try:
                sock.connect((host, port))
                sock.send(probe)
            except OSError:
                sock.close()
                continue
            sockets[port] = sock
            sel.register(sock, selectors.EVENT_READ, port)

        # Ports drop out of the selector as they refuse; whatever is still
        # registered when the deadline passes is silent-but-live (a candidate).
        deadline = time.monotonic() + timeout
        while sel.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            for key, _ in sel.select(timeout=remaining):
                sock = sockets[key.data]
                try:
                    # Data back means live; ECONNREFUSED (or any other socket
                    # error) means the port is closed/unusable — rule it out.
                    sock.recv(1)
                except OSError:
                    sel.unregister(sock)
        live = [key.data for key in sel.get_map().values()]
    finally:
        sel.close()
        for sock in sockets.values():
            with contextlib.suppress(OSError):
                sock.close()

    # The sweep's ICMP-based verdict isn't reliable on every network path --
    # issue #192 captured a segregated-VLAN device where it called three
    # ports live that a concurrent nmap scan showed as closed, while the
    # port nmap found genuinely open|filtered (49154, one of our historically
    # confirmed ports) never showed up as live at all. Rather than trust a
    # wrong "not live" verdict on a port we already have strong prior
    # evidence for, always give the historically-confirmed ports a real
    # handshake attempt too. Bounded cost: at most len(PREFERRED_PROBE_PORTS)
    # extra handshakes, only when the sweep disagrees with the prior.
    rescued = [p for p in PREFERRED_PROBE_PORTS if p in ports and p not in live]
    return _order_candidates(live + rescued)


@dataclass(frozen=True)
class _PortScan:
    """The result of the port-detection pass: which ports to hand a full DTLS
    handshake, and whether a DTLS server was actually *proven* to be on one of
    them (as opposed to merely not ruled out)."""

    candidates: list[int]
    confirmed: bool


def _clienthello_probe(host: str, port: int):
    """One stateless DTLS ClientHello against `host:port`.

    Imported lazily so an install whose smartthings-local predates the probe
    (< 0.1.2) degrades to the UDP sweep at scan time rather than failing to
    load the config flow at all.
    """
    from smartthings_local.protocol.dtls_probe import probe

    return probe(
        host,
        port,
        stateless=True,
        timeout=CLIENTHELLO_PROBE_TIMEOUT_S,
        retries=CLIENTHELLO_PROBE_RETRIES,
    )


def _clienthello_scan(host: str, ports: list[int]) -> list[int]:
    """Ports on `host` that answered a DTLS ClientHello -- i.e. ports a real
    DTLS server is listening on (issue #211).

    smartthings-local's stateless probe sends one ClientHello and stops the
    moment the server proves itself with a HelloVerifyRequest, which per RFC
    6347 §4.2.1 the server answers *without* allocating association state. So
    this identifies the device's real port in ~1 RTT, leaves nothing behind on
    the appliance, and costs it far less than the alternative of throwing N
    full certificate handshakes at it to find out.

    The whole range goes out at once. That's safe in a way racing real
    handshakes is not: each probe is bounded by CLIENTHELLO_PROBE_TIMEOUT_S
    rather than DtlsCoapSession's 12s handshake timeout, so the pool's
    shutdown-and-wait on exit costs one probe's budget, not the sum of the
    range -- no `shutdown(wait=False)` and no losing threads left running
    behind us.
    """
    with ThreadPoolExecutor(max_workers=min(len(ports), PROBE_MAX_WORKERS)) as ex:
        results = list(ex.map(lambda port: _clienthello_probe(host, port), ports))

    live = []
    for result in results:
        if result.is_dtls_server:
            live.append(result.port)
            _LOGGER.debug("DTLS server on %s:%d (%s)", host, result.port, result)
    return _order_candidates(live)


def _scan_ports(host: str) -> _PortScan:
    """Find the device's DTLS port, preferring proof over absence of evidence.

    The ClientHello probe is authoritative when it finds something: a port
    that answered one is running a DTLS server, so exactly one port gets the
    expensive certificate handshake instead of every port the old UDP sweep
    couldn't rule out (each of which cost a full 12s handshake timeout --
    issue #211's 30-40s adds).

    It stays a *gate*, not a replacement: when it confirms nothing we fall
    back to the ICMP-based sweep, which is wrong in the opposite direction
    (it reports everything it can't rule out) and so still surfaces a device
    the probe couldn't reach -- e.g. a network path that drops our
    ClientHello outright, or an install still on smartthings-local < 0.1.2.
    Issue #192's segregated-VLAN device is the reason that fallback keeps its
    own preferred-port rescue.
    """
    try:
        confirmed = _clienthello_scan(host, PROBE_PORT_RANGE)
    except Exception as exc:
        _LOGGER.debug("ClientHello probe unavailable (%s); falling back to UDP sweep", exc)
        confirmed = []
    if confirmed:
        _LOGGER.debug("DTLS port(s) confirmed on %s: %s", host, confirmed)
        return _PortScan(confirmed, True)

    candidates = _find_live_ports(host, PROBE_PORT_RANGE, LIVENESS_PROBE_TIMEOUT_S)
    # No early "every port refused" fast-fail here: _find_live_ports always
    # rescues PREFERRED_PROBE_PORTS (issue #192), so candidates is never
    # empty as long as that table is non-empty and within PROBE_PORT_RANGE --
    # both true today, which made this branch permanently unreachable. A
    # genuinely dead host fails in _handshake_and_read instead, whose error
    # carries the actual per-port timeout/refusal reason rather than a generic
    # "no live port found" message.
    _LOGGER.debug("No DTLS server confirmed on %s; sweep candidates: %s", host, candidates)
    return _PortScan(candidates, False)


class _HandshakeFailed(CannotConnect):
    """No candidate port completed a handshake.

    `cert_rejected` is True when every attempt failed with a ConnectionError
    -- the library's error for a handshake the peer actively broke off (a
    fatal alert), as opposed to the TimeoutError it raises when nothing
    answered at all. It's the signal for retrying with freshly-minted
    credentials; see _probe_and_validate.
    """

    def __init__(self, message: str, cert_rejected: bool) -> None:
        super().__init__(message)
        self.cert_rejected = cert_rejected


def _mint_credentials(ca_cert_pem: str, ca_key_pem: str) -> tuple[str, str]:
    """Fetch the current UUID from Samsung's cloud and mint a leaf cert for it."""
    _LOGGER.debug("Fetching Samsung cloud UUID from %s", _SAMSUNG_CLOUD_HOST)
    try:
        uuid = _fetch_samsung_uuid()
    except Exception as exc:
        _LOGGER.debug("UUID fetch failed: %s", exc, exc_info=True)
        raise CannotConnect(f"Failed to fetch Samsung UUID: {exc}") from exc
    _LOGGER.debug("Got UUID: %s", uuid)

    _LOGGER.debug("Minting leaf cert for UUID %s", uuid)
    try:
        fullchain_pem, leaf_key_pem = _mint_leaf_cert(ca_cert_pem, ca_key_pem, uuid)
    except InvalidCA:
        _LOGGER.debug("CA credentials invalid", exc_info=True)
        raise
    except Exception as exc:
        _LOGGER.debug("Leaf cert minting failed: %s", exc, exc_info=True)
        raise CannotConnect(f"Failed to mint leaf cert: {exc}") from exc
    _LOGGER.debug("Leaf cert minted successfully")
    return fullchain_pem, leaf_key_pem


def _read_device(sess, host: str, port: int) -> dict:
    """Resolve this device's identity over an already-connected session.

    /oic/d before /device/0, deliberately: the device's own OCF device-type
    declaration is the primary detection signal when a board populates it
    (see registry/by_type's resolve()), and read_identity's three small GETs
    settle it long before the blockwise /device/0 dump lands. read_identity is
    defensive on every GET it makes, so a device that answers neither /oic/p
    nor /oic/d just yields an empty device_types tuple and detection falls
    through to the model-string/resource-signature path.

    Everything the entry needs to name and key the device comes from here --
    resolved serial, model, manufacturer, device type -- so the coordinator
    never has to mint a registry key from a placeholder (issue #236).
    """
    import cbor2

    from .registry.batch import parse_device0_batch
    from .registry.by_type import resolve as resolve_registry
    from .registry.identity import read_identity, resolve_serial

    identity = read_identity(sess, None)

    code, payload = sess.get(["device", "0"], timeout=PROBE_GET_TIMEOUT_S)
    if code != 0x45 or not payload:
        raise CannotConnect(f"port {port}: unexpected code {code:#04x}")
    body = cbor2.loads(payload)
    resources = parse_device0_batch(body) if isinstance(body, list) else {}

    info = resources.get("/information/vs/0", {})
    model_num = info.get("x.com.samsung.da.modelNum", "")
    registry = resolve_registry(resources, device_types=identity.device_types)
    return {
        "port": port,
        "serial": resolve_serial(info.get("x.com.samsung.da.serialNum"), host),
        # Same derivation _run_discovery uses, so the device the coordinator
        # registers up front is the one discovery would have produced.
        "model": model_num.split("|", 1)[0] if model_num else identity.model,
        "manufacturer": identity.manufacturer or "Samsung",
        "device_type_name": registry.name if registry is not None else None,
        "device_type_recognized": registry is not None,
    }


def _handshake_and_read(host: str, candidates: list[int], cert_pem: str, key_pem: str) -> dict:
    """Handshake each candidate in turn, returning the first device that answers."""
    from smartthings_local.protocol.dtls_session import DtlsCoapSession

    last_exc: Exception | None = None
    rejected_only = True
    for port in candidates:
        sess = None
        try:
            sess = DtlsCoapSession(host, port, cert_pem=cert_pem, key_pem=key_pem)
            sess.connect()
            sess.start_reader()
            return _read_device(sess, host, port)
        except CannotConnect:
            # The device answered, just not with something we can use --
            # trying the remaining ports can't improve on that.
            raise
        except Exception as exc:
            last_exc = exc
            rejected_only = rejected_only and isinstance(exc, ConnectionError)
            _LOGGER.debug("port %d failed: %s", port, exc)
        finally:
            if sess is not None:
                with contextlib.suppress(Exception):
                    sess.close()
    raise _HandshakeFailed(
        f"no port responded on {host}: {last_exc}",
        cert_rejected=rejected_only and last_exc is not None,
    )


def _probe_and_validate(
    host: str,
    ca_cert_pem: str,
    ca_key_pem: str,
    existing_leaf: tuple[str, str] | None = None,
) -> dict:
    """Find the device's port, authenticate to it, and resolve its identity.

    Port detection runs first and needs no credentials at all, so an
    unreachable host fails here rather than after a round trip to Samsung's
    cloud.

    `existing_leaf` is another entry's already-minted leaf (issue #211).
    Every appliance accepts the same leaf -- CA `AC14K_M` plus the UUID from
    Samsung's cloud cert -- so adding a second device can skip the fetch and
    mint entirely, which makes it independent of Samsung-cloud reachability
    rather than merely faster. If that reused leaf turns out to be stale (the
    UUID does rotate), a confirmed-live device rejecting it is unambiguous
    enough to re-mint and try once more, so the reuse stays self-correcting.
    """
    scan = _scan_ports(host)

    if existing_leaf is not None:
        cert_pem, key_pem = existing_leaf
        _LOGGER.debug("Reusing the leaf certificate from an existing entry")
    else:
        cert_pem, key_pem = _mint_credentials(ca_cert_pem, ca_key_pem)

    try:
        info = _handshake_and_read(host, scan.candidates, cert_pem, key_pem)
    except _HandshakeFailed as exc:
        # Only the reused-leaf case is worth a second pass, and only when the
        # device proved it is there and broke the handshake off itself: a
        # timeout means nothing answered, which a fresh cert won't change.
        if existing_leaf is None or not (scan.confirmed and exc.cert_rejected):
            raise
        _LOGGER.debug("Reused leaf rejected by %s; re-minting and retrying", host)
        cert_pem, key_pem = _mint_credentials(ca_cert_pem, ca_key_pem)
        info = _handshake_and_read(host, scan.candidates, cert_pem, key_pem)

    return {**info, "leaf_cert_pem": cert_pem, "leaf_key_pem": key_pem}


class LocalThingsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._host: str = ""
        self._ca_cert_pem: str = ""
        self._ca_key_pem: str = ""
        self._pending_info: dict | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LocalThingsOptionsFlow:
        return LocalThingsOptionsFlow()

    def _create_entry(self, info: dict) -> ConfigFlowResult:
        """Persist everything the probe resolved, identity included.

        The identity fields are not decoration: the coordinator seeds
        `device_serial` and its DeviceInfo from them at construction time, so
        entity unique_ids and device identifiers are correct from the very
        first entity that registers -- even if the first poll is slow, or
        fails outright (issue #236).
        """
        from .registry.identity import device_display_name

        return self.async_create_entry(
            title=f"{device_display_name(info['device_type_name'], '')} ({self._host})",
            data={
                CONF_HOST: self._host,
                CONF_PORT: info["port"],
                CONF_CA_CERT_PEM: self._ca_cert_pem,
                CONF_CA_KEY_PEM: self._ca_key_pem,
                CONF_LEAF_CERT_PEM: info["leaf_cert_pem"],
                CONF_LEAF_KEY_PEM: info["leaf_key_pem"],
                CONF_SERIAL: info["serial"],
                CONF_MODEL: info["model"],
                CONF_MANUFACTURER: info["manufacturer"],
                CONF_DEVICE_TYPE: info["device_type_name"],
            },
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        existing = self.hass.config_entries.async_entries(DOMAIN)
        has_creds = bool(existing)

        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            existing_leaf = None
            if has_creds:
                self._ca_cert_pem = existing[0].data[CONF_CA_CERT_PEM]
                self._ca_key_pem = existing[0].data[CONF_CA_KEY_PEM]
                leaf_cert = existing[0].data.get(CONF_LEAF_CERT_PEM)
                leaf_key = existing[0].data.get(CONF_LEAF_KEY_PEM)
                if leaf_cert and leaf_key:
                    existing_leaf = (leaf_cert, leaf_key)
            else:
                self._ca_cert_pem = user_input[CONF_CA_CERT_PEM].strip()
                self._ca_key_pem = user_input[CONF_CA_KEY_PEM].strip()

            try:
                info = await self.hass.async_add_executor_job(
                    _probe_and_validate,
                    self._host,
                    self._ca_cert_pem,
                    self._ca_key_pem,
                    existing_leaf,
                )
            except InvalidCA:
                errors["base"] = "invalid_ca"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during device probe")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"localthings_{info['serial']}")
                self._abort_if_unique_id_configured()
                if info["device_type_recognized"]:
                    return self._create_entry(info)
                self._pending_info = info
                return await self.async_step_confirm_unknown_type()

        if has_creds:
            schema = vol.Schema({vol.Required(CONF_HOST): _TEXT})
            step_id = "user_reuse"
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_HOST): _TEXT,
                    vol.Required(CONF_CA_CERT_PEM): _MULTILINE,
                    vol.Required(CONF_CA_KEY_PEM): _MULTILINE,
                }
            )
            step_id = "user"

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
        )

    async def async_step_user_reuse(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the localized host-only form for additional appliances."""
        return await self.async_step_user(user_input)

    async def async_step_confirm_unknown_type(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Shown only when the probe already knows the device type is unrecognized."""
        info = self._pending_info or {}
        if user_input is not None:
            assert self._pending_info is not None
            return self._create_entry(self._pending_info)
        return self.async_show_form(
            step_id="confirm_unknown_type",
            data_schema=vol.Schema({}),
            # The probe already knows the board string detection failed on;
            # showing it here means a user filing the device-support issue
            # this step asks for can quote it without digging through logs.
            description_placeholders={"model": info.get("model") or "unknown"},
        )


class LocalThingsOptionsFlow(config_entries.OptionsFlow):
    """Per-device options: the remote-control-off write-block override
    (issue #54) plus a debug panel for writing an arbitrary body to an
    arbitrary resource href, so a user can pin down device-specific write
    behavior without waiting on a new release.

    The remote-control override exists because most devices reject writes
    outright while remote control is off and a clear error beats a silent
    device-side rejection -- but not every model actually enforces that,
    so this lets a user who's confirmed their device accepts writes anyway
    turn the block off for just that device rather than it being
    hardcoded on for everyone. The debug panel goes further: it bypasses
    that block (and every write_fn/validate_fn) entirely, sending exactly
    the body the user types to whatever href they pick.
    """

    def __init__(self) -> None:
        self._debug_href: str = ""
        self._debug_result: tuple[int, dict] | None = None

    def _coordinator(self):
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "debug_write"],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BYPASS_REMOTE_CONTROL,
                        default=self.config_entry.options.get(CONF_BYPASS_REMOTE_CONTROL, False),
                    ): bool,
                    vol.Required(
                        CONF_FINISH_TIME_HYSTERESIS_MINUTES,
                        default=self.config_entry.options.get(
                            CONF_FINISH_TIME_HYSTERESIS_MINUTES,
                            DEFAULT_FINISH_TIME_HYSTERESIS_MINUTES,
                        ),
                    ): _HYSTERESIS_MINUTES,
                }
            ),
        )

    async def async_step_debug_write(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        coord = self._coordinator()
        if coord is None:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            self._debug_href = user_input["href"]
            return await self.async_step_debug_edit()

        hrefs = sorted(coord.last_resources.keys())
        return self.async_show_form(
            step_id="debug_write",
            data_schema=vol.Schema(
                {
                    vol.Required("href"): SelectSelector(
                        SelectSelectorConfig(
                            options=hrefs,
                            custom_value=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    def _show_debug_edit_form(
        self,
        href: str,
        current: dict,
        errors: dict[str, str],
        payload,
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="debug_edit",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "payload",
                        default=(payload if payload is not None else {}),
                    ): ObjectSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "href": href,
                "current_value": (
                    json.dumps(current, indent=2, ensure_ascii=False) if current else "{}"
                ),
            },
        )

    async def async_step_debug_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        coord = self._coordinator()
        if coord is None:
            return self.async_abort(reason="not_loaded")

        href = self._debug_href
        current = coord.resource(href)

        if user_input is not None:
            payload = user_input.get("payload") or {}
            if not isinstance(payload, dict) or not payload:
                return self._show_debug_edit_form(
                    href, current, {"payload": "empty_payload"}, payload
                )
            try:
                code, new_rep = await coord.async_raw_write(href, payload)
            except Exception:
                _LOGGER.exception("debug raw write failed for %s", href)
                return self._show_debug_edit_form(href, current, {"base": "write_failed"}, payload)
            self._debug_result = (code, new_rep)
            return await self.async_step_debug_result()

        return self._show_debug_edit_form(href, current, {}, None)

    async def async_step_debug_result(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        code, new_rep = self._debug_result or (0, {})
        return self.async_show_menu(
            step_id="debug_result",
            menu_options=["debug_write", "finish"],
            description_placeholders={
                "code": f"{code >> 5}.{code & 0x1F:02d} ({code:#04x})",
                "new_value": (
                    json.dumps(new_rep, indent=2, ensure_ascii=False) if new_rep else "{}"
                ),
            },
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Close the flow without altering saved options.
        return self.async_create_entry(data=dict(self.config_entry.options))
