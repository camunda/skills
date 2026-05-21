"""Filesystem layout constants.

Source of truth for where the framework finds scenarios + sandbox
recipes. ``EVALS_ROOT`` is the ``evals/`` directory; ``SCENARIOS_DIR``
and ``SANDBOXES_DIR`` are derived from it.

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
