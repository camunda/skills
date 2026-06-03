"""Typed eval metadata.

Every eval (trigger, skill outcome, or scenario) declares an
``EvalMetadata`` — skill evals and scenarios as a module-scope ``METADATA``
passed to ``Task(..., metadata=METADATA.model_dump())``; triggers build one
inline.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvalMetadata(BaseModel):
    """The full per-eval contract."""

    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(..., min_length=1)
    """Skills the eval depends on. CI-orchestration only (drives the
    ``eval.yml`` path-filter); does NOT restrict the runtime skill surface."""

    without_skill_excludes: list[str] | Literal["all"] | None = None
    """Skills the ``without_skill`` arm drops. Defaults to ``skills`` (drop the
    skills under test); ``"all"`` drops every skill — used by the
    ``camunda-development`` meta-router and cross-skill scenarios, where the
    skill's value only shows once the whole catalog is gone."""

    max_sandboxes: int = Field(1, ge=1)
    """How many sandboxes Inspect may run in parallel (the ``--max-sandboxes``
    value). Each sample gets its own sandbox, so this is the real concurrency
    cap. Keep 1 for cluster-backed evals — a sandbox is a whole Camunda cluster
    and concurrent JVMs starve each other. Raise it for self-contained evals
    (e.g. judge-only, no cluster) to parallelize the rollouts."""

    @property
    def excluded_skills(self) -> list[str] | Literal["all"]:
        """The resolved without-skill exclusion (defaults to ``skills``)."""
        if self.without_skill_excludes is None:
            return self.skills
        return self.without_skill_excludes
