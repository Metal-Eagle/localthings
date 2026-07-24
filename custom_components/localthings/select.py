"""Select platform for Local Things."""
from __future__ import annotations

import re
from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .registry.entities import SelectDesc

from .const import DOMAIN
from .coordinator import LocalThingsCoordinator
from .entity import LocalThingsEntity, _is_included


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LocalThingsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        LocalThingsSelect(coordinator, b)
        for b in coordinator.bound
        if isinstance(b.desc, SelectDesc) and _is_included(b, coordinator)
    )


_CAMEL_BOUNDARY_RE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])')

# Keep this synchronized with entity.select.*.state in strings.json. A select
# can have a translation key for its name without translating its dynamic
# Samsung options. Only known states are normalized for HA's lowercase lookup;
# unknown future vendor values retain a readable label and exact write value.
TRANSLATED_SELECT_STATES: dict[str, frozenset[str]] = {
    'beverage_zone_mode': frozenset({
        'sp_ttype_beer_drinks', 'sp_ttype_wine_dessert',
    }),
    'brightness_level': frozenset({'33', '66', '100'}),
    'day_brightness': frozenset({'33', '66', '100'}),
    'dishwasher_cycle': frozenset({
        '07', '0e', '80', '83', '84', '86', '8d', '8e', '8f', '90',
    }),
    'door_alert': frozenset({'1', '2', '3', '4'}),
    'dryer_cycle_table_03': frozenset({
        '16', '18', '19', '1a', '1b', '1c', '1d', '1e', '1f', '20',
        '23', '24', '25', '27',
    }),
    'finish_sound': frozenset({'off', 'on'}),
    'flex_zone_mode': frozenset({
        'cv_fdr_beverage', 'cv_fdr_deli', 'cv_fdr_meat',
        'cv_fdr_soft_freezer', 'cv_fdr_wine',
        'cv_ttype_rf9000a_beverage', 'cv_ttype_rf9000a_freeze',
        'cv_ttype_rf9000a_fruit_veggies',
        'cv_ttype_rf9000a_meat_fish', 'cv_ttype_rf9000a_softfreeze',
    }),
    'heated_dry': frozenset({'extra_high', 'high', 'low', 'off'}),
    'ice_type': frozenset({
        'off', 'whiskey_iceball_3', 'whiskey_iceball_6',
        'whiskey_iceball_9',
    }),
    'led_brightness': frozenset({'high', 'low'}),
    'led_night_brightness': frozenset({'high', 'low'}),
    'oven_mode': frozenset({
        'air_fry', 'bake', 'broil', 'convection', 'convection_bake',
        'convection_broil', 'frozen_pizza_plus', 'no_operation',
        'plate_warm', 'slow_cook',
    }),
    'pantry_zone_mode': frozenset({'fdr_deli', 'fdr_drinks', 'fdr_wine'}),
    'range_burner_power_level': frozenset({'0', 'boost', 'simmer'}),
    'sound_mode': frozenset({'mute', 'tone', 'voice'}),
    'spin_speed': frozenset({'high', 'low', 'medium', 'no_spin', 'rinse_hold'}),
    'buzzer_sound': frozenset({'off', 'on'}),
    'wash_temperature': frozenset({
        'cold', 'cool', 'extra_hot', 'hot', 'none', 'warm',
    }),
    'washer_cycle_table_02': frozenset({
        '1b', '1c', '1d', '1e', '1f', '20', '21', '22', '23', '24',
        '25', '26', '27', '28', '29', '2d', '2e', '2f', '30', '32',
        '33', '36', '37', '38', '39', '66', '8f', '96',
    }),
    'detergent_quantity': frozenset({'00', '01', '02', '03'}),
    'softener_quantity': frozenset({'00', '01', '02', '03'}),
    'detergent_water_hardness': frozenset({'01', '02', '03'}),
    'softener_concentration': frozenset({'01', '02', '03'}),
    'washer_dry_level': frozenset({
        '30', '60', '90', '120', '180', '240', 'cupboard', 'none',
    }),
    'range_hood_lamp_brightness': frozenset({'1', '2'}),
}


def _translation_state(value: str, translation_key: str) -> str | None:
    """Return a known HA translation state, or None for a vendor fallback."""
    known = TRANSLATED_SELECT_STATES.get(translation_key)
    if known is None:
        return None
    direct = value.lower().replace(' ', '_')
    if direct in known:
        return direct
    snake = _CAMEL_BOUNDARY_RE.sub('_', value).lower().replace(' ', '_')
    return snake if snake in known else None


def _display(value, translation_key: Optional[str]):
    """Turn a raw device option/state value into what's shown in the UI.

    `translation_key` is the entity's already-resolved key (SelectDesc.
    translation_key can itself be a callable -- see entities.py -- so
    callers pass the resolved value, e.g. self.translation_key, not
    the raw descriptor field).

    An entity with a translation_key looks its state up in strings.json,
    and hassfest requires those keys to be lowercase -- so those values
    must be lowercased exactly to match, and the device still expects
    that same raw casing back on write (callers map the displayed value
    back to raw via _raw_options()).

    Everything else has no strings.json lookup, so there's no reason to
    destroy the device's own casing. Only two cosmetic fixups apply: a
    fully lowercase device-native token (e.g. "voice") is title-cased,
    and a PascalCase token (e.g. "ExtraHigh") gets a space inserted at
    the case boundary ("Extra High"). A value that's already
    human-friendly (e.g. "AI Wash") matches neither pattern and passes
    through unchanged.
    """
    if not isinstance(value, str):
        return value
    if translation_key and (translated := _translation_state(value, translation_key)):
        return translated
    if value.islower():
        return value.replace('_', ' ').title()
    return _CAMEL_BOUNDARY_RE.sub(' ', value)


class LocalThingsSelect(LocalThingsEntity, SelectEntity):

    def __init__(self, coordinator: LocalThingsCoordinator, bound) -> None:
        super().__init__(coordinator, bound)
        desc: SelectDesc = bound.desc
        if not desc.options_field and not callable(desc.options):
            self._attr_options = [_display(o, self.translation_key) for o in desc.options]

    def _raw_options(self) -> list[str]:
        desc: SelectDesc = self._bound.desc
        if callable(desc.options):
            # Per-device option list computed from the full resource
            # snapshot (not just this entity's own href) -- e.g. a course
            # list decoded from a sibling resource. There is no static
            # fallback: when that resource isn't populated the callable
            # returns [] and the entity's exists_fn suppresses it entirely.
            return list(desc.options(self.coordinator.last_resources) or [])
        if desc.options_field:
            rep = self.coordinator.last_resources.get(self._bound.href) or {}
            return list(rep.get(desc.options_field) or [])
        return list(desc.options)

    @property
    def options(self) -> list[str]:
        desc: SelectDesc = self._bound.desc
        if desc.options_field or callable(desc.options):
            return [_display(o, self.translation_key) for o in self._raw_options()]
        return self._attr_options

    @property
    def current_option(self):
        raw = (self.coordinator.data or {}).get(self._state_key)
        return _display(raw, self.translation_key)

    async def async_select_option(self, option: str) -> None:
        raw = next(
            (o for o in self._raw_options() if _display(o, self.translation_key) == option),
            option,
        )
        await self.coordinator.async_send_command(self._bound, raw)
