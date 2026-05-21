"""Filesystem layout constants.

Source of truth for where the framework finds scenarios + sandbox
recipes + the skills under test.

``EVALS_ROOT`` is the ``evals/`` directory; ``SCENARIOS_DIR`` and
``SANDBOXES_DIR`` are derived from it. ``SKILLS_DIR`` resolves to the
sibling ``skills/`` directory (the skills under test).

These resolve correctly when the package is installed editable (the
common case via ``uv sync``): ``__file__`` points at the source tree,
so ``parents[2]`` reaches ``evals/``. A non-editable wheel install
would break this — fine because the harness is always installed
editable from this repo.
"""

from __future__ import annotations

from pathlib import Path

EVALS_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = EVALS_ROOT / "src" / "scenarios"
SANDBOXES_DIR = EVALS_ROOT / "sandboxes"
SKILLS_DIR = EVALS_ROOT.parent / "skills"


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
