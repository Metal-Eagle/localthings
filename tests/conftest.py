import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def _resources_from_dump(dump: dict) -> dict[str, dict]:
    from custom_components.localthings.registry.batch import parse_device0_batch
    return parse_device0_batch(dump['device0'])


def _load_device(name: str) -> dict[str, dict]:
    data = json.loads((FIXTURES / f'{name}_device.json').read_text())
    return _resources_from_dump(data)


def _load_resources(ip: str) -> dict[str, dict]:
    """Legacy IP-based loader — maps known IPs to named fixtures."""
    _ip_to_name = {
        '10.0.0.129': 'dishwasher',
        '10.0.0.254': 'refrigerator',
    }
    name = _ip_to_name.get(ip)
    if name is None:
        raise ValueError(f"No fixture for IP {ip!r} — add a scrubbed fixture to tests/fixtures/")
    return _load_device(name)


@pytest.fixture
def dishwasher_resources() -> dict[str, dict]:
    return _load_device('dishwasher')


@pytest.fixture
def fridge_resources() -> dict[str, dict]:
    return _load_device('refrigerator')


@pytest.fixture
def washer_resources() -> dict[str, dict]:
    return _load_device('washer')


@pytest.fixture
def all_device_fixtures() -> dict[str, dict[str, dict]]:
    """Every scrubbed device dump, keyed by fixture name.

    For invariants that must hold across the whole corpus rather than for one
    device -- so a newly added dump exercises them automatically.
    """
    return {
        path.name[:-len('_device.json')]: _resources_from_dump(
            json.loads(path.read_text())
        )
        for path in sorted(FIXTURES.glob('*_device.json'))
    }
