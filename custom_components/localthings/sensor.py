"""Sensor platform for Local Things."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .observe import MODE_OBSERVE, MODE_POLL
from .registry.entities import SensorDesc

from .const import CONF_FINISH_TIME_DEBOUNCE_MINUTES, DEFAULT_FINISH_TIME_DEBOUNCE_MINUTES, DOMAIN
from .coordinator import LocalThingsCoordinator
from .entity import LocalThingsEntity, _is_included


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LocalThingsCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        LocalThingsSensor(coordinator, b)
        for b in coordinator.bound
        if isinstance(b.desc, SensorDesc) and _is_included(b, coordinator)
    ]
    entities.append(LocalThingsConnectionModeSensor(coordinator))
    async_add_entities(entities)


class LocalThingsSensor(LocalThingsEntity, SensorEntity):

    def __init__(self, coordinator: LocalThingsCoordinator, bound) -> None:
        super().__init__(coordinator, bound)
        desc: SensorDesc = bound.desc
        self._attr_native_unit_of_measurement = desc.unit
        self._attr_device_class = desc.device_class
        self._attr_state_class = desc.state_class
        if desc.options:
            self._attr_options = list(desc.options)
        self._debounced_value = None

    @property
    def native_unit_of_measurement(self):
        desc: SensorDesc = self._bound.desc
        if desc.unit_fn is not None:
            return desc.unit_fn(self.coordinator.resource(self._bound.href))
        return self._attr_native_unit_of_measurement

    @property
    def native_value(self):
        raw = (self.coordinator.data or {}).get(self._state_key)
        if not self._bound.desc.debounce:
            return raw
        return self._debounce(raw)

    def _debounce(self, raw):
        """Suppress a new value until it differs from the last one this
        entity actually reported by at least the configured threshold.

        Values like finish_time are `now() + remaining`, recomputed from
        scratch every poll -- both wall-clock drift between the device's own
        remaining-time updates and the device revising its own estimate mid-
        cycle produce a stream of small, real changes that are individually
        meaningless but each trigger a recorder/logbook entry. A cycle
        ending (raw is None) or starting (cache empty) always passes through
        immediately -- only in-between jitter while a value already exists
        on both sides gets held back.
        """
        threshold_min = self.coordinator.config_entry.options.get(
            CONF_FINISH_TIME_DEBOUNCE_MINUTES, DEFAULT_FINISH_TIME_DEBOUNCE_MINUTES
        )
        if (
            threshold_min
            and raw is not None
            and self._debounced_value is not None
            and abs(raw - self._debounced_value) < timedelta(minutes=threshold_min)
        ):
            return self._debounced_value
        self._debounced_value = raw
        return raw


class LocalThingsConnectionModeSensor(CoordinatorEntity[LocalThingsCoordinator], SensorEntity):
    """Diagnostic sensor exposing whether this device is currently
    receiving push notifications (observe mode) or being polled only.
    Disabled by default — it's for troubleshooting, not everyday use."""

    _attr_has_entity_name = True
    _attr_translation_key = 'connection_mode'
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [MODE_OBSERVE, MODE_POLL]

    def __init__(self, coordinator: LocalThingsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{coordinator.device_serial}_connection_mode"

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info

    @property
    def native_value(self) -> str:
        return self.coordinator.observe_mode
