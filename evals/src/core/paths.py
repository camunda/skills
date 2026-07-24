"""Filesystem layout constants."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

# parents[2] reaches evals/; relies on the editable install layout.
EVALS_ROOT = Path(__file__).resolve().parents[2]
# The two eval-target roots.
SKILL_EVALS_DIR = EVALS_ROOT / "skills"
SCENARIO_EVALS_DIR = EVALS_ROOT / "scenarios"

SANDBOXES_DIR = EVALS_ROOT / "sandboxes"
SKILLS_DIR = EVALS_ROOT.parent / "skills"  # the product skills under test

Arm = Literal["with_skill", "without_skill"]


def all_skill_dirs() -> list[Path]:
    """Return every ``skills/<name>/`` directory with a SKILL.md."""
    return sorted(
        p for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
    )


def skill_dirs_for_arm(
    arm: Arm,
    exclude: list[str] | Literal["all"] | None,
) -> list[Path]:
    """Skill dirs the agent sees, after applying the without-skill exclusion.

    ``without_skill`` drops the names in ``exclude``; ``exclude="all"``
    drops every skill.
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
