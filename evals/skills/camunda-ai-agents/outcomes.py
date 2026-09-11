"""camunda-ai-agents outcome eval: model an AI-agent subprocess BPMN and deploy it.

Deterministic, machine-checkable verification:
- ``ai_agent_shape_valid`` parses ``/workspace/process.bpmn`` and checks for
  an ad-hoc subprocess host recognized by a matching built-in AI Agent
  template marker, task type, and output collection binding, or a documented
  custom AI Agent task type; it also checks the tool-container property, tool
  documentation, ``fromAi()`` usage, per-tool ``toolCallResult`` wiring, and
  prompt/limit inputs.

Skill-load is diagnostic; the without-skill arm drops only camunda-ai-agents.
"""

from __future__ import annotations

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

AI_AGENT_TEMPLATE_MARKER_PREFIX = (
    "io.camunda.connectors.agenticai.ai-agent-subprocess."
)
AI_AGENT_TEMPLATE_TASK_TYPE_PREFIX = "io.camunda.agenticai:aiagent:subprocess:"
AI_AGENT_LEGACY_TEMPLATE_PREFIXES = (
    "io.camunda.connectors.agenticai.aiagent.jobworker.",
)
AI_AGENT_SUBPROCESS_TASK_TYPE_PREFIXES = (
    "io.camunda.agenticai:aiagent:subprocess:",
)

AI_AGENT_OUTPUT_COLLECTION = "toolCallResults"
AI_AGENT_OUTPUT_ELEMENT_KEY = "content"
AI_AGENT_OUTPUT_ELEMENT_VALUE = "toolCallResult"
CLAIM_REVIEW_TOOL_IDS = (
    "DetectDuplicateClaims",
    "CheckAmountCategoryMismatch",
    "DetectPersonalBusinessLanguage",
)


def _without_feel_string_literals(expression: str) -> str:
    characters = []
    in_string = False
    index = 0
    while index < len(expression):
        character = expression[index]
        if character == '"':
            if in_string and index + 1 < len(expression):
                if expression[index + 1] == '"':
                    characters.extend((" ", " "))
                    index += 2
                    continue
                if expression[index + 1] == "\\":
                    characters.extend((" ", " "))
                    index += 2
                    continue
            in_string = not in_string
            characters.append(" ")
        elif in_string:
            characters.append(" ")
        else:
            characters.append(character)
        index += 1
    return "".join(characters)


def _has_from_ai_call(expression: str) -> bool:
    sanitized = _without_feel_string_literals(expression)
    identifier = "fromAi"
    for index in range(len(sanitized) - len(identifier) + 1):
        if not sanitized.startswith(identifier, index):
            continue
        before = index - 1
        while before >= 0 and sanitized[before].isspace():
            before -= 1
        if before >= 0 and (
            sanitized[before].isalnum()
            or sanitized[before] == "_"
            or sanitized[before] == "."
        ):
            continue
        after_index = index + len(identifier)
        after = sanitized[after_index] if after_index < len(sanitized) else ""
        if after and (after.isalnum() or after == "_"):
            continue
        cursor = after_index
        while cursor < len(sanitized) and sanitized[cursor].isspace():
            cursor += 1
        if cursor >= len(sanitized) or sanitized[cursor] != "(":
            continue
        cursor += 1
        while cursor < len(sanitized) and sanitized[cursor].isspace():
            cursor += 1
        named_value = "value"
        if sanitized.startswith(named_value, cursor):
            value_end = cursor + len(named_value)
            while value_end < len(sanitized) and sanitized[value_end].isspace():
                value_end += 1
            if value_end >= len(sanitized) or sanitized[value_end] != ":":
                continue
            cursor = value_end + 1
            while cursor < len(sanitized) and sanitized[cursor].isspace():
                cursor += 1
        argument = "toolCall"
        if not sanitized.startswith(argument, cursor):
            continue
        cursor += len(argument)
        if cursor < len(sanitized) and (
            sanitized[cursor].isalnum() or sanitized[cursor] == "_"
        ):
            continue
        while cursor < len(sanitized) and sanitized[cursor].isspace():
            cursor += 1
        if cursor >= len(sanitized) or sanitized[cursor] != ".":
            continue
        cursor += 1
        while cursor < len(sanitized) and sanitized[cursor].isspace():
            cursor += 1
        if cursor >= len(sanitized) or not (
            sanitized[cursor].isalpha() or sanitized[cursor] == "_"
        ):
            continue
        cursor += 1
        while cursor < len(sanitized) and (
            sanitized[cursor].isalnum() or sanitized[cursor] == "_"
        ):
            cursor += 1
        while cursor < len(sanitized) and sanitized[cursor].isspace():
            cursor += 1
        if cursor >= len(sanitized) or sanitized[cursor] not in ",)":
            continue
        if sanitized[cursor] == ")":
            return True

        cursor += 1
        brace_depth = 0
        bracket_depth = 0
        parenthesis_depth = 0
        argument_has_content = False
        while cursor < len(sanitized):
            character = sanitized[cursor]
            if character == "{":
                brace_depth += 1
                argument_has_content = True
            elif character == "}":
                if brace_depth == 0:
                    return False
                brace_depth -= 1
                argument_has_content = True
            elif character == "[":
                bracket_depth += 1
                argument_has_content = True
            elif character == "]":
                if bracket_depth == 0:
                    return False
                bracket_depth -= 1
                argument_has_content = True
            elif character == "(":
                parenthesis_depth += 1
                argument_has_content = True
            elif character == ")":
                if parenthesis_depth:
                    parenthesis_depth -= 1
                    argument_has_content = True
                elif brace_depth or bracket_depth:
                    return False
                elif not argument_has_content:
                    return False
                else:
                    return True
            elif (
                character == ","
                and not brace_depth
                and not bracket_depth
                and not parenthesis_depth
            ):
                if not argument_has_content:
                    return False
                argument_has_content = False
            elif not expression[cursor].isspace():
                argument_has_content = True
            cursor += 1
    return False


def _has_top_level_feel_map_entry(
    expression: str, key: str, expected_value: str | None = None
) -> bool:
    sanitized = _without_feel_string_literals(expression)

    def valid_entry(start: int, end: int) -> tuple[str, str] | None:
        entry = sanitized[start:end]
        raw_entry = expression[start:end]
        brace_depth = 0
        bracket_depth = 0
        parenthesis_depth = 0
        colon_index: int | None = None
        for offset, character in enumerate(entry):
            if character == "{":
                brace_depth += 1
            elif character == "}":
                if brace_depth == 0:
                    return None
                brace_depth -= 1
            elif character == "[":
                bracket_depth += 1
            elif character == "]":
                if bracket_depth == 0:
                    return None
                bracket_depth -= 1
            elif character == "(":
                parenthesis_depth += 1
            elif character == ")":
                if parenthesis_depth == 0:
                    return None
                parenthesis_depth -= 1
            elif character == ":" and not (
                brace_depth or bracket_depth or parenthesis_depth
            ):
                if colon_index is not None:
                    return None
                colon_index = offset
        if (
            brace_depth
            or bracket_depth
            or parenthesis_depth
            or colon_index is None
        ):
            return None
        raw_key = raw_entry[:colon_index].strip()
        raw_value = raw_entry[colon_index + 1 :].strip()
        if not raw_key or not raw_value:
            return None
        return raw_key, raw_value

    index = 0
    while index < len(sanitized) and sanitized[index].isspace():
        index += 1
    if index >= len(sanitized) or sanitized[index] != "=":
        return False

    index += 1
    while index < len(sanitized) and sanitized[index].isspace():
        index += 1
    if index >= len(sanitized) or sanitized[index] != "{":
        return False

    entry_start = index + 1
    brace_depth = 1
    bracket_depth = 0
    parenthesis_depth = 0
    entries: list[tuple[str, str]] = []
    index += 1
    while index < len(sanitized):
        character = sanitized[index]
        if character == "{":
            brace_depth += 1
        elif character == "}":
            if brace_depth == 1:
                if bracket_depth or parenthesis_depth:
                    return False
                entry = valid_entry(entry_start, index)
                if entry is None:
                    return False
                entries.append(entry)
                index += 1
                while index < len(sanitized) and sanitized[index].isspace():
                    index += 1
                if index != len(sanitized):
                    return False
                return any(
                    entry_key.strip() == key
                    and (
                        expected_value is None
                        or entry_value.strip() == expected_value
                    )
                    for entry_key, entry_value in entries
                )
            brace_depth -= 1
        elif character == "[":
            bracket_depth += 1
        elif character == "]":
            if bracket_depth == 0:
                return False
            bracket_depth -= 1
        elif character == "(":
            parenthesis_depth += 1
        elif character == ")":
            if parenthesis_depth == 0:
                return False
            parenthesis_depth -= 1
        elif (
            character == ","
            and brace_depth == 1
            and bracket_depth == 0
            and parenthesis_depth == 0
        ):
            entry = valid_entry(entry_start, index)
            if entry is None:
                return False
            entries.append(entry)
            entry_start = index + 1
        index += 1
    return False


def has_tool_container_property(host: ET.Element) -> bool:
    properties = host.findall(
        "./bpmn:extensionElements/zeebe:properties/zeebe:property", NS
    )
    return any(
        prop.get("name") == "io.camunda.agenticai.toolContainer"
        and prop.get("value") == "true"
        for prop in properties
    )


def has_ai_agent_output_binding(host: ET.Element) -> bool:
    ad_hoc = host.find("./bpmn:extensionElements/zeebe:adHoc", NS)
    if ad_hoc is None:
        return False
    output_collection = (ad_hoc.get("outputCollection") or "").strip()
    output_element = (ad_hoc.get("outputElement") or "").strip()
    return bool(
        output_collection == AI_AGENT_OUTPUT_COLLECTION
        and output_element
        and _has_top_level_feel_map_entry(
            output_element,
            AI_AGENT_OUTPUT_ELEMENT_KEY,
            AI_AGENT_OUTPUT_ELEMENT_VALUE,
        )
    )


def has_ai_agent_connector(host: ET.Element) -> bool:
    """Accept matching built-in templates and documented custom task types."""

    template = host.get(f"{{{NS['zeebe']}}}modelerTemplate")
    task_definition = host.find(
        "./bpmn:extensionElements/zeebe:taskDefinition", NS
    )
    task_type = (
        task_definition.get("type") if task_definition is not None else ""
    ) or ""

    if template:
        if template.startswith(AI_AGENT_TEMPLATE_MARKER_PREFIX):
            if not task_type.startswith(AI_AGENT_TEMPLATE_TASK_TYPE_PREFIX):
                return False
            template_version = template.removeprefix(
                AI_AGENT_TEMPLATE_MARKER_PREFIX
            )
            task_type_version = task_type.removeprefix(
                AI_AGENT_TEMPLATE_TASK_TYPE_PREFIX
            )
            return (
                has_tool_container_property(host)
                and has_ai_agent_output_binding(host)
                and template_version.startswith("v")
                and template_version[1:].isdigit()
                and task_type_version == template_version[1:]
            )
        if any(
            template.startswith(prefix)
            for prefix in AI_AGENT_LEGACY_TEMPLATE_PREFIXES
        ):
            return False

    return any(
        task_type.startswith(prefix)
        for prefix in AI_AGENT_SUBPROCESS_TASK_TYPE_PREFIXES
    )


def has_tool_call_result(tool: ET.Element) -> bool:
    for node in tool.iter():
        if node.tag == f"{{{NS['zeebe']}}}output":
            target = node.get("target") or ""
            source = (node.get("source") or "").strip()
            if target == "toolCallResult" and source:
                return True
        if (
            node.tag == f"{{{NS['zeebe']}}}script"
            and node.get("resultVariable") == "toolCallResult"
        ):
            return True
        if node.tag == f"{{{NS['zeebe']}}}header":
            key = node.get("key")
            value = (node.get("value") or "").strip()
            if key == "resultVariable" and value == "toolCallResult":
                return True
            if key == "resultExpression" and _has_top_level_feel_map_entry(
                value, "toolCallResult"
            ):
                return True
    return False


def _validate_ai_agent_host(
    host: ET.Element,
    required_tools: set[str],
    path: str,
    expected_process_id: str | None,
) -> Score:
    tools = [child for child in list(host) if child.tag in ACTIVITY_TAGS]
    if not tools:
        return Score(
            value=0.0,
            explanation="ad-hoc subprocess has no tool activities",
        )

    tool_ids = {tool.get("id") for tool in tools if tool.get("id")}
    incoming_flow_targets = {
        flow.get("targetRef") for flow in host.findall(".//bpmn:sequenceFlow", NS)
    }
    chained_tools = sorted(
        tool_id for tool_id in tool_ids if tool_id in incoming_flow_targets
    )
    if chained_tools:
        return Score(
            value=0.0,
            explanation=(
                "root tool(s) are targeted by internal sequence flows: "
                f"{chained_tools}"
            ),
        )

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
        for tool in tools
        for inp in tool.findall(
            "./bpmn:extensionElements/zeebe:ioMapping/zeebe:input", NS
        )
        if _has_from_ai_call(inp.get("source") or "")
    ]
    if not from_ai_inputs:
        return Score(
            value=0.0,
            explanation="no zeebe:input source uses fromAi(...)",
        )

    missing_tool_results = [
        tool.get("id") or "<unknown>"
        for tool in tools
        if not has_tool_call_result(tool)
    ]
    if missing_tool_results:
        return Score(
            value=0.0,
            explanation=(
                "tool(s) missing toolCallResult mapping: "
                f"{missing_tool_results}"
            ),
        )

    host_io_mapping = host.find(
        "./bpmn:extensionElements/zeebe:ioMapping", NS
    )
    prompt_inputs = (
        {
            inp.get("target"): (inp.get("source") or "")
            for inp in host_io_mapping.findall("./zeebe:input", NS)
        }
        if host_io_mapping is not None
        else {}
    )
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


@scorer(metrics=[mean(), stderr()])
def ai_agent_shape_valid(path: str = BPMN_PATH) -> Scorer:
    """Verify that the authored BPMN contains core AI-agent subprocess wiring."""

    async def score(state: TaskState, target: Target) -> Score:
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

        candidate_hosts = [
            candidate for candidate in hosts if has_ai_agent_connector(candidate)
        ]
        if not candidate_hosts:
            return Score(
                value=0.0,
                explanation=(
                    "no ad-hoc subprocess has a matching AI Agent connector "
                    "marker, task type, output binding, or tool-container property"
                ),
            )

        candidate_scores = [
            _validate_ai_agent_host(
                candidate, required_tools, path, expected_process_id
            )
            for candidate in candidate_hosts
        ]
        return next(
            (
                candidate_score
                for candidate_score in candidate_scores
                if candidate_score.value == 1.0
            ),
            candidate_scores[0],
        )

    return score

SAVE_AND_DEPLOY = (
    "\n\nSave the BPMN to /workspace/process.bpmn. Do not stop until the file is created."
)

SAMPLES = [
    Sample(
        id="ticket-triage-subprocess",
        input=(
            "Immediately create /workspace/process.bpmn first (do not do exploratory reads).\n"
            "Create a Camunda 8.8+ BPMN process (id: ai-ticket-triage, name: "
            "'AI Ticket Triage') with an AI Agent Sub-process pattern:\n"
            "1. Start event 'Ticket received'.\n"
            "2. Ad-hoc subprocess id AgentTools (name 'Agent tools') as the AI "
            "agent host. Apply the actual AI Agent Sub-process connector element "
            "template to AgentTools with c8ctl; do not model a generic or "
            "unconfigured ad-hoc subprocess stand-in. The saved host must retain "
            "the current template marker together with its AI Agent task definition, "
            "or use the documented custom AI Agent task-type prefix.\n"
            "3. Inside AgentTools add these root tools:\n"
            "   - service task id LookupKnowledgeBase, name 'Lookup knowledge base'\n"
            "   - service task id LookupCustomerData, name 'Lookup customer data'\n"
            "   - user task id EscalateToHuman, name 'Escalate to human'\n"
            "4. Add bpmn:documentation text to each tool explaining when to use it.\n"
            "5. Use fromAi(...) for at least one tool input parameter.\n"
            "6. Ensure tool outputs are mapped to toolCallResult.\n"
            "7. Configure agent prompts as FEEL strings and set "
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
        },
    ),
    Sample(
        id="claim-review-subprocess",
        input=(
            "Immediately create /workspace/process.bpmn first (do not do exploratory reads).\n"
            "Create a Camunda 8.8+ BPMN process (id: claim-review, name: "
            "'Claim Review') with an AI Agent Sub-process pattern:\n"
            "1. Start event 'Claim received'.\n"
            "2. Ad-hoc subprocess id ClaimReviewAgent (name 'Claim review agent') "
            "as the AI agent host. Apply the actual AI Agent Sub-process connector "
            "element template to ClaimReviewAgent with c8ctl; do not model a "
            "generic or unconfigured ad-hoc subprocess stand-in. The saved host "
            "must retain the current template marker together with its AI Agent "
            "task definition, or use the documented custom AI Agent task-type prefix.\n"
            "3. Inside ClaimReviewAgent add these independent root tools (do not "
            "replace them with one generic tool):\n"
            "   - service task id DetectDuplicateClaims, name 'Detect duplicate claims'\n"
            "   - service task id CheckAmountCategoryMismatch, name 'Check amount and category mismatch'\n"
            "   - service task id DetectPersonalBusinessLanguage, name "
            "'Detect personal versus business language'\n"
            "4. Add bpmn:documentation text to each tool explaining when to use it.\n"
            "5. Use fromAi(...) for at least one tool input parameter.\n"
            "6. Ensure every tool output is mapped to toolCallResult.\n"
            "7. Configure agent prompts as FEEL strings and set "
            "data.limits.maxModelCalls.\n"
            "Write the BPMN in one pass and finish as soon as /workspace/process.bpmn exists."
            + SAVE_AND_DEPLOY
        ),
        metadata={
            "process_id": "claim-review",
            "required_tools": list(CLAIM_REVIEW_TOOL_IDS),
        },
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
            assert_skill_loaded("camunda-ai-agents", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=420,
        token_limit=140_000,
        message_limit=45,
    )
