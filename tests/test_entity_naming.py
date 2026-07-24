"""Tests for translated entity naming and dynamic instance placeholders."""
from custom_components.localthings.entity import LocalThingsEntity
from custom_components.localthings.registry.capability import Capability
from custom_components.localthings.registry.discovery import BoundEntity
from custom_components.localthings.registry.entities import BinarySensorDesc


class _FakeCoordinator:
    device_serial = 'TEST-SERIAL'

    def __init__(self, last_resources=None):
        self.last_resources = last_resources or {}


def _make_entity(desc, href='/x/vs/0', key_override=None, instance='', instance_name=None):
    capability = Capability(href=href, entities=(desc,))
    bound = BoundEntity(href=href, capability=capability, desc=desc,
                         instance=instance, key_override=key_override,
                         instance_name=instance_name)
    return LocalThingsEntity(_FakeCoordinator(), bound)


def test_explicit_fallback_name_uses_translation_instead_of_attr_name():
    """An _attr_name would take precedence over HA's translation catalog."""
    desc = BinarySensorDesc(key='enabled', name='Explicit name')
    entity = _make_entity(desc, instance_name='Cubed Ice')
    assert entity.translation_key == 'enabled'
    assert not hasattr(entity, '_attr_name')


def test_device_instance_name_becomes_translation_placeholder():
    desc = BinarySensorDesc(
        key='enabled', translation_key='instance_enabled', use_instance_name=True
    )
    entity = _make_entity(desc, key_override='icemaker_one_enabled',
                           instance_name='Cubed Ice')
    assert entity.translation_key == 'instance_enabled'
    assert entity.translation_placeholders == {'instance_name': 'Cubed Ice'}
    assert not hasattr(entity, '_attr_name')


def test_href_instance_name_becomes_translation_placeholder():
    desc = BinarySensorDesc(
        key='enabled', translation_key='instance_enabled', use_instance_name=True
    )
    entity = _make_entity(desc, key_override='icemaker_one_enabled')
    assert entity.translation_placeholders == {'instance_name': 'Icemaker One'}


def test_untranslated_vendor_entity_keeps_readable_fallback_name():
    desc = BinarySensorDesc(key='vendor_feature')
    entity = _make_entity(desc, key_override='vendor_feature_1')
    assert entity.translation_key is None
    assert entity._attr_name == 'Vendor Feature 1'
