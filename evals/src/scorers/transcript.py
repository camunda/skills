"""Transcript scorers: assert which skills the agent loaded / which tools it called.

Walks ``state.messages`` and inspects ``ChatMessageAssistant.tool_calls``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState


def _iter_tool_calls(state: TaskState):
    for msg in state.messages:
        for tc in getattr(msg, "tool_calls", None) or []:
            yield tc.function, (tc.arguments or {})


def _arguments_text(arguments: dict) -> str:
    parts: list[str] = []
    for value in arguments.values():
        if isinstance(value, (str, int, float, bool)):
            parts.append(str(value))
        else:
            try:
                parts.append(json.dumps(value))
            except (TypeError, ValueError):
                parts.append(repr(value))
    return " ".join(parts)


def _skill_path(skill: str) -> str:
    return f"skills/{skill}/SKILL.md"


def skills_loaded(state: TaskState, candidates: Sequence[str]) -> set[str]:
    """Subset of ``candidates`` the agent loaded — via the skill tool or a
    direct SKILL.md read. Matches three shapes: react()'s ``skill`` tool
    (``command=camunda-X``), claude_code's ``Skill`` (``skill=camunda-X``),
    and any tool arg containing ``skills/camunda-X/SKILL.md``.
    """
    cand = set(candidates)
    seen: set[str] = set()
    for function, arguments in _iter_tool_calls(state):
        args_text = _arguments_text(arguments)
        is_skill_tool = (function or "").lower() == "skill"
        invoked = arguments.get("command") or arguments.get("skill")
        for name in cand:
            if is_skill_tool and invoked == name:
                seen.add(name)
            elif _skill_path(name) in args_text:
                seen.add(name)
    return seen


@scorer(metrics=[mean(), stderr()])
def assert_skill_loaded(skill: str | Sequence[str], gating: bool = True) -> Scorer:
    """1.0 when the agent loaded every named skill, else 0.0.

    ``gating=False`` keeps the score out of the pass/fail gate (diagnostic):
    skill-load measures routing, not task success.
    """
    expected = [skill] if isinstance(skill, str) else list(skill)

    async def score(state: TaskState, target: Target) -> Score:
        seen = skills_loaded(state, expected)
        missing = [s for s in expected if s not in seen]
        return Score(
            value=1.0 if not missing else 0.0,
            answer=",".join(sorted(seen)) or None,
            explanation=(
                f"missing skills: {missing}" if missing else f"loaded: {sorted(seen)}"
            ),
            metadata={"expected": expected, "loaded": sorted(seen), "gating": gating},
        )

    return score


@scorer(metrics=[mean(), stderr()])
def assert_skill_not_loaded(skill: str | Sequence[str], gating: bool = True) -> Scorer:
    """1.0 when NONE of the named skills were loaded, else 0.0.

    Coexistence / negative-trigger check: the agent must route to the right
    skill without pulling in an anti-pattern one.
    """
    forbidden = [skill] if isinstance(skill, str) else list(skill)

    async def score(state: TaskState, target: Target) -> Score:
        loaded = skills_loaded(state, forbidden)
        return Score(
            value=0.0 if loaded else 1.0,
            answer=",".join(sorted(loaded)) or None,
            explanation=(
                f"loaded forbidden: {sorted(loaded)}"
                if loaded
                else f"avoided: {forbidden}"
            ),
            metadata={"forbidden": forbidden, "loaded": sorted(loaded), "gating": gating},
        )

    return score


@scorer(metrics=[mean(), stderr()])
def assert_tool_called(tool: str, subcommand: str | None = None) -> Scorer:
    """1.0 when a tool call references ``tool`` (and ``subcommand`` if given).

    Substring match over function name + arguments — covers both
    ``bash_session(command='c8ctl deploy ...')`` and direct calls.
    """

    async def score(state: TaskState, target: Target) -> Score:
        for function, arguments in _iter_tool_calls(state):
            haystack = f"{function} {_arguments_text(arguments)}"
            if tool not in haystack:
                continue
            if subcommand is None or subcommand in haystack:
                return Score(
                    value=1.0,
                    answer=f"{tool} {subcommand or ''}".strip(),
                    explanation=f"matched tool call: {function}({arguments})",
                )
        return Score(
            value=0.0,
            answer=None,
            explanation=f"no tool call matched {tool} {subcommand or ''}".strip(),
        )

    return score
