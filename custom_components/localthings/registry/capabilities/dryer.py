"""Capabilities specific to the dryer family (Samsung DA_WM_TP1/TP2-class).

Dryer-specific controls only. The shared laundry surface -- power/kids-lock/
remote-control fallback pairs, buzzer, energy meter, job-beginning-status, and
the /course/vs/0 cycle select -- lives in laundry.py.

  /washer/vs/0   -> DRYER_SETTINGS (dryLevel, dryTime, dryerType, wrinklePrevent)
  /course/vs/0   -> DRYER_COURSE (shared cycle select; see below)
  /diagnosis/vs/0 -> DRYER_DIAGNOSIS
"""

from ..capability import Capability
from ..entities import SensorDesc, SwitchDesc
from .laundry import cycle_select, drum_clean_cycles_remaining, drum_clean_last_cleaned


def _wrinkle_write(p, rep, href=None):
    if p not in ("On", "Off"):
        return None
    return ["washer", "vs", "0"], {"x.com.samsung.da.wrinklePrevent": p}


DRYER_SETTINGS = Capability(
    href="/washer/vs/0",
    poll_tier="warm",
    entities=(
        SensorDesc(key="dry_level", field="x.com.samsung.da.dryLevel", icon="mdi:water-percent"),
        SensorDesc(key="dry_time", field="x.com.samsung.da.dryTime", icon="mdi:timer"),
        SensorDesc(key="dryer_type", field="x.com.samsung.da.dryerType", icon="mdi:tumble-dryer"),
        SwitchDesc(
            key="wrinkle_prevent",
            field="x.com.samsung.da.wrinklePrevent",
            icon="mdi:iron",
            value_fn=lambda v: v == "On",
            write_fn=_wrinkle_write,
        ),
    ),
)

# /course/vs/0 -- cycle selection, shared with washer/dishwasher via
# laundry.cycle_select (options read live from /wm/editcourse/vs/0, written as
# an RMW on the options array). Course display names live in translations
# under entity.select.dryer_cycle (Table_03, DV5000-class, captured
# 2026-05-29). Codes 0x21 and 0x4C appear in the issue #14 DV90BB5245AES1
# editCourseList but aren't identified yet -- they render as the raw code
# until named. Codes '01' Normal and '06' Time dry were confirmed on a
# DVE50A8600V/A3 (also Table_03) by selecting each cycle on the physical
# appliance and reading back the raw code from the entity's state (issue
# #80). The /st/dryercourse/vs/0 resource re-encodes the same selected
# course and is ignored (ignored.py) -- the mirror of how /st/washercourse/vs/0
# is ignored for washers.
#
# Drum Clean+ maintenance tracking (issue #258) reuses washer.py's
# DrumCleanProposal_/WashingTimes_/DrumCleanLog_ tokens on this same
# options[] array -- see laundry.drum_clean_cycles_remaining/
# drum_clean_last_cleaned's docstrings for the field contract, including
# the dryer-specific '|'-joined multi-entry DrumCleanLog_ shape. No
# separate heat-exchanger-clean tracking was found on either dump #258
# supplied (DV90BB7445GES7, DV91T6440LE/SA) -- no HeatExchanger*-prefixed
# token, nor any other options[] entry that looks like a second maintenance
# counter -- so if the Samsung app surfaces that reminder for these units,
# it isn't computed from anything this integration can read locally.
DRYER_COURSE = Capability(
    href="/course/vs/0",
    entities=(
        cycle_select(
            translation_key="dryer_cycle",
            icon="mdi:tumble-dryer",
            table_href="/st/dryercourse/vs/0",
        ),
        SensorDesc(
            key="drum_clean_cycles_remaining",
            unit="cycles",
            icon="mdi:tumble-dryer-alert",
            state_class="measurement",
            exists_fn=lambda rep, resources: drum_clean_cycles_remaining(rep) is not None,
            rep_fn=drum_clean_cycles_remaining,
        ),
        SensorDesc(
            key="drum_clean_last_cleaned",
            device_class="timestamp",
            icon="mdi:calendar-clock",
            entity_category="diagnostic",
            exists_fn=lambda rep, resources: drum_clean_last_cleaned(rep) is not None,
            rep_fn=drum_clean_last_cleaned,
        ),
    ),
)

DRYER_DIAGNOSIS = Capability(
    href="/diagnosis/vs/0",
    poll_tier="warm",
    entities=(
        SensorDesc(
            key="diagnosis", field="x.com.samsung.da.diagnosisStart", entity_category="diagnostic"
        ),
    ),
)
