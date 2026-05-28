"""Agent loop selection — shared across scenarios.

Two interchangeable agent paths:

- ``react`` — Inspect's ``react()`` with ``bash_session``,
  ``text_editor``, ``grep``, ``list_files``, ``web_search``, and
  ``skill``. Inspect-driven loop; submit() terminates.
- ``claude_code`` — ``inspect_swe.claude_code()`` bridge: runs the
  real Claude Code CLI inside the sandbox, brings its own native
  Bash/Edit/Read/Grep/Glob/WebSearch toolset, accepts ``skills`` as
  a list of directories. Halts when the agent stops calling tools.

``build_agent(kind, skill_dirs)`` returns an Inspect ``Agent``;
wrap with ``solvers.collect_artifacts.with_artifact_collection`` to
keep artifact capture working regardless of which loop is selected.

The system-prompt rules here are domain-agnostic — only workspace
operation (`/workspace` durability) and the react-loop submit()
convention. Per-scenario environment facts (e.g. "a cluster is
already running") belong in the user prompt; implementation hints
(port numbers, tool names) stay out so the skills carry them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from inspect_ai.agent import Agent, AgentPrompt, react
from inspect_ai.tool import bash_session, grep, list_files, skill, text_editor, web_search
from inspect_swe import claude_code

AgentKind = Literal["react", "claude_code"]

# System-prompt rules carry only how to operate in the workspace. No
# hint about the task domain, no hint that this is an eval — the
# agent should treat the session as a normal user session.
_WORKSPACE_RULES = """\
/workspace is the only path you share with the user — anything you save
there is what they will see and use afterwards. Save every file you
produce to /workspace (for example, /workspace/output.json). Files
written to /tmp, your home directory, or any other path are lost when
the session ends and the user will never see them.

Your working directory at session start is /workspace.
"""

# react() needs an explicit submit() instruction; claude_code() halts
# when the agent stops calling tools.
_INSTRUCTIONS_REACT = (
    _WORKSPACE_RULES
    + "\nWhen you've completed the task, call submit() with a brief "
    "summary of what you did.\n"
)

_INSTRUCTIONS_CLAUDE_CODE = _WORKSPACE_RULES


def build_agent(
    kind: AgentKind,
    skill_dirs: Sequence[Path],
    submit: bool = True,
) -> Agent:
    """Construct the configured agent loop with the given skill set.

    ``submit=False`` removes react's submit() tool; the agent then
    halts as soon as it stops calling tools (matching claude_code's
    halt-on-no-tool-call behavior). Useful for advisory scenarios
    where the agent's final text IS the deliverable and a separate
    "submit" step would just nudge the agent toward implementation.
    Has no effect for claude_code (no submit tool to remove).
    """
    if kind == "react":
        instructions = (
            _INSTRUCTIONS_REACT if submit else _WORKSPACE_RULES
        )
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
            # ExitPlanMode tarpits the headless bridge: invoking it
            # returns the literal prompt "Exit plan mode?" as the tool
            # result rather than transitioning the agent out of plan
            # mode. The agent then loops on it or halts without
            # producing artifacts. Empirically observed in early CC
            # runs; root cause (bridge missing approval hook? CLI bug?
            # by design?) not documented. Disabling it sidesteps the
            # tarpit — when ExitPlanMode is unavailable, the agent
            # tends not to call EnterPlanMode either.
            disallowed_tools=["ExitPlanMode"],
        )
    raise ValueError(f"unknown agent: {kind!r} (expected 'react' or 'claude_code')")
