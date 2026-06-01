"""Scorer: run ``c8ctl bpmn lint`` against the agent's BPMN artifacts.

Excludes the ``skill()`` tool's plants under ``workspace/skills/``.
"""

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox


@scorer(metrics=[mean(), stderr()])
def bpmn_lint_clean(workspace: str = "/workspace") -> Scorer:
    """Score 1.0 when every BPMN under ``workspace`` lints clean.

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
                "-maxdepth", "3",
                "-name", "*.bpmn",
                "-not", "-path", f"{ws}/skills/*",
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
        violations: list[str] = []
        for path in paths:
            result = await sb.exec(
                ["c8ctl", "bpmn", "lint", path], timeout=60
            )
            per_file[path] = {
                "returncode": result.returncode,
                "stdout": (result.stdout or "")[-1500:],
                "stderr": (result.stderr or "")[-500:],
            }
            if result.returncode != 0:
                violations.append(path)

        if not violations:
            return Score(
                value=1.0,
                explanation=f"all {len(paths)} BPMN file(s) lint-clean",
                metadata={"files": per_file},
            )

        first_bad = violations[0]
        tail = per_file[first_bad]["stdout"] or per_file[first_bad]["stderr"]
        return Score(
            value=0.0,
            explanation=(
                f"{len(violations)}/{len(paths)} BPMN file(s) failed lint; "
                f"first: {first_bad}\n{tail[-800:]}"
            ),
            metadata={"files": per_file, "violations": violations},
        )

    return score
