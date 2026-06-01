"""Typed scenario metadata.

Each ``task.py`` declares a ``METADATA: ScenarioMetadata`` at module
scope, passed to ``Task(..., metadata=METADATA.model_dump())``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BaselineConfig(BaseModel):
    """Comparison-arm config. See docs/evals/concepts.md § baseline."""

    model_config = ConfigDict(extra="forbid")

    exclude: list[str] | Literal["all"] | None = None
    """Which skills the ``without_skill`` arm drops (``"all"`` = every skill)."""


class ScenarioMetadata(BaseModel):
    """The full per-scenario contract."""

    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(..., min_length=1)
    """Skills the scenario depends on. CI-orchestration only (drives the
    ``eval.yml`` path-filter); does NOT restrict the runtime skill surface."""

    baseline: BaselineConfig
    """Which without-skill arm to compare against."""
