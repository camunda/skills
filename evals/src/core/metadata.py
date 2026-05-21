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
Verifier = Literal["cpt", "exit-code", "transcript", "judge", "composite"]


class BaselineConfig(BaseModel):
    """Comparison-arm config. See docs/evals/concepts.md § baseline."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["without-skill", "none"]
    exclude: list[str] | Literal["all"] | None = None


class ScenarioMetadata(BaseModel):
    """The full per-scenario contract.

    The scenario id is the directory name (resolved by the registry);
    no ``id`` field here. The sandbox is declared explicitly on
    ``Task(sandbox=...)`` per scenario — no field here either.
    """

    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(..., min_length=1)
    epochs: int = Field(default=1, ge=1)
    tier: Tier
    verifier: Verifier
    baseline: BaselineConfig
