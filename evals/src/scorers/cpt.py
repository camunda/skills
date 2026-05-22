"""Scorer: run a CPT (Camunda Process Test) project and parse results.

Invokes ``mvn test`` inside the verifier sandbox against the
scenario's ``cpt-verifier/`` project (mounted read-only at
``/scenarios/<id>/cpt-verifier`` via compose-cpt-verifier.yaml).
We copy the project to a writable ``/workspace`` first so mvn can
create ``target/`` without escaping the container.

The verifier container also mounts the agent's outputs/ at
``/outputs:ro``, so the CPT project can reference the agent's BPMN
via that path (e.g. ``/outputs/process.bpmn``).
"""

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox


@scorer(metrics=[])
def cpt_scorer(project_dir: str) -> Scorer:
    """Run ``mvn test`` and score 1.0 on success, 0.0 on any failure.

    ``project_dir`` is the path inside the verifier container — e.g.
    ``/scenarios/rocket-launch/cpt-verifier``. Compose's
    ``../src/scenarios:/scenarios:ro`` mount makes that resolve to the
    scenario's CPT project in the repo.
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox("verifier")
        # Copy to a writable location so mvn can create target/.
        # /workspace starts empty in the verifier image.
        copy = await sb.exec(["sh", "-c", f"cp -r {project_dir}/. /workspace/"])
        if copy.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"could not copy CPT project from {project_dir}: "
                f"{copy.stderr[-500:]}",
            )
        run = await sb.exec(
            ["mvn", "-B", "-f", "/workspace/pom.xml", "test"],
            timeout=600,
        )
        passed = run.returncode == 0
        # Surefire XML lives under /workspace/target/surefire-reports.
        # mvn's stderr/stdout already surface failures; surface them
        # directly rather than re-parse the XML for v1.
        explanation = (
            "mvn test passed"
            if passed
            else f"mvn exit {run.returncode}: {(run.stderr or run.stdout)[-2000:]}"
        )
        return Score(
            value=1.0 if passed else 0.0,
            answer=None,
            explanation=explanation,
            metadata={"mvn_returncode": run.returncode},
        )

    return score
