"""Local Things — Samsung appliance local control integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_HOST, CONF_PORT, CONF_SERIAL, DOMAIN, PLATFORMS
from .coordinator import LocalThingsCoordinator

_LOGGER = logging.getLogger(__name__)


def _serial_from_unique_id(entry: ConfigEntry) -> str | None:
    """The device identity a pre-v2 entry was created with.

    The config flow has always keyed the entry's unique_id on the serial the
    probe read (`localthings_<serial>`), so that string is the identity the
    entry's registry entries were minted from -- there is no need to reach the
    device to recover it.

    One wrinkle: for a board reporting a placeholder serial (issues #83/#189)
    the two sides used to disagree. The config flow fell back to `host:port`
    while the coordinator fell back to `host`, so the entry and its own
    devices/entities were keyed differently. Collapse that to the
    coordinator's form, which is the one the registry actually holds.
    """
    prefix = f"{DOMAIN}_"
    unique_id = entry.unique_id or ""
    if not unique_id.startswith(prefix):
        return None
    serial = unique_id[len(prefix) :]
    if serial == f"{entry.data[CONF_HOST]}:{entry.data.get(CONF_PORT)}":
        return entry.data[CONF_HOST]
    return serial or None


@callback
def _repair_placeholder_keys(hass: HomeAssistant, entry: ConfigEntry, serial: str) -> None:
    """Re-key registry entries this entry minted from the placeholder identity.

    Before the identity moved onto the config entry, the coordinator seeded
    `device_serial` with the host and only replaced it after the first
    successful poll. Anything that registered in between -- the connection-mode
    sensor especially, since it is added unconditionally rather than from
    `bound` -- was written into the registry keyed on the IP address
    permanently, and was orphaned the moment the serial-keyed identity
    appeared (issue #236). Deleting the orphans by hand didn't help: the next
    restart that lost the same race recreated them.

    Rewriting beats deleting where it's possible -- an entity keeps its
    entity_id, name, area and every automation that references it. It's only
    possible when the serial-keyed key is still free, though; where both exist
    the placeholder-keyed one is the dead duplicate (it has been unavailable
    since the restart that created it), so it goes.
    """
    host = entry.data[CONF_HOST]
    if serial == host:
        # A board with no usable serial resolves *to* the host, so its keys
        # were never placeholders -- there is nothing here to re-key.
        return

    ent_reg = er.async_get(hass)
    stale_prefix = f"{DOMAIN}_{host}_"
    for entity in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        if not entity.unique_id.startswith(stale_prefix):
            continue
        new_unique_id = f"{DOMAIN}_{serial}_{entity.unique_id[len(stale_prefix) :]}"
        if ent_reg.async_get_entity_id(entity.domain, DOMAIN, new_unique_id):
            _LOGGER.debug("removing orphaned entity %s", entity.entity_id)
            ent_reg.async_remove(entity.entity_id)
        else:
            _LOGGER.debug("re-keying entity %s to %s", entity.entity_id, new_unique_id)
            ent_reg.async_update_entity(entity.entity_id, new_unique_id=new_unique_id)

    dev_reg = dr.async_get(hass)
    for device in list(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)):
        # `host` for the master, `host_<key>` for a subdevice (device_info_for).
        stale = {
            ident
            for ident in device.identifiers
            if ident[0] == DOMAIN and (ident[1] == host or ident[1].startswith(f"{host}_"))
        }
        if not stale:
            continue
        fresh = {(DOMAIN, f"{serial}{ident[1][len(host) :]}") for ident in stale}
        existing = dev_reg.async_get_device(identifiers=fresh)
        if existing is not None and existing.id != device.id:
            _LOGGER.debug("removing orphaned device %s", device.id)
            dev_reg.async_remove_device(device.id)
        else:
            _LOGGER.debug("re-keying device %s to %s", device.id, fresh)
            dev_reg.async_update_device(
                device.id, new_identifiers=(device.identifiers - stale) | fresh
            )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an entry to the current version.

    v1 -> v2 stores the device's identity on the entry so the coordinator can
    key its registry entries before the first poll (issue #236), and repairs
    whatever the old placeholder-keyed registration already orphaned.
    """
    if entry.version > 2:
        # Downgrade: this release doesn't know the newer entry's shape.
        return False

    if entry.version == 1:
        serial = (
            entry.data.get(CONF_SERIAL) or _serial_from_unique_id(entry) or entry.data[CONF_HOST]
        )
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_SERIAL: serial},
            unique_id=f"{DOMAIN}_{serial}",
            version=2,
        )
        _repair_placeholder_keys(hass, entry, serial)
        _LOGGER.debug("migrated entry %s to version 2 (serial=%s)", entry.entry_id, serial)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    coordinator = LocalThingsCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        # `_poll_once` deliberately leaves the session up on a `TimeoutError`
        # (the transfer may just be slow -- see its docstring), so a refresh
        # that fails that way ends here with a live, bound UDP socket that
        # nothing would ever close. HA retries setup on its own backoff with
        # a *new* coordinator, and each device's source port is fixed by
        # design (`_local_source_port`), so an abandoned socket squats the
        # exact port the next attempt binds -- SO_REUSEADDR lets that bind
        # succeed, leaving two sockets racing for the device's datagrams.
        await coordinator.async_close()
        raise ConfigEntryNotReady(f"Cannot connect to device: {err}") from err
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Send the DTLS close_notify on Core shutdown, not just on unload (issue
    # #254). `async_close` otherwise only runs via `async_unload_entry`, and
    # HA does not unload entries on a plain Core restart -- so a restart left
    # the previous run's association orphaned on the appliance, which is what
    # makes the *next* run's handshake time out. Complements the fixed source
    # port, which covers the unclean-exit case this cannot (see
    # `_local_source_port`).
    #
    # A coroutine listener, not one that spawns its own task: the event bus
    # runs it as a hass-tracked job, so the close is awaited by the
    # `async_block_till_done()` inside `hass.async_stop`. A detached task
    # would likely be cancelled mid-shutdown -- the exact no-close_notify
    # case this exists to prevent.
    async def _async_close_on_stop(_event: Event) -> None:
        await coordinator.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_close_on_stop)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: dr.DeviceEntry,
) -> bool:
    """Allow deleting a device this entry no longer provides (issue #214).

    Defining this at all is what makes Home Assistant offer the "Delete
    device" action for our devices; without it a device registry entry
    belonging to a loaded config entry can never be removed from the UI. That
    matters because a subdevice's HA device outlives the discovery that
    created it: a candidate that materialized under an older release (issue
    #214's phantom second air conditioner, born from an unused /device/1 slot
    reporting the appliance's energy counter -- see
    registry/subdevices.py's liveness gate) leaves a device entry behind that
    nothing recreates and nothing cleans up once the gate stops materializing
    it. Same for a sibling that a firmware update stops exposing.

    Removal is refused for devices this entry *does* currently provide --
    HA would recreate them on the next entity add, so allowing it would look
    like the delete silently failed. Deliberately no automatic pruning at
    discovery time: subdevice enumeration is one-shot and a sibling can fail
    to answer for a poll (issue #205 is exactly that on the reference
    hardware), so auto-removal would throw away a real subdevice's name,
    area and automation references on a transient miss. The user gets the
    button; the integration doesn't guess.
    """
    coordinator: LocalThingsCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        # Entry not loaded (or already unloaded) -- nothing is claiming this
        # device, so there's nothing to protect it from being removed.
        return True
    live = set(coordinator.device_info.get("identifiers") or set())
    for subdevice in coordinator.subdevices:
        live |= set(coordinator.device_info_for(subdevice).get("identifiers") or set())
    return not (device.identifiers & live)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: LocalThingsCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
    return unloaded
