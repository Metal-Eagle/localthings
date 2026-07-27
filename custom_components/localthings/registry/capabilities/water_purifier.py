"""Capabilities for the Samsung water-purifier family (TP2X_WATERPURIFIER-class,
issue #90, model TP2X_WATERPURIFIER_20K).

Resources verified against the issue #90 diagnostics dump.
"""
from datetime import datetime, timezone

from ..capability import Capability
from ..entities import BinarySensorDesc, NumberDesc, SelectDesc, SensorDesc, SwitchDesc
from .common import int_or_none


def _parse_iso_utc(raw):
    """Bare ISO datetime with no timezone field alongside it -- treated as
    UTC, matching this integration's convention for other bare ISO datetime
    fields (see washer.py's drum-clean-log comment)."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


DISPENSE = Capability(
    href='/setting/waterpurifier/vs/0',
    poll_tier='warm',
    entities=(
        SelectDesc(key='dispense_type', field='x.com.samsung.da.desiredType',
                   icon='mdi:cup-water',
                   options_field='x.com.samsung.da.supportedTypes',
                   write_fn=lambda p, rep, href=None: (
                       ['setting', 'waterpurifier', 'vs', '0'],
                       {'x.com.samsung.da.desiredType': p})),
        # Only a handful of discrete temperatures are selectable (not a
        # continuous range) -- a select over the live-reported set, not a
        # number with invented bounds.
        SelectDesc(key='hot_water_temperature', field='x.com.samsung.da.tempDesiredHotWater',
                   icon='mdi:thermometer',
                   entity_category='config',
                   options_field='x.com.samsung.da.supportedHotTemperatures',
                   write_fn=lambda p, rep, href=None: (
                       ['setting', 'waterpurifier', 'vs', '0'],
                       {'x.com.samsung.da.tempDesiredHotWater': p})),
        # Bounds and step come live from the device's own
        # desiredCapacityRange/capacityResolution fields, not a hardcoded
        # constant -- see the adding-device-support skill's "never hard-code
        # the one dump's values" section. No unit is set: capacityUnit reads
        # "C" on this dump, which can't be right for a volume field, so per
        # the 'don't guess' rule the unit is left unset rather than assumed
        # to be mL.
        NumberDesc(key='dispense_capacity', field='x.com.samsung.da.desiredCapacity',
                   icon='mdi:cup-water',
                   value_fn=int_or_none,
                   range_field='x.com.samsung.da.desiredCapacityRange',
                   step_fn=lambda rep: int_or_none(
                       rep.get('x.com.samsung.da.capacityResolution')) or 1,
                   write_fn=lambda p, rep, href=None: (
                       ['setting', 'waterpurifier', 'vs', '0'],
                       {'x.com.samsung.da.desiredCapacity': str(int(round(float(p))))})),
        BinarySensorDesc(key='pouring', field='x.com.samsung.da.pourStatus',
                          icon='mdi:cup-water',
                          value_fn=lambda v: v == 'On'),
    ),
)

STATUS = Capability(
    href='/status/waterpurifier/vs/0',
    poll_tier='warm',
    entities=(
        SensorDesc(key='waterpurifier_status', field='x.com.samsung.da.status',
                   icon='mdi:water-pump',
                   entity_category='diagnostic'),
        BinarySensorDesc(key='filter_door_status', field='x.com.samsung.da.filterDoorStatus',
                          device_class='door',
                          entity_category='diagnostic',
                          value_fn=lambda v: v == 'Open'),
        SensorDesc(key='sterilize_period', field='x.com.samsung.da.sterilizePeriod',
                   icon='mdi:calendar-sync',
                   entity_category='diagnostic'),
        SensorDesc(key='sterilize_run_time', field='x.com.samsung.da.sterilizeRunTime',
                   icon='mdi:timer-outline',
                   entity_category='diagnostic'),
        SensorDesc(key='sterilize_last_time', device_class='timestamp',
                   entity_category='diagnostic',
                   rep_fn=lambda rep: _parse_iso_utc(
                       rep.get('x.com.samsung.da.sterilizeLastTime'))),
        SensorDesc(key='sterilize_plan_time', device_class='timestamp',
                   entity_category='diagnostic',
                   rep_fn=lambda rep: _parse_iso_utc(
                       rep.get('x.com.samsung.da.sterilizePlanTime'))),
        SensorDesc(key='filter_clean_remain_time', field='x.com.samsung.da.filterCleanRemainTime',
                   icon='mdi:timer-sand',
                   entity_category='diagnostic'),
    ),
)

FAVORITE_CAPACITY = Capability(
    href='/favorite/capacity/vs/0',
    poll_tier='cold',
    entities=(
        SwitchDesc(key='favorite_capacity_enabled', field='x.com.samsung.da.switchCapacity',
                   icon='mdi:star-outline',
                   entity_category='config',
                   value_fn=lambda v: v == 'On',
                   write_fn=lambda p, rep, href=None: (
                       ['favorite', 'capacity', 'vs', '0'],
                       {'x.com.samsung.da.switchCapacity': 'On' if p == 'On' else 'Off'})),
        SelectDesc(key='favorite_capacity', field='x.com.samsung.da.defaultCapacity',
                   icon='mdi:cup-water',
                   entity_category='config',
                   options_field='x.com.samsung.da.capacityList',
                   write_fn=lambda p, rep, href=None: (
                       ['favorite', 'capacity', 'vs', '0'],
                       {'x.com.samsung.da.defaultCapacity': p})),
    ),
)

LOCK = Capability(
    href='/status/lock/vs/0',
    poll_tier='warm',
    entities=(
        SwitchDesc(key='hotwater_lock', field='x.com.samsung.da.hotwaterLock',
                   device_class='lock',
                   entity_category='config',
                   value_fn=lambda v: v != 'Unlocked',
                   write_fn=lambda p, rep, href=None: (
                       ['status', 'lock', 'vs', '0'],
                       {'x.com.samsung.da.hotwaterLock': 'Locked' if p == 'On' else 'Unlocked'})),
        SwitchDesc(key='coldwater_lock', field='x.com.samsung.da.coldwaterLock',
                   device_class='lock',
                   entity_category='config',
                   value_fn=lambda v: v != 'Unlocked',
                   write_fn=lambda p, rep, href=None: (
                       ['status', 'lock', 'vs', '0'],
                       {'x.com.samsung.da.coldwaterLock': 'Locked' if p == 'On' else 'Unlocked'})),
        SwitchDesc(key='buzz_lock', field='x.com.samsung.da.buzzLock',
                   device_class='lock',
                   entity_category='config',
                   value_fn=lambda v: v != 'Unlocked',
                   write_fn=lambda p, rep, href=None: (
                       ['status', 'lock', 'vs', '0'],
                       {'x.com.samsung.da.buzzLock': 'Locked' if p == 'On' else 'Unlocked'})),
    ),
)

# ---------------------------------------------------------------------------
# Water-purifier-scoped coverage: hrefs with no user-actionable state or no
# confirmed contract, following the 'don't guess' rule.
# ---------------------------------------------------------------------------
_WP_IGNORED = [
    # supportedModes carries a single opaque wizard-workflow token
    # ('HOMECARE_WIZARD_V2') and modes reports a completely different,
    # unrelated value ('WATERFILTER_DISABLE') not even present in
    # supportedModes -- internal plumbing, not a real user-facing mode
    # select. OCF-standard /mode/0 mirrors the same vendor resource but is
    # already covered by the global ignored.IGNORED (fridge's OCF-native
    # vacation-mode flag shares that href).
    '/mode/vs/0',
    # Static support-flags blob (automation.supported.modes/options) -- no
    # live "current automation setting" field to expose.
    '/automation/waterpurifier/vs/0',
]

COVERAGE = [Capability(href=h) for h in _WP_IGNORED]
