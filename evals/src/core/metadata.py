"""Typed scenario metadata.

Each ``task.py`` declares a ``METADATA: ScenarioMetadata`` at module
scope. The registry imports it; Pydantic validates the schema
(``extra="forbid"`` catches typos at task-load time).

The metadata is passed to ``Task(..., metadata=METADATA.model_dump())``
so Inspect AI sees the canonical dict shape.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BaselineConfig(BaseModel):
    """Comparison-arm config. See docs/evals/concepts.md § baseline."""

    model_config = ConfigDict(extra="forbid")

    exclude: list[str] | Literal["all"] | None = None
    """Which skills the ``without_skill`` arm drops. ``"all"`` removes
    every skill; a list removes the named ones; ``None`` keeps the full
    menu (rarely useful for a baseline arm)."""


class ScenarioMetadata(BaseModel):
    """The full per-scenario contract.

    The scenario id is the directory name (resolved by the registry);
    no ``id`` field here. The sandbox is declared explicitly on
    ``Task(sandbox=...)`` per scenario — no field here either. The
    scorer list lives on the ``Task`` too; ``ScenarioMetadata`` doesn't
    duplicate it (one source of truth).
    """

    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(..., min_length=1)
    """Skills the scenario depends on. CI-orchestration only — drives
    the path-filter in ``eval.yml`` (a PR touching ``skills/<X>/`` runs
    scenarios where ``X in metadata.skills``) and acts as documentation
    of the load-bearing dependencies. Does NOT restrict the skill tool
    surface at runtime; the agent sees every installed skill modulo
    the without-skill arm's ``baseline.exclude``.
    """

    baseline: BaselineConfig
    """Which without-skill arm to compare against. See
    ``docs/evals/concepts.md`` § baseline."""
