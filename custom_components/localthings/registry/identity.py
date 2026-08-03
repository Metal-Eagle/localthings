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
