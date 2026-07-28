"""TP1X_DA-AC-RAC-01001_0000 fan-strength codes (model AR07C9150HZN, issue
#155).

Its /wind/strength/vs/0 reports supportedModes "0"/"31"/"32"/"33"/"34"/"35"
instead of the "0"-"4" scale climate.py's _DEVICE_TO_FAN was built from
(every other AC fixture in this repo uses "0"-"4", some with a 6th "5" --
see airconditioner_window_ac_device.json). Only "0" matched _DEVICE_TO_FAN,
so fan_modes silently dropped every speed but Auto. The fix reads the
device's own modesName labels (parallel-indexed with supportedModes) for
any code _DEVICE_TO_FAN doesn't already cover, instead of hardcoding a
second numeric scale.
"""
from custom_components.localthings.climate import (
    LocalThingsClimate, _DEVICE_TO_FAN, _wind_strength_label,
)
from custom_components.localthings.registry import by_type
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import ClimateDesc

from tests.conftest import _load_device

FIXTURE = 'airconditioner_tp1x_rac_01001'


class _FakeCoordinator:
    device_serial = 'TEST-RAC-01001-SERIAL'
    device_info = {}
    data = {}

    def __init__(self, resources):
        self.last_resources = resources
        self.commands = []

    def resource(self, href):
        return self.last_resources.get(href, {})

    async def async_send_command(self, bound, payload):
        self.commands.append((bound, payload))


def _climate(resources, coordinator=None):
    info = resources['/information/vs/0']
    reg = by_type.for_device_by_model(
        info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'])
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    climate_bound = next(item for item in bound if isinstance(item.desc, ClimateDesc))
    return LocalThingsClimate(coordinator or _FakeCoordinator(resources), climate_bound)


def test_wind_strength_label_reads_the_devices_own_modes_name():
    rep = {
        'x.com.samsung.da.supportedModes': ['0', '31', '32', '33', '34', '35'],
        'x.com.samsung.da.modesName': ['Auto', '1', '2', '3', '4', 'MAX'],
    }
    assert _wind_strength_label('32', rep) == '2'
    assert _wind_strength_label('35', rep) == 'max'


def test_wind_strength_label_falls_back_to_raw_code_when_names_absent():
    assert _wind_strength_label('32', {}) == '32'


def test_fan_modes_include_every_supported_speed_not_just_auto():
    """Before the fix, only '0' matched _DEVICE_TO_FAN and fan_modes was
    ['auto'] -- exactly the reported symptom."""
    resources = _load_device(FIXTURE)
    entity = _climate(resources)
    assert entity.fan_modes == ['auto', '1', '2', '3', '4', 'max']


def test_fan_mode_reads_the_current_dynamic_code():
    """Fixture's /wind/strength/vs/0 modes is '32' -> modesName '2'."""
    resources = _load_device(FIXTURE)
    entity = _climate(resources)
    assert entity.fan_mode == '2'


def test_standard_scale_codes_still_use_device_to_fan():
    """A code _DEVICE_TO_FAN already covers keeps its existing friendly
    label rather than falling through to the device's own (blunter) one --
    no regression for boards using the standard "0"-"4" scale."""
    resources = _load_device(FIXTURE)
    resources['/wind/strength/vs/0']['x.com.samsung.da.modes'] = '0'
    entity = _climate(resources)
    assert entity.fan_mode == _DEVICE_TO_FAN['0'] == 'auto'


async def test_set_fan_mode_resolves_a_dynamic_label_back_to_its_code():
    resources = _load_device(FIXTURE)
    coordinator = _FakeCoordinator(resources)
    entity = _climate(resources, coordinator)

    await entity.async_set_fan_mode('max')

    assert coordinator.commands[-1][1] == ('fan', '35')


async def test_set_fan_mode_still_resolves_standard_scale_labels():
    resources = _load_device(FIXTURE)
    coordinator = _FakeCoordinator(resources)
    entity = _climate(resources, coordinator)

    await entity.async_set_fan_mode('auto')

    assert coordinator.commands[-1][1] == ('fan', '0')
