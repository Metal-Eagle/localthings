"""Read device identity from standard OCF resources (/oic/p, /oic/d, /oic/res)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cbor2

from .batch import parse_device0_batch

# Speculative /device/<n> siblings to probe alongside the coordinator's own
# /device/0 seed poll (issue #177). Confirmed against a real dump: /oic/res's
# baseline-Interface response only lists resources with the discoverable
# policy bit set, and /device/0's whole x.com.samsung.da.* tree is registered
# without it -- so a second logical Device's Collection, if one exists, would
# be just as invisible to /oic/res as /device/0 is. A direct GET is the only
# way left to check, and it's a plain RETRIEVE (non-mutating, tolerated-404
# already the norm throughout this module) -- not the kind of guess the
# write-contract 'don't guess' rule is about. Bounded to a couple of indices;
# widen only if a real Composite Device ever turns out to need more.
_SPECULATIVE_DEVICE_INDICES = (1, 2)


@dataclass(frozen=True)
class DeviceIdentity:
    manufacturer: str
    model: str
    name: str
    serial: Optional[str]
    device_types: tuple[str, ...] = ()
    raw: dict[str, dict] = field(default_factory=dict)


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


def _get_device_batch(sess, index: int) -> dict[str, dict]:
    """GET /device/<index> and parse it the same way the coordinator parses
    /device/0 -- a Samsung Collection RETRIEVE returns
    [devcol-rep, {href, rep}, {href, rep}, ...], not a bare Property map or
    Link array. Missing/malformed responses fall through to {} (via
    parse_device0_batch on an empty/non-list body), same tolerated-absence
    posture as _get/_get_links above."""
    try:
        code, pl = sess.get(['device', str(index)], timeout=10.0)
        if code == 0x45 and pl:
            body = cbor2.loads(pl)
            if isinstance(body, list):
                return parse_device0_batch(body)
    except Exception:
        pass
    return {}


def _device_types(d: dict) -> tuple[str, ...]:
    """/oic/d's `rt` -- the device's own OCF device-type declaration.

    In OCF this is the one standardized "what am I" field: alongside the
    generic 'oic.wk.d' it carries a concrete type such as 'oic.d.airconditioner'
    or a Samsung 'x.com.samsung.da.*' equivalent. Nothing routes on it yet --
    device-type detection currently parses board part numbers out of
    /information/vs/0's modelNum instead (see registry/by_type/__init__.py) --
    because no captured dump has ever included it: /device/0 batch responses
    don't carry /oic/d, and diagnostics didn't report it. It's surfaced in
    diagnostics so incoming issue reports can tell us whether real hardware
    populates it usefully enough to route on.
    """
    rt = d.get('rt')
    if isinstance(rt, str):
        rt = [rt]
    if not isinstance(rt, (list, tuple)):
        return ()
    return tuple(t for t in rt if isinstance(t, str))


def read_identity(sess, serial: Optional[str]) -> DeviceIdentity:
    p = _get(sess, ['oic', 'p'])
    d = _get(sess, ['oic', 'd'])
    # /oic/res is OCF's baseline resource-discovery endpoint: a unicast
    # RETRIEVE on it returns every Resource/Collection href this endpoint
    # hosts, not just the one /device/0 seed path the coordinator polls.
    # Relevant for the OCF "Composite Device" model (issue #177: a single
    # physical unit -- one IP, one /oic/p -- exposing more than one logical
    # Device, each as its own Collection resource, same rt shape as our own
    # /device/0). Nothing consumes this yet; captured so a report from a
    # multi-unit device shows us whether its firmware actually implements
    # that model before any code assumes it does.
    res = _get_links(sess, ['oic', 'res'])
    extra_devices = {
        f'/device/{n}': _get_device_batch(sess, n)
        for n in _SPECULATIVE_DEVICE_INDICES
    }
    return DeviceIdentity(
        manufacturer=p.get('mnmn') or 'Samsung',
        model=p.get('mnmo') or '',
        name=d.get('n') or '',
        serial=serial,
        device_types=_device_types(d),
        # Kept whole rather than field-by-field: these resources are outside
        # the /device/0 dump diagnostics already captures, and we don't yet
        # know which of their fields will turn out to identify a device type.
        # /device/1 and /device/2 are always present here (empty {} when the
        # device didn't answer) so a diagnostics reader can tell "checked,
        # nothing there" apart from "never checked".
        raw={'/oic/p': p, '/oic/d': d, '/oic/res': res, **extra_devices},
    )
