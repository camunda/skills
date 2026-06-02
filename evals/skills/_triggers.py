"""Generic trigger eval — one parametrized task driven by the YAML files.

A trigger eval asks "given this prompt, does the right skill load and the
wrong one stay out?" The data lives in ``evals/skills/<skill>/triggers.yaml``;
this single ``@task`` reads one skill's file (selected via ``-T skill=…``) and
names itself ``trigger_<skill>`` so each run is its own eval in the viewer.

    inspect eval skills/_triggers.py -T skill=camunda-feel    # one skill
    make eval-trigger SKILL=camunda-feel                       # same, wrapped
    make eval-triggers                                         # loop all skills

Routing is a single structured-output call: the model gets the skill catalog
(the same ``<available_skills>`` block the ``skill`` tool discloses) and the
task prompt, and returns the skill names it would load — no tools, no sandbox,
no skill content read. We score that set against the sample's assertions.

A file's ``excluded_skills`` drops skills from that catalog — used to hide
the meta-router ``camunda-development`` from the leaf skills it routes to, so
their trigger doesn't just re-test whether the router fires.

The leading underscore on this filename is load-bearing: Inspect skips
``_``-prefixed files when globbing a directory for tasks, so it isn't
auto-instantiated (``trigger`` has no default ``skill``). We always invoke it
explicitly as ``skills/_triggers.py@trigger``. Result evals are hand-written
``task.py`` per directory.
"""

from __future__ import annotations

import json

from inspect_ai import Task, task
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
from core.triggers import load_trigger_file

ROUTED_KEY = "routed_skills"

INSTRUCTIONS = (
    "The following skills provide specialized instructions for specific tasks. "
    "Given the task, decide which skill(s) you would load to handle it, judging "
    "relevance from each description. Do not solve the task — return only the "
    "names of the skills you would load, or an empty list if none apply."
)


def _catalog(omit: list[str]) -> tuple[str, list[str]]:
    """The ``<available_skills>`` block + valid names, as the skill tool
    discloses them, minus any skills in ``omit``."""
    skills = read_skills([str(p) for p in all_skill_dirs()])
    skills = [s for s in skills if s.name not in omit]
    return _available_skills(skills), [s.name for s in skills]


@solver
def route(omit: list[str]) -> Solver:
    catalog, names = _catalog(omit)
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


@task
def trigger(skill: str) -> Task:
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
    )
