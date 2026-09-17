from __future__ import annotations

import asyncio
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from inspect_ai.tool import ToolDef


def _load_outcomes() -> ModuleType:
    path = Path(__file__).with_name("outcomes.py")
    spec = importlib.util.spec_from_file_location("camunda_ai_agents_outcomes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_outcomes = _load_outcomes()


def _host(
    template: str | None, task_type: str | None, tool_container: bool = True
) -> ET.Element:
    attributes = {}
    if template:
        attributes[f"{{{_outcomes.NS['zeebe']}}}modelerTemplate"] = template
    host = ET.Element(f"{{{_outcomes.NS['bpmn']}}}adHocSubProcess", attributes)
    if task_type or tool_container:
        extensions = ET.SubElement(host, f"{{{_outcomes.NS['bpmn']}}}extensionElements")
    if task_type:
        ET.SubElement(
            extensions,
            f"{{{_outcomes.NS['zeebe']}}}taskDefinition",
            {"type": task_type},
        )
    if tool_container:
        properties = ET.SubElement(extensions, f"{{{_outcomes.NS['zeebe']}}}properties")
        ET.SubElement(
            properties,
            f"{{{_outcomes.NS['zeebe']}}}property",
            {
                "name": _outcomes.AI_AGENT_TOOL_CONTAINER_PROPERTY,
                "value": "true",
            },
        )
    return host


@pytest.mark.parametrize(
    ("template", "task_type", "expected"),
    [
        (
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            "io.camunda.agenticai:aiagent-job-worker:1",
            True,
        ),
        (
            "io.camunda.connectors.agenticai.ai-agent-subprocess.v2",
            "io.camunda.agenticai:aiagent:subprocess:2",
            True,
        ),
        (
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            "io.camunda.agenticai:aiagent:subprocess:2",
            False,
        ),
        (
            "io.camunda.connectors.agenticai.ai-agent-subprocess.v2",
            "io.camunda.agenticai:aiagent-job-worker:1",
            False,
        ),
        (None, None, False),
        (
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            None,
            False,
        ),
        (
            "io.camunda.connectors.http-json.v1",
            "io.camunda.agenticai:aiagent-job-worker:1",
            False,
        ),
        (
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            "io.camunda.agenticai:other:1",
            False,
        ),
        (
            "io.camunda.connectors.agenticai.aiagent.v1",
            "io.camunda.agenticai:aiagent:subprocess:1",
            False,
        ),
        (
            "io.camunda.connectors.agenticai.ai-agent-subprocess.",
            "io.camunda.agenticai:aiagent:subprocess:",
            False,
        ),
    ],
)
def test_requires_ai_agent_template_and_task_definition(
    template: str | None, task_type: str | None, expected: bool
) -> None:
    assert _outcomes.has_ai_agent_connector(_host(template, task_type)) is expected


def test_requires_ai_agent_tool_container_property() -> None:
    host = _host(
        "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
        "io.camunda.agenticai:aiagent-job-worker:1",
        tool_container=False,
    )

    assert not _outcomes.has_ai_agent_connector(host)


def _configuration_score(
    *calls: tuple[str, dict[str, object]],
    artifacts: tuple[str, ...] = (),
    expected_fields: tuple[str, ...] = ("provider", "model", "secret_names"),
) -> float:
    state = SimpleNamespace(
        metadata={"missing_configuration": list(expected_fields)},
        messages=[
            SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(function=function, arguments=arguments)
                    for function, arguments in calls
                ]
            )
        ],
        store={"artifacts": {path: "" for path in artifacts}},
    )
    return asyncio.run(_outcomes.configuration_requested()(state, None)).value


def test_configuration_tool_requests_required_values() -> None:
    tool = ToolDef(_outcomes.request_configuration())
    message = asyncio.run(tool.tool(missing=["provider"]))

    assert tool.name == "request_configuration"
    assert "configuration fields" in tool.description
    assert tool.parameters.required == ["missing"]
    assert "Wait for the user response" in message


def test_configuration_request_stops_before_bpmn_work() -> None:
    request = (
        "request_configuration",
        {"missing": ["provider", "model", "secret_names"]},
    )

    assert _configuration_score(request) == 1.0
    assert _configuration_score(request, ("list_files", {})) == 0.0
    assert _configuration_score(request, artifacts=("/workspace/process.BPMN",)) == 0.0
    assert (
        _configuration_score(
            ("request_configuration", {"missing": ["model"]}),
            expected_fields=("model",),
        )
        == 1.0
    )
    assert (
        _configuration_score(
            ("request_configuration", {"missing": ["secret"]}),
            expected_fields=("secret_names",),
        )
        == 0.0
    )


def test_claude_code_keeps_positive_sample() -> None:
    task = _outcomes.camunda_ai_agents(agent="claude_code")

    assert [sample.id for sample in task.dataset] == ["ticket-triage-subprocess"]
