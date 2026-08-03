"""Tests for /airlevelcheck/vs/0 -- the "AI Purify" periodic air-quality
sensing engine (issues #84 and #190).

The resource is reported by three of this registry's four board families, so
the read assertions run against each family's own fixture; the write contracts
were exercised on AVT-WW-TP1-23-AXX500 hardware and are asserted here at the
body level.
"""

import datetime

from custom_components.localthings.registry.adapter import flatten
from custom_components.localthings.registry.by_type import resolve
from custom_components.localthings.registry.capabilities import air_purifier
from custom_components.localthings.registry.discovery import discover
from tests.conftest import _load_device

# The three fixtures whose dumps carry this resource. air_purifier (the
# ARTIK051_TVTL family, issue #56) has no such href and is deliberately absent.
FAMILIES = ("air_purifier_avt_ww", "air_purifier_vtww", "air_purifier_tp1x_da_ac_air")


def _state(fixture):
    resources = _load_device(fixture)
    reg = resolve(resources)
    assert reg is not None and reg.name == "air_purifier", fixture
    return flatten(discover(resources, reg.capabilities, reg.pattern_capabilities), resources)


def _desc(key):
    return next(d for d in air_purifier.AIR_LEVEL_CHECK.entities if d.key == key)


def test_air_level_check_is_bound_not_covered():
    """The href used to sit in COVERAGE as opaque scheduler plumbing. Guard
    against it being covered again, which would silently drop every entity
    below while still reporting zero unbound hrefs."""
    covered = {cap.href for cap in air_purifier.COVERAGE}
    assert "/airlevelcheck/vs/0" not in covered


def test_every_reporting_family_binds_the_cluster():
    for fixture in FAMILIES:
        state = _state(fixture)
        for key in (
            "sensing_mode",
            "periodic_air_sensing",
            "periodic_sensing_skip_status",
            "sensing_skip_start",
            "sensing_skip_end",
            "air_sensing_state",
            "last_air_sensing_time",
            "last_air_sensing_level",
        ):
            assert key in state, f"{fixture}: {key}"


def test_tvtl_family_is_untouched():
    """Issue #56's board has no /airlevelcheck href at all -- nothing this
    change adds may appear on it."""
    state = _state("air_purifier")
    for key in ("sensing_mode", "periodic_air_sensing", "sensing_interval", "sensing_skip_start"):
        assert key not in state, key


def test_sensing_interval_only_where_the_field_exists():
    """TP1X_DA-AC-AIR (issue #130) omits periodicSensingInterval; the other two
    report it. The entity must follow the field, not the href."""
    assert "sensing_interval" in _state("air_purifier_avt_ww")
    assert "sensing_interval" in _state("air_purifier_vtww")
    assert "sensing_interval" not in _state("air_purifier_tp1x_da_ac_air")


def test_no_unbound_hrefs_on_any_reporting_family():
    for fixture in FAMILIES:
        resources = _load_device(fixture)
        reg = resolve(resources)
        assert reg is not None, fixture
        unbound = []
        discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
        assert unbound == [], f"{fixture}: {unbound}"


def test_sensing_mode_folds_toggle_and_action():
    """Off beats any pending auto-action; On with no action is 'sensing only'."""
    assert (
        air_purifier._sensing_mode(
            {
                "x.com.samsung.da.periodicSensingActivationState": "Off",
                "x.com.samsung.da.autoExeState": "Airpurify",
            }
        )
        == "off"
    )
    assert (
        air_purifier._sensing_mode(
            {
                "x.com.samsung.da.periodicSensingActivationState": "On",
                "x.com.samsung.da.autoExeState": "Off",
            }
        )
        == "sensing_only"
    )
    assert (
        air_purifier._sensing_mode(
            {
                "x.com.samsung.da.periodicSensingActivationState": "On",
                "x.com.samsung.da.autoExeState": "Airpurify",
            }
        )
        == "auto_purify"
    )
    assert (
        air_purifier._sensing_mode(
            {
                "x.com.samsung.da.periodicSensingActivationState": "On",
                "x.com.samsung.da.autoExeState": "Alarm",
            }
        )
        == "st_alarm"
    )


def test_sensing_mode_write_sets_both_fields_in_one_body():
    href, body = air_purifier._sensing_mode_write("auto_purify", {})
    assert href == ["airlevelcheck", "vs", "0"]
    assert body == {
        "x.com.samsung.da.periodicSensingActivationState": "On",
        "x.com.samsung.da.autoExeState": "Airpurify",
    }
    # 'off' only needs the toggle -- the pending action is preserved.
    assert air_purifier._sensing_mode_write("off", {})[1] == {
        "x.com.samsung.da.periodicSensingActivationState": "Off"
    }
    assert air_purifier._sensing_mode_write("nonsense", {}) is None


def test_sensing_mode_write_does_not_mutate_the_shared_body_table():
    before = dict(air_purifier._SENSING_MODE_BODIES["auto_purify"])
    _, body = air_purifier._sensing_mode_write("auto_purify", {})
    body["x.com.samsung.da.autoExeState"] = "clobbered"
    assert air_purifier._SENSING_MODE_BODIES["auto_purify"] == before


def test_interval_is_minutes_in_the_ui_and_seconds_on_the_wire():
    assert air_purifier._interval_minutes("600") == 10
    assert air_purifier._interval_minutes(None) is None
    assert air_purifier._interval_write(10, {})[1] == {
        "x.com.samsung.da.periodicSensingInterval": "600"
    }


def test_skip_time_splits_the_hhmmhhmm_window():
    read_start = air_purifier._skip_time_read("start")
    read_end = air_purifier._skip_time_read("end")
    # Issue #190's unit ships a real window: 03:00-23:00.
    assert read_start("03002300") == datetime.time(3, 0)
    assert read_end("03002300") == datetime.time(23, 0)
    # Issue #84's unit sits at the inert default.
    assert read_start("00000000") == datetime.time(0, 0)
    # Junk and short strings read as unknown rather than raising.
    assert read_start("") is None
    assert read_start("99999999") is None
    assert read_end("0300") is None


def test_skip_time_write_preserves_the_other_half():
    rep = {"x.com.samsung.da.periodicSensingSkipTime": "03002300"}
    _, body = air_purifier._skip_time_write("start")(datetime.time(7, 30), rep)
    assert body == {"x.com.samsung.da.periodicSensingSkipTime": "07302300"}
    _, body = air_purifier._skip_time_write("end")(datetime.time(22, 5), rep)
    assert body == {"x.com.samsung.da.periodicSensingSkipTime": "03002205"}
    # A board that has never had a window set still round-trips.
    _, body = air_purifier._skip_time_write("end")(datetime.time(1, 2), {})
    assert body == {"x.com.samsung.da.periodicSensingSkipTime": "00000102"}


def test_periodic_sensing_and_skip_switch_bodies():
    assert air_purifier._periodic_sensing_write("On", {})[1] == {
        "x.com.samsung.da.periodicSensingActivationState": "On"
    }
    assert air_purifier._periodic_sensing_write("Off", {})[1] == {
        "x.com.samsung.da.periodicSensingActivationState": "Off"
    }
    assert air_purifier._skip_status_write("On", {})[1] == {
        "x.com.samsung.da.periodicSensingSkipStatus": "On"
    }


def test_last_sensing_time_reads_as_utc():
    state = _state("air_purifier_avt_ww")
    assert state["last_air_sensing_time"].tzinfo is not None
    assert state["last_air_sensing_time"].year >= 2020


def test_read_only_keys_match_the_range_hood_capability():
    """Same href, same fields -- the keys are shared deliberately so both
    families read from one translation catalog entry. If either side renames
    one, this catches the drift."""
    from custom_components.localthings.registry.capabilities import range_hood

    hood = {d.key for d in range_hood.AIR_LEVEL_CHECK.entities}
    ours = {d.key for d in air_purifier.AIR_LEVEL_CHECK.entities}
    assert {
        "air_sensing_state",
        "last_air_sensing_time",
        "last_air_sensing_level",
        "periodic_air_sensing",
    } <= hood & ours


def test_periodic_air_sensing_is_writable_here_and_read_only_on_hoods():
    """The reason range_hood.AIR_LEVEL_CHECK is not imported directly: the hood
    models this key as a read-only BinarySensorDesc, this board needs a
    writable SwitchDesc. Reusing the hood's capability would migrate every hood
    user's entity to a different platform."""
    from custom_components.localthings.registry.capabilities import range_hood
    from custom_components.localthings.registry.entities import BinarySensorDesc, SwitchDesc

    hood = next(d for d in range_hood.AIR_LEVEL_CHECK.entities if d.key == "periodic_air_sensing")
    assert isinstance(hood, BinarySensorDesc)
    ours = _desc("periodic_air_sensing")
    assert isinstance(ours, SwitchDesc)
    assert ours.write_fn is not None
