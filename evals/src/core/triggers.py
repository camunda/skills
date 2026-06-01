"""Trigger evals: one ``triggers.yaml`` per skill, parsed + validated here.

A trigger eval asks "given this prompt, does the right skill load and the
wrong one stay out?" The data lives in ``evals/skills/<skill>/triggers.yaml``;
``evals/skills/_triggers.py`` turns each file into a ``trigger_<skill>`` task.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from core.paths import SKILL_EVALS_DIR


class TriggerSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    should_load: list[str] = Field(default_factory=list)
    should_not_load: list[str] = Field(default_factory=list)


class TriggerFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_skill: str
    # CI-detection only: editing one of these skills also reruns this eval.
    # No effect on what runs at agent time.
    also_run_when_changed: list[str] = Field(default_factory=list)
    samples: list[TriggerSample] = Field(..., min_length=1)

    @property
    def skills(self) -> list[str]:
        return [self.target_skill, *self.also_run_when_changed]


def _load(path: Path) -> TriggerFile:
    skill_dir = path.parent.name
    data = yaml.safe_load(path.read_text()) or {}
    spec = TriggerFile.model_validate(data)
    if spec.target_skill != skill_dir:
        raise ValueError(
            f"{path}: target_skill {spec.target_skill!r} != directory {skill_dir!r}"
        )
    return spec


def load_trigger_file(skill: str) -> TriggerFile:
    """The validated ``triggers.yaml`` for one skill (raises if absent)."""
    path = SKILL_EVALS_DIR / skill / "triggers.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no triggers.yaml for skill {skill!r} ({path})")
    return _load(path)


def load_trigger_files() -> list[TriggerFile]:
    """Every ``evals/skills/<skill>/triggers.yaml``, validated.

    The directory name is the canonical target skill; ``target_skill`` in
    the body must match it (guards against rename drift).
    """
    if not SKILL_EVALS_DIR.exists():
        return []
    return [_load(p) for p in sorted(SKILL_EVALS_DIR.glob("*/triggers.yaml"))]
