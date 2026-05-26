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

Tier = Literal["pr", "nightly", "release"]


class BaselineConfig(BaseModel):
    """Comparison-arm config. See docs/evals/concepts.md § baseline."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["without-skill", "none"]
    exclude: list[str] | Literal["all"] | None = None


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

    epochs: int = Field(default=1, ge=1)
    """Inspect's per-sample repetition count. Bump to ≥3 for
    trigger / judge-scored scenarios where pass-rate flake matters.
    """

    tier: Tier
    """When CI runs this scenario. ``pr`` = on PR (when CI is on);
    ``nightly`` = scheduled main run only; ``release`` = on ``v*``
    tags. Local ``make eval`` ignores this — runs whatever you ask for.
    """

    baseline: BaselineConfig
    """Which without-skill arm to compare against. See
    ``docs/evals/concepts.md`` § baseline."""
