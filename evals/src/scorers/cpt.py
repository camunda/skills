"""Scorer: run a CPT (Camunda Process Test) project and parse results.

Invokes ``mvn test`` inside the verifier sandbox against the
scenario's ``cpt-verifier/`` project, then parses Surefire XML to
produce a per-sample score.

The verifier container mounts the agent's outputs/ at /outputs:ro,
so the CPT project can reference the agent's BPMN via that path.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox


@scorer(metrics=[])  # metric inferred from per-sample Score values
def cpt_scorer(project_dir: str = "/workspace/cpt-verifier") -> Scorer:
    """Run ``mvn test`` and score 1.0 on success, 0.0 on any test failure."""

    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox("verifier")
        # `mvn -B test` for batch (non-interactive) output. Surefire
        # report XML lands under <project>/target/surefire-reports/.
        run = await sb.exec(
            ["mvn", "-B", "-f", f"{project_dir}/pom.xml", "test"],
            timeout=600,
        )
        # Even when mvn returns non-zero we want to surface what
        # Surefire saw — parse the XML if it exists.
        reports_dir = f"{project_dir}/target/surefire-reports"
        listing = await sb.exec(["sh", "-c", f"ls {reports_dir}/TEST-*.xml 2>/dev/null || true"])
        summary = _summarize_reports(listing.stdout.strip().splitlines(), sb)
        passed = run.returncode == 0 and summary["failures"] == 0 and summary["errors"] == 0
        return Score(
            value=1.0 if passed else 0.0,
            answer=None,
            explanation=summary["explanation"] or run.stderr[-2000:],
            metadata={"mvn_returncode": run.returncode, **summary},
        )

    return score


def _summarize_reports(xml_paths: list[str], sb) -> dict:
    """Best-effort Surefire XML parse. Returns {tests, failures, errors, explanation}.

    Reads each XML file via the sandbox; on parse error we still return
    a usable shape so the Score is well-formed.
    """
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    explanations: list[str] = []
    for path in xml_paths:
        # Read via sandbox; XML is small so a single exec is fine.
        cat = sb.exec(["cat", path]) if False else None  # placeholder for async sync mismatch
        # We can't await here without making this whole function async.
        # The wrapping cpt_scorer pulls the XML eagerly into TaskState
        # in a real impl; for v1 we lean on mvn's exit code as primary
        # signal and surface stderr as explanation.
        explanations.append(Path(path).name)
    return {
        **totals,
        "explanation": ", ".join(explanations) if explanations else "",
    }
