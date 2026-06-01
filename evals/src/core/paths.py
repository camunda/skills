"""Filesystem layout constants.

Source of truth for where the framework finds scenarios + sandbox
recipes + the skills under test.

``EVALS_ROOT`` is the ``evals/`` directory; ``SCENARIOS_DIR`` and
``SANDBOXES_DIR`` are derived from it. ``SKILLS_DIR`` resolves to the
sibling ``skills/`` directory (the skills under test).

These resolve correctly when the package is installed editable (the
common case via ``uv sync``): ``__file__`` points at the source tree
(``evals/src/core/paths.py``), so ``parents[2]`` reaches ``evals/``
regardless of where ``pyproject.toml`` lives. A non-editable wheel
install would break this — fine because the harness is always
installed editable from this repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

EVALS_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = EVALS_ROOT / "scenarios"
SANDBOXES_DIR = EVALS_ROOT / "sandboxes"
SKILL_EVALS_DIR = EVALS_ROOT / "skills"
SKILLS_DIR = EVALS_ROOT.parent / "skills"

Arm = Literal["with_skill", "without_skill"]


def all_skill_dirs() -> list[Path]:
    """Return every ``skills/<name>/`` directory with a SKILL.md.

    Matches what a real CLI plugin loader would expose: all installed
    skills, no per-scenario allowlist. Trigger/discovery behavior then
    falls out of the agent's tool-choice, not our configuration.
    """
    return sorted(
        p for p in SKILLS_DIR.iterdir()
        if p.is_dir() and (p / "SKILL.md").exists()
    )


def skill_dirs_for_arm(
    arm: Arm,
    exclude: list[str] | Literal["all"] | None,
) -> list[Path]:
    """Skill dirs the agent sees, after applying the without-skill exclusion.

    ``with_skill``: every installed skill (the full menu).
    ``without_skill``: drop the names listed in ``exclude`` (the load-bearing
    skills the scenario is measuring); ``exclude="all"`` drops every skill,
    leaving the agent with no skill tool surface at all.
    """
    dirs = all_skill_dirs()
    if arm == "with_skill":
        return dirs
    if arm == "without_skill":
        if exclude == "all":
            return []
        if exclude:
            excluded = set(exclude)
            return [d for d in dirs if d.name not in excluded]
        return dirs
    raise ValueError(f"unknown arm: {arm!r} (expected 'with_skill' or 'without_skill')")
