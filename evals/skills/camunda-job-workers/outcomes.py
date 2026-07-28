"""camunda-job-workers outcome eval: choose the correct worker strategy.

Deterministic, no judge. Each sample asks for one routing decision and the agent
must write a strict JSON object to /workspace/answer.json. The scorer validates
that the selected enum matches the expected outcome for the scenario.
"""

from __future__ import annotations

import json

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-job-workers"])

SAVE = (
    "\n\nWrite ONLY this JSON object to /workspace/answer.json: "
    '{"recommendation":"<one-enum-value>"}. No markdown, no extra keys, no commentary.'
)

SAMPLES = [
    Sample(
        id="node-no-jvm",
        input=(
            "Our backend stack is Node.js/TypeScript only. We need a Camunda 8 "
            "service-task integration and do not want to run any JVM runtime. "
            "Choose ONE recommendation enum from this list: "
            "typescript-job-worker, spring-job-worker, java-job-worker, "
            "custom-java-connector, ootb-rest-connector." + SAVE
        ),
        metadata={"expected": {"recommendation": "typescript-job-worker"}},
    ),
    Sample(
        id="spring-boot-3-bridge",
        input=(
            "We already run a Spring Boot 3.5.x service and must add a Camunda "
            "job worker inside this app right now (no platform upgrade yet). "
            "Choose ONE recommendation enum from this list: "
            "spring-job-worker-sb3-starter, spring-job-worker-sb4-starter, "
            "java-job-worker, typescript-job-worker." + SAVE
        ),
        metadata={"expected": {"recommendation": "spring-job-worker-sb3-starter"}},
    ),
    Sample(
        id="payment-declined-path",
        input=(
            "In a worker, a payment provider returns a business decline that the "
            "BPMN model already handles with an error boundary event. "
            "Choose ONE recommendation enum from this list: "
            "fail-with-retries, throw-bpmn-error, unhandled-exception." + SAVE
        ),
        metadata={"expected": {"recommendation": "throw-bpmn-error"}},
    ),
]


@scorer(metrics=[mean(), stderr()])
def job_worker_outcome() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        _ = target
        sb = sandbox()
        read = await sb.exec(["cat", "/workspace/answer.json"], timeout=10)
        if read.returncode != 0:
            return Score(value=0.0, explanation="/workspace/answer.json not created")

        try:
            actual = json.loads(read.stdout)
        except json.JSONDecodeError as exc:
            return Score(value=0.0, explanation=f"answer.json is not valid JSON: {exc}")

        if not isinstance(actual, dict):
            return Score(value=0.0, explanation="answer.json must contain a JSON object")

        expected = ((state.metadata or {}).get("expected") or {}).copy()
        if not expected:
            return Score(value=0.0, explanation="missing expected metadata")

        mismatches = []
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                mismatches.append(
                    f"{key}: expected {expected_value!r}, got {actual.get(key)!r}"
                )

        if mismatches:
            return Score(
                value=0.0,
                explanation="; ".join(mismatches),
                metadata={"actual": actual, "expected": expected},
            )

        return Score(
            value=1.0,
            explanation="recommendation matches expected outcome",
            metadata={"actual": actual},
        )

    return score


@task
def camunda_job_workers(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        # submit=False: the JSON decision file is the deliverable.
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            job_worker_outcome(),
            assert_skill_loaded("camunda-job-workers", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-advisory.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=180,
        token_limit=120_000,
        message_limit=40,
    )
