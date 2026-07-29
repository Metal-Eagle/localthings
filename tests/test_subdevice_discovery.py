"""End-to-end discovery tests for issue #177's two composite-device
fixtures, against the real LocalThingsCoordinator (not the HA-free
registry-level helpers test_subdevices.py/test_unique_ids.py use) -- this is
what actually exercises _enumerate_subdevices_blocking + _run_discovery
together, including device_info_for/via_device and the "no phantom
/device/2 entities" guarantee.
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings.const import (
    CONF_HOST, CONF_LEAF_CERT_PEM, CONF_LEAF_KEY_PEM, CONF_PORT, DOMAIN,
)
from custom_components.localthings.coordinator import LocalThingsCoordinator
from custom_components.localthings.registry.entities import ClimateDesc
from custom_components.localthings.registry.identity import DeviceIdentity

from tests.conftest import FakeCoapSession, _load_device_full

ENTRY_DATA = {
    CONF_HOST: '10.0.0.177',
    CONF_PORT: 49154,
    CONF_LEAF_CERT_PEM: '-----BEGIN CERTIFICATE-----\nTEST-LEAF\n-----END CERTIFICATE-----',
    CONF_LEAF_KEY_PEM: '-----BEGIN PRIVATE KEY-----\nTEST-LEAF-KEY\n-----END PRIVATE KEY-----',
}


def _coordinator(hass: HomeAssistant) -> LocalThingsCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id='localthings_SUBDEVICE-TEST',
    )
    entry.add_to_hass(hass)
    return LocalThingsCoordinator(hass, entry)


async def _discover(coordinator: LocalThingsCoordinator, name: str) -> None:
    """Run the same two-step sequence _async_update_data's first cycle does
    (enumerate, then discover) against fixture data, without the polling/
    reconnect machinery around it -- see coordinator.py's
    _enumerate_subdevices_blocking/_run_discovery."""
    resources, oic_res, seeds = _load_device_full(name)
    coordinator._session = FakeCoapSession(seeds)
    # _connect_session (skipped here -- the session is pre-set) is what
    # normally populates _identity via read_identity; set it directly with
    # the fixture's real /oic/res so enumeration sees the same links a live
    # read_identity call would have captured.
    coordinator._identity = DeviceIdentity(
        manufacturer='Samsung Electronics', model='', name='', serial=None,
        device_types=(), raw={'/oic/p': {}, '/oic/d': {}, '/oic/res': oic_res},
    )
    merged = await coordinator.hass.async_add_executor_job(
        coordinator._enumerate_subdevices_blocking, resources,
    )
    # Mirror _async_update_data's first-cycle order exactly: discover, then
    # drop the candidates the liveness gate rejected, then apply what's left
    # to the observe/cache layer. The apply has to happen (canonical_resources
    # -- device_info_for, is_legacy_board, ... -- reads the cache, not the
    # dict passed to _run_discovery), but it has to happen *after* the gate,
    # or a rejected slot's reps get frozen into the cache forever. Applying
    # first here would leave this helper testing an ordering production no
    # longer uses.
    coordinator._run_discovery(merged)
    for href, rep in coordinator._live_subdevice_resources(merged).items():
        coordinator._observe.apply(href, rep, source='poll')


def _climate_bound(coordinator, subdevice_key: str):
    from custom_components.localthings.registry.subdevices import MAIN
    for b in coordinator.bound:
        if isinstance(b.desc, ClimateDesc):
            if subdevice_key is None and b.subdevice == MAIN:
                return b
            if subdevice_key is not None and b.subdevice.key == subdevice_key:
                return b
    return None


# ---------------------------------------------------------------------------
# HJcom -- ARTIK051_DONGLE_FAC_18K, Pattern A (indexed siblings)
# ---------------------------------------------------------------------------

async def test_hjcom_materializes_master_and_bedroom_subdevice(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    await _discover(coordinator, 'airconditioner_artik051_dongle_fac_18k')

    assert [su.key for su in coordinator.subdevices] == ['1']

    main_climate = _climate_bound(coordinator, None)
    sub1_climate = _climate_bound(coordinator, '1')
    assert main_climate is not None
    assert sub1_climate is not None
    assert main_climate.href == '/mode/vs/0'
    assert sub1_climate.href == '/mode/vs/1'


async def test_hjcom_device_2_produces_no_entities_at_all(hass: HomeAssistant):
    """HJcom's /device/2 is the unused SmartThings slot (DESIGN-177.md
    section 4): it answers its seed with a full-shaped batch, but every
    climate-state rep on it is empty. It must be recorded as skipped, not
    materialized, and must contribute zero bound entities."""
    coordinator = _coordinator(hass)
    await _discover(coordinator, 'airconditioner_artik051_dongle_fac_18k')

    assert '2' not in [su.key for su in coordinator.subdevices]
    assert any(
        skip.subdevice.kind == 'indexed' and skip.subdevice.key == '2'
        for skip in coordinator._skipped_subdevices
    )
    assert not any(b.subdevice.key == '2' for b in coordinator.bound)
    assert not any(href.endswith('/2') for href in coordinator._hot_hrefs)
    assert not any(href.endswith('/2') for href in coordinator._warm_hrefs)


async def test_hjcom_sub1_device_info_links_via_device_to_master(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    await _discover(coordinator, 'airconditioner_artik051_dongle_fac_18k')

    sub1 = next(su for su in coordinator.subdevices if su.key == '1')
    info = coordinator.device_info_for(sub1)

    master_serial = coordinator.device_serial
    assert info['identifiers'] == {(DOMAIN, f'{master_serial}_1')}
    assert info['via_device'] == (DOMAIN, master_serial)
    # The subdevice's own /information/vs/1 (real, ARTIK051_DONGLE_FAC_RAC_18K)
    # is what names/models this device, not the master's.
    assert info['model'] == 'ARTIK051_DONGLE_FAC_RAC_18K'


# ---------------------------------------------------------------------------
# jhkwon19 -- TP2X_FAC_BORA_21K, Pattern B (UUID-prefixed tree)
# ---------------------------------------------------------------------------

_SUB_UUID = '6c2dff6d-ee5c-dad1-6a5e-000000000001'


async def test_fac_bora_2in1_materializes_prefixed_wall_subdevice(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    await _discover(coordinator, 'airconditioner_fac_bora_2in1')

    assert [su.key for su in coordinator.subdevices] == [_SUB_UUID]
    assert coordinator.subdevices[0].kind == 'prefixed'

    main_climate = _climate_bound(coordinator, None)
    sub_climate = _climate_bound(coordinator, _SUB_UUID)
    assert main_climate is not None
    assert sub_climate is not None
    assert main_climate.href == '/mode/vs/0'
    assert sub_climate.href == f'/{_SUB_UUID}/mode/vs/0'


async def test_fac_bora_2in1_subdevice_device_info(hass: HomeAssistant):
    coordinator = _coordinator(hass)
    await _discover(coordinator, 'airconditioner_fac_bora_2in1')

    subdevice = coordinator.subdevices[0]
    info = coordinator.device_info_for(subdevice)

    master_serial = coordinator.device_serial
    assert info['identifiers'] == {(DOMAIN, f'{master_serial}_{_SUB_UUID}')}
    assert info['via_device'] == (DOMAIN, master_serial)
    # Confirmed live by the reporter (DESIGN-177.md section 1): the wall
    # subdevice's own identity, distinct from the master's TP2X_FAC_BORA_21K.
    assert info['model'] == 'TP2X_FAC_BORA_RAC_21K'


async def test_fac_bora_2in1_unique_ids_include_subdevice_prefix(hass: HomeAssistant):
    """The prefixed subdevice's unique_id carries the full subdevice UUID
    (non-alphanumerics stripped), not a truncation or an ordinal -- see
    Subdevice.key_prefix."""
    coordinator = _coordinator(hass)
    await _discover(coordinator, 'airconditioner_fac_bora_2in1')

    from custom_components.localthings.entity import LocalThingsEntity
    sub_climate = _climate_bound(coordinator, _SUB_UUID)
    entity = LocalThingsEntity(coordinator, sub_climate)
    expected_slug = _SUB_UUID.replace('-', '')
    assert entity._attr_unique_id == (
        f"{DOMAIN}_{coordinator.device_serial}_subdevice_{expected_slug}_climate"
    )


async def test_multidevice_probe_never_reaches_discovery_or_the_cache(
    hass: HomeAssistant,
):
    """/multidevice/vs/0 is probed on every device but is metadata, not state.

    It has to stay out of the resources dict on both counts. Discovery would
    otherwise report it as an unbound href on every family whose registry
    doesn't ignore that path -- only the AC one does -- raising a spurious
    "incomplete capability coverage" repair for, say, a washer whose
    firmware happens to answer it. And nothing polls it after discovery, so
    anything applied to the state cache would sit frozen there forever.

    Driven with a washer fixture precisely because the AC registry's own
    ignore entry would mask the coverage half of this on an AC.
    """
    resources, _oic, _seeds = _load_device_full('washer_flexwash')
    coordinator = _coordinator(hass)
    coordinator._session = FakeCoapSession({
        '/multidevice/vs/0': {'x.com.samsung.da.numofsubdevice': '2'},
    })
    coordinator._identity = DeviceIdentity(
        manufacturer='Samsung Electronics', model='', name='', serial=None,
        device_types=(), raw={'/oic/p': {}, '/oic/d': {}, '/oic/res': []},
    )
    merged = await hass.async_add_executor_job(
        coordinator._enumerate_subdevices_blocking, resources,
    )
    coordinator._run_discovery(merged)
    for href, rep in coordinator._live_subdevice_resources(merged).items():
        coordinator._observe.apply(href, rep, source='poll')

    assert '/multidevice/vs/0' not in merged
    assert '/multidevice/vs/0' not in coordinator._unbound_hrefs
    assert '/multidevice/vs/0' not in coordinator.last_resources
    # Still captured, just not as device state.
    assert coordinator._multidevice == {'x.com.samsung.da.numofsubdevice': '2'}
