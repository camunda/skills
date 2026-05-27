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

The INSTRUCTIONS blocks carry only Inspect-harness conventions
(``/workspace`` persistence; submit() for the react path). Every
Camunda fact the agent needs is either in the user prompt or
discoverable via the skill tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

from inspect_ai.agent import Agent, AgentPrompt, react
from inspect_ai.tool import bash_session, grep, list_files, skill, text_editor, web_search
from inspect_swe import claude_code

AgentKind = Literal["react", "claude_code"]

# react() needs an explicit submit() instruction; claude_code()
# completes when the agent stops calling tools.
_INSTRUCTIONS_REACT = """\
A local Camunda cluster is already running. Don't start a new one.

Files you create only persist for review if they're under /workspace.
Anything you write to /tmp, the home directory, etc. is lost when the
session ends.

When you've completed the task, call submit() with a brief summary
of what you did.
"""

_INSTRUCTIONS_CLAUDE_CODE = """\
A local Camunda cluster is already running. Don't start a new one.

Files you create only persist for review if they're under /workspace.
Anything you write to /tmp, the home directory, etc. is lost when the
session ends.
"""


def build_agent(kind: AgentKind, skill_dirs: Sequence[Path]) -> Agent:
    """Construct the configured agent loop with the given skill set."""
    if kind == "react":
        return react(
            prompt=AgentPrompt(instructions=_INSTRUCTIONS_REACT),
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
        )
    raise ValueError(f"unknown agent: {kind!r} (expected 'react' or 'claude_code')")
