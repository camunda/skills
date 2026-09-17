"""camunda-ai-agents outcome eval: model an AI-agent subprocess BPMN and deploy it.

Deterministic, machine-checkable verification:
- ``ai_agent_shape_valid`` parses ``/workspace/process.bpmn`` and checks for
  an AI Agent connector-backed ad-hoc subprocess host, tool documentation, ``fromAi()`` usage,
  ``toolCallResult`` wiring, and prompt/limit inputs.

Skill-load is diagnostic; the without-skill arm drops only camunda-ai-agents.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal
import xml.etree.ElementTree as ET

from core.agents import AgentKind, WORKSPACE_RULES, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from inspect_ai import Task, task
from inspect_ai.agent import Agent, AgentPrompt, react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.tool import (
    Tool,
    bash_session,
    grep,
    list_files,
    skill,
    text_editor,
    tool as inspect_tool,
    web_search,
)
from inspect_ai.util import sandbox
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-ai-agents"], max_sandboxes=1)

BPMN_PATH = "/workspace/process.bpmn"

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

AI_AGENT_CONNECTOR_FAMILIES = (
    (
        "io.camunda.connectors.agenticai.aiagent.jobworker.",
        "io.camunda.agenticai:aiagent-job-worker:",
    ),
    (
        "io.camunda.connectors.agenticai.ai-agent-subprocess.",
        "io.camunda.agenticai:aiagent:subprocess:",
    ),
)
AI_AGENT_TOOL_CONTAINER_PROPERTY = "io.camunda.agenticai.toolContainer"


@inspect_tool
def request_configuration() -> Tool:
    """Request specific configuration from the user."""

    async def execute(
        missing: list[Literal["provider", "model", "secret_names"]],
    ) -> str:
        """Request the missing configuration fields from the user.

        Args:
            missing: ``provider``, exact ``model``, or existing ``secret_names``.
                Never request secret values.
        """

        return "Configuration request sent. Wait for the user response before further work."

    return execute


def _build_evaluator_agent(agent: AgentKind, skill_dirs: Sequence[Path]) -> Agent:
    if agent != "react":
        return build_agent(agent, skill_dirs, submit=False)
    return react(
        prompt=AgentPrompt(instructions=WORKSPACE_RULES),
        submit=False,
        tools=[
            bash_session(timeout=300),
            text_editor(timeout=60),
            grep(timeout=30),
            list_files(timeout=30),
            web_search(),
            *([skill(list(skill_dirs))] if skill_dirs else []),
            request_configuration(),
        ],
    )


def has_ai_agent_connector(host: ET.Element) -> bool:
    """Check for connector metadata emitted by an AI Agent template."""

    template = host.get(f"{{{NS['zeebe']}}}modelerTemplate", "")
    task_definition = host.find("./bpmn:extensionElements/zeebe:taskDefinition", NS)
    task_type = task_definition.get("type", "") if task_definition is not None else ""
    tool_container = any(
        prop.get("name") == AI_AGENT_TOOL_CONTAINER_PROPERTY
        and prop.get("value") == "true"
        for prop in host.findall(
            "./bpmn:extensionElements/zeebe:properties/zeebe:property", NS
        )
    )
    return tool_container and any(
        template.startswith(template_prefix)
        and bool(template.removeprefix(template_prefix))
        and task_type.startswith(task_type_prefix)
        and bool(task_type.removeprefix(task_type_prefix))
        for template_prefix, task_type_prefix in AI_AGENT_CONNECTOR_FAMILIES
    )


@scorer(metrics=[mean(), stderr()])
def ai_agent_shape_valid(path: str = BPMN_PATH) -> Scorer:
    """Verify that the authored BPMN contains core AI-agent subprocess wiring."""

    async def score(state: TaskState, target: Target) -> Score:
        if not (state.metadata or {}).get("check_shape", True):
            return Score(value=1.0, explanation="shape check not applicable")

        expected_process_id = (state.metadata or {}).get("process_id")
        required_tools = set((state.metadata or {}).get("required_tools", []))

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
        if not has_ai_agent_connector(host):
            return Score(
                value=0.0,
                explanation=(
                    "ad-hoc subprocess is not configured with the AI Agent "
                    "connector template"
                ),
            )

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
def configuration_requested() -> Scorer:
    """Verify that incomplete provider configuration stops BPMN authoring."""

    async def score(state: TaskState, target: Target) -> Score:
        expected_fields = (state.metadata or {}).get("missing_configuration")
        if not expected_fields:
            return Score(value=1.0, explanation="configuration request not applicable")

        calls = [
            (str(call.function), call.arguments or {})
            for message in state.messages
            for call in getattr(message, "tool_calls", None) or []
        ]
        artifacts = state.store.get("artifacts") or {}
        bpmn_paths = [path for path in artifacts if path.lower().endswith(".bpmn")]
        requested = [
            (index, arguments)
            for index, (name, arguments) in enumerate(calls)
            if name == "request_configuration"
        ]
        if len(requested) != 1 or requested[0][0] != len(calls) - 1 or bpmn_paths:
            return Score(
                value=0.0,
                explanation="did not request configuration and stop before BPMN work",
            )
        missing = requested[0][1].get("missing")
        if (
            not isinstance(missing, list)
            or not all(isinstance(field, str) for field in missing)
            or sorted(missing) != sorted(expected_fields)
        ):
            return Score(
                value=0.0,
                explanation=(
                    f"requested {missing!r}, expected missing fields {expected_fields!r}"
                ),
            )
        return Score(value=1.0, explanation="requested configuration before BPMN work")

    return score


SAVE_AND_DEPLOY = "\n\nSave the BPMN to /workspace/process.bpmn. Do not stop until the file is created."

SAMPLES = [
    Sample(
        id="ticket-triage-subprocess",
        input=(
            "Use only the camunda-ai-agents skill; do not load other skills or "
            "references.\n"
            "Create a Camunda 8.8+ BPMN process (id: ai-ticket-triage, name: "
            "'AI Ticket Triage') with an AI Agent Sub-process pattern:\n"
            "1. Start event 'Ticket received'.\n"
            "2. Ad-hoc subprocess id AgentTools (name 'Agent tools') as the AI "
            "agent host. Before running c8ctl, write a diagrammed BPMN process "
            "with an empty AgentTools host to /workspace/process.bpmn. Then run "
            "exactly "
            "`c8ctl element-template sync`, use "
            '`c8ctl element-template search "AI Agent Sub-process" '
            "--engine-version 8.8.0` to find the non-hybrid template, inspect "
            "only `provider.type`, `provider.openai.model.model`, "
            "`provider.openai.authentication.apiKey`, `data.systemPrompt.prompt`, "
            "`data.userPrompt.prompt`, and `data.limits.maxModelCalls` with "
            "`c8ctl element-template get-properties <id> provider.type "
            "provider.openai.model.model provider.openai.authentication.apiKey "
            "data.systemPrompt.prompt data.userPrompt.prompt "
            "data.limits.maxModelCalls --engine-version 8.8.0`, then apply that "
            "template ID with `c8ctl element-template apply -i <id> AgentTools "
            "/workspace/process.bpmn --set provider.type=openai --set "
            "provider.openai.model.model=gpt-4.1-mini --set "
            "provider.openai.authentication.apiKey={{secrets.OPENAI_API_KEY}} --set "
            "'data.systemPrompt.prompt==\"You are a ticket-triage agent. Use the "
            "available tools.\"' --set "
            "'data.userPrompt.prompt==\"Triage the current ticket.\"' --set "
            "'data.limits.maxModelCalls==10'`. Use OpenAI with model "
            "`gpt-4.1-mini` and existing connector secret `OPENAI_API_KEY`; do "
            "not invent another provider or secret name, inspect unrelated "
            "template properties, or hand-write connector metadata. Do not stop "
            "until the command succeeds. Then add the tools below.\n"
            "3. Inside AgentTools add these root tools:\n"
            "   - service task id LookupKnowledgeBase, name 'Lookup knowledge base'\n"
            "   - service task id LookupCustomerData, name 'Lookup customer data'\n"
            "   - user task id EscalateToHuman, name 'Escalate to human'\n"
            "4. Add bpmn:documentation text to each tool explaining when to use it.\n"
            "5. Use fromAi(...) for at least one tool input parameter.\n"
            "6. Ensure tool outputs are mapped to toolCallResult.\n"
            "7. Configure agent prompts as FEEL strings and set "
            "data.limits.maxModelCalls.\n"
            "Save the completed BPMN to /workspace/process.bpmn." + SAVE_AND_DEPLOY
        ),
        metadata={
            "process_id": "ai-ticket-triage",
            "required_tools": [
                "LookupKnowledgeBase",
                "LookupCustomerData",
                "EscalateToHuman",
            ],
        },
    ),
    Sample(
        id="missing-provider-configuration",
        input=(
            "Use only the camunda-ai-agents skill. Create an AI Agent Sub-process "
            "BPMN, but no provider, exact model identifier, or connector-secret "
            "names were supplied."
        ),
        metadata={
            "check_shape": False,
            "missing_configuration": ["provider", "model", "secret_names"],
        },
    ),
    Sample(
        id="missing-model-configuration",
        input=(
            "Use only the camunda-ai-agents skill. Create an AI Agent Sub-process "
            "BPMN with provider `openai` and existing connector secret "
            "`OPENAI_API_KEY`, but no exact model identifier was supplied."
        ),
        metadata={
            "check_shape": False,
            "missing_configuration": ["model"],
        },
    ),
    Sample(
        id="missing-secret-configuration",
        input=(
            "Use only the camunda-ai-agents skill. Create an AI Agent Sub-process "
            "BPMN with provider `openai` and exact model identifier "
            "`gpt-4.1-mini`, but no connector-secret name was supplied."
        ),
        metadata={
            "check_shape": False,
            "missing_configuration": ["secret_names"],
        },
    ),
]


@task
def camunda_ai_agents(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    # Claude Code does not receive the test-only request_configuration tool.
    samples = SAMPLES if agent == "react" else SAMPLES[:1]
    return Task(
        dataset=samples,
        solver=with_artifact_collection(_build_evaluator_agent(agent, skill_dirs)),
        scorer=[
            ai_agent_shape_valid(),
            configuration_requested(),
            assert_skill_loaded("camunda-ai-agents", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=420,
        token_limit=140_000,
        message_limit=45,
    )
