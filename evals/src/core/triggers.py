"""Trigger evals — data, validation, and the routing task, all in one place.

A trigger eval asks "given this prompt, does the right skill load and the
wrong one stay out?" The data lives in ``evals/skills/<skill>/triggers.yaml``;
each skill dir has a thin ``triggers.py`` shim that calls ``build_trigger`` here
to register a ``trigger_<skill>`` task. Run one with
``inspect eval skills/<skill>/triggers.py``; run them all with the glob
``inspect eval skills/*/triggers.py``.

Samples are grouped by intent. ``positive`` prompts should load the target
skill; ``negative`` prompts should route elsewhere and leave the target out.
The target is implicit — a positive auto-asserts ``should_load: [target]``, a
negative auto-asserts ``should_not_load: [target]`` — so it's never repeated.
Sample ids are auto-prefixed ``pos-`` / ``neg-`` from their group.

Routing is a single structured-output call: the model gets the skill catalog
(the same ``<available_skills>`` block the ``skill`` tool discloses) plus the
prompt and returns the skill names it would load — no agent, no tools, no
sandbox, no skill content read. A file's ``excluded_skills`` drops skills from
that catalog (used to hide the meta-router ``camunda-development`` from the leaf
skills it routes to, so their trigger doesn't just re-test the router).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from inspect_ai import Task
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessageSystem,
    GenerateConfig,
    ResponseSchema,
    get_model,
)
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool._tools._skill.read import read_skills
from inspect_ai.tool._tools._skill.tool import _available_skills
from inspect_ai.util import JSONSchema
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SKILL_EVALS_DIR, all_skill_dirs


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


ROUTED_KEY = "routed_skills"

INSTRUCTIONS = (
    "The following skills provide specialized instructions for specific tasks. "
    "Given the task, decide which skill(s) you would load to handle it, judging "
    "relevance from each description. Do not solve the task — return only the "
    "names of the skills you would load, or an empty list if none apply."
)


def _catalog(excluded: list[str]) -> tuple[str, list[str]]:
    """The ``<available_skills>`` block + valid names, as the skill tool
    discloses them, minus any skills in ``excluded``."""
    skills = read_skills([str(p) for p in all_skill_dirs()])
    skills = [s for s in skills if s.name not in excluded]
    return _available_skills(skills), [s.name for s in skills]


@solver
def route(excluded: list[str]) -> Solver:
    catalog, names = _catalog(excluded)
    system = f"{INSTRUCTIONS}\n\n{catalog}"
    schema = ResponseSchema(
        name="skill_routing",
        strict=True,
        json_schema=JSONSchema(
            type="object",
            properties={
                "skills": JSONSchema(
                    type="array", items=JSONSchema(type="string", enum=names)
                )
            },
            required=["skills"],
            additionalProperties=False,
        ),
    )

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        out = await get_model().generate(
            [ChatMessageSystem(content=system), *state.messages],
            config=GenerateConfig(response_schema=schema),
        )
        state.output = out
        state.messages.append(out.message)
        try:
            routed = json.loads(out.completion).get("skills", [])
        except (json.JSONDecodeError, AttributeError, TypeError):
            routed = []
        state.store.set(ROUTED_KEY, routed)
        return state

    return solve


@scorer(metrics=[mean(), stderr()])
def skill_loaded() -> Scorer:
    """Gating: every skill in the sample's ``should_load`` was routed to.
    ``None`` (no-op) for samples without a ``should_load``."""

    async def score(state: TaskState, target: Target) -> Score | None:
        expected = state.metadata.get("should_load") or []
        if not expected:
            return None
        routed = set(state.store.get(ROUTED_KEY) or [])
        missing = [s for s in expected if s not in routed]
        return Score(
            value=1.0 if not missing else 0.0,
            answer=",".join(sorted(routed)) or None,
            explanation=f"missing: {missing}"
            if missing
            else f"routed: {sorted(routed)}",
            metadata={"expected": expected, "routed": sorted(routed)},
        )

    return score


@scorer(metrics=[mean(), stderr()])
def skill_not_loaded() -> Scorer:
    """Gating: none of the sample's ``should_not_load`` skills were routed to.
    ``None`` for samples without a ``should_not_load``."""

    async def score(state: TaskState, target: Target) -> Score | None:
        forbidden = state.metadata.get("should_not_load") or []
        if not forbidden:
            return None
        routed = set(state.store.get(ROUTED_KEY) or [])
        hit = sorted(routed & set(forbidden))
        return Score(
            value=0.0 if hit else 1.0,
            answer=",".join(hit) or None,
            explanation=f"routed to forbidden: {hit}" if hit else "ok",
            metadata={"forbidden": forbidden, "routed": sorted(routed)},
        )

    return score


def build_trigger(skill: str) -> Task:
    """The ``trigger_<skill>`` routing task for one skill's ``triggers.yaml``.

    Each ``skills/<skill>/triggers.py`` is a one-line shim that calls this with
    its own directory name — copy that shim into a new skill dir alongside a
    ``triggers.yaml`` and the trigger eval exists. Run one with
    ``inspect eval skills/<skill>/triggers.py``; run them all with the glob
    ``inspect eval skills/*/triggers.py`` (the filename selects triggers).

    ``tags=["trigger"]`` marks it in the log; the task is single-arm (you can't
    load an absent skill) so it has no token baseline.
    """
    spec = load_trigger_file(skill)
    samples = [
        Sample(
            id=s.id,
            input=s.prompt,
            metadata={
                "should_load": s.should_load,
                "should_not_load": s.should_not_load,
            },
        )
        for s in spec.samples
    ]
    metadata = ScenarioMetadata(
        skills=spec.skills, baseline=BaselineConfig(exclude="all")
    )
    return Task(
        name=f"trigger_{skill.replace('-', '_')}",
        dataset=samples,
        solver=route(spec.excluded_skills),
        scorer=[skill_loaded(), skill_not_loaded()],
        metadata=metadata.model_dump(),
        token_limit=20_000,
        tags=["trigger"],
    )
