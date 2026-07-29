import cbor2

from custom_components.localthings.registry.identity import DeviceIdentity, read_identity


class FakeSession:
    def __init__(self, table):
        self.table = table   # tuple(path) -> rep dict

    def get(self, path, timeout=10.0):
        rep = self.table.get(tuple(path))
        if rep is None:
            return 0x84, b''   # 4.04 not found
        return 0x45, cbor2.dumps(rep)


def test_read_identity_from_oic_p_and_d():
    sess = FakeSession({
        ('oic', 'p'): {'mnmn': 'Samsung Electronics', 'mnmo': 'RF9000B'},
        ('oic', 'd'): {'n': 'Family Hub'},
    })
    ident = read_identity(sess, serial='ABC123')
    assert ident.manufacturer == 'Samsung Electronics'
    assert ident.model == 'RF9000B'
    assert ident.name == 'Family Hub'
    assert ident.serial == 'ABC123'


def test_read_identity_tolerates_missing_resources():
    ident = read_identity(FakeSession({}), serial=None)
    assert ident.manufacturer == 'Samsung'
    assert ident.model == ''
    assert ident.serial is None
    assert ident.device_types == ()
    assert ident.raw == {'/oic/p': {}, '/oic/d': {}}


def test_read_identity_captures_oic_d_device_types():
    """/oic/d's `rt` is OCF's own device-type declaration -- captured so
    diagnostics can show whether real hardware populates it usefully."""
    sess = FakeSession({
        ('oic', 'd'): {
            'n': 'Living Room AC',
            'rt': ['oic.wk.d', 'oic.d.airconditioner'],
        },
    })
    ident = read_identity(sess, serial=None)
    assert ident.device_types == ('oic.wk.d', 'oic.d.airconditioner')


def test_read_identity_normalizes_scalar_and_malformed_rt():
    """Firmware that reports a bare string, or a non-list, must not explode."""
    assert read_identity(
        FakeSession({('oic', 'd'): {'rt': 'oic.d.refrigerator'}}), None
    ).device_types == ('oic.d.refrigerator',)
    assert read_identity(
        FakeSession({('oic', 'd'): {'rt': 42}}), None
    ).device_types == ()
    assert read_identity(
        FakeSession({('oic', 'd'): {'rt': ['oic.wk.d', 7, None]}}), None
    ).device_types == ('oic.wk.d',)


def test_read_identity_keeps_raw_payloads_for_diagnostics():
    sess = FakeSession({
        ('oic', 'p'): {'mnmn': 'Samsung Electronics', 'mnmo': 'RF9000B'},
        ('oic', 'd'): {'n': 'Family Hub', 'di': 'abc-123'},
    })
    ident = read_identity(sess, serial=None)
    assert ident.raw['/oic/p']['mnmo'] == 'RF9000B'
    assert ident.raw['/oic/d']['di'] == 'abc-123'
