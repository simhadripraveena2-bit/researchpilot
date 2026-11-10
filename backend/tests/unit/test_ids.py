from researchpilot.core.ids import uuid7


def test_uuid7_version_variant_and_order() -> None:
    ids = [uuid7() for _ in range(200)]
    assert all(u.version == 7 for u in ids)
    assert all(u.variant == "specified in RFC 4122" for u in ids)
    assert len(set(ids)) == len(ids)
    # Time-ordered at millisecond resolution: the timestamp prefix never decreases.
    prefixes = [u.int >> 80 for u in ids]
    assert prefixes == sorted(prefixes)
