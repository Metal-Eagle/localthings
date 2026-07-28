"""Tests for Samsung air-conditioner support (issue #17).

These stay HA-free like the rest of the suite: they exercise the registry,
discovery/flatten, and the CLIMATE capability's write contract. The composite
climate entity itself lives in climate.py (imports homeassistant) and is not
importable here -- consistent with how the other HA platform files are untested.
"""
from custom_components.localthings.registry.adapter import flatten
from custom_components.localthings.registry.by_type import for_device, for_device_by_model
from custom_components.localthings.registry.capabilities import airconditioner
from custom_components.localthings.registry.discovery import discover
from custom_components.localthings.registry.entities import ClimateDesc, SelectDesc

from tests.conftest import _load_device


def _ac():
    resources = _load_device('airconditioner')
    info = resources['/information/vs/0']
    reg = for_device_by_model(
        info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'],
    )
    return reg, resources


def _resolve(name):
    """Mirror the coordinator's detection order: oneUiVersion first, modelNum
    fallback second (needed for issue #37's board, which reports neither
    oneUiVersion nor a '_PRAC_' modelNum token)."""
    resources = _load_device(name)
    otn = resources.get('/otninformation/vs/0', {})
    one_ui = otn.get('swVersionInfo', {}).get('oneUiVersion', '')
    info = resources['/information/vs/0']
    reg = for_device(one_ui) if one_ui else None
    if reg is None:
        reg = for_device_by_model(
            info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'],
        )
    return reg, resources


def _bound():
    reg, resources = _ac()
    return discover(resources, reg.capabilities, reg.pattern_capabilities), resources


def _state():
    bound, resources = _bound()
    return flatten(bound, resources)


def test_ac_model_resolves_to_airconditioner_registry():
    reg, _ = _ac()
    assert reg is not None and reg.name == 'airconditioner'


def test_no_unbound_hrefs():
    """Every resource in the issue #17 dump binds or is covered -- clears the
    coverage-gap repair."""
    reg, resources = _ac()
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_climate_entity_is_bound():
    """The composite climate entity binds the primary /mode/vs/0 resource."""
    bound, _ = _bound()
    climate = [b for b in bound if isinstance(b.desc, ClimateDesc)]
    assert len(climate) == 1
    assert climate[0].href == '/mode/vs/0'


def test_expected_state_keys_present():
    state = _state()
    for key in ('climate', 'air_purify', 'auto_clean', 'air_filter_status',
                'air_filter_usage', 'diagnosis_status', 'alarm_code', 'energy_kwh'):
        assert key in state, key


def test_power_and_convenient_folded_into_climate():
    """On/off is the climate entity's HVACMode.OFF and convenient mode is its
    preset_mode -- neither surfaces as a standalone switch/select."""
    state = _state()
    assert 'power_switch' not in state
    assert 'convenient_mode' not in state


def test_air_filter_usage_is_percentage_of_capacity():
    """filterUsage is a raw count in the capacity unit (100 of 500), surfaced as
    a percentage rather than the misleading raw value."""
    assert _state()['air_filter_usage'] == 20


def test_climate_write_targets():
    """The CLIMATE write_fn maps each (kind, value) command to the right vendor
    POST target and body. `value` is already the raw device code. Power and
    temperature target the vendor /power/vs/0 and /temperatures/vs/0 (the OCF
    /power/0 is absent on most boards and a non-authoritative mirror where
    present; /temperature/desired/0 is only written via the temperature_ocf
    kind, on boards that have the OCF pair)."""
    write = airconditioner.CLIMATE.entities[0].write_fn
    assert write(('power', True), {}) == (
        ['power', 'vs', '0'], {'x.com.samsung.da.power': 'On'})
    assert write(('power', False), {}) == (
        ['power', 'vs', '0'], {'x.com.samsung.da.power': 'Off'})
    assert write(('mode', 'Heat'), {}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.modes': ['Heat']})
    # OCF-pair boards: temperature_ocf -> /temperature/desired/0.
    assert write(('temperature_ocf', 23.6), {}) == (
        ['temperature', 'desired', '0'], {'temperature': 24})
    # Vendor boards: temperature -> /temperatures/vs/0, carrying only the id
    # and the changed field -- the device merges current/min/max/unit itself
    # (see common.merge_items_field, wired into async_send_command, for the
    # read-side half that keeps the optimistic cache complete).
    assert write(('temperature', 22), {}) == (
        ['temperatures', 'vs', '0'],
        {'x.com.samsung.da.items': [
            {'x.com.samsung.da.id': '0', 'x.com.samsung.da.desired': '22'}]})
    assert write(('fan', '2'), {}) == (
        ['wind', 'strength', 'vs', '0'], {'x.com.samsung.da.modes': '2'})
    assert write(('swing', 'All'), {}) == (
        ['wind', 'direction', 'vs', '0'], {'x.com.samsung.da.modes': 'All'})
    assert write(('preset', 'Sleep'), {}) == (
        ['mode', 'convenient', 'vs', '0'], {'x.com.samsung.da.modes': 'Sleep'})
    assert write(('bogus', 1), {}) is None


def test_climate_consumed_hrefs_declared_as_coverage():
    """The climate-consumed and ambiguous hrefs are declared in the AC registry
    (as no-entity coverage caps) so they don't leak as gaps -- but produce no
    standalone entities. /temperature/current/0 and /temperatures/vs/0 are
    NOT in this list -- CURRENT_TEMPERATURE / CURRENT_TEMPERATURE_VS give
    those two real sensor entities (issue #75). /sensors/vs/0 is also NOT
    here -- AIR_QUALITY gives it real entity sensors."""
    reg, _ = _ac()
    for href in ('/power/0', '/power/vs/0', '/temperature/desired/0',
                 '/wind/strength/vs/0', '/mode/convenient/vs/0',
                 '/humidity/0'):
        caps = reg.capabilities.get(href)
        assert caps, href
        assert all(c.entities == () for c in caps), href


# ---------------------------------------------------------------------------
# TP1X_DA-AC-RAC-01011 (oneUiVersion "7.0 Air conditioner", Tizen Lite) -- a
# newer model class than the ARTIK051_PRAC dump above. It has no OCF-standard
# /temperature/current+desired pair (temperature lives on the vendor
# /temperatures/vs/0 items[] resource), exposes a /light/vs/0 display light, and
# carries extra vendor housekeeping hrefs. Issue #17 for this class (PR #36).
# ---------------------------------------------------------------------------

def _ac_tp1x():
    resources = _load_device('airconditioner_tp1x_da_ac_rac_01011')
    one_ui = resources['/otninformation/vs/0']['swVersionInfo']['oneUiVersion']
    return for_device(one_ui), resources


def test_tp1x_resolves_to_airconditioner_registry():
    reg, _ = _ac_tp1x()
    assert reg is not None and reg.name == 'airconditioner'


def test_tp1x_no_unbound_hrefs():
    """Every resource in the TP1X dump binds or is covered -- including
    /temperatures/vs/0, /light/vs/0 and the housekeeping hrefs absent from
    the ARTIK051 dump. Clears the coverage-gap repair."""
    reg, resources = _ac_tp1x()
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_tp1x_display_light_switch_present():
    """/light/vs/0 (mode On/Off) surfaces as the display-light switch."""
    reg, resources = _ac_tp1x()
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert state.get('display_light') is True  # device reports mode == 'On'


def test_tp1x_vendor_temperature_and_light_covered():
    """The vendor temperature resource (read by the climate entity) and the
    display-light resource both resolve in the registry -- no gap."""
    reg, _ = _ac_tp1x()
    assert reg.capabilities.get('/temperatures/vs/0'), '/temperatures/vs/0'
    assert reg.capabilities.get('/light/vs/0'), '/light/vs/0'


def test_tp1x_climate_entity_is_bound():
    """The composite climate entity still binds the primary /mode/vs/0."""
    reg, resources = _ac_tp1x()
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    climate = [b for b in bound if isinstance(b.desc, ClimateDesc)]
    assert len(climate) == 1 and climate[0].href == '/mode/vs/0'


def test_tp2x_rac_20k_model_resolves_via_model_fallback():
    """TP2X_RAC_20K (issue #37) reports no oneUiVersion and no '_PRAC_' token
    -- resolved via the '_RAC_' modelNum fallback added for this device."""
    reg, _ = _resolve('airconditioner_tp2x_rac_20k')
    assert reg is not None and reg.name == 'airconditioner'


def test_tp2x_rac_20k_no_unbound_hrefs():
    reg, resources = _resolve('airconditioner_tp2x_rac_20k')
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_tp1x_rac_model_resolves_via_one_ui_version():
    """TP1X_DA-AC-RAC-01001_0000 (issue #38) self-reports oneUiVersion
    '7.0 Air conditioner' -- resolved via for_device(), not the modelNum
    fallback."""
    reg, _ = _resolve('airconditioner_tp1x_rac')
    assert reg is not None and reg.name == 'airconditioner'


def test_tp1x_rac_no_unbound_hrefs():
    reg, resources = _resolve('airconditioner_tp1x_rac')
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_tp1x_rac_expected_state_keys_present():
    reg, resources = _resolve('airconditioner_tp1x_rac')
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    state = flatten(bound, resources)
    for key in ('climate', 'display_light', 'mute_once', 'selfcheck_status',
                'selfcheck_result', 'current_limit_enabled', 'current_limit_level'):
        assert key in state, key


def test_caww_tp2_model_resolves_via_model_fallback():
    """A-CAWW-TP2-20-COMMON (issue #52, System AC) reports no oneUiVersion
    and no '_RAC_'/'_PRAC_' token -- resolved via the '-CAWW-' modelNum
    fallback added for this device."""
    reg, _ = _resolve('airconditioner_caww_tp2')
    assert reg is not None and reg.name == 'airconditioner'


def test_caww_tp2_no_unbound_hrefs():
    """Every resource in the issue #52 dump binds or is ignored -- clears
    the coverage-gap repair. Only new href beyond the existing RAC/PRAC
    surface is /sac/installationinfo/vs/0 (opaque SAC installation topology,
    ignored)."""
    reg, resources = _resolve('airconditioner_caww_tp2')
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_caww_tp2_sac_installationinfo_is_ignored():
    ignored_hrefs = {cap.href for cap in airconditioner.COVERAGE}
    assert '/sac/installationinfo/vs/0' in ignored_hrefs


def test_mute_once_write_target():
    write = airconditioner.MUTE_ONCE.entities[0].write_fn
    assert write('On', {}) == (['option', 'muteonce', 'vs', '0'], {'muteonce': 'On'})
    assert write('Off', {}) == (['option', 'muteonce', 'vs', '0'], {'muteonce': 'Off'})


def test_display_light_write_target():
    write = airconditioner.DISPLAY_LIGHT.entities[0].write_fn
    assert write('On', {}) == (['light', 'vs', '0'], {'mode': 'On'})
    assert write('Off', {}) == (['light', 'vs', '0'], {'mode': 'Off'})


def test_current_limit_is_read_only():
    """Meaning/write contract for the current-limit levels isn't confirmed
    from the dump alone -- exposed as read-only diagnostic sensors rather
    than a guessed writable control."""
    for desc in airconditioner.CURRENT_LIMIT.entities:
        assert getattr(desc, 'write_fn', None) is None


# ---------------------------------------------------------------------------
# TP1X_DA-AC-RAC-01001 cool-only global variant (issue #91). Same modelNum as
# the issue #38 board above, but its /otninformation/vs/0 ships no
# swVersionInfo block, so oneUiVersion is empty and detection must fall back
# to the hyphenated '-RAC-' modelNum token (the older '_RAC_' underscore match
# doesn't fire on this DA-AC-RAC spelling). Adds /stepcontrol/vs/0 and
# /remotedeviceinfo/vs/0 (both ignored) and exposes the WindFree preset via
# the Nano/NanoSleep convenient-mode codes. Its panel light is carried inside
# /mode/vs/0's options blob instead of a dedicated /light/vs/0 switch.
# ---------------------------------------------------------------------------

def test_tp1x_rac_coolonly_resolves_via_hyphenated_model_fallback():
    """Empty oneUiVersion -> resolved by the '-RAC-' modelNum token, not
    for_device(). Guards the regression where this unit loaded as 'unknown'."""
    resources = _load_device('airconditioner_tp1x_rac_coolonly')
    otn = resources.get('/otninformation/vs/0', {})
    assert otn.get('swVersionInfo', {}).get('oneUiVersion', '') == ''
    reg, _ = _resolve('airconditioner_tp1x_rac_coolonly')
    assert reg is not None and reg.name == 'airconditioner'


def test_tp1x_rac_coolonly_no_unbound_hrefs():
    """Every resource binds or is ignored -- including the two hrefs unique
    to this dump (/stepcontrol/vs/0, /remotedeviceinfo/vs/0). Clears the gap
    repair."""
    reg, resources = _resolve('airconditioner_tp1x_rac_coolonly')
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_tp1x_rac_coolonly_stray_hrefs_ignored():
    ignored_hrefs = {cap.href for cap in airconditioner.COVERAGE}
    assert '/stepcontrol/vs/0' in ignored_hrefs
    assert '/remotedeviceinfo/vs/0' in ignored_hrefs


def test_tp1x_rac_coolonly_climate_bound():
    reg, resources = _resolve('airconditioner_tp1x_rac_coolonly')
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    climate = [b for b in bound if isinstance(b.desc, ClimateDesc)]
    assert len(climate) == 1 and climate[0].href == '/mode/vs/0'


def test_tp1x_rac_coolonly_display_light_from_mode_options():
    """This board has no /light/vs/0 switch; the panel light lives in
    /mode/vs/0's options and surfaces as a display_light switch. The token is
    inverted vs its name (confirmed by a live toggle test): with the panel
    lit the option reads `Light_Off`, and with it dark it reads `Light_On`."""
    reg, resources = _resolve('airconditioner_tp1x_rac_coolonly')
    state = flatten(discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert state.get('display_light') is True


def test_display_light_option_parsing_and_gating():
    # Inverted token: Light_Off -> panel lit (on), Light_On -> panel dark (off).
    lit = {'x.com.samsung.da.options': ['CoolCapa_35', 'Light_Off', 'Volume_Mute']}
    dark = {'x.com.samsung.da.options': ['Light_On']}
    absent = {'x.com.samsung.da.options': ['Volume_Mute']}
    assert airconditioner._display_light_on(lit) is True
    assert airconditioner._display_light_on(dark) is False
    assert airconditioner._display_light_on(absent) is None
    assert airconditioner._has_display_light_option(lit, {}) is True
    assert airconditioner._has_display_light_option(absent, {}) is False


def test_mode_options_display_light_write_is_inverted_single_token():
    """Turning the lamp ON writes the inverted 'Light_Off' token as a
    single-element options list (single-token merge); OFF writes 'Light_On'."""
    sw = next(e for e in airconditioner.CLIMATE.entities if e.key == 'display_light')
    assert sw.write_fn('On', {}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Light_Off']})
    assert sw.write_fn('Off', {}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Light_On']})


def test_light_switch_board_gates_out_mode_options_light():
    """Boards with a real /light/vs/0 switch carry no Light_* option, so the
    mode-options display-light entity doesn't double up (mutually exclusive
    encodings)."""
    reg, resources = _resolve('airconditioner_tp1x_rac')
    assert airconditioner._has_display_light_option(resources['/mode/vs/0'], resources) is False


# ---------------------------------------------------------------------------
# WindFree unit (issue #75): same ARTIK051_PRAC_20K modelNum family as the
# original issue #17 fixture, but its /mode/convenient/vs/0 additionally
# supports Nano/NanoSleep/MotionDirect/MotionIndirect, /wind/direction/vs/0
# additionally supports Left_And_Right, and /humidity/vs/0's
# fivepercentHumidity is populated (unlike the all-zero original dump).
# ---------------------------------------------------------------------------

def _ac_windfree():
    resources = _load_device('airconditioner_windfree')
    info = resources['/information/vs/0']
    reg = for_device_by_model(
        info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'],
    )
    return reg, resources


def test_windfree_no_unbound_hrefs():
    reg, resources = _ac_windfree()
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_windfree_humidity_and_temperature_sensors_present():
    reg, resources = _ac_windfree()
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    state = flatten(bound, resources)
    assert state['humidity'] == 42.0        # fivepercentHumidity, not the stuck humidity=0 field
    assert state['current_temperature_c'] == 27.0


def test_current_temperature_vs_only_binds_when_ocf_href_absent():
    """CURRENT_TEMPERATURE_VS's match_fn must not double-bind alongside
    CURRENT_TEMPERATURE when a device (like this one) reports both
    /temperature/current/0 and /temperatures/vs/0."""
    match = airconditioner.CURRENT_TEMPERATURE_VS.match_fn
    assert match({}, {'/temperature/current/0': {}}) is False
    assert match({}, {}) is True


def test_humidity_reads_five_percent_field_not_stuck_humidity_field():
    desc = airconditioner.HUMIDITY.entities[0]
    rep = {'x.com.samsung.da.humidity': '0', 'x.com.samsung.da.fivepercentHumidity': '42'}
    assert desc.rep_fn(rep) == 42.0


def test_humidity_falls_back_to_the_plain_field_where_five_percent_is_absent():
    """ARTIK051 boards (issue #136) have no fivepercentHumidity field at all.
    Their plain field is not stuck -- it carries a reading while Air monitoring
    is on -- so 0 means "not measuring" on both generations, not 0% humidity."""
    desc = airconditioner.HUMIDITY.entities[0]
    assert desc.rep_fn({'x.com.samsung.da.humidity': '51'}) == 51.0
    assert desc.rep_fn({'x.com.samsung.da.humidity': '0'}) is None
    assert desc.rep_fn({}) is None


def test_humidity_five_percent_field_passes_a_genuine_zero_through():
    """issue #160: fivepercentHumidity's zero-as-"not measuring" carve-out
    (added in #146 to cover ARTIK051's plain humidity field) was
    over-applied to fivepercentHumidity too, silently turning a real 0%
    reading on every other AC board into unknown. Only the humidity
    fallback field collapses 0 -- fivepercentHumidity's 0 is a real
    reading."""
    desc = airconditioner.HUMIDITY.entities[0]
    assert desc.rep_fn({'x.com.samsung.da.fivepercentHumidity': '0'}) == 0.0


# ---------------------------------------------------------------------------
# Wind-Free 2-in-1 (TP2X_FAC_BORA_21K, issues #150/#153): a floor-standing +
# wall-mounted indoor unit pair sharing one outdoor unit and one local IP.
# Reported "no climate entity is generated, only power" -- the device simply
# fell back to 'unknown' for lack of a '_FAC_' modelNum routing token; once
# routed, it binds against the exact same CLIMATE composite every other RAC
# family uses, zero unbound hrefs, no new capabilities needed beyond ignoring
# the two hrefs (/subdevices/vs/0, /runn/vs/0) unique to this board.
# ---------------------------------------------------------------------------

def _ac_fac_bora():
    resources = _load_device('airconditioner_fac_bora')
    info = resources['/information/vs/0']
    reg = for_device_by_model(
        info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'],
    )
    return reg, resources


def test_fac_bora_resolves_to_airconditioner_registry():
    reg, _ = _ac_fac_bora()
    assert reg is not None and reg.name == 'airconditioner'


def test_fac_bora_no_unbound_hrefs():
    reg, resources = _ac_fac_bora()
    unbound = []
    discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
    assert unbound == []


def test_fac_bora_climate_entity_present():
    """The actual reported gap: only a power switch existed before, no
    climate entity at all."""
    reg, resources = _ac_fac_bora()
    bound = discover(resources, reg.capabilities, reg.pattern_capabilities)
    assert any(isinstance(item.desc, ClimateDesc) for item in bound)


def test_fac_bora_subdevices_and_runningmode_are_ignored_not_guessed():
    assert '/subdevices/vs/0' in airconditioner._AC_IGNORED
    assert '/runn/vs/0' in airconditioner._AC_IGNORED


# ---------------------------------------------------------------------------
# Additive entities layered on the ARTIK051_PRAC family on top of the upstream
# registry: beep (Volume_* option), tropical night mode (Sleep_<N> option),
# filter usage hours + alarm threshold (filterUsage / filterDesiredUsage),
# air-quality sensors (/sensors/vs/0 items), and software/firmware version
# (/information/vs/0 items). Beep and tropical night use the single-token
# option_write merge -- a full options RMW reverts on ARTIK051_PRAC (see the
# [[samsung-ac-local-vs-cloud-control]] memory).
# ---------------------------------------------------------------------------

def _beep_desc():
    return next(e for e in airconditioner.CLIMATE.entities if e.key == 'beep')


def _tropical_desc():
    return next(e for e in airconditioner.CLIMATE.entities
                if e.key == 'tropical_night_mode')


def test_beep_read_from_volume_token():
    """Volume_100 (and any non-Mute) -> on; Volume_Mute -> off; no Volume_ slot
    -> None (entity won't bind via exists_fn)."""
    assert airconditioner._beep_on(
        {'x.com.samsung.da.options': ['Volume_100']}) is True
    assert airconditioner._beep_on(
        {'x.com.samsung.da.options': ['Volume_Mute']}) is False
    assert airconditioner._beep_on(
        {'x.com.samsung.da.options': ['Light_Off']}) is None
    assert airconditioner._beep_on({}) is None


def test_beep_write_is_single_token_options_merge():
    """One-element options array, not a full RMW (which reverts on
    ARTIK051_PRAC). 'On' restores the last non-Mute level so an intermediate
    setting (e.g. Volume_50) survives an off/on cycle; falls back to 100 when
    no prior level is known or the prior token is itself Mute."""
    write = _beep_desc().write_fn
    assert write('On', {}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Volume_100']})
    assert write('On', {'x.com.samsung.da.options': ['Volume_50']}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Volume_50']})
    assert write('On', {'x.com.samsung.da.options': ['Volume_Mute']}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Volume_100']})
    assert write('Off', {}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Volume_Mute']})
    assert write('Bogus', {}) is None


def test_beep_absent_when_no_volume_token():
    """TP1X_DA-AC-RAC-01011 carries no Volume_ option -- beep must not bind."""
    reg, resources = _ac_tp1x()
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert 'beep' not in state


def test_beep_state_on_windfree():
    """The WindFree fixture reports Volume_100 -> beep reads True."""
    reg, resources = _ac_windfree()
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert state['beep'] is True


def test_tropical_night_read_from_sleep_token():
    """Sleep_<N> -> N; absent -> None."""
    assert airconditioner._tropical_night_value(
        {'x.com.samsung.da.options': ['Sleep_0']}) == 0
    assert airconditioner._tropical_night_value(
        {'x.com.samsung.da.options': ['Sleep_16']}) == 16
    assert airconditioner._tropical_night_value(
        {'x.com.samsung.da.options': ['Volume_100']}) is None
    assert airconditioner._tropical_night_value({}) is None


def test_tropical_night_write_is_single_token_options_merge():
    """Valid 0-16 -> `['Sleep_<N>']`; out of range / non-numeric -> None (no
    write). Cloud counterpart: custom.airConditionerTropicalNightMode (0-16)."""
    write = _tropical_desc().write_fn
    assert write(0, {}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Sleep_0']})
    assert write(16, {}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Sleep_16']})
    assert write(17, {}) is None
    assert write(-1, {}) is None
    assert write('not-a-number', {}) is None
    # Float rounds to nearest int within range.
    assert write(5.6, {}) == (
        ['mode', 'vs', '0'], {'x.com.samsung.da.options': ['Sleep_6']})


def test_tropical_night_absent_when_no_sleep_token():
    """TP1X_DA-AC-WAC (window AC) carries no Sleep_ option -- tropical night
    mode must not bind."""
    resources = _load_device('airconditioner_window_ac')
    info = resources['/information/vs/0']
    reg = for_device_by_model(
        info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'])
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert 'tropical_night_mode' not in state


def test_tropical_night_state_levels_across_fixtures():
    """Sleep_0 / Sleep_6 / Sleep_16 surface as 0 / 6 / 16 respectively."""
    def level(name):
        res = _load_device(name)
        info = res['/information/vs/0']
        r = for_device_by_model(
            info['x.com.samsung.da.modelNum'], info['x.com.samsung.da.description'])
        return flatten(discover(res, r.capabilities, r.pattern_capabilities), res).get(
            'tropical_night_mode')
    assert level('airconditioner_windfree') == 0
    assert level('airconditioner_tp1x_da_ac_rac_01011') == 6
    assert level('airconditioner_tp2x_rac_20k') == 16


def test_air_filter_usage_hours_reads_raw_count():
    """filterUsage is a lifetime hour counter (41 of 500) that resets on
    filter replacement -- total_increasing, not measurement. Unit comes from
    filterCapacityUnit via unit_fn, not a hardcoded 'h'."""
    desc = next(e for e in airconditioner.AIR_FILTER.entities
                if e.key == 'air_filter_usage_hours')
    assert desc.value_fn('41') == 41
    assert desc.value_fn(41) == 41
    assert desc.value_fn(None) is None
    assert desc.value_fn('not-a-number') is None
    assert desc.device_class == 'duration'
    assert desc.state_class == 'total_increasing'
    assert desc.unit_fn({'x.com.samsung.da.filterCapacityUnit': 'Hour'}) == 'h'
    assert desc.unit_fn({'x.com.samsung.da.filterCapacityUnit': 'Minute'}) == 'min'
    assert desc.unit_fn({}) == 'h'  # static fallback when the field is absent


def test_air_filter_threshold_is_writable_select():
    """filterDesiredUsage is a locally writable option (confirmed live on
    ARTIK051_PRAC: POST 700 -> 2.04, persisted). Exposed as a Select keyed to
    the device's supportedFilterDesiredUsage enum; the write POSTs the scalar
    field back to /filter/airdustfilter/vs/0. Only binds where the enum is
    advertised -- boards without it leave this writable field unexposed rather
    than guess the valid set."""
    desc = next(e for e in airconditioner.AIR_FILTER.entities
                if e.key == 'air_filter_threshold')
    assert isinstance(desc, SelectDesc)
    assert desc.options_field == 'x.com.samsung.da.supportedFilterDesiredUsage'
    assert desc.exists_fn(
        {'x.com.samsung.da.supportedFilterDesiredUsage': ['180', '300', '500', '700']},
        {}) is True
    assert desc.exists_fn({}, {}) is False
    # Current value is stringified for option matching.
    assert desc.value_fn('500') == '500'
    assert desc.value_fn(500) == '500'
    assert desc.value_fn(None) is None
    # Write POSTs the selected option as the scalar field.
    assert desc.write_fn('700', {}) == (
        ['filter', 'airdustfilter', 'vs', '0'],
        {'x.com.samsung.da.filterDesiredUsage': '700'})


def test_air_filter_threshold_absent_without_supported_enum():
    """WindFree (ARTIK051_PRAC) advertises no supportedFilterDesiredUsage, so
    the writable threshold Select must not bind there -- even though the
    scalar field is present and writable. Don't expose a control whose valid
    options aren't known."""
    reg, resources = _ac_windfree()
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert 'air_filter_threshold' not in state
    assert state['air_filter_usage_hours'] == 41
    assert state['air_filter_usage'] == 8  # 41/500 -> 8%


def test_air_filter_threshold_binds_on_enum_board():
    """tp1x_rac advertises supportedFilterDesiredUsage -> threshold Select
    binds, current value read from filterDesiredUsage."""
    reg, resources = _resolve('airconditioner_tp1x_rac')
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert state['air_filter_threshold'] == '500'


def test_air_quality_sensors_from_sensors_vs_items():
    """/sensors/vs/0 items[] surface as diagnostic scalars (no unit advertised
    on the resource, so no device_class until a populated reading + unit is
    observed -- the 'don't guess' rule). CleanLevel is corroborated as numeric
    by a top-level cleanLevel scalar, so it's an int measurement; the others
    are string diagnostics. Dust/FineDust/SuperFineDust carry a 2-element
    array whose second element is unconfirmed -- v[0] is taken as the reading
    (see _sensor_item_value)."""
    reg, resources = _ac_windfree()
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert state['clean_level'] == 0           # numeric (int), corroborated
    for key in ('odor', 'dust', 'fine_dust', 'super_fine_dust'):
        assert state[key] == '0'               # string diagnostic
    # tp1x_da_ac_rac_01011 is the only fixture with a non-zero air-quality
    # reading -- the one that catches a value_fn regression.
    reg2, resources2 = _ac_tp1x()
    state2 = flatten(
        discover(resources2, reg2.capabilities, reg2.pattern_capabilities), resources2)
    assert state2['clean_level'] == 1


def test_air_quality_absent_when_no_sensor_items():
    """A board whose /sensors/vs/0 carries an empty items[] (the cool-only
    RAC variant) binds no air-quality entities -- exists_fn gates each on its
    item type, not merely on the href being present."""
    reg, resources = _resolve('airconditioner_tp1x_rac_coolonly')
    assert '/sensors/vs/0' in resources  # the href is there, just empty
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    for key in ('clean_level', 'odor', 'dust', 'fine_dust', 'super_fine_dust'):
        assert key not in state, key


def test_sensor_item_value_picks_first_value():
    """_sensor_item_value returns the first element of the value list, as a
    string; None when the item is absent or its value is empty."""
    items = [
        {'x.com.samsung.da.type': 'Dust', 'x.com.samsung.da.value': ['0', '0']},
        {'x.com.samsung.da.type': 'Odor', 'x.com.samsung.da.value': []},
    ]
    assert airconditioner._sensor_item_value(items, 'Dust') == '0'
    assert airconditioner._sensor_item_value(items, 'Odor') is None
    assert airconditioner._sensor_item_value(items, 'Missing') is None
    assert airconditioner._sensor_item_value(None, 'Dust') is None


def test_beep_and_tropical_night_stay_off_legacy_krac_board():
    """ARTIK051_KRAC_18K (issue #136) reports both a Volume_ and a Sleep_
    option token, but they're already modeled as buzzer_volume/good_sleep
    (see airconditioner.CLIMATE) -- beep/tropical_night_mode must not also
    bind there, or the same options[] slot would surface as two entities."""
    reg, resources = _resolve('airconditioner_artik051_krac_18k')
    state = flatten(
        discover(resources, reg.capabilities, reg.pattern_capabilities), resources)
    assert 'beep' not in state
    assert 'tropical_night_mode' not in state
    assert state['buzzer_volume'] == 100.0
    assert state['good_sleep'] == 0.0
