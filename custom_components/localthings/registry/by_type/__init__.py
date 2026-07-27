"""Per-device-type registries."""
from typing import Optional

from ._base import DeviceRegistry
from . import (
    air_purifier, airconditioner, cooktop, dishwasher, dryer, oven,
    range as _range, range_hood, refrigerator, washer,
)

__all__ = [
    'DeviceRegistry', '_type_key', 'for_device', 'for_device_by_model',
    'for_device_by_resources',
]


_REGISTRY_BY_KEY: dict[str, DeviceRegistry] = {
    'air_purifier': air_purifier.REGISTRY,
    'airpurifier': air_purifier.REGISTRY,
    'airconditioner': airconditioner.REGISTRY,
    'air_conditioner': airconditioner.REGISTRY,
    'cooktop': cooktop.REGISTRY,
    'dishwasher': dishwasher.REGISTRY,
    'dryer': dryer.REGISTRY,
    'oven': oven.REGISTRY,
    'hood': range_hood.REGISTRY,
    'range': _range.REGISTRY,
    'range_hood': range_hood.REGISTRY,
    'refrigerator': refrigerator.REGISTRY,
    'washer': washer.REGISTRY,
}


def _type_key(one_ui_version: str) -> str:
    """Convert oneUiVersion string to registry key.

    Args:
        one_ui_version: String like '7.0 Dishwasher' or 'Oven'.

    Returns:
        Lowercase key with version prefix stripped and spaces/hyphens converted to underscores.

    Examples:
        '7.0 Dishwasher' -> 'dishwasher'
        '7.0 French Door Refrigerator' -> 'french_door_refrigerator'
        'Oven' -> 'oven'
    """
    if ' ' in one_ui_version:
        # Strip version prefix: everything before and including the first space
        suffix = one_ui_version.split(' ', 1)[-1]
    else:
        suffix = one_ui_version

    return suffix.lower().replace(' ', '_').replace('-', '_')


def for_device(one_ui_version: str) -> Optional[DeviceRegistry]:
    """Return the DeviceRegistry for the given oneUiVersion string, or None if unknown.

    Args:
        one_ui_version: Device's oneUiVersion string (e.g., '7.0 Dishwasher').

    Returns:
        DeviceRegistry if a matching registry exists, None otherwise.
    """
    key = _type_key(one_ui_version)
    if key in _REGISTRY_BY_KEY:
        return _REGISTRY_BY_KEY[key]
    # Suffix fallback: e.g. "french_door_refrigerator" ends with "_refrigerator"
    for rkey, reg in _REGISTRY_BY_KEY.items():
        if key.endswith(f'_{rkey}'):
            return reg
    return None


# Consumer-model prefix (first two letters of the '_'-delimited token in
# `description` right before any '/board-info' suffix) -> registry key.
# NOT derived from `modelNum` -- washer and dryer share the same 'DA_WM_'
# internal board-family prefix there, and dishwasher's modelNum contains
# the substring 'WW', so a modelNum-only rule misroutes both.
_CONSUMER_PREFIX_TO_KEY: dict[str, str] = {
    'WW': 'washer',
    'WD': 'washer',
    'WF': 'washer',
    'WV': 'washer',  # FlexWash twin units (e.g. WV55M9600AW) -- issue #19
    'DV': 'dryer',
    'DW': 'dishwasher',
}


def _consumer_model_key(description: str) -> Optional[str]:
    """Registry key from the consumer-model token in `description`, or None.

    Usually that token is the last '_'-delimited segment before any
    '/board-info' suffix (e.g. '..._WW90DG6U25LEU4' -> 'WW90DG6U25LEU4').
    But issue #79's dryer pairs two model numbers in one description --
    '..._DVE50A8800_8600/DC92-...' -- so the true consumer token
    ('DVE50A8800') sits one segment *before* the actual last segment
    ('8600', a bare second model number with no recognizable prefix). Scan
    segments from the end and take the first one that resolves, rather
    than assuming the last segment is always it.
    """
    segments = (description or '').split('/', 1)[0].split('_')
    for segment in reversed(segments):
        key = _CONSUMER_PREFIX_TO_KEY.get(segment[:2].upper())
        if key is not None:
            return key
    return None


def for_device_by_model(model_num: str, description: str) -> Optional[DeviceRegistry]:
    """Fallback device-type detection for hardware that never reports
    oneUiVersion (confirmed for washers -- their /otninformation/vs/0 has
    no swVersionInfo key at all).

    Args:
        model_num: x.com.samsung.da.modelNum from /information/vs/0.
        description: x.com.samsung.da.description from /information/vs/0.

    Returns:
        DeviceRegistry if the consumer-model code or modelNum resolves to a
        known type, None otherwise.
    """
    key = _consumer_model_key(description)
    if key is None and '_REF_' in (model_num or ''):
        key = 'refrigerator'
    # Room air conditioners (e.g. ARTIK051_PRAC_20K) report no oneUiVersion and
    # a modelNum carrying the '_PRAC_' (Package Room Air Conditioner) token.
    if key is None and '_PRAC_' in (model_num or ''):
        key = 'airconditioner'
    # Older/simpler RAC boards (e.g. TP2X_RAC_20K, issue #37) use the plain
    # '_RAC_' token instead -- distinct from '_PRAC_' above (no overlap: the
    # 'P' sits between the underscore and 'RAC' in that token).
    if key is None and '_RAC_' in (model_num or ''):
        key = 'airconditioner'
    # System air conditioners (multi-indoor-unit commercial installs, e.g.
    # A-CAWW-TP2-20-COMMON, issue #52) report no oneUiVersion either and
    # carry the '-CAWW-' board-family token instead of '_RAC_'/'_PRAC_'.
    # Same TP1X/TP2X-class resource surface as the room-AC models above
    # (confirmed by the issue #52 dump binding cleanly against the existing
    # airconditioner registry once routed here), plus one new SAC-specific
    # resource (see airconditioner.py's _AC_IGNORED).
    if key is None and '-CAWW-' in (model_num or '').upper():
        key = 'airconditioner'
    # Air purifiers (e.g. ARTIK051_TVTL_18K, issue #56) report no
    # oneUiVersion either, and carry the '_TVTL_' board-family token.
    if key is None and '_TVTL_' in (model_num or ''):
        key = 'air_purifier'
    model_identity = f'{model_num} {description}'.upper()
    if key is None and ('_COOKTOP' in model_identity or '_GB_CT_' in model_identity):
        key = 'cooktop'
    if key is None and model_identity.startswith('AHD-'):
        key = 'range_hood'
    # Range/cooktop-oven combos (e.g. TP1X_DA-KS-RANGE-0102X, issue #44) --
    # like the RAC/PRAC air conditioners above, these report no oneUiVersion
    # and don't match the washer/dryer/dishwasher consumer-prefix map either.
    if key is None and '-RANGE-' in (model_num or '').upper():
        key = 'range'
    # Wall ovens (e.g. TP1X_DA-KS-OVEN-0107X, issue #55) -- same board-family
    # naming as the range combo above, minus the burners; also reports no
    # oneUiVersion and doesn't match the washer/dryer/dishwasher prefix map.
    if key is None and '-OVEN-' in (model_num or '').upper():
        key = 'oven'
    return _REGISTRY_BY_KEY.get(key) if key else None


def for_device_by_resources(resources: dict[str, dict]) -> Optional[DeviceRegistry]:
    """Detect a device family from a distinctive local-resource signature.

    Some newer cooktops omit both ``oneUiVersion`` and
    ``/information/vs/0``.  Their mode resource still identifies them: it
    contains a DeviceType option and multiple per-burner OperationState
    options.  Require both shapes so an oven's unrelated ``/mode/vs/0`` is
    not misclassified.
    """
    mode = resources.get('/mode/vs/0', {})
    options = mode.get('x.com.samsung.da.options') or ()
    has_device_type = any(
        isinstance(option, str) and option.startswith('DeviceType_')
        for option in options
    )
    operation_states = sum(
        1 for option in options
        if isinstance(option, str) and option.startswith('OperationState')
    )
    if has_device_type and operation_states >= 2:
        return _REGISTRY_BY_KEY['cooktop']
    if (
        '/hood/fanspeed/vs/0' in resources
        and '/hood/lamp/vs/0' in resources
    ):
        return _REGISTRY_BY_KEY['range_hood']
    # Oven/range-combo boards that report no /information/vs/0 at all
    # (issue #74's NE63B8411SS -- the resource is simply absent from the
    # dump, not just empty) can't be matched via for_device_by_model's
    # modelNum tokens either. 'Bake' is oven/range cook-mode vocabulary that
    # no other family's /mode/vs/0 uses (confirmed against the microwave,
    # cooktop, and every laundry fixture), so its presence alongside the
    # oven cavity resource is a safe signature. Distinguish range (has a
    # cooktop half) from a plain wall oven by which cooktop-status resource,
    # if any, is also present.
    supported_modes = mode.get('x.com.samsung.da.supportedModes') or ()
    if '/oven/vs/0' in resources and 'Bake' in supported_modes:
        if '/cooktopmonitoring/vs/0' in resources or '/cooktop/status/vs/0' in resources:
            return _REGISTRY_BY_KEY['range']
        return _REGISTRY_BY_KEY['oven']
    return None
