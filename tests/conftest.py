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


def _load_device_full(name: str):
    """Like _load_device, but also returns the optional `oic_res`/`seeds`
    keys a sub-unit-capable fixture (issue #177) may carry alongside
    `device0` -- see the two `airconditioner_*` fixtures with a
    `seeds_note` field. `oic_res`/`seeds` default to `[]`/`{}` for every
    other fixture, so this is safe to call on any fixture in the corpus.

    Returns `(resources, oic_res, seeds)` where `seeds` is
    `{seed_href: raw_batch_list}` -- the same [devcol-rep, {href, rep}, ...]
    shape a real /device/<n> or /<id>/device/0 RETRIEVE returns, ready to
    hand to a FakeCoapSession.

    A fixture's optional `probes` map (plain Property-map resources that
    belong to no batch, e.g. the hand-read /multidevice/vs/0 in the
    ARTIK051_DONGLE_FAC_18K fixture) is folded into `seeds` here, since
    FakeCoapSession answers both shapes off the same href key.
    """
    data = json.loads((FIXTURES / f'{name}_device.json').read_text())
    resources = _resources_from_dump(data)
    seeds = {**data.get('seeds', {}), **data.get('probes', {})}
    return resources, data.get('oic_res', []), seeds


class FakeCoapSession:
    """Minimal stand-in for smartthings_local's DtlsCoapSession, backed by a
    fixture's `seeds` map (raw device0-batch-shaped lists keyed by seed
    href -- plus any `probes` entries, which are plain Property maps rather
    than batch lists; both are just CBOR bodies at this layer, and the two
    readers in registry.subunits already type-check what they get back).
    Enough surface for registry.subunits.enumerate_sub_units and
    LocalThingsCoordinator's blocking sub-unit polls to run against fixture
    data without a live device -- same idea as test_identity.py's
    FakeSession, but keyed by href string (post path-join) rather than a
    path tuple, since callers here pass a `seed_path` tuple straight
    through.
    """

    def __init__(self, seeds: dict[str, list] | None = None):
        self.seeds = seeds or {}

    def get(self, path, timeout=None):
        href = '/' + '/'.join(path)
        body = self.seeds.get(href)
        if body is None:
            return 0x84, b''   # 4.04 not found -- tolerated absence
        import cbor2
        return 0x45, cbor2.dumps(body)

    def pace(self):
        pass


def _discover_full(resources: dict[str, dict], oic_res, seeds: dict[str, list]):
    """Run the *whole* sub-unit-aware discovery pipeline against fixture
    data, HA-free -- mirrors exactly what LocalThingsCoordinator does across
    _enumerate_sub_units_blocking + _run_discovery (issue #177), so a test
    exercising this exercises the real code path, not a re-implementation of
    it. See the adding-device-support skill's section 2 for the plain
    (non-sub-unit) equivalent this extends.

    Returns `(bound, materialized, skipped, full_resources, device_type_name)`:
    - `bound`: every BoundEntity, main + every materialized sub-unit.
    - `materialized`/`skipped`: SubUnit / SkippedSubUnit lists straight from
      discover_partitioned.
    - `full_resources`: `resources` merged with every candidate's seed data
      (actual hrefs) -- what a coordinator's cache would hold.
    - `device_type_name`: the master's resolved registry name.
    """
    from custom_components.localthings.registry.by_type import resolve
    from custom_components.localthings.registry.registry import CAPABILITIES
    from custom_components.localthings.registry.subunits import (
        discover_partitioned, enumerate_sub_units,
    )

    sess = FakeCoapSession(seeds)
    candidates, extra = enumerate_sub_units(sess, resources, oic_res)
    full_resources = {**resources, **extra}
    bound, device_type_name, materialized, skipped = discover_partitioned(
        full_resources, candidates, resolve, CAPABILITIES,
    )
    return bound, materialized, skipped, full_resources, device_type_name


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
