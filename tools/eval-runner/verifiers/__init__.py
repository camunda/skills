"""Auto-discovery for verifier types.

A verifier module exposes:

    VERIFIER_TYPE: str   # e.g. "feel-evaluate"

    def run(case: dict, agent_outputs_dir: Path, repo_root: Path) -> Result: ...

The runner dispatches each entry of a case's ``verifiers[]`` array (in
evals.json) to the module whose ``VERIFIER_TYPE`` matches ``verifiers[i].type``.

This file holds the registry only. Real verifier implementations land in
sibling modules (feel_evaluate.py, bpmn_lint.py, etc.) under separate issues.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass
class Result:
    type: str
    passed: bool
    message: str
    details: dict[str, Any] | None = None
    skipped: bool = False  # True when prerequisite (e.g. cluster) is unavailable


class VerifierFn(Protocol):
    def __call__(
        self, case: dict, agent_outputs_dir: Path, repo_root: Path
    ) -> Result: ...


def discover() -> dict[str, VerifierFn]:
    """Return a mapping {verifier_type -> callable} of registered verifiers."""
    registry: dict[str, VerifierFn] = {}
    package = importlib.import_module(__name__)
    for mod_info in pkgutil.iter_modules(package.__path__):
        if mod_info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{mod_info.name}")
        vtype = getattr(mod, "VERIFIER_TYPE", None)
        run: Callable[..., Result] | None = getattr(mod, "run", None)
        if isinstance(vtype, str) and callable(run):
            if vtype in registry:
                raise RuntimeError(
                    f"duplicate verifier type {vtype!r} "
                    f"(already registered by another module)"
                )
            registry[vtype] = run
    return registry


__all__ = ["Result", "VerifierFn", "discover"]
