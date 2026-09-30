import compat_matrix


def test_floor_treats_bare_version_as_lower_bound() -> None:
    assert compat_matrix.floor("8.8") == (8, 8)


def test_floor_accepts_lower_bound_comparators() -> None:
    assert compat_matrix.floor(">=8.8") == (8, 8)
    assert compat_matrix.floor(">8.8") == (8, 8)
    assert compat_matrix.floor("~8.8") == (8, 8)
    assert compat_matrix.floor("^8.8") == (8, 8)
    assert compat_matrix.floor("=8.8") == (8, 8)


def test_floor_rejects_upper_only_ranges() -> None:
    # An upper-only range declares a ceiling, not a minimum; it must not be
    # rendered under a "Minimum version" heading.
    assert compat_matrix.floor("<9.0") is None
    assert compat_matrix.floor("<=9.0") is None


def test_floor_rejects_malformed_ranges() -> None:
    assert compat_matrix.floor("*") is None
    assert compat_matrix.floor("not-a-version") is None
    assert compat_matrix.floor(">=8.8.1.2") is None
