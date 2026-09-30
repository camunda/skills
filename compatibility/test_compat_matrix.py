import compat_matrix


def test_floor_treats_bare_version_as_lower_bound() -> None:
    assert compat_matrix.floor("8.8") == (8, 8)


def test_floor_accepts_lower_bound_comparators() -> None:
    assert compat_matrix.floor(">=8.8") == (8, 8)
    assert compat_matrix.floor("~8.8") == (8, 8)
    assert compat_matrix.floor("^8.8") == (8, 8)
    assert compat_matrix.floor("=8.8") == (8, 8)


def test_floor_rejects_strict_lower_bound() -> None:
    # A strict lower bound (`>8.8`) is not satisfied by 8.8, so reducing it to
    # `(8, 8)` and rendering it under a "Minimum version" heading would mislead.
    # It must not contribute a floor.
    assert compat_matrix.floor(">8.8") is None
    assert compat_matrix.floor(">9.0.1") is None


def test_floor_rejects_upper_only_ranges() -> None:
    # An upper-only range declares a ceiling, not a minimum; it must not be
    # rendered under a "Minimum version" heading.
    assert compat_matrix.floor("<9.0") is None
    assert compat_matrix.floor("<=9.0") is None


def test_floor_rejects_malformed_ranges() -> None:
    assert compat_matrix.floor("*") is None
    assert compat_matrix.floor("not-a-version") is None
    assert compat_matrix.floor(">=8.8.1.2") is None
