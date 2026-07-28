"""Unit tests for the microwave-family capabilities (issue #121/#66 split
into their own device type instead of being folded into oven.py)."""
from custom_components.localthings.registry.by_type import for_device_by_model
from custom_components.localthings.registry.capabilities import microwave
from custom_components.localthings.registry.discovery import discover


# ---------------------------------------------------------------------------
# Device-type detection + full-dump coverage
# ---------------------------------------------------------------------------

def test_microwave_fixture_resolves_and_has_no_unbound_hrefs():
    from tests.conftest import _load_device
    resources = _load_device('microwave_mw7300b')
    info = resources['/information/vs/0']
    reg = for_device_by_model(
        info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'])
    assert reg is not None
    assert reg.name == 'microwave'

    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_microwave_hood_fan_fixture_resolves_and_has_no_unbound_hrefs():
    """Issues #137/#142: `/hood/fanspeed/vs/0` (the combi unit's built-in
    vent fan) was previously unbound on this family."""
    from tests.conftest import _load_device
    resources = _load_device('microwave_me7500d')
    info = resources['/information/vs/0']
    reg = for_device_by_model(
        info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'])
    assert reg is not None
    assert reg.name == 'microwave'

    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


# ---------------------------------------------------------------------------
# MICROWAVE_SETPOINT — NumberDesc with RMW write semantics
# ---------------------------------------------------------------------------

def test_microwave_setpoint_write_is_read_modify_write():
    desc = microwave.MICROWAVE_SETPOINT.entities[0]
    rep = {'x.com.samsung.da.items': [{'x.com.samsung.da.desired': '0'}]}
    path, body = desc.write_fn(180, rep)
    assert path == ['temperatures', 'vs', '0']
    assert body['x.com.samsung.da.items'][0]['x.com.samsung.da.desired'] == '180'


def test_microwave_setpoint_rmw_preserves_other_item_fields():
    desc = microwave.MICROWAVE_SETPOINT.entities[0]
    rep = {'x.com.samsung.da.items': [{
        'x.com.samsung.da.current': '150',
        'x.com.samsung.da.desired': '150',
    }]}
    path, body = desc.write_fn(180, rep)
    item = body['x.com.samsung.da.items'][0]
    assert item['x.com.samsung.da.desired'] == '180'
    assert item['x.com.samsung.da.current'] == '150'


def test_microwave_setpoint_clamps_to_step():
    desc = microwave.MICROWAVE_SETPOINT.entities[0]
    rep = {'x.com.samsung.da.items': [{'x.com.samsung.da.desired': '0'}]}
    _, body = desc.write_fn(182, rep)   # nearest 5 = 180
    assert body['x.com.samsung.da.items'][0]['x.com.samsung.da.desired'] == '180'


def test_microwave_setpoint_rejects_out_of_range():
    desc = microwave.MICROWAVE_SETPOINT.entities[0]
    rep = {'x.com.samsung.da.items': [{'x.com.samsung.da.desired': '100'}]}
    assert desc.write_fn(20, rep) is None     # below min (40)
    assert desc.write_fn(210, rep) is None    # above max (200)


def test_microwave_setpoint_rejects_missing_items():
    desc = microwave.MICROWAVE_SETPOINT.entities[0]
    assert desc.write_fn(180, {}) is None


def test_microwave_setpoint_exists_only_for_celsius():
    """No Fahrenheit dump exists for this family (unlike oven.py's, verified
    against issue #44) -- the writable setpoint stays hidden rather than
    showing unverified bounds under the wrong unit."""
    desc = microwave.MICROWAVE_SETPOINT.entities[0]
    celsius_rep = {'x.com.samsung.da.items': [{'x.com.samsung.da.unit': 'Celsius'}]}
    fahrenheit_rep = {'x.com.samsung.da.items': [{'x.com.samsung.da.unit': 'Fahrenheit'}]}
    assert desc.exists_fn(celsius_rep, {}) is True
    assert desc.exists_fn(fahrenheit_rep, {}) is False


# ---------------------------------------------------------------------------
# MICROWAVE_CAVITY — power_level sensor
# ---------------------------------------------------------------------------

def test_power_level_parses_watt_suffix():
    """Issue #121's combi dump reports e.g. '0W'."""
    desc = next(e for e in microwave.MICROWAVE_CAVITY.entities if e.key == 'power_level')
    assert desc.value_fn('900W') == 900


def test_power_level_parses_bare_number():
    """Issue #137's plain microwave reports the bare number, no 'W' suffix."""
    desc = next(e for e in microwave.MICROWAVE_CAVITY.entities if e.key == 'power_level')
    assert desc.value_fn('0') == 0


def test_power_level_handles_missing_value():
    desc = next(e for e in microwave.MICROWAVE_CAVITY.entities if e.key == 'power_level')
    assert desc.value_fn(None) is None


# ---------------------------------------------------------------------------
# MICROWAVE_MODE — SelectDesc with non-empty, family-specific options
# ---------------------------------------------------------------------------

def test_microwave_mode_options_nonempty():
    desc = microwave.MICROWAVE_MODE.entities[0]
    assert len(desc.options) > 0
    assert 'MicroWave' in desc.options
    assert 'AirFryer' in desc.options   # distinct spelling from oven.py's 'AirFry'


def test_microwave_mode_write_round_trips():
    desc = microwave.MICROWAVE_MODE.entities[0]
    path, body = desc.write_fn('MicroWave', {})
    assert path == ['mode', 'vs', '0']
    assert body['x.com.samsung.da.modes'] == ['MicroWave']


def test_microwave_mode_rejects_unknown():
    desc = microwave.MICROWAVE_MODE.entities[0]
    assert desc.write_fn('SpaghettiMode', {}) is None


# ---------------------------------------------------------------------------
# MICROWAVE_MODE — lamp/sound options-array writes
# ---------------------------------------------------------------------------

def test_sound_write_is_single_token():
    desc = next(e for e in microwave.MICROWAVE_MODE.entities if e.key == 'sound')
    rep = {'x.com.samsung.da.options': ['Sound_On']}
    path, body = desc.write_fn('Off', rep)
    assert path == ['mode', 'vs', '0']
    assert body == {'x.com.samsung.da.options': ['Sound_Off']}


def test_lamp_gated_absent_when_no_lamp_option():
    """Issue #121's combi dump has no 'Lamp_*' token at all -- unlike
    oven.py's lamp switch (assumed universal), this one self-gates off."""
    desc = next(e for e in microwave.MICROWAVE_MODE.entities if e.key == 'lamp')
    rep = {'x.com.samsung.da.options': ['DeviceType_MW7300B-/EU1', 'Sound_Off']}
    assert desc.exists_fn(rep, {}) is False


def test_lamp_gated_present_when_lamp_option_reported():
    """Issue #137's plain microwave reports 'Lamp_Off'."""
    desc = next(e for e in microwave.MICROWAVE_MODE.entities if e.key == 'lamp')
    rep = {'x.com.samsung.da.options': ['Lamp_Off', 'Sound_On']}
    assert desc.exists_fn(rep, {}) is True


def test_lamp_write_is_single_token():
    """issue #152: the device has never been observed accepting 'On' --
    only 'High'/'Off' -- so the switch's "on" write uses 'High'."""
    desc = next(e for e in microwave.MICROWAVE_MODE.entities if e.key == 'lamp')
    rep = {'x.com.samsung.da.options': ['Lamp_Off']}
    path, body = desc.write_fn('On', rep)
    assert path == ['mode', 'vs', '0']
    assert body == {'x.com.samsung.da.options': ['Lamp_High']}


def test_lamp_write_requires_existing_options():
    desc = next(e for e in microwave.MICROWAVE_MODE.entities if e.key == 'lamp')
    assert desc.write_fn('On', {}) is None


def test_lamp_reads_off_as_false():
    desc = next(e for e in microwave.MICROWAVE_MODE.entities if e.key == 'lamp')
    assert desc.value_fn(['Lamp_Off']) is False


def test_lamp_reads_any_non_off_level_as_true():
    """issue #152's ME7500D reports 'Lamp_High', not the binary 'Lamp_On'
    #137's dump implied -- any non-Off/non-absent value must read as on, not
    just a literal 'On'."""
    desc = next(e for e in microwave.MICROWAVE_MODE.entities if e.key == 'lamp')
    assert desc.value_fn(['Lamp_High']) is True
