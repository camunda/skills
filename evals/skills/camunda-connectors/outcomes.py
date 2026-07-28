"""camunda-connectors outcome eval: apply and configure an OOTB connector.

Deterministic, machine-checkable scoring:
- bpmn_lint_clean: resulting BPMN must lint clean.
- rest_connector_configured: Task_FetchWeather must carry the REST connector
  template and the required input/output mappings.

Skill-load is diagnostic; the without-skill arm drops camunda-connectors only.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.bpmn_lint import bpmn_lint_clean
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-connectors"])

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
ZEEBE_NS = "http://camunda.org/schema/zeebe/1.0"
NS = {"bpmn": BPMN_NS, "zeebe": ZEEBE_NS}


def _attr(elem: ET.Element, local_name: str) -> str | None:
    return elem.attrib.get(f"{{{ZEEBE_NS}}}{local_name}")


@scorer(metrics=[mean(), stderr()])
def rest_connector_configured() -> Scorer:
    """Check that Task_FetchWeather is configured as REST connector."""

    async def score(state: TaskState, target: Target) -> Score:
        result = await sandbox().exec(["cat", "/workspace/process.bpmn"], timeout=10)
        if result.returncode != 0:
            return Score(value=0.0, explanation="missing /workspace/process.bpmn")

        try:
            root = ET.fromstring(result.stdout)
        except ET.ParseError as exc:
            return Score(value=0.0, explanation=f"invalid BPMN XML: {exc}")

        task = root.find(".//bpmn:serviceTask[@id='Task_FetchWeather']", NS)
        if task is None:
            return Score(
                value=0.0, explanation="service task Task_FetchWeather missing"
            )

        template = _attr(task, "modelerTemplate")
        if template != "io.camunda.connectors.HttpJson.v2":
            return Score(
                value=0.0,
                explanation=f"unexpected modelerTemplate: {template!r}",
            )

        task_definition = task.find(
            "./bpmn:extensionElements/zeebe:taskDefinition",
            NS,
        )
        task_type = (
            task_definition.attrib.get("type") if task_definition is not None else None
        )
        if task_type != "io.camunda:http-json:1":
            return Score(
                value=0.0, explanation=f"unexpected taskDefinition.type: {task_type!r}"
            )

        io_inputs = {
            inp.attrib.get("target"): inp.attrib.get("source")
            for inp in task.findall(
                "./bpmn:extensionElements/zeebe:ioMapping/zeebe:input",
                NS,
            )
        }
        expected_inputs = {
            "method": "GET",
            "url": '="https://api.weather.gov/points/" + string(latitude) + "," + string(longitude)',
        }
        missing_inputs = {
            key: value
            for key, value in expected_inputs.items()
            if io_inputs.get(key) != value
        }
        if missing_inputs:
            return Score(
                value=0.0,
                explanation=f"missing/incorrect inputs: {missing_inputs}",
                metadata={"found_inputs": io_inputs},
            )

        headers = {
            header.attrib.get("key"): header.attrib.get("value")
            for header in task.findall(
                "./bpmn:extensionElements/zeebe:taskHeaders/zeebe:header",
                NS,
            )
        }
        expected_headers = {
            "resultVariable": "weatherResponse",
            "resultExpression": "={forecast: response.body.properties.forecast}",
        }
        missing_headers = {
            key: value
            for key, value in expected_headers.items()
            if headers.get(key) != value
        }
        if missing_headers:
            return Score(
                value=0.0,
                explanation=f"missing/incorrect task headers: {missing_headers}",
                metadata={"found_headers": headers},
            )

        return Score(
            value=1.0,
            explanation="Task_FetchWeather configured with expected REST connector settings",
        )

    return score


SAMPLES = [
    Sample(
        id="rest-template-apply",
        input=(
            "Create a BPMN 2.0 process named 'Weather lookup' with process id "
            "`weather-lookup`. It must include exactly: a start event "
            "'Request received', a service task with id `Task_FetchWeather` and "
            "name 'Fetch weather', then an end event 'Done'.\n\n"
            "Then configure that service task with the REST outbound connector "
            "template by following this workflow:\n"
            "1) sync the OOTB template catalog\n"
            "2) search for REST templates\n"
            "3) inspect the chosen template's settable properties\n"
            "4) apply `io.camunda.connectors.HttpJson.v2` to Task_FetchWeather\n"
            "5) set these values during apply:\n"
            "   - method=GET\n"
            '   - url=\'="https://api.weather.gov/points/" + string(latitude) + '
            '"," + string(longitude)\'\n'
            "   - resultVariable=weatherResponse\n"
            "   - resultExpression='={forecast: "
            "response.body.properties.forecast}'\n\n"
            "Save the final BPMN to /workspace/process.bpmn."
        ),
    )
]


@task
def camunda_connectors(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        # submit=False: the BPMN file is the deliverable.
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            bpmn_lint_clean(),
            rest_connector_configured(),
            assert_skill_loaded("camunda-connectors", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=360,
        token_limit=120_000,
        message_limit=40,
    )
