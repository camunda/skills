"""Scorer: run a CPT (Camunda Process Test) project and parse results."""

from __future__ import annotations

from collections.abc import Callable

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox


@scorer(metrics=[mean(), stderr()])
def cpt_scorer(
    project_dir: str,
    mvn_extra: Callable[[str], list[str]] | None = None,
) -> Scorer:
    """Run ``mvn test`` and score 1.0 on success, 0.0 on any failure.

    ``project_dir`` is the path inside the verifier container, e.g.
    ``/scenarios/rocket-launch/cpt-verifier``.

    ``mvn_extra`` is an optional callable that receives the current
    ``state.sample_id`` and returns additional Maven arguments, e.g.
    ``lambda sid: ["-Dtest=MyIT#myMethod"]`` to restrict which test runs.
    """

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox("verifier")
        # Copy to a writable location so mvn can create target/.
        copy = await sb.exec(
            ["sh", "-c", f"cp -r {project_dir}/. /verifier-workspace/"]
        )
        if copy.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"could not copy CPT project from {project_dir}: "
                f"{copy.stderr[-500:]}",
            )
        extra = mvn_extra(state.sample_id or "") if mvn_extra else []
        run = await sb.exec(
            ["mvn", "-B", "-f", "/verifier-workspace/pom.xml", "test"] + extra,
            timeout=600,
        )
        passed = run.returncode == 0
        combined = "\n".join(filter(None, [run.stdout, run.stderr]))
        if passed:
            explanation = "mvn test passed"
        else:
            # Filter mvn's download chatter down to the failure lines.
            interesting = [
                line
                for line in combined.splitlines()
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
                # Raw tail as a fallback when the filter misses the signal.
                "raw_tail": combined[-2000:],
            },
        )

    return score
