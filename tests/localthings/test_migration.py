"""Config-entry migration and the placeholder-identity repair (issue #236)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.localthings.const import (
    CONF_HOST,
    CONF_SERIAL,
    DOMAIN,
)

from .conftest import LEGACY_ENTRY_DATA, MOCK_HOST, MOCK_PORT, MOCK_SERIAL


def _legacy_entry(hass: HomeAssistant, unique_id: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=LEGACY_ENTRY_DATA,
        unique_id=unique_id,
        version=1,
    )
    entry.add_to_hass(hass)
    return entry


async def test_migration_recovers_serial_from_unique_id(
    hass: HomeAssistant, mock_coordinator_session
) -> None:
    """A v1 entry's identity is recoverable without reaching the device: the
    config flow has always keyed the entry's unique_id on the serial its probe
    read."""
    entry = _legacy_entry(hass, f"{DOMAIN}_{MOCK_SERIAL}")

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.data[CONF_SERIAL] == MOCK_SERIAL


async def test_migration_collapses_the_host_port_unique_id(
    hass: HomeAssistant, mock_coordinator_session
) -> None:
    """A board with no usable serial (issues #83/#189) used to be keyed two
    different ways at once: `host:port` on the config entry, `host` in the
    device and entity registries. Migration collapses the entry onto the
    registry's form, so the two finally name the same thing."""
    entry = _legacy_entry(hass, f"{DOMAIN}_{MOCK_HOST}:{MOCK_PORT}")

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.data[CONF_SERIAL] == MOCK_HOST
    assert entry.unique_id == f"{DOMAIN}_{MOCK_HOST}"


async def test_migration_rekeys_an_ip_keyed_device_and_entity(
    hass: HomeAssistant, mock_coordinator_session
) -> None:
    """The registry entries the old placeholder identity minted are rewritten
    in place, so an orphan keeps its entity_id, name, area and every
    automation that referenced it -- rather than being replaced by a
    serial-keyed duplicate with a `_2` suffix while it sits permanently
    unavailable (issue #236)."""
    entry = _legacy_entry(hass, f"{DOMAIN}_{MOCK_SERIAL}")
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    orphan_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, MOCK_HOST)},
        name=f"Samsung Appliance ({MOCK_HOST})",
    )
    orphan_entity = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_{MOCK_HOST}_connection_mode",
        config_entry=entry,
        device_id=orphan_device.id,
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Same registry rows, now keyed on the real identity.
    rekeyed_device = dev_reg.async_get(orphan_device.id)
    assert rekeyed_device is not None
    assert rekeyed_device.identifiers == {(DOMAIN, MOCK_SERIAL)}
    rekeyed = ent_reg.async_get(orphan_entity.entity_id)
    assert rekeyed is not None
    assert rekeyed.unique_id == f"{DOMAIN}_{MOCK_SERIAL}_connection_mode"
    # And nothing is left keyed on the IP.
    assert dev_reg.async_get_device(identifiers={(DOMAIN, MOCK_HOST)}) is None


async def test_migration_removes_an_orphan_that_is_already_duplicated(
    hass: HomeAssistant, mock_coordinator_session
) -> None:
    """Where the serial-keyed entry already exists, the IP-keyed one is the
    dead duplicate the race left behind -- it has been unavailable since the
    restart that created it and nothing will ever update it, so it goes
    rather than being rewritten onto a key that is taken."""
    entry = _legacy_entry(hass, f"{DOMAIN}_{MOCK_SERIAL}")
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    real_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, MOCK_SERIAL)},
    )
    real_entity = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_{MOCK_SERIAL}_connection_mode",
        config_entry=entry,
        device_id=real_device.id,
    )
    orphan_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, MOCK_HOST)},
    )
    orphan_entity = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_{MOCK_HOST}_connection_mode",
        config_entry=entry,
        device_id=orphan_device.id,
    )
    assert orphan_entity.entity_id != real_entity.entity_id

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get(orphan_entity.entity_id) is None
    assert dev_reg.async_get(orphan_device.id) is None
    # The working pair is untouched.
    assert ent_reg.async_get(real_entity.entity_id) is not None
    assert dev_reg.async_get(real_device.id) is not None


async def test_migration_leaves_a_host_identity_device_alone(
    hass: HomeAssistant, mock_coordinator_session
) -> None:
    """A board whose serial resolves *to* the host was never keyed on a
    placeholder -- its host-keyed device is the real one, and re-keying or
    removing it would orphan a working device to fix a problem it doesn't
    have."""
    entry = _legacy_entry(hass, f"{DOMAIN}_{MOCK_HOST}")
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, MOCK_HOST)},
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.data[CONF_SERIAL] == MOCK_HOST
    unchanged = dev_reg.async_get(device.id)
    assert unchanged is not None
    assert unchanged.identifiers == {(DOMAIN, MOCK_HOST)}


async def test_migration_rejects_a_future_entry_version(hass: HomeAssistant) -> None:
    """A downgrade must fail the entry rather than silently mangling data
    written by a newer release."""
    from custom_components.localthings import async_migrate_entry

    entry = MockConfigEntry(domain=DOMAIN, data=LEGACY_ENTRY_DATA, version=3)
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is False


async def test_migration_without_a_unique_id_falls_back_to_host(hass: HomeAssistant) -> None:
    """Nothing to recover the identity from means the host, which is exactly
    what the coordinator used to seed -- so the registry keys such an entry
    already holds stay valid."""
    from custom_components.localthings import async_migrate_entry

    entry = MockConfigEntry(domain=DOMAIN, data=LEGACY_ENTRY_DATA, version=1)
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.data[CONF_SERIAL] == entry.data[CONF_HOST]
    assert entry.unique_id == f"{DOMAIN}_{MOCK_HOST}"
