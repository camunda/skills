"""Generic trigger eval — one parametrized task driven by the YAML files.

A trigger eval asks "given this prompt, does the right skill load and the
wrong one stay out?" The data lives in ``evals/skills/<skill>/triggers.yaml``;
this single ``@task`` reads one skill's file (selected via ``-T skill=…``) and
names itself ``trigger_<skill>`` so each run is its own eval in the viewer.

    inspect eval skills/_triggers.py -T skill=camunda-feel    # one skill
    make eval-trigger SKILL=camunda-feel                       # same, wrapped
    make eval-triggers                                         # loop all skills

(Inspect discovers file tasks by AST-parsing ``@task`` decorators, so the task
must be defined literally here — not generated dynamically. Result evals are
hand-written ``task.py`` per directory.)
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.agent import AgentState
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store

from core.agents import AgentKind, build_agent
from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, all_skill_dirs
from core.triggers import load_trigger_file
from scorers.transcript import skills_loaded
from solvers.collect_artifacts import with_artifact_collection

_ADVISORY = SANDBOXES_DIR / "compose-advisory.yaml"
_TARGETS_KEY = "trigger_targets"


def _loaded_skills(state: AgentState) -> set[str]:
    loaded: set[str] = set()
    for msg in state.messages:
        for call in getattr(msg, "tool_calls", None) or []:
            if (call.function or "").lower() == "skill":
                name = (call.arguments or {}).get("command")
                if name:
                    loaded.add(name)
    return loaded


async def _stop_when_targets_loaded(state: AgentState) -> bool | str:
    """Stop the routing loop once every ``should_load`` target is loaded, so
    the target's SKILL.md is never read into a follow-up generation (that
    re-read is the bulk of a trigger's cost). Until then keep going — some
    prompts route through ``camunda-development`` before the leaf skill."""
    targets = set(store().get(_TARGETS_KEY) or [])
    if targets and targets <= _loaded_skills(state):
        return False
    return "If a skill applies to this request, load it; otherwise reply briefly."


@solver
def _routing(agent) -> Solver:
    """Stash the sample's ``should_load`` so the stop hook can read it, then
    run the agent (artifacts collected whatever happens)."""
    inner = with_artifact_collection(agent)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.store.set(_TARGETS_KEY, state.metadata.get("should_load") or [])
        return await inner(state, generate)

    return solve


@scorer(metrics=[mean(), stderr()])
def skill_loaded() -> Scorer:
    """Gating: every skill in the sample's ``should_load`` was loaded.
    ``None`` (no-op) for samples without a ``should_load``."""

    async def score(state: TaskState, target: Target) -> Score | None:
        expected = state.metadata.get("should_load") or []
        if not expected:
            return None
        seen = skills_loaded(state, expected)
        missing = [s for s in expected if s not in seen]
        return Score(
            value=1.0 if not missing else 0.0,
            answer=",".join(sorted(seen)) or None,
            explanation=f"missing: {missing}" if missing else f"loaded: {sorted(seen)}",
            metadata={"expected": expected, "loaded": sorted(seen)},
        )

    return score


@scorer(metrics=[mean(), stderr()])
def skill_not_loaded() -> Scorer:
    """Gating: none of the sample's ``should_not_load`` skills were loaded.
    ``None`` for samples without a ``should_not_load``."""

    async def score(state: TaskState, target: Target) -> Score | None:
        forbidden = state.metadata.get("should_not_load") or []
        if not forbidden:
            return None
        loaded = skills_loaded(state, forbidden)
        return Score(
            value=0.0 if loaded else 1.0,
            answer=",".join(sorted(loaded)) or None,
            explanation=f"loaded forbidden: {sorted(loaded)}" if loaded else "ok",
            metadata={"forbidden": forbidden, "loaded": sorted(loaded)},
        )

    return score


@task
def trigger(skill: str, agent: AgentKind = "react") -> Task:
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
        solver=_routing(
            build_agent(
                agent,
                all_skill_dirs(),
                submit=False,
                skill_only=True,
                on_continue=_stop_when_targets_loaded,
            )
        ),
        scorer=[skill_loaded(), skill_not_loaded()],
        sandbox=("docker", str(_ADVISORY)),
        metadata=metadata.model_dump(),
        time_limit=180,
        token_limit=200_000,
        message_limit=40,
    )
