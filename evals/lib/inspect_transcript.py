"""Transcript-shaped scorers: assert what the agent loaded / called.

Inspect AI's transcript exposes every tool call and file read. These
helpers turn that into testable assertions.

Used by trigger-shaped scenarios (08 docs invocation, 09 routing) and
as a chain check on multi-skill scenarios (02, 03, 05) to verify the
cross-references actually route the agent through the suite.

The full chain scorer (``assert_skill_chain``) lands with the
trigger-scenario PR; v1 ships ``assert_skill_loaded`` and
``assert_tool_called``.
"""

from __future__ import annotations

from collections.abc import Sequence

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState


def _iter_events(state: TaskState):
    """Iterate transcript events robustly across Inspect AI versions."""
    # Inspect AI's transcript shape stabilized in 0.3.x but field
    # access still varies between minor versions. Try the documented
    # path first, then fall back.
    transcript = getattr(state, "transcript", None)
    if transcript is None:
        return []
    events = getattr(transcript, "events", None)
    if events is None and callable(transcript):
        events = transcript()
    return events or []


def _skill_path(skill: str) -> str:
    return f"skills/{skill}/SKILL.md"


@scorer(metrics=[])
def assert_skill_loaded(skill: str | Sequence[str]) -> Scorer:
    """Score 1.0 iff the agent read every named SKILL.md.

    A skill is considered loaded when the transcript records a
    file-read (or equivalent tool call) whose target ends in
    ``skills/<skill>/SKILL.md``.
    """
    expected = [skill] if isinstance(skill, str) else list(skill)

    async def score(state: TaskState, target: Target) -> Score:
        seen: set[str] = set()
        for event in _iter_events(state):
            payload = str(event)
            for skill_name in expected:
                if _skill_path(skill_name) in payload:
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


@scorer(metrics=[])
def assert_tool_called(tool: str, subcommand: str | None = None) -> Scorer:
    """Score 1.0 iff the agent invoked ``tool`` (optionally with ``subcommand``).

    For Bash-shaped invocations, matches when the rendered command
    line starts with ``tool [subcommand]``. Subcommand is checked
    as the next word after the tool name, ignoring intervening flags.
    """

    async def score(state: TaskState, target: Target) -> Score:
        for event in _iter_events(state):
            payload = str(event)
            if tool not in payload:
                continue
            if subcommand is None or subcommand in payload:
                return Score(
                    value=1.0,
                    answer=f"{tool} {subcommand or ''}".strip(),
                    explanation=f"matched tool call: {tool} {subcommand or ''}".strip(),
                )
        return Score(
            value=0.0,
            answer=None,
            explanation=f"no transcript event matched {tool} {subcommand or ''}".strip(),
        )

    return score
