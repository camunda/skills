"""camunda-docs outcome eval: verify docs facts and return machine-checkable JSON.

Each sample asks the agent to confirm a specific REST endpoint against official
Camunda docs and write a strict JSON payload to /workspace/answer.json.
Scoring is deterministic: exact method/path match + evidence URL shape checks.
"""

from __future__ import annotations

import json
import re

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

METADATA = EvalMetadata(skills=["camunda-docs"], max_sandboxes=10)

SAVE = (
    "\n\nReturn your verified result in /workspace/answer.json as strict JSON "
    "with exactly these keys: method, path, evidence_url."
)


@scorer(metrics=[mean(), stderr()])
def docs_endpoint_outcome() -> Scorer:
    """Score 1.0 when the JSON answer matches expected endpoint facts."""

    async def score(state: TaskState, target: Target) -> Score:
        expected_method = (state.metadata or {}).get("expected_method")
        expected_path = (state.metadata or {}).get("expected_path")
        allowed_paths = (state.metadata or {}).get("allowed_paths", [])
        evidence_fragment = (state.metadata or {}).get("evidence_fragment")

        sb = sandbox()
        result = await sb.exec(["cat", "/workspace/answer.json"], timeout=10)
        if result.returncode != 0 or not (result.stdout or "").strip():
            payload = _extract_payload_from_messages(state, expected_path or "")
            if payload is None:
                return Score(
                    value=0.0,
                    explanation="/workspace/answer.json not created",
                )
        else:
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                return Score(
                    value=0.0,
                    explanation=f"/workspace/answer.json is not valid JSON: {exc}",
                )

        if not isinstance(payload, dict):
            return Score(value=0.0, explanation="answer JSON must be an object")

        if set(payload.keys()) != {"method", "path", "evidence_url"}:
            return Score(
                value=0.0,
                explanation=(
                    "answer JSON must contain exactly keys: method, path, evidence_url"
                ),
                metadata={"keys": sorted(payload.keys())},
            )

        method = payload.get("method")
        path = payload.get("path")
        evidence_url = payload.get("evidence_url")

        if not all(
            isinstance(v, str) and v.strip() for v in (method, path, evidence_url)
        ):
            return Score(
                value=0.0,
                explanation="method, path, evidence_url must all be non-empty strings",
                metadata={"payload": payload},
            )

        method = method.strip().upper()
        path = path.strip()
        evidence_url = evidence_url.strip()

        accepted_paths = {expected_path, *allowed_paths}
        checks = {
            "method": method == expected_method,
            "path": path in accepted_paths,
            "evidence_url_prefix": evidence_url.startswith(
                "https://docs.camunda.io/docs/"
            ),
            "evidence_url_fragment": (
                True
                if not evidence_fragment
                else evidence_fragment.rstrip("/") in evidence_url
            ),
        }
        ok = all(checks.values())

        return Score(
            value=1.0 if ok else 0.0,
            explanation=(
                f"method={method!r}, path={path!r}, evidence_url={evidence_url!r}; "
                f"expected method={expected_method!r}, path={expected_path!r}"
            ),
            metadata={"checks": checks, "payload": payload},
        )

    return score


def _extract_payload_from_messages(
    state: TaskState, expected_path: str
) -> dict[str, str] | None:
    """Best-effort fallback when answer.json is missing."""

    messages = getattr(state, "messages", []) or []
    for msg in reversed(messages):
        if getattr(msg, "role", "") != "assistant":
            continue
        content = _message_text(msg)
        if not content:
            continue
        method_match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", content, re.I)
        path_matches = re.findall(r"/v2/[a-z0-9\-\/]+|/[a-z0-9\-\/]+", content, re.I)
        url_match = re.search(r"https://docs\.camunda\.io/docs/[^\s)\"']+", content)
        preferred = expected_path.split("/")[-1] if expected_path else ""
        path = ""
        if preferred:
            for candidate in path_matches:
                if preferred in candidate:
                    path = candidate
                    break
        if not path and path_matches:
            path = path_matches[0]
        if method_match and path and url_match:
            return {
                "method": method_match.group(1).upper(),
                "path": path.rstrip(".,"),
                "evidence_url": url_match.group(0).rstrip(".,"),
            }
    return None


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


SAMPLES = [
    Sample(
        id="verify-create-process-instance-endpoint",
        input=(
            "Using official Camunda docs (stable), verify the REST endpoint to "
            "create a process instance in the Orchestration Cluster API." + SAVE
        ),
        metadata={
            "expected_method": "POST",
            "expected_path": "/v2/process-instances",
            "allowed_paths": ["/process-instances"],
            "evidence_fragment": "/create-process-instance/",
        },
    ),
    Sample(
        id="verify-get-topology-endpoint",
        input=(
            "Using official Camunda docs (stable), verify the REST endpoint to "
            "get cluster topology in the Orchestration Cluster API. "
            "Do not stop after searching docs: you must create /workspace/answer.json "
            "with the final JSON object before finishing." + SAVE
        ),
        metadata={
            "expected_method": "GET",
            "expected_path": "/v2/topology",
            "allowed_paths": ["/topology"],
            "evidence_fragment": "/get-topology/",
        },
    ),
]


@task
def camunda_docs(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            docs_endpoint_outcome(),
            assert_skill_loaded("camunda-docs", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-advisory.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=180,
        token_limit=120_000,
        message_limit=60,
    )
