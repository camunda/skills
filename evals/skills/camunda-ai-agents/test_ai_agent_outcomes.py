from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

import pytest


def _load_outcomes() -> ModuleType:
    path = Path(__file__).with_name("outcomes.py")
    spec = importlib.util.spec_from_file_location("camunda_ai_agents_outcomes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_outcomes = _load_outcomes()


def _host(template: str | None, task_type: str | None) -> ET.Element:
    attributes = {}
    if template:
        attributes[f"{{{_outcomes.NS['zeebe']}}}modelerTemplate"] = template
    host = ET.Element(f"{{{_outcomes.NS['bpmn']}}}adHocSubProcess", attributes)
    if task_type:
        extensions = ET.SubElement(host, f"{{{_outcomes.NS['bpmn']}}}extensionElements")
        ET.SubElement(
            extensions,
            f"{{{_outcomes.NS['zeebe']}}}taskDefinition",
            {"type": task_type},
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
    ],
)
def test_requires_ai_agent_template_and_task_definition(
    template: str | None, task_type: str | None, expected: bool
) -> None:
    assert _outcomes.has_ai_agent_connector(_host(template, task_type)) is expected
