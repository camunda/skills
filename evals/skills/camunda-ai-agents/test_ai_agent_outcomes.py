from __future__ import annotations

import asyncio
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_outcomes() -> ModuleType:
    path = Path(__file__).with_name("outcomes.py")
    spec = importlib.util.spec_from_file_location(
        "camunda_ai_agents_outcomes", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_outcomes = _load_outcomes()


def _host(
    *,
    template: str | None = None,
    task_type: str | None = None,
    tool_container: bool = False,
    output_binding: bool | None = None,
    output_collection: str = "toolCallResults",
    output_element: str = "={content: toolCallResult}",
) -> ET.Element:
    attrs = {}
    if template is not None:
        attrs[f"{{{_outcomes.NS['zeebe']}}}modelerTemplate"] = template
    host = ET.Element(f"{{{_outcomes.NS['bpmn']}}}adHocSubProcess", attrs)

    extension_elements = ET.SubElement(
        host, f"{{{_outcomes.NS['bpmn']}}}extensionElements"
    )
    if output_binding is None:
        output_binding = template is not None
    if output_binding:
        ET.SubElement(
            extension_elements,
            f"{{{_outcomes.NS['zeebe']}}}adHoc",
            {
                "outputCollection": output_collection,
                "outputElement": output_element,
            },
        )
    if task_type is not None:
        ET.SubElement(
            extension_elements,
            f"{{{_outcomes.NS['zeebe']}}}taskDefinition",
            {"type": task_type},
        )
    if tool_container:
        properties = ET.SubElement(
            extension_elements, f"{{{_outcomes.NS['zeebe']}}}properties"
        )
        ET.SubElement(
            properties,
            f"{{{_outcomes.NS['zeebe']}}}property",
            {"name": "io.camunda.agenticai.toolContainer", "value": "true"},
        )
    return host


@pytest.mark.parametrize(
    ("template", "task_type", "tool_container", "expected"),
    [
        (
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            "io.camunda.agenticai:aiagent-job-worker:1",
            True,
            False,
        ),
        (
            "io.camunda.connectors.agenticai.ai-agent-subprocess.v2",
            "io.camunda.agenticai:aiagent:subprocess:2",
            True,
            True,
        ),
        (
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            "io.camunda.agenticai:aiagent:subprocess:2",
            True,
            False,
        ),
        (
            "io.camunda.connectors.agenticai.ai-agent-subprocess.v2",
            "io.camunda.agenticai:aiagent-job-worker:1",
            True,
            False,
        ),
        (
            "io.camunda.connectors.agenticai.ai-agent-subprocess.v2",
            "io.camunda.agenticai:aiagent:subprocess:2",
            False,
            False,
        ),
        (
            "com.example.custom.ai-agent.v1",
            "io.camunda.agenticai:aiagent:subprocess:custom",
            False,
            True,
        ),
        (
            None,
            "io.camunda.agenticai:aiagent-job-worker:custom",
            False,
            False,
        ),
        (
            None,
            "io.camunda.agenticai:aiagent:subprocess:custom",
            False,
            True,
        ),
        (None, "io.camunda.agenticai:aiagent:1", False, False),
        (None, "io.camunda.other:worker:1", False, False),
        (
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            None,
            True,
            False,
        ),
        (
            "io.camunda.connectors.agenticai.ai-agent-subprocess.v3",
            "io.camunda.agenticai:aiagent:subprocess:3",
            True,
            False,
        ),
    ],
    ids=[
        "legacy-built-in-rejected",
        "current-built-in",
        "legacy-marker-current-type",
        "current-marker-legacy-type",
        "missing-tool-container-property",
        "custom-marker-with-subprocess-type",
        "legacy-task-family-rejected",
        "custom-subprocess",
        "legacy-agent-task-rejected",
        "unrelated-custom-type",
        "marker-without-task-type",
        "unknown-built-in-template-contract",
    ],
)
def test_ai_agent_connector_matching(
    template: str | None,
    task_type: str | None,
    tool_container: bool,
    expected: bool,
) -> None:
    host = _host(
        template=template,
        task_type=task_type,
        tool_container=tool_container,
    )

    assert _outcomes.has_ai_agent_connector(host) is expected


def _tool(
    tool_id: str,
    *,
    result_target: str | None = None,
    result_header: tuple[str, str] | None = None,
) -> ET.Element:
    tool = ET.Element(f"{{{_outcomes.NS['bpmn']}}}serviceTask", {"id": tool_id})
    if result_target is not None or result_header is not None:
        extension_elements = ET.SubElement(
            tool, f"{{{_outcomes.NS['bpmn']}}}extensionElements"
        )
        if result_target is not None:
            ET.SubElement(
                extension_elements,
                f"{{{_outcomes.NS['zeebe']}}}output",
                {"target": result_target},
            )
        if result_header is not None:
            key, value = result_header
            ET.SubElement(
                extension_elements,
                f"{{{_outcomes.NS['zeebe']}}}header",
                {"key": key, "value": value},
            )
    return tool


def test_tool_call_result_is_scoped_to_each_tool() -> None:
    result_tool = _tool("ResultTool", result_target="toolCallResult.status")
    missing_tool = _tool("MissingTool")

    assert _outcomes.has_tool_call_result(result_tool)
    assert not _outcomes.has_tool_call_result(missing_tool)


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("resultVariable", "toolCallResult", True),
        ("resultVariable", "not_toolCallResult", False),
        ("resultExpression", "={toolCallResult: response.body}", True),
        ("resultExpression", "={not_toolCallResult: response.body}", False),
        ("resultExpression", '="toolCallResult"', False),
        (
            "resultExpression",
            '="not a map, toolCallResult: text"',
            False,
        ),
        (
            "resultExpression",
            '={message: "toolCallResult: text", toolCallResult: response.body}',
            True,
        ),
        (
            "resultExpression",
            "={details: {status: 1, toolCallResult: response.body}}",
            False,
        ),
        ("resultExpression", "={toolCallResult:}", False),
    ],
    ids=[
        "exact-result-variable",
        "result-variable-name-is-not-a-substring",
        "result-expression-map-entry",
        "result-expression-key-is-not-a-substring",
        "result-expression-is-not-a-map",
        "quoted-map-like-text-is-not-a-map",
        "quoted-text-does-not-hide-real-map-entry",
        "nested-map-entry-is-not-root-mapping",
        "empty-map-entry-value",
    ],
)
def test_tool_call_result_headers_require_an_exact_mapping(
    key: str, value: str, expected: bool
) -> None:
    tool = _tool("HeaderTool", result_header=(key, value))

    assert _outcomes.has_tool_call_result(tool) is expected


def _minimal_bpmn(
    *,
    connector: bool,
    template_output_binding: bool = True,
    include_unmapped_tool: bool = False,
    template_output_collection: str = "toolCallResults",
    template_output_element: str = "={content: toolCallResult}",
    tool_ids: tuple[str, ...] = ("LookupKnowledgeBase",),
    chain_tools: bool = False,
    prepend_unrelated_host: bool = False,
    prepend_connector_host: bool = False,
    from_ai_source: str | None = "=fromAi(toolCall.query)",
    host_from_ai_source: str | None = None,
) -> str:
    if connector:
        host_attributes = (
            'zeebe:modelerTemplate="'
            "io.camunda.connectors.agenticai.ai-agent-subprocess.v2\""
        )
        connector_extension = """
      <zeebe:taskDefinition type="io.camunda.agenticai:aiagent:subprocess:2" />
      <zeebe:properties>
        <zeebe:property name="io.camunda.agenticai.toolContainer" value="true" />
      </zeebe:properties>
"""
    else:
        host_attributes = ""
        connector_extension = ""

    if connector and template_output_binding:
        output_binding = (
            f'      <zeebe:adHoc outputCollection="{template_output_collection}" '
            f'outputElement="{template_output_element}" />\n'
        )
    else:
        output_binding = ""
    tool_input_mapping = (
        f"""          <zeebe:ioMapping>
            <zeebe:input source="{from_ai_source}" target="query" />
          </zeebe:ioMapping>
"""
        if from_ai_source is not None
        else ""
    )
    tool_xml = "\n".join(
        f"""      <bpmn:serviceTask id="{tool_id}">
        <bpmn:documentation>Look up relevant knowledge.</bpmn:documentation>
        <bpmn:extensionElements>
{tool_input_mapping if index == 0 else ""}\
          <zeebe:output target="toolCallResult" />
        </bpmn:extensionElements>
      </bpmn:serviceTask>"""
        for index, tool_id in enumerate(tool_ids)
    )
    sequence_flows = ""
    if chain_tools:
        sequence_flows = "\n".join(
            f'      <bpmn:sequenceFlow id="flow-{source}-{target}" '
            f'sourceRef="{source}" targetRef="{target}" />'
            for source, target in zip(tool_ids, tool_ids[1:])
        )
    unrelated_host = ""
    if prepend_unrelated_host:
        unrelated_host = """\
    <bpmn:adHocSubProcess id="UnrelatedTools">
      <bpmn:serviceTask id="UnrelatedTool">
        <bpmn:documentation>This is not the AI Agent host.</bpmn:documentation>
      </bpmn:serviceTask>
    </bpmn:adHocSubProcess>
"""
    connector_host = ""
    if prepend_connector_host and connector:
        connector_host = f"""\
    <bpmn:adHocSubProcess id="FirstAgent" {host_attributes}>
      <bpmn:extensionElements>
{output_binding}{connector_extension}      </bpmn:extensionElements>
    </bpmn:adHocSubProcess>
"""
    unmapped_tool = (
        """
      <bpmn:serviceTask id="UnmappedTool">
        <bpmn:documentation>This tool intentionally has no result mapping.</bpmn:documentation>
      </bpmn:serviceTask>
"""
        if include_unmapped_tool
        else ""
    )
    host_from_ai_input = (
        f'            <zeebe:input source="{host_from_ai_source}" target="hostQuery" />\n'
        if host_from_ai_source is not None
        else ""
    )

    return f"""\
<bpmn:definitions
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:zeebe="http://camunda.org/schema/zeebe/1.0">
  <bpmn:process id="ai-ticket-triage">
  {unrelated_host}{connector_host}\
      <bpmn:adHocSubProcess id="AgentTools" {host_attributes}>
        <bpmn:extensionElements>
  {output_binding}{connector_extension}
          <zeebe:ioMapping>
{host_from_ai_input}\
            <zeebe:input source="=&quot;system&quot;" target="data.systemPrompt.prompt" />
            <zeebe:input source="=&quot;user&quot;" target="data.userPrompt.prompt" />
            <zeebe:input source="=10" target="data.limits.maxModelCalls" />
          </zeebe:ioMapping>
        </bpmn:extensionElements>
  {tool_xml}
  {unmapped_tool}{sequence_flows}
      </bpmn:adHocSubProcess>
    </bpmn:process>
  </bpmn:definitions>
  """


def _score_artifact(
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
    required_tools: list[str] | None = None,
):
    class ExecResult:
        returncode = 0
        stdout = artifact

    class Sandbox:
        async def exec(self, command: list[str], timeout: int) -> ExecResult:
            assert command[0:1] == ["cat"]
            assert timeout == 10
            return ExecResult()

    monkeypatch.setattr(_outcomes, "sandbox", lambda: Sandbox())
    scorer = _outcomes.ai_agent_shape_valid("/workspace/process.bpmn")
    state = SimpleNamespace(
        metadata={
            "process_id": "ai-ticket-triage",
            "required_tools": required_tools or ["LookupKnowledgeBase"],
        }
    )
    return asyncio.run(scorer(state, None))


def test_ai_agent_shape_scorer_requires_connector_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_score = _score_artifact(monkeypatch, _minimal_bpmn(connector=True))
    invalid_score = _score_artifact(monkeypatch, _minimal_bpmn(connector=False))
    copied_metadata_score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(connector=True, template_output_binding=False),
    )

    assert valid_score.value == 1.0
    assert invalid_score.value == 0.0
    assert copied_metadata_score.value == 0.0


def test_ai_agent_shape_scorer_selects_matching_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(connector=True, prepend_unrelated_host=True),
    )

    assert score.value == 1.0


def test_ai_agent_shape_scorer_checks_all_connector_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(connector=True, prepend_connector_host=True),
    )

    assert score.value == 1.0


@pytest.mark.parametrize(
    ("output_collection", "output_element"),
    [
        ("notToolCallResults", "={content: toolCallResult}"),
        ("toolCallResults", "=if false then toolCallResult else null"),
        ("toolCallResults", "={content: notToolCallResult}"),
        ("toolCallResults", "={content: toolCallResult"),
        ("toolCallResults", "={content: toolCallResult} trailing"),
        ("toolCallResults", "={content: toolCallResult, broken:}"),
    ],
    ids=[
        "wrong-output-collection",
        "non-map-output-element",
        "wrong-content-source",
        "truncated-map",
        "trailing-expression",
        "invalid-sibling-map-entry",
    ],
)
def test_ai_agent_shape_scorer_rejects_malformed_template_binding(
    monkeypatch: pytest.MonkeyPatch,
    output_collection: str,
    output_element: str,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(
            connector=True,
            template_output_collection=output_collection,
            template_output_element=output_element,
        ),
    )

    assert score.value == 0.0


def test_ai_agent_shape_scorer_ignores_quoted_from_ai_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(
            connector=True,
            from_ai_source="=&quot;The literal text fromAi(&quot;",
        ),
    )

    assert score.value == 0.0


@pytest.mark.parametrize(
    "from_ai_source",
    [
        "=fromAi(toolCall.query)",
        "=fromAi(value: toolCall.query, description: &quot;Search term&quot;)",
    ],
)
def test_ai_agent_shape_scorer_accepts_named_from_ai_value(
    monkeypatch: pytest.MonkeyPatch,
    from_ai_source: str,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(connector=True, from_ai_source=from_ai_source),
    )

    assert score.value == 1.0


@pytest.mark.parametrize(
    "from_ai_source",
    [
        "=fromAi",
        "=some.fromAi",
        "=fromAiValue(toolCall.query)",
        "=fromAi(&quot;literal&quot;)",
        "=some.fromAi(toolCall.query)",
        "=fromAi(process.query)",
        "=fromAi(value: process.query)",
        "=fromAi(toolCall.query.extra)",
        "=fromAi(toolCall.query",
    ],
)
def test_ai_agent_shape_scorer_requires_from_ai_call(
    monkeypatch: pytest.MonkeyPatch,
    from_ai_source: str,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(connector=True, from_ai_source=from_ai_source),
    )

    assert score.value == 0.0


def test_ai_agent_shape_scorer_requires_from_ai_on_tool_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(
            connector=True,
            from_ai_source=None,
            host_from_ai_source="=fromAi(toolCall.query)",
        ),
    )

    assert score.value == 0.0


def test_ai_agent_shape_scorer_requires_each_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(connector=True, include_unmapped_tool=True),
    )

    assert score.value == 0.0


def test_ai_agent_shape_scorer_rejects_chained_claim_review_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score_artifact(
        monkeypatch,
        _minimal_bpmn(
            connector=True,
            tool_ids=_outcomes.CLAIM_REVIEW_TOOL_IDS,
            chain_tools=True,
        ),
        required_tools=list(_outcomes.CLAIM_REVIEW_TOOL_IDS),
    )

    assert score.value == 0.0


def test_ai_agent_shape_scorer_rejects_single_claim_review_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _minimal_bpmn(connector=True).replace(
        "LookupKnowledgeBase", "DetectDuplicateClaims"
    )
    score = _score_artifact(
        monkeypatch,
        artifact,
        required_tools=list(_outcomes.CLAIM_REVIEW_TOOL_IDS),
    )

    assert score.value == 0.0
