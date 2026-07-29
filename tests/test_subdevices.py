"""Tests for registry/subdevices.py -- multi-indoor-subdevice ("composite
device") support, issue #177. See DESIGN-177.md for the two board patterns
(`ARTIK051_DONGLE_FAC_18K`'s indexed siblings, `TP2X_FAC_BORA_21K`'s
UUID-prefixed tree) this module unifies.
"""
from __future__ import annotations

import cbor2

from custom_components.localthings.registry.capability import Capability
from custom_components.localthings.registry.entities import BinarySensorDesc, SensorDesc
from custom_components.localthings.registry.subdevices import (
    MAIN, Subdevice, canonical_view, discover_partitioned, enumerate_subdevices,
    normalize_seed_batch,
)

_UUID = '6c2dff6d-ee5c-dad1-6a5e-000000000001'


def _indexed(n: str) -> Subdevice:
    return Subdevice(kind='indexed', key=n, seed_path=('device', n))


def _prefixed(sub_id: str) -> Subdevice:
    return Subdevice(kind='prefixed', key=sub_id, seed_path=(sub_id, 'device', '0'))


# ---------------------------------------------------------------------------
# Subdevice.to_actual / to_canonical / owns / key_prefix
# ---------------------------------------------------------------------------

class TestMainIsIdentity:
    def test_to_actual_unchanged(self):
        assert MAIN.to_actual('/mode/vs/0') == '/mode/vs/0'

    def test_to_canonical_unchanged(self):
        assert MAIN.to_canonical('/mode/vs/0') == '/mode/vs/0'

    def test_owns_is_always_false(self):
        """MAIN never "owns" a href by this definition -- it gets whatever's
        left after every other subdevice's hrefs are excluded (canonical_view)."""
        assert MAIN.owns('/mode/vs/0') is False
        assert MAIN.owns('/mode/vs/1') is False

    def test_key_prefix_is_empty(self):
        """The master's flattened state keys must stay byte-identical
        to every device shipped before issue #177 -- see adapter._key."""
        assert MAIN.key_prefix == ''


class TestIndexedTransform:
    def test_to_actual_rewrites_trailing_zero(self):
        subdevice = _indexed('1')
        assert subdevice.to_actual('/mode/vs/0') == '/mode/vs/1'
        assert subdevice.to_actual('/device/0') == '/device/1'

    def test_to_actual_leaves_non_zero_trailing_segment_alone(self):
        """Deliberately not a "replace any trailing digit" rule -- a genuine
        multi-instance resource (the fridge's pattern-cap hrefs, e.g.
        '/door/vs/1') must not be misread as a subdevice's own href."""
        subdevice = _indexed('1')
        assert subdevice.to_actual('/door/vs/1') == '/door/vs/1'

    def test_to_canonical_round_trips(self):
        subdevice = _indexed('1')
        assert subdevice.to_canonical(subdevice.to_actual('/mode/vs/0')) == '/mode/vs/0'

    def test_to_canonical_rejects_wrong_index(self):
        subdevice = _indexed('1')
        assert subdevice.to_canonical('/mode/vs/2') is None

    def test_to_canonical_rejects_index_zero(self):
        """Index 0 belongs to MAIN, never to an indexed subdevice."""
        subdevice = _indexed('1')
        assert subdevice.to_canonical('/mode/vs/0') is None

    def test_owns(self):
        subdevice = _indexed('1')
        assert subdevice.owns('/mode/vs/1') is True
        assert subdevice.owns('/mode/vs/0') is False
        assert subdevice.owns('/mode/vs/2') is False

    def test_key_prefix(self):
        assert _indexed('1').key_prefix == 'subdevice1_'
        assert _indexed('2').key_prefix == 'subdevice2_'


class TestPrefixedTransform:
    def test_to_actual_prepends_id(self):
        subdevice = _prefixed(_UUID)
        assert subdevice.to_actual('/mode/vs/0') == f'/{_UUID}/mode/vs/0'

    def test_to_canonical_round_trips(self):
        subdevice = _prefixed(_UUID)
        assert subdevice.to_canonical(subdevice.to_actual('/mode/vs/0')) == '/mode/vs/0'

    def test_to_canonical_rejects_missing_prefix(self):
        subdevice = _prefixed(_UUID)
        assert subdevice.to_canonical('/mode/vs/0') is None

    def test_to_canonical_requires_path_boundary(self):
        """A different, longer id that merely starts with the same
        characters must not be mistaken for this one's own href."""
        subdevice = _prefixed(_UUID)
        assert subdevice.to_canonical(f'/{_UUID}extra/mode/vs/0') is None

    def test_owns(self):
        subdevice = _prefixed(_UUID)
        assert subdevice.owns(f'/{_UUID}/mode/vs/0') is True
        assert subdevice.owns('/mode/vs/0') is False

    def test_key_prefix_strips_non_alphanumerics(self):
        assert _prefixed(_UUID).key_prefix == 'subdevice_6c2dff6dee5cdad16a5e000000000001_'


# ---------------------------------------------------------------------------
# canonical_view
# ---------------------------------------------------------------------------

class TestCanonicalView:
    def test_main_with_no_subdevices_is_unchanged(self):
        resources = {'/mode/vs/0': {'a': 1}, '/power/vs/0': {'b': 2}}
        assert canonical_view(MAIN, resources, []) == resources

    def test_main_excludes_subdevice_owned_hrefs(self):
        """A sibling's own /mode/vs/1 must not leak into the master's
        canonical /mode/vs/0 view -- otherwise exists_fn/is_legacy_board
        checks that scan the whole dict would see two subdevices' state mixed
        together under one key."""
        resources = {
            '/mode/vs/0': {'unit': 'main'},
            '/mode/vs/1': {'unit': 'sibling'},
        }
        sub1 = _indexed('1')
        view = canonical_view(MAIN, resources, [sub1])
        assert view == {'/mode/vs/0': {'unit': 'main'}}

    def test_indexed_view_is_rewritten_to_canonical_hrefs(self):
        resources = {
            '/mode/vs/0': {'unit': 'main'},
            '/mode/vs/1': {'unit': 'sibling'},
            '/power/vs/1': {'p': 'On'},
        }
        sub1 = _indexed('1')
        view = canonical_view(sub1, resources, [sub1])
        assert view == {
            '/mode/vs/0': {'unit': 'sibling'},
            '/power/vs/0': {'p': 'On'},
        }

    def test_prefixed_view_is_rewritten_to_canonical_hrefs(self):
        resources = {
            f'/{_UUID}/mode/vs/0': {'unit': 'sub'},
            '/mode/vs/0': {'unit': 'main'},
        }
        subdevice = _prefixed(_UUID)
        view = canonical_view(subdevice, resources, [subdevice])
        assert view == {'/mode/vs/0': {'unit': 'sub'}}

    def test_including_main_in_subdevices_is_harmless(self):
        """MAIN.owns() is always False, so passing the full roster
        (including MAIN itself) to canonical_view must not change anything."""
        resources = {'/mode/vs/0': {'unit': 'main'}, '/mode/vs/1': {'unit': 'sib'}}
        sub1 = _indexed('1')
        assert (canonical_view(MAIN, resources, [MAIN, sub1])
                == canonical_view(MAIN, resources, [sub1]))


# ---------------------------------------------------------------------------
# normalize_seed_batch
# ---------------------------------------------------------------------------

def test_normalize_seed_batch_indexed_is_a_no_op():
    subdevice = _indexed('1')
    batch = {'/mode/vs/1': {'a': 1}}
    assert normalize_seed_batch(subdevice, batch) == batch


def test_normalize_seed_batch_prefixed_adds_missing_prefix():
    subdevice = _prefixed(_UUID)
    batch = {'/mode/vs/0': {'a': 1}}
    assert normalize_seed_batch(subdevice, batch) == {f'/{_UUID}/mode/vs/0': {'a': 1}}


def test_normalize_seed_batch_prefixed_leaves_already_prefixed_alone():
    subdevice = _prefixed(_UUID)
    batch = {f'/{_UUID}/mode/vs/0': {'a': 1}}
    assert normalize_seed_batch(subdevice, batch) == batch


# ---------------------------------------------------------------------------
# enumerate_subdevices
# ---------------------------------------------------------------------------

class _FakeSession:
    """path-tuple -> raw batch list, cbor-encoded on GET -- same shape as
    test_identity.py's FakeSession, extended to serve Collection batches
    (a CBOR list), not just a bare Property map."""

    def __init__(self, table):
        self.table = table

    def get(self, path, timeout=10.0):
        body = self.table.get(tuple(path))
        if body is None:
            return 0x84, b''
        return 0x45, cbor2.dumps(body)


_DEVCOL_REP = {'rt': ['x.com.samsung.devcol', 'oic.wk.col']}


def test_enumerate_indexed_from_oic_res_links():
    oic_res = [{'di': 'aaaa', 'links': [
        {'href': '/device/0'}, {'href': '/device/1'}, {'href': '/device/2'},
    ]}]
    sess = _FakeSession({
        ('device', '1'): [_DEVCOL_REP, {'href': '/mode/vs/1', 'rep': {'m': 1}}],
        ('device', '2'): [_DEVCOL_REP, {'href': '/mode/vs/2', 'rep': {'m': 2}}],
    })
    subdevices, extra = enumerate_subdevices(sess, {}, oic_res)
    assert sorted((u.kind, u.key) for u in subdevices) == [
        ('indexed', '1'), ('indexed', '2'),
    ]
    assert extra == {'/mode/vs/1': {'m': 1}, '/mode/vs/2': {'m': 2}}


def test_enumerate_indexed_falls_back_to_speculative_probe_when_oic_res_hides_the_tree():
    """A board whose /oic/res doesn't reveal a second logical Device (e.g.
    it hides the whole tree, TP2X_FAC_BORA_21K-style) falls back to probing
    /device/1 and /device/2 directly -- the same bound the old
    identity.py-level probe used."""
    sess = _FakeSession({
        ('device', '1'): [_DEVCOL_REP, {'href': '/mode/vs/1', 'rep': {'m': 1}}],
        # /device/2 not in the table -> 4.04 -> not materialized.
    })
    subdevices, extra = enumerate_subdevices(sess, {}, oic_res_links=[])
    assert [(u.kind, u.key) for u in subdevices] == [('indexed', '1')]
    assert extra == {'/mode/vs/1': {'m': 1}}


def test_enumerate_indexed_only_materializes_subdevices_with_a_non_empty_batch():
    """Per issue #177's design call: any seed that answers with a non-empty
    batch is materialized, but an empty ({}) answer is not -- no separate
    "is this subdevice real" gate."""
    sess = _FakeSession({})   # neither /device/1 nor /device/2 answers
    subdevices, extra = enumerate_subdevices(sess, {}, oic_res_links=[])
    assert subdevices == []
    assert extra == {}


def test_enumerate_prefixed_from_subdevice_id_list():
    resources = {
        '/subdevices/vs/0': {'x.com.samsung.da.subdeviceIdList': [_UUID]},
    }
    sess = _FakeSession({
        (_UUID, 'device', '0'): [
            _DEVCOL_REP, {'href': '/mode/vs/0', 'rep': {'m': 'cool'}},
        ],
    })
    subdevices, extra = enumerate_subdevices(sess, resources, oic_res_links=[])
    assert [(u.kind, u.key) for u in subdevices] == [('prefixed', _UUID)]
    # Batch echoed the bare (unprefixed) href -- normalized to carry the id.
    assert extra == {f'/{_UUID}/mode/vs/0': {'m': 'cool'}}


def test_enumerate_prefixed_tolerates_redacted_string_id_list():
    """subdeviceIdList matches redact.py's 'deviceid' substring rule, and the
    real airconditioner_fac_bora_device.json fixture carries the literal
    redacted string there -- this must yield zero subdevices, not crash."""
    resources = {
        '/subdevices/vs/0': {'x.com.samsung.da.subdeviceIdList': 'REDACTED'},
    }
    subdevices, extra = enumerate_subdevices(_FakeSession({}), resources, oic_res_links=[])
    assert subdevices == []
    assert extra == {}


def test_enumerate_no_subdevices_resource_at_all():
    subdevices, extra = enumerate_subdevices(_FakeSession({}), {}, oic_res_links=[])
    assert subdevices == []
    assert extra == {}


def test_enumerate_indexed_materializes_candidate_regardless_of_content():
    """enumerate_subdevices itself has no way to tell a real sibling from an
    unused slot that merely answers the same shape (HJcom's /device/2) --
    that's discover_partitioned's job (see its own tests below). A
    same-shaped batch of otherwise-empty reps is still returned as a
    candidate here."""
    oic_res = [{'di': 'a', 'links': [{'href': '/device/2'}]}]
    sess = _FakeSession({
        ('device', '2'): [_DEVCOL_REP, {'href': '/power/vs/2', 'rep': {}},
                           {'href': '/configuration/vs/2', 'rep': {'region': '123'}}],
    })
    subdevices, extra = enumerate_subdevices(sess, {}, oic_res)
    assert [(u.kind, u.key) for u in subdevices] == [('indexed', '2')]
    assert extra == {'/power/vs/2': {}, '/configuration/vs/2': {'region': '123'}}


def test_enumerate_probe_log_reports_every_attempt():
    oic_res = [{'di': 'aaaa', 'links': [{'href': '/device/1'}]}]
    sess = _FakeSession({
        ('device', '1'): [_DEVCOL_REP, {'href': '/mode/vs/1', 'rep': {'m': 1}}],
    })
    probes: dict[str, bool] = {}
    enumerate_subdevices(sess, {}, oic_res, probe_log=probes.__setitem__)
    # /multidevice/vs/0 is always probed too (issue #177 follow-up) -- not
    # in this session's table, so it reports "checked, nothing there".
    assert probes == {'/device/1': True, '/multidevice/vs/0': False}


def test_enumerate_probe_log_reports_empty_answers_too():
    """Distinguishes "checked, nothing there" from "never checked" (the
    posture the speculative-probe code this replaced used to document
    directly in identity.py)."""
    probes: dict[str, bool] = {}
    enumerate_subdevices(_FakeSession({}), {}, oic_res_links=[], probe_log=probes.__setitem__)
    assert probes == {
        '/device/1': False, '/device/2': False, '/multidevice/vs/0': False,
    }


def test_enumerate_multidevice_vs_0_is_captured_for_diagnostics_not_a_gate():
    """/multidevice/vs/0 (issue #177 follow-up) is corroborating evidence
    only -- captured into the merged resources so diagnostics can report
    it, never consulted by the liveness gate itself."""
    sess = _FakeSession({
        ('multidevice', 'vs', '0'): {'x.com.samsung.da.numofsubdevice': '2'},
    })
    subdevices, extra = enumerate_subdevices(sess, {}, oic_res_links=[])
    assert subdevices == []   # no /device/<n> or subdevice id answered
    assert extra == {
        '/multidevice/vs/0': {'x.com.samsung.da.numofsubdevice': '2'},
    }


def test_enumerate_both_patterns_checked_independently():
    """No board needs disambiguation logic -- enumeration just checks both
    signals and takes whatever answers."""
    resources = {
        '/subdevices/vs/0': {'x.com.samsung.da.subdeviceIdList': [_UUID]},
    }
    oic_res = [{'di': 'a', 'links': [{'href': '/device/1'}]}]
    sess = _FakeSession({
        (_UUID, 'device', '0'): [_DEVCOL_REP, {'href': '/mode/vs/0', 'rep': {'m': 1}}],
        ('device', '1'): [_DEVCOL_REP, {'href': '/mode/vs/1', 'rep': {'m': 2}}],
    })
    subdevices, extra = enumerate_subdevices(sess, resources, oic_res)
    assert sorted((u.kind, u.key) for u in subdevices) == [
        ('indexed', '1'), ('prefixed', _UUID),
    ]


# ---------------------------------------------------------------------------
# discover_partitioned
# ---------------------------------------------------------------------------

class _FakeRegistry:
    def __init__(self, name, capabilities, pattern_capabilities=()):
        self.name = name
        self.capabilities = capabilities
        self.pattern_capabilities = list(pattern_capabilities)


def test_discover_partitioned_binds_main_and_subdevice_separately():
    mode_cap = Capability(
        href='/mode/vs/0',
        entities=(BinarySensorDesc(key='mode', field='m'),),
    )
    registry = {'/mode/vs/0': [mode_cap]}
    reg = _FakeRegistry('airconditioner', registry)

    sub1 = _indexed('1')
    resources = {
        '/mode/vs/0': {'m': 'main'},
        '/mode/vs/1': {'m': 'sibling'},
    }

    def resolve(_resources):
        return reg

    bound, device_type_name, materialized, skipped = discover_partitioned(
        resources, [sub1], resolve, fallback_capabilities={},
    )

    assert device_type_name == 'airconditioner'
    assert materialized == [sub1]
    assert skipped == []
    by_href = {b.href: b for b in bound}
    assert set(by_href) == {'/mode/vs/0', '/mode/vs/1'}
    assert by_href['/mode/vs/0'].subdevice == MAIN
    assert by_href['/mode/vs/1'].subdevice == sub1


def test_discover_partitioned_main_pass_excludes_subdevice_hrefs_from_unbound():
    """A subdevice's own /mode/vs/1 must not land in the main pass's unbound
    list -- otherwise it raises a spurious coverage-gap repair for a href
    nothing in the main registry claims literally, even though the *same*
    canonical /mode/vs/0 href is properly claimed for both subdevices.

    A registry that binds /mode/vs/0 (so both the main pass and the
    subdevice pass over their own canonical views have something to claim
    it) makes this unambiguous: if partitioning were broken -- e.g. the
    main pass iterating unfiltered `resources` instead of `main_view` --
    /mode/vs/1 would show up in `unbound` because nothing in the registry
    is keyed on the literal string '/mode/vs/1'. With correct partitioning
    the main pass never sees that href at all (canonical_view excludes it),
    and the subdevice pass resolves it via its own canonical '/mode/vs/0'."""
    cap = Capability(href='/mode/vs/0', entities=(BinarySensorDesc(key='mode', field='m'),))
    reg = _FakeRegistry('airconditioner', {'/mode/vs/0': [cap]})
    sub1 = _indexed('1')
    resources = {
        '/mode/vs/0': {'m': 'main'},
        '/mode/vs/1': {'m': 'sibling'},
    }

    unbound = []
    discover_partitioned(
        resources, [sub1], lambda r: reg, fallback_capabilities={},
        log=unbound.append,
    )
    assert unbound == []


def test_discover_partitioned_subdevice_resolves_its_own_registry():
    """A subdevice reporting its own /information/vs/0 resolves its own
    device type (jhkwon19's wall subdevice: TP2X_FAC_BORA_RAC_21K -> RAC ->
    airconditioner) independent of the master's."""
    main_cap = Capability(href='/mode/vs/0', entities=(BinarySensorDesc(key='m', field='x'),))
    sub_cap = Capability(href='/mode/vs/0', entities=(BinarySensorDesc(key='m2', field='x'),))
    main_reg = _FakeRegistry('main_type', {'/mode/vs/0': [main_cap]})
    sub_reg = _FakeRegistry('sub_type', {'/mode/vs/0': [sub_cap]})

    sub1 = _indexed('1')
    resources = {'/mode/vs/0': {'x': 1}, '/mode/vs/1': {'x': 2}}

    def resolve(view):
        # The subdevice's canonical view is exactly {'/mode/vs/0': {'x': 2}}.
        return sub_reg if view.get('/mode/vs/0', {}).get('x') == 2 else main_reg

    bound, device_type_name, materialized, skipped = discover_partitioned(
        resources, [sub1], resolve, fallback_capabilities={},
    )
    assert device_type_name == 'main_type'
    assert materialized == [sub1]
    assert skipped == []
    keys = {(b.href, b.desc.key) for b in bound}
    assert ('/mode/vs/0', 'm') in keys
    assert ('/mode/vs/1', 'm2') in keys


def test_discover_partitioned_subdevice_falls_back_to_master_registry():
    """A subdevice that reports no identity of its own resolves through the
    master's registry instead of the global fallback -- the master itself
    must actually resolve here (it reports /information/vs/0), or there is
    no master registry for the fallback to reach for."""
    cap = Capability(href='/mode/vs/0', entities=(BinarySensorDesc(key='m', field='x'),))
    main_reg = _FakeRegistry('airconditioner', {'/mode/vs/0': [cap]})
    sub1 = _indexed('1')
    resources = {
        '/information/vs/0': {'model': 'main'},
        '/mode/vs/0': {'x': 1},
        '/mode/vs/1': {'x': 2},
    }

    def resolve(view):
        return main_reg if view.get('/information/vs/0') else None

    bound, _, materialized, skipped = discover_partitioned(
        resources, [sub1], resolve, fallback_capabilities={},
    )
    assert materialized == [sub1]
    assert skipped == []
    hrefs = {b.href for b in bound}
    assert '/mode/vs/1' in hrefs


def test_discover_partitioned_no_subdevices_matches_plain_discover():
    """For a device with no subdevices this must be exactly the single
    discover() call it replaces -- the hard regression guard the whole
    design exists to protect."""
    from custom_components.localthings.registry.discovery import discover

    cap = Capability(href='/mode/vs/0', entities=(BinarySensorDesc(key='m', field='x'),))
    reg = _FakeRegistry('airconditioner', {'/mode/vs/0': [cap]})
    resources = {'/mode/vs/0': {'x': 1}}

    bound_via_helper, _, materialized, skipped = discover_partitioned(
        resources, [], lambda r: reg, fallback_capabilities={},
    )
    bound_direct = discover(resources, reg.capabilities, reg.pattern_capabilities)

    assert bound_via_helper == bound_direct
    assert materialized == []
    assert skipped == []


# ---------------------------------------------------------------------------
# discover_partitioned's materialization gate: a candidate is only kept if
# it produced at least one *primary* (no entity_category) bound entity whose
# flattened value isn't None. This is what tells HJcom's real /device/1
# sibling apart from the unused /device/2 slot that answers the same shape.
# ---------------------------------------------------------------------------

def test_discover_partitioned_skips_candidate_with_no_live_primary_entity():
    """A candidate whose only populated entity is diagnostic-category
    doesn't count -- exactly HJcom's /device/2 shape (an alarm_code
    sensor reading something even though the subdevice itself is empty)."""
    diag_cap = Capability(
        href='/alarms/vs/0',
        entities=(SensorDesc(key='alarm_code', field='code', entity_category='diagnostic'),),
    )
    reg = _FakeRegistry('airconditioner', {'/alarms/vs/0': [diag_cap]})
    unit2 = _indexed('2')
    resources = {
        '/alarms/vs/0': {'code': 'main-alarm'},
        '/alarms/vs/2': {'code': 'ErrorCode_OFF'},   # populated, but diagnostic-only
    }

    bound, _, materialized, skipped = discover_partitioned(
        resources, [unit2], lambda r: reg, fallback_capabilities={},
    )
    assert materialized == []
    assert len(skipped) == 1
    assert skipped[0].subdevice == unit2
    assert skipped[0].hrefs == ('/alarms/vs/2',)
    # The candidate contributes nothing at all -- not even its diagnostic
    # entity -- once skipped.
    assert all(b.subdevice != unit2 for b in bound)


def test_discover_partitioned_materializes_candidate_with_live_primary_entity():
    """A candidate with a populated *primary* (no entity_category) entity
    is materialized, even alongside an all-empty diagnostic sibling href --
    exactly HJcom's /device/1 shape."""
    climate_cap = Capability(
        href='/mode/vs/0',
        entities=(BinarySensorDesc(key='mode', field='m'),),   # no entity_category -> primary
    )
    diag_cap = Capability(
        href='/alarms/vs/0',
        entities=(SensorDesc(key='alarm_code', field='code', entity_category='diagnostic'),),
    )
    reg = _FakeRegistry(
        'airconditioner', {'/mode/vs/0': [climate_cap], '/alarms/vs/0': [diag_cap]},
    )
    sub1 = _indexed('1')
    resources = {
        '/mode/vs/0': {'m': 'main'},
        '/alarms/vs/0': {'code': 'main-alarm'},
        '/mode/vs/1': {'m': 'Cool'},
        '/alarms/vs/1': {},   # empty -- not what makes this subdevice live
    }

    bound, _, materialized, skipped = discover_partitioned(
        resources, [sub1], lambda r: reg, fallback_capabilities={},
    )
    assert materialized == [sub1]
    assert skipped == []
    hrefs = {b.href for b in bound if b.subdevice == sub1}
    assert hrefs == {'/mode/vs/1', '/alarms/vs/1'}


def test_discover_partitioned_skipped_candidate_contributes_no_hot_warm_hrefs():
    """A skipped candidate's hrefs must not appear via tier_log either --
    'no entities, no hot/warm hrefs' (the skip is total, not just
    entity-level)."""
    cap = Capability(href='/mode/vs/0', poll_tier='warm',
                      entities=(SensorDesc(key='alarm_code', field='code',
                                            entity_category='diagnostic'),))
    reg = _FakeRegistry('airconditioner', {'/mode/vs/0': [cap]})
    unit2 = _indexed('2')
    resources = {'/mode/vs/0': {'code': 'x'}, '/mode/vs/2': {'code': 'y'}}

    tiers = []
    discover_partitioned(
        resources, [unit2], lambda r: reg, fallback_capabilities={},
        tier_log=lambda href, tier: tiers.append(href),
    )
    assert '/mode/vs/2' not in tiers
