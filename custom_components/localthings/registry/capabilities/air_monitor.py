"""Capabilities for the Samsung Air Monitor Plus family (ASM-KR-TP1-22-*
board, issue #210) -- a small battery-powered standalone air-quality sensor
puck, not a controllable appliance. No `/power/*` resource at all (battery
only); this registry deliberately doesn't include common.POWER.

`/sensors/vs/0` is the same {type, value: [...]} items-list shape
air_purifier.AIR_QUALITY and range_hood.AIR_QUALITY already read via
common.sensor_item_value -- reused here rather than re-decoded, including
the same dust/fine_dust/super_fine_dust/odor/clean_level keys so this
device shares those capabilities' catalog entries. This board additionally
reports a CO2 reading the other two families don't.

A second `value` list element on the particulate-matter types (e.g. Dust's
`['31', '2']`) reads like a coarse quality-grade code, but nothing on this
board (no `supportedGrades`/similar field, no repeated dump to compare
against) confirms what its scale means -- left unbound rather than guessed,
per the adding-device-support skill's "still never invent... from nothing"
rule. Same reasoning `air_purifier.AIR_QUALITY` already applies to this
shape; index 0 is the only slot any family has ever read.

Dust/FineDust/SuperFineDust aren't assigned an HA `device_class`
(pm10/pm25/pm1) or `unit` despite the values reading like plausible
ug/m3 particulate readings in a physically consistent order (coarser
>= finer): Samsung's own two-tier Korean convention (i.e. "fine dust"/
"ultra-fine dust") maps only to a PM10/PM2.5 pair, and this board's
three-tier naming doesn't confirm where the extra tier or a PM1 reading
actually fits. The adding-device-support skill's read-side rule says
leave unit/device_class unset when the dump gives no field that
nominates one -- a wrong guess would silently mislabel every reading
forever, and the write-side rejection safety net doesn't cover reads.
Exposed as plain `measurement` sensors named after the device's own
field instead (matching air_purifier.AIR_QUALITY's existing precedent).
"""

from datetime import time as dt_time

from ..capability import Capability
from ..entities import BinarySensorDesc, SensorDesc, SwitchDesc, TimeDesc
from .air_purifier import _AIR_QUALITY_SENSORS
from .common import int_or_none, sensor_item_value

SENSORS = Capability(
    href="/sensors/vs/0",
    poll_tier="warm",
    entities=(
        *(
            SensorDesc(
                key=key,
                field="x.com.samsung.da.items",
                icon=icon,
                state_class="measurement",
                value_fn=lambda items, t=sensor_type: sensor_item_value(items, t),
            )
            for key, icon, sensor_type in _AIR_QUALITY_SENSORS
        ),
        SensorDesc(
            key="co2",
            field="x.com.samsung.da.items",
            device_class="carbon_dioxide",
            state_class="measurement",
            unit="ppm",
            value_fn=lambda items: sensor_item_value(items, "CO2"),
        ),
    ),
)

HUMIDITY = Capability(
    href="/humidity/vs/0",
    poll_tier="warm",
    entities=(
        SensorDesc(
            key="humidity",
            field="x.com.samsung.da.humidity",
            device_class="humidity",
            state_class="measurement",
            unit="%",
            value_fn=int_or_none,
        ),
    ),
)

BATTERY = Capability(
    href="/energy/battery/vs/0",
    poll_tier="warm",
    entities=(
        SensorDesc(
            key="battery",
            field="x.com.samsung.da.battery",
            device_class="battery",
            state_class="measurement",
            unit="%",
            entity_category="diagnostic",
            value_fn=int_or_none,
        ),
        BinarySensorDesc(
            key="battery_charging",
            field="x.com.samsung.da.charging",
            device_class="battery_charging",
            entity_category="diagnostic",
            value_fn=lambda v: v == "On",
        ),
    ),
)

AIR_QUALITY_STANDARD = Capability(
    href="/airqualitystandard/vs/0",
    poll_tier="cold",
    entities=(
        SensorDesc(
            key="air_quality_standard",
            field="x.com.samsung.da.standard",
            entity_category="diagnostic",
        ),
    ),
)


def _parse_hms(v):
    """'HH:MM:SS' -> datetime.time, same contract as laundry._parse_hm but
    tolerant of the trailing ':SS' this board's dnd start/end times carry."""
    if not v:
        return None
    try:
        parts = v.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def _dnd_time_write(field):
    def _write(p, rep, href=None):
        return ["dnd", "vs", "0"], {field: f"{p.hour:02d}:{p.minute:02d}:00"}

    return _write


# Issue #210: no idle-vs-active dump pair exists for this href (only one
# dump total, DND never toggled in it), so this write contract is an
# educated guess, not a confirmed one -- symmetric with the read side
# (writing the same 'true'/'false' string shape and 'HH:MM:SS' format the
# device itself reports back) rather than invented from nothing, but still
# needs a reporter to actually flip it on real hardware and confirm. See
# the adding-device-support skill's "Educated guesses are fine" section.
DND = Capability(
    href="/dnd/vs/0",
    poll_tier="cold",
    entities=(
        SwitchDesc(
            key="dnd",
            field="x.com.samsung.da.value",
            icon="mdi:sleep",
            entity_category="config",
            value_fn=lambda v: v == "true",
            write_fn=lambda p, rep, href=None: (
                ["dnd", "vs", "0"],
                {"x.com.samsung.da.value": "true" if p == "On" else "false"},
            ),
        ),
        TimeDesc(
            key="dnd_start",
            field="x.com.samsung.da.startTime",
            icon="mdi:clock-start",
            entity_category="config",
            value_fn=_parse_hms,
            write_fn=_dnd_time_write("x.com.samsung.da.startTime"),
        ),
        TimeDesc(
            key="dnd_end",
            field="x.com.samsung.da.endTime",
            icon="mdi:clock-end",
            entity_category="config",
            value_fn=_parse_hms,
            write_fn=_dnd_time_write("x.com.samsung.da.endTime"),
        ),
    ),
)

# ---------------------------------------------------------------------------
# Air-monitor-scoped coverage: hrefs with no explainable live state,
# following the 'don't guess' rule.
# ---------------------------------------------------------------------------
_AM_IGNORED = [
    # A single bare integer ('keepnormal': 0) with no description, no
    # supported-values list, and no second dump to compare against -- opaque.
    "/keepnormalstate/vs/0",
    # {'remove': ''} -- looks like data-sink/cache-clearing plumbing, not a
    # live user-facing field.
    "/sensordatasinks/vs/0",
]

COVERAGE = [Capability(href=h) for h in _AM_IGNORED]
