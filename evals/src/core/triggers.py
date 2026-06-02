"""Trigger evals — the authoring types and the routing task, in one place.

A trigger eval asks "given this prompt, does the right skill load and the wrong
one stay out?" Each ``evals/skills/<skill>/triggers.py`` inlines its samples and
calls ``build_trigger_eval`` here to register a ``trigger_<skill>`` task. Run one with
``inspect eval skills/<skill>/triggers.py``; run them all with the glob
``inspect eval skills/*/triggers.py``.

Samples are grouped by intent. ``Positive`` prompts should load the target
skill; ``Negative`` prompts should route elsewhere and leave the target out.
The target is implicit — a positive auto-asserts ``should_load=[target]``, a
negative auto-asserts ``should_not_load=[target]`` — so it's never repeated.
Sample ids are auto-prefixed ``pos-`` / ``neg-`` from their group.

Routing is a single structured-output call: the model gets the skill catalog
(the same ``<available_skills>`` block the ``skill`` tool discloses) plus the
prompt and returns the skill names it would load — no agent, no tools, no
sandbox, no skill content read. ``excluded_skills`` drops skills from that
catalog (used to hide the meta-router ``camunda-development`` from the leaf
skills it routes to, so their trigger doesn't just re-test the router).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

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

from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import all_skill_dirs


@dataclass(frozen=True)
class Positive:
    """A prompt that should load the target skill.

    ``should_not_load`` is an OPTIONAL extra guard — sibling skills that must
    stay out even on this positive prompt (coexistence). Omit it to assert only
    that the target loads.
    """

    id: str
    prompt: str
    should_not_load: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Negative:
    """A prompt that should route elsewhere, leaving the target skill out.

    ``should_load`` is an OPTIONAL extra guard — the skill(s) that should fire
    instead. Omit it to assert only that the target stays out.
    """

    id: str
    prompt: str
    should_load: list[str] = field(default_factory=list)


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
    # Built lazily on first sample so constructing the Task (e.g. when the
    # registry calls trigger() just to read metadata) reads no SKILL.md.
    cache: dict[str, object] = {}

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if not cache:
            catalog, names = _catalog(excluded)
            cache["system"] = f"{INSTRUCTIONS}\n\n{catalog}"
            cache["schema"] = ResponseSchema(
                name="skill_routing",
                strict=True,
                json_schema=JSONSchema(
                    type="object",
                    properties={
                        "skills": JSONSchema(
                            type="array",
                            items=JSONSchema(type="string", enum=names),
                        )
                    },
                    required=["skills"],
                    additionalProperties=False,
                ),
            )
        out = await get_model().generate(
            [ChatMessageSystem(content=cache["system"]), *state.messages],
            config=GenerateConfig(response_schema=cache["schema"]),
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


def build_trigger_eval(
    skill: str,
    *,
    positive: list[Positive] = (),
    negative: list[Negative] = (),
    excluded_skills: list[str] = (),
    also_run_when_changed: list[str] = (),
) -> Task:
    """The ``trigger_<skill>`` routing task for one skill.

    Each ``skills/<skill>/triggers.py`` calls this with its own directory name
    and inlined samples. The target skill is implicit in the assertions
    (positive → ``should_load=[skill]``, negative → ``should_not_load=[skill]``)
    and ids are prefixed ``pos-`` / ``neg-``.

    ``excluded_skills`` hides skills from the routing catalog.
    ``also_run_when_changed`` widens the CI changed-skills filter only (it joins
    ``skill`` in ``metadata.skills``; no runtime effect). ``tags=["trigger"]``
    marks the log; the task is single-arm so it has no token baseline.
    """
    if not positive and not negative:
        raise ValueError(f"{skill}: need at least one positive or negative sample")
    if skill in excluded_skills:
        raise ValueError(f"{skill}: excluded_skills cannot hide the target skill")

    samples = [
        Sample(
            id=f"pos-{s.id}",
            input=s.prompt,
            metadata={"should_load": [skill], "should_not_load": s.should_not_load},
        )
        for s in positive
    ] + [
        Sample(
            id=f"neg-{s.id}",
            input=s.prompt,
            metadata={"should_load": s.should_load, "should_not_load": [skill]},
        )
        for s in negative
    ]
    metadata = ScenarioMetadata(
        skills=[skill, *also_run_when_changed], baseline=BaselineConfig(exclude="all")
    )
    return Task(
        name=f"trigger_{skill.replace('-', '_')}",
        dataset=samples,
        solver=route(list(excluded_skills)),
        scorer=[skill_loaded(), skill_not_loaded()],
        metadata=metadata.model_dump(),
        token_limit=20_000,
        tags=["trigger"],
    )
