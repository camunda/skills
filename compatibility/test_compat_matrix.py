import json
from pathlib import Path

import compat_matrix


def write_skill(root: Path, name: str, requires: dict[str, str]) -> None:
    sidecar = root / "skills" / name
    sidecar.mkdir(parents=True)
    (sidecar / "portability.json").write_text(
        json.dumps({"requires": requires}), encoding="utf-8"
    )


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


def test_render_emits_bundle_version_and_max_floors(tmp_path: Path) -> None:
    # The rendered Compatibility section is published verbatim into each GitHub
    # Release's notes, so assert the exact Markdown: the bundle version, the
    # per-tool floor aggregated as the *maximum* across skills, and the table.
    root = tmp_path / "repository"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"version": "2.3.4"}), encoding="utf-8"
    )
    write_skill(root, "alpha", {"camunda": ">=8.8", "c8ctl": ">=3.0.0"})
    write_skill(root, "beta", {"camunda": ">=8.9", "c8ctl": ">=3.1.0"})

    assert compat_matrix.render(root) == (
        "### Compatibility\n"
        "\n"
        "`camunda-skills@2.3.4` declares these minimum versions:\n"
        "\n"
        "| Component | Minimum version |\n"
        "| --- | --- |\n"
        "| Skills bundle | 2.3.4 |\n"
        "| Camunda | 8.9 |\n"
        "| c8ctl | 3.1.0 |\n"
        "\n"
        "Per-skill dependency envelopes (including any language/tooling floors)"
        " are declared in each skill's `portability.json` under `requires`.\n"
    )


def test_render_omits_tools_without_a_lower_bound(tmp_path: Path) -> None:
    # A tool whose every range is upper-only (`<9.0`) or strict (`>8.8`) yields
    # no safe minimum, so it must not appear under the "Minimum version"
    # heading; a tool that no skill declares is omitted entirely.
    root = tmp_path / "repository"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"version": "1.0.0"}), encoding="utf-8"
    )
    write_skill(root, "alpha", {"camunda": "<9.0", "c8ctl": ">=3.0.0"})
    write_skill(root, "beta", {"camunda": ">8.8"})

    rendered = compat_matrix.render(root)

    assert "| c8ctl | 3.0.0 |" in rendered
    assert "| Camunda |" not in rendered
