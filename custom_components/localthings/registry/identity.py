"""Read device identity from standard OCF resources (/oic/p, /oic/d)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cbor2


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
    return DeviceIdentity(
        manufacturer=p.get('mnmn') or 'Samsung',
        model=p.get('mnmo') or '',
        name=d.get('n') or '',
        serial=serial,
        device_types=_device_types(d),
        # Kept whole rather than field-by-field: these resources are outside
        # the /device/0 dump diagnostics already captures, and we don't yet
        # know which of their fields will turn out to identify a device type.
        raw={'/oic/p': p, '/oic/d': d},
    )
