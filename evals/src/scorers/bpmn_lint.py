"""Scorer: run ``c8ctl bpmn lint`` against the agent's BPMN artifacts.

Excludes the ``skill()`` tool's plants under ``workspace/skills/``.
"""

from __future__ import annotations

import json

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

# c8ctl reads .bpmnlintrc from its cwd; "/" isn't agent-writable, so the
# agent can't relax the rules being scored.
LINT_CWD = "/"
CAMUNDA_RULESET = "camunda-compat/camunda-cloud-"


async def _c8ctl_json(sb, args: list[str]) -> tuple[dict | None, dict]:
    result = await sb.exec(["c8ctl", *args], cwd=LINT_CWD, timeout=60)
    raw = {
        "returncode": result.returncode,
        "stdout": (result.stdout or "")[-1500:],
        "stderr": (result.stderr or "")[-500:],
    }
    try:
        parsed = json.loads(result.stdout or "")
    except json.JSONDecodeError:
        return None, raw
    return (parsed if isinstance(parsed, dict) else None), raw


def _lint_problem(dry_run: dict | None, lint: dict | None) -> str | None:
    if dry_run is None:
        return "c8ctl bpmn lint --dry-run produced no JSON"
    extends = (dry_run.get("config") or {}).get("extends") or []
    if not any(CAMUNDA_RULESET in entry for entry in extends):
        return (
            "Camunda ruleset not applied — missing or unsupported "
            "modeler:executionPlatformVersion"
        )
    if lint is None:
        return "c8ctl bpmn lint produced no JSON"
    errors, warnings = lint.get("errorCount"), lint.get("warningCount")
    if errors == 0 and warnings == 0:
        return None
    issues = "; ".join(
        f"{i.get('elementId')}: {i.get('message')} ({i.get('rule')})"
        for i in lint.get("issues") or []
    )
    return f"{errors} error(s), {warnings} warning(s): {issues}"


@scorer(metrics=[mean(), stderr()])
def bpmn_lint_clean(workspace: str = "/workspace") -> Scorer:
    """Score 1.0 when every BPMN under ``workspace`` has zero lint errors and
    warnings under the Camunda ruleset for its declared version.

    On a violation, the explanation lists the offending file(s) and
    the metadata carries per-file ``c8ctl bpmn lint`` output for
    debugging.
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        ws = workspace.rstrip("/")
        find = await sb.exec(
            [
                "find",
                ws,
                "-maxdepth",
                "3",
                "-name",
                "*.bpmn",
                "-not",
                "-path",
                f"{ws}/skills/*",
            ],
            timeout=10,
        )
        paths = [p for p in (find.stdout or "").splitlines() if p]
        if not paths:
            return Score(
                value=0.0,
                explanation=f"no BPMN file found under {workspace}",
            )

        per_file: dict[str, dict] = {}
        violations: dict[str, str] = {}
        for path in paths:
            dry_run, dry_run_raw = await _c8ctl_json(
                sb, ["--dry-run", "bpmn", "lint", "--json", path]
            )
            lint, lint_raw = await _c8ctl_json(sb, ["bpmn", "lint", "--json", path])
            per_file[path] = {**lint_raw, "dry_run": dry_run_raw}
            problem = _lint_problem(dry_run, lint)
            if problem:
                violations[path] = problem

        if not violations:
            return Score(
                value=1.0,
                explanation=f"all {len(paths)} BPMN file(s) lint-clean",
                metadata={"files": per_file},
            )

        first_bad, problem = next(iter(violations.items()))
        return Score(
            value=0.0,
            explanation=(
                f"{len(violations)}/{len(paths)} BPMN file(s) failed lint; "
                f"first: {first_bad}\n{problem[:800]}"
            ),
            metadata={"files": per_file, "violations": list(violations)},
        )

    return score
