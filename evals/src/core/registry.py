"""Eval target registry — the single source of truth for CI.

Discovers two eval kinds and exposes them as a flat JSON list (consumed by the
path-filtered PR workflow and the nightly run):

- ``outcome`` — an agent-in-sandbox e2e eval (``outcomes.py``). Scope is the
  directory: ``skills/<skill>/`` (single-skill) or ``scenarios/<id>/``
  (cross-skill). Same execution; the scope shows in the id (``skill:`` /
  ``scenario:``).
- ``trigger`` — ``skills/<skill>/triggers.py`` (run via ``…@trigger_eval``).

Each target carries the Inspect invocation (path / task / args) and the
skills it depends on, so the CI matrix can both run it and filter by
changed skills.

    uv run evals-list [--json] [--changed-skills <skill> ...]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.metadata import EvalMetadata
from core.paths import EVALS_ROOT, SCENARIOS_DIR, SKILL_EVALS_DIR

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class EvalTarget:
    id: str  # "scenario:<id>" | "skill:<skill>" | "trigger:<skill>"
    kind: str
    skills: list[str]
    path: str  # relative to EVALS_ROOT
    task: str | None = None  # explicit @task name, if any
    args: dict[str, str] = field(default_factory=dict)
    max_sandboxes: int = 1  # --max-sandboxes for outcome evals (from METADATA)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "skills": self.skills,
            "path": self.path,
            "task": self.task,
            "args": self.args,
            "max_sandboxes": self.max_sandboxes,
        }


def _import_module(module_py: Path):
    # Include the file stem so outcomes.py and triggers.py in the same skill dir
    # don't collide in sys.modules.
    module_name = (
        f"_evals_{module_py.parent.parent.name}"
        f"_{module_py.parent.name.replace('-', '_')}_{module_py.stem}"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _metadata(outcomes_py: Path) -> EvalMetadata:
    meta = getattr(_import_module(outcomes_py), "METADATA", None)
    if isinstance(meta, EvalMetadata):
        return meta
    if isinstance(meta, dict):
        return EvalMetadata.model_validate(meta)
    raise RuntimeError(f"{outcomes_py}: must define METADATA: EvalMetadata")


def _rel(path: Path) -> str:
    return path.relative_to(EVALS_ROOT).as_posix()


def _outcome_targets(base: Path, scope: str) -> list[EvalTarget]:
    # ``scope`` ("skill" | "scenario") is just the id prefix; both run the same.
    targets: list[EvalTarget] = []
    if not base.exists():
        return targets
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        outcomes_py = d / "outcomes.py"
        if not outcomes_py.exists():
            continue
        if not NAME_PATTERN.match(d.name):
            raise RuntimeError(
                f"{d.name}: directory name must match {NAME_PATTERN.pattern}"
            )
        meta = _metadata(outcomes_py)
        targets.append(
            EvalTarget(
                id=f"{scope}:{d.name}",
                kind="outcome",
                skills=list(meta.skills),
                path=_rel(outcomes_py),
                max_sandboxes=meta.max_sandboxes,
            )
        )
    return targets


def _trigger_targets() -> list[EvalTarget]:
    targets: list[EvalTarget] = []
    if not SKILL_EVALS_DIR.exists():
        return targets
    for triggers_py in sorted(SKILL_EVALS_DIR.glob("*/triggers.py")):
        skill = triggers_py.parent.name
        if not NAME_PATTERN.match(skill):
            raise RuntimeError(
                f"{skill}: directory name must match {NAME_PATTERN.pattern}"
            )
        # Call the @task to read its metadata (the catalog is built lazily, so
        # this constructs the Task without reading any SKILL.md).
        task = _import_module(triggers_py).trigger_eval()
        targets.append(
            EvalTarget(
                id=f"trigger:{skill}",
                kind="trigger",
                skills=list(task.metadata["skills"]),
                path=_rel(triggers_py),
                task="trigger_eval",
            )
        )
    return targets


def discover() -> list[EvalTarget]:
    targets = _outcome_targets(SCENARIOS_DIR, "scenario")
    targets += _outcome_targets(SKILL_EVALS_DIR, "skill")
    targets += _trigger_targets()
    return targets


def filter_by_changed_skills(
    targets: list[EvalTarget], changed_skills: list[str]
) -> list[EvalTarget]:
    changed = set(changed_skills)
    return [t for t in targets if changed.intersection(t.skills)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit JSON (default: human table)"
    )
    parser.add_argument(
        "--changed-skills",
        nargs="*",
        default=None,
        help="filter by skills (intersection); used by the CI path-filter",
    )
    args = parser.parse_args()

    targets = discover()
    if args.changed_skills is not None:
        targets = filter_by_changed_skills(targets, args.changed_skills)

    if args.json:
        print(json.dumps([t.to_json() for t in targets], indent=2))
        return
    if not targets:
        print("(no eval targets)")
        return
    print(f"{'id':<34} {'kind':<9} skills")
    for t in targets:
        print(f"{t.id:<34} {t.kind:<9} {','.join(t.skills)}")


if __name__ == "__main__":
    main()
