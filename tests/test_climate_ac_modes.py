"""Tests for the AC HVAC-mode device<->HA map in climate.py (issue #93).

`_DEVICE_TO_HVAC`/`_HVAC_TO_DEVICE` are plain module-level dicts with no
coordinator/entity dependency, so -- like `_temps_vs_item` in
test_climate_temperature_fallback.py -- they're testable directly.
"""
from homeassistant.components.climate import HVACMode

from custom_components.localthings.climate import _DEVICE_TO_HVAC, _HVAC_TO_DEVICE


def test_aicomfort_maps_to_auto():
    """A-CAWW-TP2-20-COMMON (issue #93) reports 'AIComfort' in its
    supportedModes alongside 'Auto' -- a separate AI-driven auto-comfort
    mode, distinct from the existing 'Auto' -> HEAT_COOL entry."""
    assert _DEVICE_TO_HVAC['AIComfort'] == HVACMode.AUTO


def test_auto_still_maps_to_heat_cool():
    """'AIComfort' is additive -- the existing 'Auto' -> HEAT_COOL mapping
    (a different device code) is unchanged."""
    assert _DEVICE_TO_HVAC['Auto'] == HVACMode.HEAT_COOL


def test_hvac_auto_writes_back_aicomfort():
    """Reverse map: selecting HA's Auto hvac_mode writes the 'AIComfort'
    device code, not 'Auto' (which is reserved for HEAT_COOL)."""
    assert _HVAC_TO_DEVICE[HVACMode.AUTO] == 'AIComfort'


def test_fan_only_still_reachable_via_wind():
    """Guard against regressing the existing 'Wind' -> FAN_ONLY entry while
    editing this map."""
    assert _DEVICE_TO_HVAC['Wind'] == HVACMode.FAN_ONLY
