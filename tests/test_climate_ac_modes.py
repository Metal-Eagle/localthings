"""Tests for the AC HVAC-mode/preset device<->HA maps in climate.py (issue #93).

Module-level dicts/constants with no coordinator/entity dependency, so --
like `_temps_vs_item` in test_climate_temperature_fallback.py -- they're
testable directly.
"""
from homeassistant.components.climate import HVACMode

from custom_components.localthings.climate import (
    _AI_COMFORT_MODE, _DEVICE_TO_HVAC, _HVAC_TO_DEVICE, PRESET_AI_COMFORT,
    _preset_to_ha,
)


def test_auto_maps_to_hvac_auto():
    """The device's 'Auto' is a single-setpoint "device decides" mode -> HA
    HVACMode.AUTO, not HEAT_COOL (issue #91 review): HEAT_COOL implies a
    two-setpoint heat+cool range these single-setpoint units (including
    cool-only models) don't have. AIComfort is handled separately, not
    folded into this map."""
    assert _DEVICE_TO_HVAC['Auto'] == HVACMode.AUTO


def test_aicomfort_not_in_flat_hvac_map():
    """AIComfort isn't a flat _DEVICE_TO_HVAC entry -- it's an AI overlay on
    top of 'Auto', modeled as hvac_mode=AUTO + a dedicated preset instead of
    a distinct HVACMode value (see the climate.py module comment)."""
    assert _AI_COMFORT_MODE not in _DEVICE_TO_HVAC


def test_hvac_auto_writes_back_to_plain_auto_not_aicomfort():
    """HVACMode.AUTO is reachable via async_set_hvac_mode -- it writes the
    device's plain 'Auto' code. AIComfort stays reachable only through the
    ai_comfort preset, since it isn't a flat _DEVICE_TO_HVAC entry (see
    test_aicomfort_not_in_flat_hvac_map) and so can never win the reverse
    {v: k} dict even though both map to HVACMode.AUTO conceptually."""
    assert _HVAC_TO_DEVICE[HVACMode.AUTO] == 'Auto'


def test_fan_only_still_reachable_via_wind():
    """Guard against regressing the existing 'Wind' -> FAN_ONLY entry while
    editing this map."""
    assert _DEVICE_TO_HVAC['Wind'] == HVACMode.FAN_ONLY


def test_fan_only_still_reachable_via_fan():
    """'Fan' (e.g. TP1X_DA-AC-RAC-01011) is a second FAN_ONLY spelling
    alongside 'Wind' -- issue #91."""
    assert _DEVICE_TO_HVAC['Fan'] == HVACMode.FAN_ONLY


def test_fan_only_reverse_fallback_prefers_wind():
    """_device_code_for_hvac() resolves FAN_ONLY from a unit's own
    supportedModes first, so _HVAC_TO_DEVICE is only a fallback for a unit
    reporting no supportedModes at all. That fallback must stay 'Wind' (the
    original single spelling, predating 'Fan') rather than silently
    flipping to whichever of the two duplicate-value entries happens to
    come last in _DEVICE_TO_HVAC."""
    assert _HVAC_TO_DEVICE[HVACMode.FAN_ONLY] == 'Wind'


def test_preset_ai_comfort_constant():
    assert PRESET_AI_COMFORT == 'ai_comfort'


def test_preset_to_ha_off_maps_to_preset_none():
    from homeassistant.components.climate import PRESET_NONE
    assert _preset_to_ha('Off') == PRESET_NONE


def test_preset_to_ha_lowercases_other_codes():
    """Every other device code is exposed as its lowercased self -- resolved
    dynamically, not via a per-model table (issue #91)."""
    assert _preset_to_ha('Sleep') == 'sleep'
    assert _preset_to_ha('NanoSleep') == 'nanosleep'
    assert _preset_to_ha('MotionIndirect') == 'motionindirect'
