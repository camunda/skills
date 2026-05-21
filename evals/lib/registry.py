"""Scenario metadata registry.

Imports every ``task.py`` under ``evals/scenarios/`` and exposes a
flat JSON view for CI consumers (path-filtered workflow, PR comment
summarizer, nightly orchestration, assertion-hygiene cron).

Single source of truth: ``@task(metadata={...})`` declared inside
each scenario's ``task.py``. No YAML sidecars.

Run as a script to dump the registry:

    uv run python -m evals.lib.registry [--json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"

# Schema for metadata. Validated explicitly here so violations surface
# at registry-load time rather than at scenario-run time.
ALLOWED_IMAGES = {"base", "with-c8ctl", "with-c8ctl+verifier"}
ALLOWED_TIERS = {"pr", "nightly", "release"}
ALLOWED_VERIFIERS = {"cpt", "exit-code", "transcript", "judge", "composite"}
ALLOWED_BASELINE_MODES = {"without-skill", "none"}


@dataclass(frozen=True)
class ScenarioMeta:
    id: str
    path: Path
    skills: list[str]
    image: Literal["base", "with-c8ctl", "with-c8ctl+verifier"]
    epochs: int
    tier: Literal["pr", "nightly", "release"]
    verifier: Literal["cpt", "exit-code", "transcript", "judge", "composite"]
    baseline: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": str(self.path.relative_to(SCENARIOS_DIR.parent.parent)),
            "skills": list(self.skills),
            "image": self.image,
            "epochs": self.epochs,
            "tier": self.tier,
            "verifier": self.verifier,
            "baseline": self.baseline,
        }


def _validate(scenario_id: str, meta: dict[str, Any]) -> None:
    missing = {"skills", "image", "epochs", "tier", "verifier", "baseline"} - meta.keys()
    if missing:
        raise ValueError(f"{scenario_id}: missing metadata fields: {sorted(missing)}")

    if not isinstance(meta["skills"], list) or not all(isinstance(s, str) for s in meta["skills"]):
        raise ValueError(f"{scenario_id}: 'skills' must be list[str]")
    if meta["image"] not in ALLOWED_IMAGES:
        raise ValueError(f"{scenario_id}: image must be one of {sorted(ALLOWED_IMAGES)}")
    if not isinstance(meta["epochs"], int) or meta["epochs"] < 1:
        raise ValueError(f"{scenario_id}: epochs must be int >= 1")
    if meta["tier"] not in ALLOWED_TIERS:
        raise ValueError(f"{scenario_id}: tier must be one of {sorted(ALLOWED_TIERS)}")
    if meta["verifier"] not in ALLOWED_VERIFIERS:
        raise ValueError(f"{scenario_id}: verifier must be one of {sorted(ALLOWED_VERIFIERS)}")

    baseline = meta["baseline"]
    if not isinstance(baseline, dict) or "mode" not in baseline:
        raise ValueError(f"{scenario_id}: baseline must be a dict with a 'mode' key")
    if baseline["mode"] not in ALLOWED_BASELINE_MODES:
        raise ValueError(
            f"{scenario_id}: baseline.mode must be one of {sorted(ALLOWED_BASELINE_MODES)}"
        )
    if baseline["mode"] == "without-skill":
        exclude = baseline.get("exclude")
        if exclude != "all" and not (
            isinstance(exclude, list) and all(isinstance(s, str) for s in exclude)
        ):
            raise ValueError(
                f"{scenario_id}: baseline.exclude must be 'all' or list[str] when mode='without-skill'"
            )


def _import_task_module(task_py: Path):
    """Import a scenario's task.py as a fresh module.

    Uses the file path as a synthetic module name so multiple
    scenarios with the same function name don't clash in sys.modules.
    """
    module_name = f"_evals_scenario_{task_py.parent.name}"
    spec = importlib.util.spec_from_file_location(module_name, task_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {task_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _extract_meta(module) -> dict[str, Any] | None:
    """Find the @task-decorated callable and return its metadata dict.

    Inspect AI attaches metadata via the @task decorator. We invoke
    the task callable to read the resulting Task object's metadata,
    falling back to a module-level ``METADATA`` dict when invoking
    isn't safe (e.g., during static scenario discovery in CI).
    """
    if hasattr(module, "METADATA") and isinstance(module.METADATA, dict):
        return module.METADATA
    for attr in vars(module).values():
        if callable(attr) and hasattr(attr, "__wrapped__"):
            # Best-effort: read metadata from the @task decorator
            # closure. Inspect AI exposes it on the resulting Task,
            # so prefer the module-level METADATA convention above.
            meta = getattr(attr, "metadata", None)
            if isinstance(meta, dict):
                return meta
    return None


def load_all() -> list[ScenarioMeta]:
    scenarios: list[ScenarioMeta] = []
    if not SCENARIOS_DIR.exists():
        return scenarios

    for scenario_dir in sorted(p for p in SCENARIOS_DIR.iterdir() if p.is_dir()):
        task_py = scenario_dir / "task.py"
        if not task_py.exists():
            continue
        module = _import_task_module(task_py)
        meta = _extract_meta(module)
        if meta is None:
            raise RuntimeError(
                f"{scenario_dir.name}: task.py must define METADATA or a @task with metadata"
            )
        _validate(scenario_dir.name, meta)
        scenarios.append(
            ScenarioMeta(
                id=scenario_dir.name,
                path=scenario_dir,
                skills=meta["skills"],
                image=meta["image"],
                epochs=meta["epochs"],
                tier=meta["tier"],
                verifier=meta["verifier"],
                baseline=meta["baseline"],
            )
        )
    return scenarios


def filter_by_changed_skills(
    scenarios: list[ScenarioMeta], changed_skills: list[str]
) -> list[ScenarioMeta]:
    """Return scenarios where ``metadata.skills`` intersects ``changed_skills``.

    Used by the path-filtered PR workflow to scope the run.
    """
    changed = set(changed_skills)
    return [s for s in scenarios if changed.intersection(s.skills)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON (default: human table)")
    parser.add_argument(
        "--changed-skills",
        nargs="*",
        default=None,
        help="filter by skills (intersection); used by CI path-filter",
    )
    args = parser.parse_args()

    scenarios = load_all()
    if args.changed_skills is not None:
        scenarios = filter_by_changed_skills(scenarios, args.changed_skills)

    if args.json:
        print(json.dumps([s.to_json() for s in scenarios], indent=2))
        return

    if not scenarios:
        print("(no scenarios)")
        return
    print(f"{'id':<35} {'image':<22} {'tier':<10} {'verifier':<12} skills")
    for s in scenarios:
        print(
            f"{s.id:<35} {s.image:<22} {s.tier:<10} {s.verifier:<12} {','.join(s.skills)}"
        )


if __name__ == "__main__":
    main()
