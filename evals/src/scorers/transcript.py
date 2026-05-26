"""Transcript-shaped scorers: assert what the agent loaded / called.

Walks ``state.messages`` (the proper Inspect API) and inspects
``ChatMessageAssistant.tool_calls`` to test claims about agent
behaviour.

Used by trigger-shaped scenarios (docs invocation, routing) and as a
chain check on multi-skill scenarios to verify the cross-references
actually route the agent through the suite.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState


def _iter_tool_calls(state: TaskState):
    """Yield (function_name, arguments_dict) for every tool call in
    the transcript.

    Iterates assistant messages — those are the only ones that emit
    tool calls. Returns the arguments dict directly; callers can
    stringify or pull specific keys as needed.
    """
    for msg in state.messages:
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            yield tc.function, (tc.arguments or {})


def _arguments_text(arguments: dict) -> str:
    """Render a tool call's arguments to a single searchable string.

    bash_session / bash typically expose ``command`` or ``input``;
    text_editor uses ``command`` + ``path`` + ``file_text``; the
    skill tool uses ``name``. Joining values covers all of them
    without per-tool knowledge.
    """
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


@scorer(metrics=[mean(), stderr()])
def assert_skill_loaded(skill: str | Sequence[str]) -> Scorer:
    """Score 1.0 when the agent loaded every named skill via the
    skill tool (or read its SKILL.md directly); 0.0 otherwise.

    Matches both shapes:
    - Inspect's ``skill`` tool was called with ``name="camunda-X"``
    - The agent read ``skills/camunda-X/SKILL.md`` via any tool whose
      arguments include that path
    """
    expected = [skill] if isinstance(skill, str) else list(skill)

    async def score(state: TaskState, target: Target) -> Score:
        seen: set[str] = set()
        for function, arguments in _iter_tool_calls(state):
            args_text = _arguments_text(arguments)
            for skill_name in expected:
                if function == "skill" and arguments.get("command") == skill_name:
                    seen.add(skill_name)
                elif _skill_path(skill_name) in args_text:
                    seen.add(skill_name)
        missing = [s for s in expected if s not in seen]
        return Score(
            value=1.0 if not missing else 0.0,
            answer=",".join(sorted(seen)) or None,
            explanation=(
                f"missing skills: {missing}" if missing else f"loaded: {sorted(seen)}"
            ),
            metadata={"expected": expected, "loaded": sorted(seen)},
        )

    return score


@scorer(metrics=[mean(), stderr()])
def assert_tool_called(tool: str, subcommand: str | None = None) -> Scorer:
    """Score 1.0 when the agent's tool calls reference ``tool`` (and
    ``subcommand`` if provided); 0.0 otherwise.

    Matches on substring within tool-call arguments — covers both
    "agent called bash_session with command='c8ctl deploy ...'" and
    direct function-name calls. Useful for "did the agent reach for
    c8ctl deploy" without coupling to the specific tool wrapper.
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
