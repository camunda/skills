"""Auto-discovery for verifier types.

A verifier module exposes:

    VERIFIER_TYPE: str   # e.g. "feel-evaluate"

    def run(verifier: dict, case: dict, outputs_dir: Path, repo_root: Path) -> Result:
        ...

Where:

  - ``verifier`` is the single entry being checked from
    ``evals.json[].verifiers[i]`` (e.g. ``{"type": "feel-evaluate",
    "context": {...}, "expected": ...}``).
  - ``case`` is the full case dict for context (id, prompt, expectations).
  - ``outputs_dir`` is the per-trial agent outputs directory containing
    files such as ``answer.feel`` or ``process.bpmn``.
  - ``repo_root`` is the repo root, useful for resolving the c8ctl CLI or
    other tooling paths.

The orchestrator iterates ``case.verifiers[]``, dispatches each entry to the
module whose ``VERIFIER_TYPE`` matches, and aggregates the Results.

Result.skipped=True signals "could not run the check" (e.g. ``c8`` CLI not
installed, cluster unreachable). Skipped verifiers do NOT fail the case —
they are reported in summary.json so reviewers can see what wasn't
checked.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass
class Result:
    type: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str | None = None  # e.g. "no-cli", "no-cluster", "no-output-file"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "passed": self.passed,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "message": self.message,
            "details": self.details,
        }


class VerifierFn(Protocol):
    def __call__(
        self,
        verifier: dict[str, Any],
        case: dict[str, Any],
        outputs_dir: Path,
        repo_root: Path,
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


def run_all(
    case: dict[str, Any],
    outputs_dir: Path,
    repo_root: Path,
    registry: dict[str, VerifierFn] | None = None,
) -> list[Result]:
    """Dispatch every ``case.verifiers[i]`` to the matching module."""
    if registry is None:
        registry = discover()
    out: list[Result] = []
    for v in case.get("verifiers", []) or []:
        vtype = v.get("type")
        fn = registry.get(vtype)
        if fn is None:
            out.append(
                Result(
                    type=str(vtype),
                    passed=False,
                    message=f"unknown verifier type {vtype!r}",
                )
            )
            continue
        try:
            out.append(fn(v, case, outputs_dir, repo_root))
        except Exception as e:  # noqa: BLE001
            out.append(
                Result(
                    type=str(vtype),
                    passed=False,
                    message=f"verifier raised: {e!r}",
                )
            )
    return out


__all__ = ["Result", "VerifierFn", "discover", "run_all"]
