from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

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
) -> ET.Element:
    attrs = {}
    if template is not None:
        attrs[f"{{{_outcomes.NS['zeebe']}}}modelerTemplate"] = template
    host = ET.Element(f"{{{_outcomes.NS['bpmn']}}}adHocSubProcess", attrs)

    extension_elements = ET.SubElement(
        host, f"{{{_outcomes.NS['bpmn']}}}extensionElements"
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
            True,
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
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            "io.camunda.agenticai:aiagent-job-worker:1",
            False,
            False,
        ),
        (
            None,
            "io.camunda.agenticai:aiagent-job-worker:custom",
            False,
            True,
        ),
        (None, "io.camunda.agenticai:aiagent:1", False, True),
        (None, "io.camunda.other:worker:1", False, False),
        (
            "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
            None,
            True,
            False,
        ),
    ],
    ids=[
        "legacy-built-in",
        "current-built-in",
        "legacy-marker-current-type",
        "current-marker-legacy-type",
        "missing-tool-container-property",
        "custom-job-worker",
        "custom-agent-family",
        "unrelated-custom-type",
        "marker-without-task-type",
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


def _tool(tool_id: str, *, result_target: str | None = None) -> ET.Element:
    tool = ET.Element(f"{{{_outcomes.NS['bpmn']}}}serviceTask", {"id": tool_id})
    if result_target is not None:
        extension_elements = ET.SubElement(
            tool, f"{{{_outcomes.NS['bpmn']}}}extensionElements"
        )
        ET.SubElement(
            extension_elements,
            f"{{{_outcomes.NS['zeebe']}}}output",
            {"target": result_target},
        )
    return tool


def test_tool_call_result_is_scoped_to_each_tool() -> None:
    result_tool = _tool("ResultTool", result_target="toolCallResult.status")
    missing_tool = _tool("MissingTool")

    assert _outcomes.has_tool_call_result(result_tool)
    assert not _outcomes.has_tool_call_result(missing_tool)
