"""HA fan-entity mapping tests for the A-VTWW-TP2-21-COMMON BESPOKE Cube Air
(issue #151).

This board's /wind/strength/vs/0 reports numeric wind-strength codes
("87"/"89"/"90"/"91") with a separate modesName array ("SMART"/"MAX"/
"WINDFREE"/"Sleep") giving the actual names, unlike the TP1X_DA-AC-AIR
family's /mode/vs/0 (issue #130) where supportedModes IS the name list
already. LocalThingsAirPurifierFan._label_for_code resolves both shapes
without a per-model map.
"""
from custom_components.localthings.fan import LocalThingsAirPurifierFan
from custom_components.localthings.registry.by_type import air_purifier, for_device_by_model
from custom_components.localthings.registry.capabilities.air_purifier import HREF_WIND_STRENGTH
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import FanDesc

from tests.conftest import _load_device


class _FakeCoordinator:
    device_serial = 'TEST-VTWW-SERIAL'
    device_info = {}
    data = {}

    def __init__(self, resources):
        self.last_resources = resources
        self.commands = []

    def resource(self, href):
        return self.last_resources.get(href, {})

    async def async_send_command(self, bound, payload):
        self.commands.append((bound, payload))


def _resources():
    return _load_device('air_purifier_vtww')


def _reg(resources):
    info = resources['/information/vs/0']
    return for_device_by_model(
        info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'])


def _entity(resources, coordinator=None):
    reg = _reg(resources)
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    fan_bound = next(
        item for item in bound
        if isinstance(item.desc, FanDesc) and item.href == HREF_WIND_STRENGTH
    )
    return LocalThingsAirPurifierFan(coordinator or _FakeCoordinator(resources), fan_bound)


def test_resolves_to_air_purifier_registry():
    assert _reg(_resources()).name == 'air_purifier'


def test_no_unbound_hrefs():
    resources = _resources()
    reg = _reg(resources)
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_preset_modes_come_from_modes_name_not_the_raw_codes():
    entity = _entity(_resources())
    assert entity.preset_modes == ['smart', 'max', 'windfree', 'sleep']


def test_preset_mode_reads_the_current_code_via_modes_name():
    """Fixture's current mode is '87' -> modesName[0] 'SMART'."""
    entity = _entity(_resources())
    assert entity.preset_mode == 'smart'


async def test_set_preset_mode_writes_back_the_raw_code():
    resources = _resources()
    coordinator = _FakeCoordinator(resources)
    entity = _entity(resources, coordinator)

    await entity.async_set_preset_mode('windfree')

    assert coordinator.commands[-1][1] == ('mode', '90')


def test_is_on_reads_vendor_power():
    entity = _entity(_resources())
    assert entity.is_on is False
