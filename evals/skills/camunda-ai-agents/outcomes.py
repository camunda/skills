"""camunda-ai-agents outcome eval: model an AI-agent subprocess BPMN and deploy it.

Deterministic, machine-checkable verification:
- ``ai_agent_shape_valid`` parses ``/workspace/process.bpmn`` and checks for
  an ad-hoc subprocess host, tool documentation, ``fromAi()`` usage,
  ``toolCallResult`` wiring, and prompt/limit inputs.

Skill-load is diagnostic; the without-skill arm drops only camunda-ai-agents.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-ai-agents"], max_sandboxes=1)

BPMN_PATH = "/workspace/process.bpmn"
MISSING_CONFIGURATION_SAMPLE_ID = "missing-provider-configuration"

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "zeebe": "http://camunda.org/schema/zeebe/1.0",
}

ACTIVITY_TAGS = {
    f"{{{NS['bpmn']}}}serviceTask",
    f"{{{NS['bpmn']}}}scriptTask",
    f"{{{NS['bpmn']}}}userTask",
    f"{{{NS['bpmn']}}}subProcess",
}

REQUEST_MARKERS = (
    "which",
    "what",
    "provide",
    "specify",
    "confirm",
    "tell me",
    "identify",
    "indicate",
    "share",
    "supply",
)


def _normalize_literal(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.startswith("="):
        normalized = normalized[1:].strip()
    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in {"'", '"'}
    ):
        normalized = normalized[1:-1]
    return normalized


def _matches_secret_reference(source: str, expected_name: str) -> bool:
    return _normalize_literal(source) == f"{{{{secrets.{expected_name}}}}}"


def _assistant_text(state: TaskState) -> str:
    chunks: list[str] = []
    for message in state.messages:
        if getattr(message, "role", None) != "assistant":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            chunks.extend(
                part if isinstance(part, str) else str(getattr(part, "text", part))
                for part in content
            )
    return "\n".join(chunks)


def _is_request_sentence(sentence: str) -> bool:
    return "?" in sentence or any(
        re.search(rf"\b{re.escape(marker)}\b", sentence)
        for marker in REQUEST_MARKERS
    )


@scorer(metrics=[mean(), stderr()])
def ai_agent_shape_valid(path: str = BPMN_PATH) -> Scorer:
    """Verify that the authored BPMN contains core AI-agent subprocess wiring."""

    async def score(state: TaskState, target: Target) -> Score:
        if state.sample_id != "ticket-triage-subprocess":
            return Score(
                value=1.0,
                explanation="AI-agent shape check not applicable to this sample",
            )

        expected_process_id = (state.metadata or {}).get("process_id")
        required_tools = set((state.metadata or {}).get("required_tools", []))
        expected_provider = (state.metadata or {}).get("provider")
        expected_model = (state.metadata or {}).get("model")
        expected_authentication_secrets = (
            (state.metadata or {}).get("authentication_secrets") or {}
        )

        sb = sandbox()
        cat = await sb.exec(["cat", path], timeout=10)
        if cat.returncode != 0 or not (cat.stdout or "").strip():
            return Score(value=0.0, explanation=f"missing BPMN artifact at {path}")

        try:
            root = ET.fromstring(cat.stdout)
        except ET.ParseError as exc:
            return Score(value=0.0, explanation=f"invalid XML at {path}: {exc}")

        process = None
        for proc in root.findall("bpmn:process", NS):
            if expected_process_id is None or proc.get("id") == expected_process_id:
                process = proc
                break
        if process is None:
            return Score(
                value=0.0,
                explanation=f"process id {expected_process_id!r} not found in {path}",
            )

        hosts = process.findall("bpmn:adHocSubProcess", NS)
        if not hosts:
            return Score(
                value=0.0,
                explanation="missing bpmn:adHocSubProcess host for AI Agent connector",
            )

        host = hosts[0]
        tools = [child for child in list(host) if child.tag in ACTIVITY_TAGS]
        if not tools:
            return Score(
                value=0.0,
                explanation="ad-hoc subprocess has no tool activities",
            )

        tool_ids = {tool.get("id") for tool in tools if tool.get("id")}
        missing_tools = sorted(t for t in required_tools if t not in tool_ids)
        if missing_tools:
            return Score(
                value=0.0,
                explanation=f"missing required tool ids: {missing_tools}",
                metadata={"tool_ids": sorted(tool_ids)},
            )

        undocumented = []
        for tool in tools:
            doc = tool.find("bpmn:documentation", NS)
            if doc is None or not (doc.text or "").strip():
                undocumented.append(tool.get("id") or "<unknown>")
        if undocumented:
            return Score(
                value=0.0,
                explanation=f"tool(s) missing bpmn:documentation: {undocumented}",
            )

        from_ai_inputs = [
            inp
            for inp in host.findall(".//zeebe:input", NS)
            if "fromAi(" in (inp.get("source") or "")
        ]
        if not from_ai_inputs:
            return Score(
                value=0.0,
                explanation="no zeebe:input source uses fromAi(...)",
            )

        has_tool_result = False
        for node in host.iter():
            if (
                node.tag == f"{{{NS['zeebe']}}}output"
                and node.get("target") == "toolCallResult"
            ):
                has_tool_result = True
                break
            if (
                node.tag == f"{{{NS['zeebe']}}}script"
                and node.get("resultVariable") == "toolCallResult"
            ):
                has_tool_result = True
                break
            if (
                node.tag == f"{{{NS['zeebe']}}}header"
                and node.get("key") in {"resultExpression", "resultVariable"}
                and "toolCallResult" in (node.get("value") or "")
            ):
                has_tool_result = True
                break
        if not has_tool_result:
            return Score(
                value=0.0,
                explanation="missing toolCallResult mapping in tool implementation",
            )

        host_inputs = {
            inp.get("target"): inp.get("source") or ""
            for inp in host.findall(
                "./bpmn:extensionElements/zeebe:ioMapping/zeebe:input",
                NS,
            )
            if inp.get("target")
        }
        missing_configuration = []
        if expected_provider:
            provider_source = host_inputs.get("provider.type")
            if _normalize_literal(provider_source) != expected_provider:
                missing_configuration.append("provider")

        if expected_provider and expected_model:
            model_target = f"provider.{expected_provider}.model.model"
            if _normalize_literal(host_inputs.get(model_target)) != expected_model:
                missing_configuration.append("model")

        for secret_target, expected_secret in expected_authentication_secrets.items():
            if not _matches_secret_reference(
                host_inputs.get(secret_target, ""), expected_secret
            ):
                missing_configuration.append(f"connector secret ({secret_target})")

        if missing_configuration:
            return Score(
                value=0.0,
                explanation=f"missing configured AI-agent {', '.join(missing_configuration)}",
                metadata={"checked_provider_targets": sorted(host_inputs)},
            )

        prompt_inputs = {
            inp.get("target"): (inp.get("source") or "")
            for inp in host.findall(".//zeebe:input", NS)
        }
        system_prompt = prompt_inputs.get("data.systemPrompt.prompt", "")
        user_prompt = prompt_inputs.get("data.userPrompt.prompt", "")
        if not system_prompt.startswith("=") or not user_prompt.startswith("="):
            return Score(
                value=0.0,
                explanation="both system/user prompts must be FEEL strings (start with '=')",
            )
        if "data.limits.maxModelCalls" not in prompt_inputs:
            return Score(
                value=0.0,
                explanation="missing data.limits.maxModelCalls input",
            )

        return Score(
            value=1.0,
            explanation=(
                f"valid AI-agent shape in {path} for {expected_process_id}; "
                f"tools={sorted(tool_ids)}"
            ),
            metadata={
                "path": path,
                "process_id": expected_process_id,
                "tool_ids": sorted(tool_ids),
                "from_ai_inputs": len(from_ai_inputs),
            },
        )

    return score


@scorer(metrics=[mean(), stderr()])
def missing_configuration_guard(path: str = BPMN_PATH) -> Scorer:
    """Require clarification before creating an agent with missing configuration."""

    async def score(state: TaskState, target: Target) -> Score:
        if state.sample_id != MISSING_CONFIGURATION_SAMPLE_ID:
            return Score(
                value=1.0,
                explanation="missing-configuration check not applicable to this sample",
            )

        workspace = path.rsplit("/", 1)[0] or "/"
        artifacts = await sandbox().exec(
            [
                "find",
                workspace,
                "-type",
                "f",
                "-name",
                "*.bpmn",
                "-not",
                "-path",
                f"{workspace}/skills/*",
            ],
            timeout=10,
        )
        if artifacts.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"could not inspect {workspace} for BPMN artifacts",
            )
        artifact_paths = [
            artifact_path
            for artifact_path in (artifacts.stdout or "").splitlines()
            if artifact_path
        ]
        if artifact_paths:
            return Score(
                value=0.0,
                explanation=(
                    "created BPMN artifact(s) despite missing configuration: "
                    f"{artifact_paths}"
                ),
            )

        assistant_text = _assistant_text(state).casefold()
        request_sentences = re.split(r"(?<=[?.!])\s+|\n+", assistant_text)
        missing_terms = []
        for term, pattern in (
            ("provider", r"\bprovider\b"),
            ("model", r"\bmodel\b"),
            ("connector-secret name", r"\b(?:connector[- ]secret|secret) names?\b"),
        ):
            if not any(
                _is_request_sentence(sentence) and bool(re.search(pattern, sentence))
                for sentence in request_sentences
            ):
                missing_terms.append(term)
        if missing_terms:
            return Score(
                value=0.0,
                explanation=(
                    "clarification did not ask for missing "
                    f"configuration: {missing_terms}"
                ),
            )
        if any(
            "secret value" in sentence
            and not re.search(
                r"\b(?:do not|don't|never|not)\b[^.?!\n]{0,40}\bsecret values?\b",
                sentence,
            )
            and _is_request_sentence(sentence)
            for sentence in request_sentences
        ):
            return Score(
                value=0.0,
                explanation="clarification requested secret values instead of secret names",
            )

        return Score(
            value=1.0,
            explanation=(
                "agent requested the missing provider, model, and connector-secret "
                "name without creating BPMN"
            ),
        )

    return score


SAVE_AND_DEPLOY = (
    "\n\nSave the BPMN to /workspace/process.bpmn. Do not stop until the file is created."
)

SAMPLES = [
    Sample(
        id="ticket-triage-subprocess",
        input=(
            "Use the local c8run test cluster with the default c8ctl profile; this "
            "artifact-only eval does not require deployment.\n"
            "Immediately create /workspace/process.bpmn first (do not do exploratory reads).\n"
            "Create a Camunda 8.8+ BPMN process (id: ai-ticket-triage, name: "
            "'AI Ticket Triage') with an AI Agent Sub-process pattern:\n"
            "1. Start event 'Ticket received'.\n"
            "2. Ad-hoc subprocess id AgentTools (name 'Agent tools') as the AI "
            "agent host.\n"
            "3. Inside AgentTools add these root tools:\n"
            "   - service task id LookupKnowledgeBase, name 'Lookup knowledge base'\n"
            "   - service task id LookupCustomerData, name 'Lookup customer data'\n"
            "   - user task id EscalateToHuman, name 'Escalate to human'\n"
            "4. Add bpmn:documentation text to each tool explaining when to use it.\n"
            "5. Use fromAi(...) for at least one tool input parameter.\n"
            "6. Ensure tool outputs are mapped to toolCallResult.\n"
            "7. Use the OpenAI provider with model 'gpt-4.1-mini' and the "
            "already-configured connector secret 'OPENAI_API_KEY'; do not "
            "invent another provider or secret name.\n"
            "8. Configure agent prompts as FEEL strings and set "
            "data.limits.maxModelCalls.\n"
            "Write the BPMN in one pass and finish as soon as /workspace/process.bpmn exists."
            + SAVE_AND_DEPLOY
        ),
        metadata={
            "process_id": "ai-ticket-triage",
            "required_tools": [
                "LookupKnowledgeBase",
                "LookupCustomerData",
                "EscalateToHuman",
            ],
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "authentication_secrets": {
                "provider.openai.authentication.apiKey": "OPENAI_API_KEY",
            },
        },
    ),
    Sample(
        id=MISSING_CONFIGURATION_SAMPLE_ID,
        input=(
            "Use the local c8run test cluster with the default c8ctl profile. "
            "I want an AI Agent Sub-process BPMN, but I have not provided the "
            "model provider, exact model identifier, or existing connector-secret "
            "name. Ask me for each missing value, including the exact secret name "
            "rather than its secret value, and stop. Do not choose defaults, "
            "invent names, apply a connector template, or create or edit any BPMN "
            "artifact anywhere under /workspace, including /workspace/process.bpmn."
        ),
    ),
]


@task
def camunda_ai_agents(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            ai_agent_shape_valid(),
            missing_configuration_guard(),
            assert_skill_loaded("camunda-ai-agents", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=420,
        token_limit=140_000,
        message_limit=45,
    )
