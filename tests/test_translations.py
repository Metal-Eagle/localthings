"""Translation architecture and catalog synchronization tests."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from string import Formatter

from custom_components.localthings.registry.capability import Capability
from custom_components.localthings.registry.entities import PLATFORM_OF
from custom_components.localthings.select import TRANSLATED_SELECT_STATES


INTEGRATION = (
    Path(__file__).parents[1] / "custom_components" / "localthings"
)


def _load(name: str) -> dict:
    return json.loads((INTEGRATION / name).read_text(encoding="utf-8"))


def _topology(value):
    if isinstance(value, dict):
        return {key: _topology(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_topology(child) for child in value]
    return None


def _placeholders(value: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in Formatter().parse(value)
        if field_name is not None
    }


def _walk_strings(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_strings(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_strings(child, (*path, str(index)))
    elif isinstance(value, str):
        yield path, value


def _all_descriptions():
    capabilities_dir = INTEGRATION / "registry" / "capabilities"
    seen: set[int] = set()
    for module_path in capabilities_dir.glob("*.py"):
        if module_path.stem == "__init__":
            continue
        module = importlib.import_module(
            f"custom_components.localthings.registry.capabilities.{module_path.stem}"
        )

        def visit(value):
            if isinstance(value, Capability):
                if id(value) in seen:
                    return
                seen.add(id(value))
                yield from value.entities
            elif isinstance(value, (tuple, list, set)):
                for child in value:
                    yield from visit(child)

        for value in vars(module).values():
            yield from visit(value)


def test_source_and_english_translation_topology_and_placeholders_match():
    source = _load("strings.json")
    english = _load("translations/en.json")
    assert _topology(source) == _topology(english)

    english_strings = dict(_walk_strings(english))
    for path, value in _walk_strings(source):
        assert _placeholders(value) == _placeholders(english_strings[path]), path


def test_runtime_translation_catalogs_have_no_unresolved_references():
    for language in ("en", "nl"):
        unresolved = [
            (path, value)
            for path, value in _walk_strings(
                _load(f"translations/{language}.json")
            )
            if "[%key:" in value
        ]
        assert unresolved == []


def test_english_and_dutch_catalog_topology_and_placeholders_match():
    english = _load("translations/en.json")
    dutch = _load("translations/nl.json")
    assert _topology(english) == _topology(dutch)

    dutch_strings = dict(_walk_strings(dutch))
    for path, value in _walk_strings(english):
        assert _placeholders(value) == _placeholders(dutch_strings[path]), path


def test_every_translatable_descriptor_has_an_entity_catalog_entry():
    entity_strings = _load("strings.json")["entity"]
    missing = []
    for desc in _all_descriptions():
        translation_key = desc.translation_key
        if callable(translation_key):
            # Runtime table resolvers use the generic name-only fallback plus
            # the static tables currently documented by this integration.
            continue
        if translation_key is None and desc.name is not None:
            translation_key = desc.key
        if translation_key is None:
            continue  # Main fan entity: device name + HA fan translations.
        platform = PLATFORM_OF[type(desc)]
        if translation_key not in entity_strings.get(platform, {}):
            missing.append((platform, desc.key, translation_key))
    assert missing == []

    select_strings = entity_strings["select"]
    for key in ("cycle", "washer_cycle_table_02", "dryer_cycle_table_03"):
        assert key in select_strings


def test_select_state_normalization_is_synchronized_with_catalog():
    select_strings = _load("strings.json")["entity"]["select"]
    translated = {
        key: frozenset(value["state"])
        for key, value in select_strings.items()
        if "state" in value
    }
    assert TRANSLATED_SELECT_STATES == translated


def test_all_entity_state_translation_keys_are_lowercase():
    entity_strings = _load("strings.json")["entity"]
    for platform in entity_strings.values():
        for translation in platform.values():
            for state_key in translation.get("state", {}):
                assert state_key == state_key.lower()
