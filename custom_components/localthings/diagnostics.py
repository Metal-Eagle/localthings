"""Diagnostics support for Local Things.

Downloadable from Settings > Devices & Services > this integration's
device > the menu > Download diagnostics. This is what the Repairs issue
(raised in coordinator.py when capability coverage is incomplete) points
users at: a redacted snapshot of the device's raw /device/0 state, plus
enough version/coverage metadata to reproduce and diagnose the gap.
"""
from __future__ import annotations

from importlib.metadata import version as pkg_version
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .coordinator import LocalThingsCoordinator
from .registry.redact import redact_resources


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: LocalThingsCoordinator = hass.data[DOMAIN][entry.entry_id]
    integration = await async_get_integration(hass, DOMAIN)

    # importlib.metadata.version() reads the installed package's metadata off
    # disk (listdir + open + read_text), which trips HA's event-loop blocking
    # detector when called inline here. Offload it to the executor.
    stl_version = await hass.async_add_executor_job(pkg_version, "smartthings-local")

    # /oic/p, /oic/d, and /oic/res sit outside the /device/0 batch captured
    # below, so they'd otherwise never reach an issue report. /oic/d's `rt`
    # is OCF's standard device-type declaration; /oic/res is OCF's
    # discovery endpoint, listing every href/Collection the connection
    # hosts -- relevant to the "Composite Device" model (issue #177) where
    # a single physical unit exposes more than one logical Device. See
    # registry/identity.py.
    identity = coordinator._identity
    return {
        "device_type": coordinator.device_type_name or "unknown",
        "one_ui_version": coordinator.one_ui_version,
        "identity": {
            "manufacturer": identity.manufacturer,
            "model": identity.model,
            "device_types": list(identity.device_types),
            "resources": redact_resources(identity.raw),
        } if identity is not None else None,
        "unbound_hrefs": sorted(coordinator._unbound_hrefs),
        "resources": redact_resources(coordinator.last_resources),
        "integration_version": integration.version,
        "smartthings_local_version": stl_version,
        "observe_mode": coordinator.observe_mode,
        "observe_subscribed_hrefs": sorted(coordinator._observe.subscribed_hrefs),
        "observe_fallback_hrefs": sorted(coordinator._observe.fallback_hrefs),
        "observe_last_mode_change": coordinator._observe.last_mode_change_wall,
        "observe_href_freshness_s": {
            href: coordinator._cache.freshness_s(href)
            for href in coordinator._observe.subscribed_hrefs
        },
    }
