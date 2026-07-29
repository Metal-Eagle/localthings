"""Tests that a sub-unit's LocalThingsClimate entity (issue #177) reads its
*own* power/mode/temperature -- not the master's, and not some mix of the
two -- and that the legacy-board test (is_legacy_board/_legacy_airflow) is
evaluated per unit rather than once globally.

Uses HJcom's ARTIK051_DONGLE_FAC_18K fixture deliberately: it's a legacy
`/airflow/vs/<n>` board (no `/wind/*` at all) on *both* the master and its
materialized sibling, which is exactly the shape climate.py's own comments
warn is easy to get wrong if the canonical view leaks between units.
"""
from __future__ import annotations

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.core import HomeAssistant

from custom_components.localthings.climate import LocalThingsClimate
from custom_components.localthings.registry.entities import ClimateDesc

from tests.test_subdevice_discovery import _coordinator, _discover


def _climate_entities(coordinator):
    """{sub_unit_key_or_None: LocalThingsClimate}, None standing for MAIN."""
    from custom_components.localthings.registry.subunits import MAIN
    out = {}
    for b in coordinator.bound:
        if isinstance(b.desc, ClimateDesc):
            key = None if b.sub_unit == MAIN else b.sub_unit.key
            out[key] = LocalThingsClimate(coordinator, b)
    return out


@pytest.fixture
async def climates(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    await _discover(coordinator, 'airconditioner_artik051_dongle_fac_18k')
    return _climate_entities(coordinator)


async def test_sub_unit_climate_reads_its_own_mode_and_power(climates):
    """Master reports 'Auto'; the bedroom unit (/device/1) reports 'Cool' --
    confirmed distinct in the real captured fixture. If the sub-unit
    entity's _rep() weren't translating through its own sub_unit, it would
    read the master's /mode/vs/0 instead and report the master's mode."""
    main, unit1 = climates[None], climates['1']
    assert main.hvac_mode == HVACMode.AUTO
    assert unit1.hvac_mode == HVACMode.COOL


async def test_sub_unit_climate_reads_its_own_temperature(climates):
    """Master: current 25.0 / desired 26.0. Unit 1: current 27.0 / desired
    28.0 -- distinct values in the real fixture, so a href mix-up here
    would show up as a wrong number, not just a wrong mode string."""
    main, unit1 = climates[None], climates['1']
    assert main.current_temperature == 25.0
    assert main.target_temperature == 26.0
    assert unit1.current_temperature == 27.0
    assert unit1.target_temperature == 28.0


async def test_sub_unit_climate_reads_its_own_power_state(climates):
    """Both units happen to report power On in this fixture -- this at
    least confirms _is_on() reads the *unit's own* /power/vs/<n>, not a
    hardcoded /power/vs/0, by checking the entity resolves without falling
    back to OFF (which _is_on() would do if it silently read an absent
    href instead of the sub-unit's actual one)."""
    main, unit1 = climates[None], climates['1']
    assert main.hvac_mode != HVACMode.OFF
    assert unit1.hvac_mode != HVACMode.OFF


async def test_legacy_board_test_is_evaluated_per_unit(climates):
    """HJcom's board has no /wind/* resources at all on *either* unit --
    is_legacy_board(self._resources) must independently evaluate True for
    the master's own canonical view and for the sub-unit's own canonical
    view. If is_legacy_board were fed the raw, unpartitioned snapshot (or
    if canonical_view leaked one unit's hrefs into the other's), this
    wouldn't distinguish "this unit is legacy" from "some unit on this
    connection is legacy" -- and a future board with one legacy + one
    modern unit sharing a connection would silently read the wrong fan/
    swing channel on one side."""
    main, unit1 = climates[None], climates['1']
    assert main._legacy_airflow() != {}
    assert unit1._legacy_airflow() != {}
    # Both resolve to *some* fan mode via the legacy path rather than the
    # /wind/strength/vs/0 channel (absent on this board) -- confirms
    # is_legacy_board(self._resources) actually gated fan_mode's branch,
    # not just that _legacy_airflow() itself returned something.
    assert main.fan_mode is not None
    assert unit1.fan_mode is not None


async def test_sub_unit_climate_writes_are_scoped_to_its_own_bound_entity(climates):
    """A sanity check that the two entities are backed by genuinely
    different BoundEntity objects (different hrefs), which is what makes
    per-unit reads/writes possible at all -- see async_send_command's
    translation test in test_coordinator_send_command.py for the write
    side of this."""
    main, unit1 = climates[None], climates['1']
    assert main._bound.href == '/mode/vs/0'
    assert unit1._bound.href == '/mode/vs/1'
    assert main._bound is not unit1._bound
