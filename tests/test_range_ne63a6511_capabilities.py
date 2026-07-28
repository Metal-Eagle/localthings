"""Tests for the NE63A6511SS/AA range (issue #138) -- same no-/information/vs/0,
no-burner-status shape as issue #74's NE63B8411SS, confirming the existing
range_no_info detection path still resolves this model with zero unbound
hrefs, plus the ConvectionRoast/KeepWarm/BreadProof/AirFryer/Dehydrate/
SelfClean/SteamClean modes this dump's supportedModes adds to oven.OVEN_MODE."""
from custom_components.localthings.registry.adapter import flatten
from custom_components.localthings.registry.by_type import for_device_by_resources
from custom_components.localthings.registry.capabilities import oven
from custom_components.localthings.registry.discovery import discover

from tests.conftest import _load_device


def _range():
    resources = _load_device('range_ne63a6511')
    reg = for_device_by_resources(resources)
    return reg, resources


def _state():
    reg, resources = _range()
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    return flatten(bound, resources)


def test_resolves_to_range_registry():
    reg, _ = _range()
    assert reg is not None and reg.name == 'range'


def test_no_unbound_hrefs():
    reg, resources = _range()
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_expected_entities_present():
    state = _state()
    for key in (
        'power_switch', 'oven_setpoint', 'current_temp_c', 'oven_mode',
        'machine_state', 'door_open', 'cloud_connected', 'child_lock',
        'cooktop_running_state', 'warming_center_state',
    ):
        assert key in state, key


def test_oven_mode_accepts_this_devices_supported_modes():
    """This dump's /mode/vs/0 supportedModes reports ConvectionRoast,
    KeepWarm, BreadProof, AirFryer, Dehydrate, SelfClean, and SteamClean --
    none of which were in oven._OVEN_MODES before issue #138, so writes to
    them were silently rejected even though the device advertises them."""
    desc = oven.OVEN_MODE.entities[0]
    rep = {'x.com.samsung.da.modes': ['NoOperation']}
    for mode in (
        'ConvectionRoast', 'KeepWarm', 'BreadProof', 'AirFryer',
        'Dehydrate', 'SelfClean', 'SteamClean',
    ):
        path, body = desc.write_fn(mode, rep)
        assert path == ['mode', 'vs', '0']
        assert body['x.com.samsung.da.modes'] == [mode]
