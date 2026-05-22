"""Scorer: run a CPT (Camunda Process Test) project and parse results.

Invokes ``mvn test`` inside the verifier sandbox against the
scenario's ``cpt-verifier/`` project (mounted read-only at
``/scenarios/<id>/cpt-verifier`` via compose-cpt-verifier.yaml).
We copy the project to a writable ``/verifier-workspace`` first so
mvn can create ``target/`` without escaping the container.

The verifier container mounts the agent's whole ``/workspace`` volume
read-only at ``/agent-workspace``, so the CPT test can pick up any
BPMN the agent wrote — no requirement on the exact filename or
subdirectory.
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
        # /verifier-workspace starts empty in the verifier image.
        copy = await sb.exec(["sh", "-c", f"cp -r {project_dir}/. /verifier-workspace/"])
        if copy.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"could not copy CPT project from {project_dir}: "
                f"{copy.stderr[-500:]}",
            )
        run = await sb.exec(
            ["mvn", "-B", "-f", "/verifier-workspace/pom.xml", "test"],
            timeout=600,
        )
        passed = run.returncode == 0
        combined = "\n".join(filter(None, [run.stdout, run.stderr]))
        if passed:
            explanation = "mvn test passed"
        else:
            # mvn output is dominated by download chatter; filter to the
            # lines that actually explain the failure so the scorer's
            # 2000-char window goes to signal, not noise.
            interesting = [
                line for line in combined.splitlines()
                if any(
                    marker in line
                    for marker in (
                        "[ERROR]",
                        "BUILD FAILURE",
                        "Tests run:",
                        "FAILED!",
                        "<<< FAILURE",
                        "<<< ERROR",
                        "ConditionTimeoutException",
                        "Caused by:",
                    )
                )
            ]
            tail = "\n".join(interesting[-60:]) if interesting else combined[-2000:]
            explanation = f"mvn exit {run.returncode}\n{tail}"
        return Score(
            value=1.0 if passed else 0.0,
            answer=None,
            explanation=explanation,
            metadata={
                "mvn_returncode": run.returncode,
                # Keep a short prefix of raw output for cases where the
                # filter misses the real signal (e.g. CPT setup errors
                # that don't carry an [ERROR] marker).
                "raw_tail": combined[-2000:],
            },
        )

    return score
