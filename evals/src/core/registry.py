"""Scenario metadata registry.

Imports every ``task.py`` under ``scenarios/`` and exposes a
flat JSON view for CI consumers (path-filtered workflow, PR comment
summarizer, nightly orchestration).

Single source of truth: ``METADATA: ScenarioMetadata`` declared at
the top of each scenario's ``task.py``. Schema lives in
``core.metadata`` (Pydantic).

Exposed as a console script via ``[project.scripts]`` in
``pyproject.toml``:

    uv run evals-list [--json] [--changed-skills <skill> ...]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.metadata import ScenarioMetadata
from core.paths import SCENARIOS_DIR

SCENARIO_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class ScenarioEntry:
    """A scenario discovered by ``load_all()``.

    ``id`` is the on-disk directory name. The registry validates the
    name shape (``^[a-z][a-z0-9-]*$``) at load time.
    """

    id: str
    path: Path
    metadata: ScenarioMetadata

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": str(self.path),
            **self.metadata.model_dump(),
        }


def _import_task_module(task_py: Path):
    """Import a scenario's task.py as a fresh module.

    Uses the file path as a synthetic module name so multiple
    scenarios with the same function name don't clash in sys.modules.
    """
    module_name = f"_evals_scenario_{task_py.parent.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, task_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {task_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _extract_meta(scenario_dir: Path, module) -> ScenarioMetadata:
    meta = getattr(module, "METADATA", None)
    if isinstance(meta, ScenarioMetadata):
        return meta
    if isinstance(meta, dict):
        return ScenarioMetadata.model_validate(meta)
    raise RuntimeError(
        f"{scenario_dir.name}: task.py must define METADATA: ScenarioMetadata"
    )


def load_all() -> list[ScenarioEntry]:
    scenarios: list[ScenarioEntry] = []
    if not SCENARIOS_DIR.exists():
        return scenarios

    for scenario_dir in sorted(p for p in SCENARIOS_DIR.iterdir() if p.is_dir()):
        task_py = scenario_dir / "task.py"
        if not task_py.exists():
            continue
        if not SCENARIO_ID_PATTERN.match(scenario_dir.name):
            raise RuntimeError(
                f"{scenario_dir.name}: directory name must match "
                f"{SCENARIO_ID_PATTERN.pattern}"
            )
        module = _import_task_module(task_py)
        meta = _extract_meta(scenario_dir, module)
        scenarios.append(
            ScenarioEntry(id=scenario_dir.name, path=scenario_dir, metadata=meta)
        )
    return scenarios


def filter_by_changed_skills(
    scenarios: list[ScenarioEntry], changed_skills: list[str]
) -> list[ScenarioEntry]:
    """Return scenarios whose ``metadata.skills`` intersects ``changed_skills``.

    Used by the path-filtered PR workflow to scope the run.
    """
    changed = set(changed_skills)
    return [s for s in scenarios if changed.intersection(s.metadata.skills)]


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
    print(f"{'id':<25} skills")
    for s in scenarios:
        print(f"{s.id:<25} {','.join(s.metadata.skills)}")


if __name__ == "__main__":
    main()
