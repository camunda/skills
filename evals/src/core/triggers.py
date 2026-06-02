"""Trigger evals: one ``triggers.yaml`` per skill, parsed + validated here.

A trigger eval asks "given this prompt, does the right skill load and the
wrong one stay out?" The data lives in ``evals/skills/<skill>/triggers.yaml``;
``evals/skills/_triggers.py`` turns each file into a ``trigger_<skill>`` task.

Samples are grouped by intent. ``positive`` prompts should load the target
skill; ``negative`` prompts should route elsewhere and leave the target out.
The target is implicit — a positive auto-asserts ``should_load: [target]``, a
negative auto-asserts ``should_not_load: [target]`` — so it's never repeated.
Sample ids are auto-prefixed ``pos-`` / ``neg-`` from their group.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.paths import SKILL_EVALS_DIR


class TriggerSample(BaseModel):
    """A normalized sample: prompt + the two skill-load assertions."""

    id: str
    prompt: str
    should_load: list[str] = Field(default_factory=list)
    should_not_load: list[str] = Field(default_factory=list)


class PositiveSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    # Coexistence guard: siblings that must stay out even on a positive prompt.
    should_not_load: list[str] = Field(default_factory=list)


class NegativeSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    # The skill that should load instead of the target.
    should_load: list[str] = Field(default_factory=list)


class TriggerFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_skill: str
    # CI-detection only: editing one of these skills also reruns this eval.
    # No effect on what runs at agent time.
    also_run_when_changed: list[str] = Field(default_factory=list)
    # Skills to hide from the catalog the model routes against. Use it to drop
    # a meta-router (camunda-development) that would otherwise absorb this
    # skill's prompts before the leaf skill gets a look-in.
    excluded_skills: list[str] = Field(default_factory=list)
    positive: list[PositiveSample] = Field(default_factory=list)
    negative: list[NegativeSample] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> TriggerFile:
        if not self.positive and not self.negative:
            raise ValueError(
                "triggers.yaml needs at least one positive or negative sample"
            )
        if self.target_skill in self.excluded_skills:
            raise ValueError("excluded_skills cannot hide the target skill")
        return self

    @property
    def skills(self) -> list[str]:
        return [self.target_skill, *self.also_run_when_changed]

    @property
    def samples(self) -> list[TriggerSample]:
        out = [
            TriggerSample(
                id=f"pos-{s.id}",
                prompt=s.prompt,
                should_load=[self.target_skill],
                should_not_load=s.should_not_load,
            )
            for s in self.positive
        ]
        out += [
            TriggerSample(
                id=f"neg-{s.id}",
                prompt=s.prompt,
                should_load=s.should_load,
                should_not_load=[self.target_skill],
            )
            for s in self.negative
        ]
        return out


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
