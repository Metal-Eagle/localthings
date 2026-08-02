"""Local Things — Samsung appliance local control integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .coordinator import LocalThingsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    coordinator = LocalThingsCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        # Close whatever the failed refresh left open before handing this
        # coordinator to the garbage collector. `_poll_once` deliberately
        # leaves the session up on a `TimeoutError` (the transfer may just
        # be slow -- see its docstring), so a refresh that fails that way
        # ends here with a live, bound UDP socket that nothing will ever
        # close. HA retries setup on its own backoff with a *new*
        # coordinator, and every device's source port is fixed by design
        # (`_local_source_port`), so each abandoned socket keeps squatting
        # the exact port the next attempt binds -- SO_REUSEADDR lets the
        # bind succeed, and then two sockets on one port race for the
        # device's datagrams. Failing setup is precisely when retries are
        # most likely, so leaking there is what would hurt most.
        await coordinator.async_close()
        raise ConfigEntryNotReady(f"Cannot connect to device: {err}") from err
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Send the DTLS close_notify on Core shutdown, not just on unload
    # (issue #254). `async_close` otherwise only runs via
    # `async_unload_entry` -- a reload or a remove -- and HA does not unload
    # config entries on a plain Core restart, so a restart left the previous
    # run's association orphaned on the appliance. The device then holds that
    # stale session for minutes, which is what makes the next run's handshake
    # time out in the first place. Closing cleanly here means there is
    # usually nothing to evict on the way back up. This is belt-and-braces
    # with the fixed source port (RFC 6347 section 4.2.8 eviction): that
    # handles the unclean-shutdown case this cannot, e.g. a power cut or a
    # SIGKILL, where no close_notify is ever sent.
    #
    # Registered as a coroutine listener rather than one that spawns its own
    # task: the event bus runs it as a hass-tracked job, so the close is
    # awaited by the `async_block_till_done()` inside `hass.async_stop`. A
    # detached task would just as likely be cancelled mid-shutdown, which is
    # the exact no-close_notify case this exists to prevent.
    async def _async_close_on_stop(_event: Event) -> None:
        await coordinator.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_close_on_stop)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry,
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
    coordinator: LocalThingsCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is None:
        # Entry not loaded (or already unloaded) -- nothing is claiming this
        # device, so there's nothing to protect it from being removed.
        return True
    live = set(coordinator.device_info.get('identifiers') or set())
    for subdevice in coordinator.subdevices:
        live |= set(coordinator.device_info_for(subdevice).get('identifiers') or set())
    return not (device.identifiers & live)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: LocalThingsCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
    return unloaded
