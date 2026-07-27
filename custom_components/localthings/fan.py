"""Fan platform for Samsung range hoods and air purifiers.

Two FanDesc-bound hrefs exist, one per family, dispatched by href in
async_setup_entry below since they need different HA fan semantics: the
range hood's fan speed is an ordered set of numeric levels (SET_SPEED), while
the newer air-purifier board family's modes (Smart/Max/Mid/WindFree/Sleep,
issue #130) are named behaviors with no linear order (PRESET_MODE)."""

from __future__ import annotations

import logging

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import DOMAIN
from .coordinator import LocalThingsCoordinator
from .entity import LocalThingsEntity, _is_included
from .registry.capabilities.air_purifier import HREF_MODE as AIR_PURIFIER_FAN_HREF
from .registry.entities import FanDesc

_LOGGER = logging.getLogger(__name__)

POWER_HREF = '/power/0'
POWER_VS_HREF = '/power/vs/0'
_FAN_SPEED_FIELD = 'x.com.samsung.da.hood.fanSpeed'
_SUPPORTED_FAN_SPEED_FIELD = 'x.com.samsung.da.hood.supportedFanSpeed'

_MODES_FIELD = 'x.com.samsung.da.modes'
_SUPPORTED_MODES_FIELD = 'x.com.samsung.da.supportedModes'


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LocalThingsCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for bound in coordinator.bound:
        if not (isinstance(bound.desc, FanDesc) and _is_included(bound, coordinator)):
            continue
        if bound.href == AIR_PURIFIER_FAN_HREF:
            entities.append(LocalThingsAirPurifierFan(coordinator, bound))
        else:
            entities.append(LocalThingsRangeHoodFan(coordinator, bound))
    async_add_entities(entities)


class LocalThingsRangeHoodFan(LocalThingsEntity, FanEntity):
    """A hood fan combining sibling power and fan-speed resources."""

    _enable_turn_on_off_backwards_compatibility = False
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: LocalThingsCoordinator, bound) -> None:
        super().__init__(coordinator, bound)
        self._attr_name = None

    def _rep(self, href: str) -> dict:
        return self.coordinator.resource(href) or {}

    def _all_speed_codes(self) -> list[str]:
        rep = self._rep(self._bound.href)
        return [str(value) for value in rep.get(_SUPPORTED_FAN_SPEED_FIELD, ())]

    def _active_speed_codes(self) -> list[str]:
        # Power is carried by the separate /power resource.  fanSpeed retains
        # the selected setting while power is off (as the lamp's `current`
        # field does), so every advertised code is an active ordered speed.
        return self._all_speed_codes()

    def _power_payload(self, enabled: bool) -> tuple[str, bool, str]:
        """Target whichever power resource this hood actually exposes."""
        resources = self.coordinator.last_resources
        target = POWER_HREF if POWER_HREF in resources else POWER_VS_HREF
        return 'power', enabled, target

    @property
    def is_on(self) -> bool:
        rep = self._rep(POWER_HREF)
        if 'value' in rep:
            return bool(rep.get('value'))
        return str(
            self._rep(POWER_VS_HREF).get('x.com.samsung.da.power', '')
        ).lower() == 'on'

    @property
    def speed_count(self) -> int:
        return len(self._active_speed_codes())

    @property
    def percentage(self) -> int | None:
        if not self.is_on:
            return 0
        codes = self._active_speed_codes()
        current = str(self._rep(self._bound.href).get(_FAN_SPEED_FIELD, ''))
        if not codes or current not in codes:
            return None
        return ordered_list_item_to_percentage(codes, current)

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None,
        **kwargs,
    ) -> None:
        await self.coordinator.async_send_command(
            self._bound, self._power_payload(True),
        )
        if percentage is not None:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_send_command(
            self._bound, self._power_payload(False),
        )

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage <= 0:
            await self.async_turn_off()
            return
        codes = self._active_speed_codes()
        if not codes:
            return
        if not self.is_on:
            await self.coordinator.async_send_command(
                self._bound, self._power_payload(True),
            )
        code = percentage_to_ordered_list_item(codes, percentage)
        await self.coordinator.async_send_command(self._bound, ('speed', code))


class LocalThingsAirPurifierFan(LocalThingsEntity, FanEntity):
    """Air-purifier fan: named preset modes, not an ordered percentage --
    see air_purifier.FAN's comment for why (Smart/WindFree/Sleep aren't
    "faster/slower" than Max/Mid)."""

    _enable_turn_on_off_backwards_compatibility = False
    _attr_supported_features = (
        FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: LocalThingsCoordinator, bound) -> None:
        super().__init__(coordinator, bound)
        self._attr_name = None

    def _rep(self, href: str) -> dict:
        return self.coordinator.resource(href) or {}

    def _mode_rep(self) -> dict:
        return self._rep(self._bound.href)

    def _power_payload(self, enabled: bool) -> tuple[str, bool, str]:
        """Target whichever power resource this unit actually exposes --
        same pattern as LocalThingsRangeHoodFan._power_payload above.
        Writing a hardcoded href here would silently no-op on a board that
        only reports the other one, even though is_on already falls back
        correctly."""
        resources = self.coordinator.last_resources
        target = POWER_VS_HREF if POWER_VS_HREF in resources else POWER_HREF
        return 'power', enabled, target

    @property
    def is_on(self) -> bool:
        power = self._rep(POWER_VS_HREF).get('x.com.samsung.da.power')
        if power is not None:
            return str(power).lower() == 'on'
        return bool(self._rep(POWER_HREF).get('value'))

    @property
    def preset_modes(self) -> list[str]:
        return [
            str(code).lower()
            for code in self._mode_rep().get(_SUPPORTED_MODES_FIELD, ())
        ]

    @property
    def preset_mode(self) -> str | None:
        modes = self._mode_rep().get(_MODES_FIELD)
        code = modes[0] if isinstance(modes, (list, tuple)) and modes else modes
        return str(code).lower() if code is not None else None

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None,
        **kwargs,
    ) -> None:
        await self.coordinator.async_send_command(self._bound, self._power_payload(True))
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_send_command(self._bound, self._power_payload(False))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        # Reverse-resolve against the unit's own supportedModes -- the
        # write needs the raw device code (e.g. 'WindFree'), not the
        # lowercased HA value.
        for code in self._mode_rep().get(_SUPPORTED_MODES_FIELD, ()):
            if str(code).lower() == preset_mode:
                await self.coordinator.async_send_command(self._bound, ('mode', code))
                return
        _LOGGER.warning(
            "%s: %r is not a valid preset mode (supported: %s)",
            self.entity_id, preset_mode, self.preset_modes,
        )
