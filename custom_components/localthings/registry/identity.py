"""Read device identity from standard OCF resources (/oic/p, /oic/d, /oic/res)."""

from __future__ import annotations

from dataclasses import dataclass, field

import cbor2


@dataclass(frozen=True)
class DeviceIdentity:
    manufacturer: str
    model: str
    name: str
    serial: str | None
    device_types: tuple[str, ...] = ()
    raw: dict[str, dict | list] = field(default_factory=dict)


def is_placeholder_serial(serial: str) -> bool:
    """True for a non-empty serialNum that isn't actually a real identity.

    The ARTIK051_DONGLE_REF firmware family reports the literal string
    'Nothing(SVC)' for every unit -- non-empty, so a plain `if not serial`
    check doesn't catch it, and the resolved serial feeds both the HA
    device-registry identifier and every entity's unique_id (entity.py), so
    two such units on the same install silently collide and the second one's
    entities get dropped (issue #83).

    Issue #189: the DA_WM_A51_20_COMMON (ARTIK051) laundry board family
    reports a flash-unset sentinel instead -- every character the same
    repeated hex digit (a washer and a dryer, two different physical units,
    both reported the literal serialNum 'FFFFFFFFFFFFFFF') -- which the
    'nothing' check above doesn't catch either, so the second unit's config
    flow aborted as already configured.

    Lives here, rather than being duplicated in config_flow.py and
    coordinator.py as it once was, because the config flow now resolves the
    serial once and persists it on the entry for the coordinator to seed its
    registry keys from (issue #236). Two copies of this rule meant the two
    sides could disagree about what a device's identity is -- and a
    disagreement is exactly what orphans a registry entry.
    """
    s = serial.strip()
    if s.lower().startswith("nothing"):
        return True
    upper = s.upper()
    return len(upper) >= 8 and len(set(upper)) == 1 and upper[0] in "0123456789ABCDEF"


def resolve_serial(raw_serial: str | None, host: str) -> str:
    """The device identity to mint registry keys from.

    `raw_serial` is /information/vs/0's x.com.samsung.da.serialNum as the
    device reported it. Boards that report nothing usable fall back to the
    host, which is stable per install and unique across devices on one
    network -- see is_placeholder_serial for the two families that need it.
    """
    s = (raw_serial or "").strip()
    if not s or is_placeholder_serial(s):
        return host
    return s


def resolve_model(model_num: str, identity: DeviceIdentity | None) -> str:
    """The model string to name and register a device under.

    `model_num` is /information/vs/0's x.com.samsung.da.modelNum, which many
    boards report as `<model>|<board>` -- only the part before the pipe is the
    model a user would recognize. A board that reports no modelNum at all
    falls back to /oic/p's mnmo, which read_identity already parsed.

    Shared with resolve_serial's motivation: the config flow resolves this
    once and persists it on the entry, and the coordinator recomputes it after
    the first poll. Two copies of the split rule would let those two disagree,
    and a device that renames itself on the first poll is the visible symptom.
    """
    if model_num:
        return model_num.split("|", 1)[0]
    return identity.model if identity else ""


def device_display_name(device_type_name: str | None, model: str) -> str:
    """The HA device name for a resolved device type + model.

    Shared by the config flow (which builds the entry's stored identity) and
    the coordinator's post-discovery rebuild, so the name a device is first
    registered under is the same string discovery would produce later --
    otherwise every setup would rename the device once the first poll landed.
    """
    device_type = device_type_name.replace("_", " ").title() if device_type_name else "Appliance"
    return f"Samsung {device_type} ({model})" if model else f"Samsung {device_type}"


def _get(sess, path) -> dict:
    try:
        code, pl = sess.get(path, timeout=10.0)
        if code == 0x45 and pl:
            body = cbor2.loads(pl)
            return body if isinstance(body, dict) else {}
    except Exception:
        pass
    return {}


def _get_links(sess, path) -> list:
    """Like _get, but for /oic/res: a baseline-Interface RETRIEVE on it
    returns a CBOR array of Link objects (href/rt/if/di/...), not a single
    Property map."""
    try:
        code, pl = sess.get(path, timeout=10.0)
        if code == 0x45 and pl:
            body = cbor2.loads(pl)
            return body if isinstance(body, list) else []
    except Exception:
        pass
    return []


def _device_types(d: dict) -> tuple[str, ...]:
    """/oic/d's `rt` -- the device's own OCF device-type declaration.

    In OCF this is the one standardized "what am I" field: alongside the
    generic 'oic.wk.d' it carries a concrete type such as 'oic.d.airconditioner'
    or a SmartThings 'x.com.st.d.*' equivalent. `registry/by_type/resolve()`
    now consults this first, ahead of board-part-number parsing, via
    `for_device_by_oic_type` and its `_OIC_TYPE_TO_KEY` table -- but only a
    minority of dumps populate it, so the modelNum/description path stays
    load-bearing for everything else. It's also kept whole in diagnostics
    (see `raw` below) so incoming issue reports keep surfacing types that
    table doesn't know about yet.
    """
    rt = d.get("rt")
    if isinstance(rt, str):
        rt = [rt]
    if not isinstance(rt, (list, tuple)):
        return ()
    return tuple(t for t in rt if isinstance(t, str))


def read_identity(sess, serial: str | None) -> DeviceIdentity:
    p = _get(sess, ["oic", "p"])
    d = _get(sess, ["oic", "d"])
    # /oic/res is OCF's baseline resource-discovery endpoint: a unicast
    # RETRIEVE on it returns every Resource/Collection href this endpoint
    # hosts, not just the one /device/0 seed path the coordinator polls.
    # Relevant for the OCF "Composite Device" model (issue #177: a single
    # physical device -- one IP, one /oic/p -- exposing more than one logical
    # subdevice, each as its own Collection resource, same rt shape as our own
    # /device/0). This is what registry.subdevices.enumerate_subdevices reads
    # to find a board's `/device/<n>` siblings (Pattern A -- the reporter's
    # ARTIK051_DONGLE_FAC_18K) -- that probing, plus the /device/1 and
    # /device/2 speculative fallback it used to run right here on every
    # _connect_session (including every reconnect), moved to that module so
    # it only runs once, at first discovery, instead of on every reconnect.
    res = _get_links(sess, ["oic", "res"])
    return DeviceIdentity(
        manufacturer=p.get("mnmn") or "Samsung",
        model=p.get("mnmo") or "",
        name=d.get("n") or "",
        serial=serial,
        device_types=_device_types(d),
        # Kept whole rather than field-by-field: these resources are outside
        # the /device/0 dump diagnostics already captures, and we don't yet
        # know which of their fields will turn out to identify a device type.
        raw={"/oic/p": p, "/oic/d": d, "/oic/res": res},
    )
