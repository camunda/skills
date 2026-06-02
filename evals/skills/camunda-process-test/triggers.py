"""Trigger eval for this skill — see ``core.triggers.build_trigger``."""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import build_trigger


@task
def trigger() -> Task:
    return build_trigger(Path(__file__).parent.name)
