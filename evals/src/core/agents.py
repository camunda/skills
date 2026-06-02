"""Agent loop selection (react / claude_code) shared across scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from inspect_ai.agent import Agent, AgentPrompt, react
from inspect_ai.tool import (
    bash_session,
    grep,
    list_files,
    skill,
    text_editor,
    web_search,
)
from inspect_swe import claude_code

AgentKind = Literal["react", "claude_code"]

_WORKSPACE_RULES = """\
/workspace is the only path you share with the user — anything you save
there is what they will see and use afterwards. Save every file you
produce to /workspace (for example, /workspace/output.json). Files
written to /tmp, your home directory, or any other path are lost when
the session ends and the user will never see them.

Your working directory at session start is /workspace.
"""

_INSTRUCTIONS_REACT = (
    _WORKSPACE_RULES + "\nWhen you've completed the task, call submit() with a brief "
    "summary of what you did.\n"
)

_INSTRUCTIONS_CLAUDE_CODE = _WORKSPACE_RULES


def build_agent(
    kind: AgentKind,
    skill_dirs: Sequence[Path],
    submit: bool = True,
) -> Agent:
    """Construct the configured agent loop with the given skill set.

    ``submit=False`` removes react's submit() tool, so the agent halts when
    it stops calling tools.
    """
    if kind == "react":
        instructions = _INSTRUCTIONS_REACT if submit else _WORKSPACE_RULES
        return react(
            prompt=AgentPrompt(instructions=instructions),
            submit=submit,
            tools=[
                bash_session(timeout=300),
                text_editor(timeout=60),
                grep(timeout=30),
                list_files(timeout=30),
                web_search(),
                *([skill(list(skill_dirs))] if skill_dirs else []),
            ],
        )
    if kind == "claude_code":
        return claude_code(
            system_prompt=_INSTRUCTIONS_CLAUDE_CODE,
            skills=[str(p) for p in skill_dirs] if skill_dirs else None,
            cwd="/workspace",
            # ExitPlanMode tarpits the headless bridge (returns the
            # "Exit plan mode?" prompt instead of transitioning), so the
            # agent loops or halts without producing artifacts.
            disallowed_tools=["ExitPlanMode"],
        )
    raise ValueError(f"unknown agent: {kind!r} (expected 'react' or 'claude_code')")
