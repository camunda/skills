"""Typed scenario metadata.

Each ``task.py`` declares a ``METADATA: ScenarioMetadata`` at module
scope. The registry imports it, validates structurally via Pydantic
(no manual checks), and exposes it to CI consumers as JSON.

The metadata is passed to ``Task(..., metadata=METADATA.model_dump())``
so Inspect AI sees the canonical dict shape. Solvers / scorers /
registry consumers can round-trip back to the typed model via
``ScenarioMetadata.model_validate(task_metadata)`` (or
``Sample.metadata_as(ScenarioMetadata)`` per Inspect's
``metadata_as`` pattern).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Phase 1 (agent) container image. Verifier presence is implicit from
# `verifier` — when it's "cpt" or a composite that includes CPT, the
# verifier service spins up via the cpt-verifier compose archetype.
Image = Literal["base", "with-c8ctl"]

Tier = Literal["pr", "nightly", "release"]

Verifier = Literal["cpt", "exit-code", "transcript", "judge", "composite"]


class BaselineConfig(BaseModel):
    """Comparison-arm config. See docs/evals/concepts.md § baseline."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["without-skill", "none"]
    exclude: list[str] | Literal["all"] | None = None


class ScenarioMetadata(BaseModel):
    """The full per-scenario contract.

    Defined at module scope in each scenario's ``task.py`` as ``METADATA``;
    Inspect AI consumes ``METADATA.model_dump()`` via the ``Task(metadata=...)``
    parameter.
    """

    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(..., min_length=1)
    image: Image
    epochs: int = Field(default=1, ge=1)
    tier: Tier
    verifier: Verifier
    baseline: BaselineConfig
