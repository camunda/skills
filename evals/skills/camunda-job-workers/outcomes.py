"""camunda-job-workers — zero-dependency Node.js worker, end-to-end.

Unit under test: the ``references/worker-http-no-sdk.md`` sample — a worker
using only Node built-ins over the ``/v2/jobs/*`` REST API (no ``package.json``,
no ``node_modules``, no SDK). The agent writes the worker, deploys a fixed BPMN,
runs the worker against the live cluster, and starts an instance.

Three gating scorers:
  - worker_is_zero_dependency  — the worker really is built-ins-only (the capability)
  - process_deployed_on_cluster — the BPMN reached the cluster
  - cpt_scorer                  — the CPT verifier runs the process in two modes:
      integration (the real worker completes a job) and process (CPT completes it),
      so a failure localizes to the worker vs the BPMN wiring.

The BPMN is a fixed fixture (the prompt hands the agent the exact XML to save).
It is a test input, not the unit under test, so it is linted once at authoring.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.cluster import process_deployed_on_cluster
from scorers.cpt import cpt_scorer
from scorers.worker import worker_is_zero_dependency
from solvers.collect_artifacts import with_artifact_collection


METADATA = EvalMetadata(
    skills=["camunda-job-workers"],
)

# The exact BPMN the agent saves verbatim. Fixed so the eval tests the worker,
# not BPMN authoring; the CPT verifier deploys its own committed copy of this
# same shape. `process-order` is the job type the worker must poll.
FIXTURE_BPMN = """\
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
                  xmlns:zeebe="http://camunda.org/schema/zeebe/1.0"
                  xmlns:modeler="http://camunda.org/schema/modeler/1.0"
                  id="Definitions_NoSdkWorkerDemo"
                  targetNamespace="http://bpmn.io/schema/bpmn"
                  modeler:executionPlatform="Camunda Cloud"
                  modeler:executionPlatformVersion="8.8.0">
  <bpmn:process id="NoSdkWorkerDemo" name="No-SDK worker demo" isExecutable="true">
    <bpmn:startEvent id="StartEvent" name="Order received">
      <bpmn:outgoing>Flow_Start</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:serviceTask id="ProcessOrder" name="Process order">
      <bpmn:extensionElements>
        <zeebe:taskDefinition type="process-order" />
      </bpmn:extensionElements>
      <bpmn:incoming>Flow_Start</bpmn:incoming>
      <bpmn:outgoing>Flow_End</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:endEvent id="EndEvent" name="Order processed">
      <bpmn:incoming>Flow_End</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_Start" sourceRef="StartEvent" targetRef="ProcessOrder" />
    <bpmn:sequenceFlow id="Flow_End" sourceRef="ProcessOrder" targetRef="EndEvent" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="NoSdkWorkerDemo">
      <bpmndi:BPMNShape id="StartEvent_di" bpmnElement="StartEvent">
        <dc:Bounds x="172" y="102" width="36" height="36" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="158" y="145" width="66" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="ProcessOrder_di" bpmnElement="ProcessOrder">
        <dc:Bounds x="260" y="80" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="EndEvent_di" bpmnElement="EndEvent">
        <dc:Bounds x="412" y="102" width="36" height="36" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="396" y="145" width="69" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="Flow_Start_di" bpmnElement="Flow_Start">
        <di:waypoint x="208" y="120" />
        <di:waypoint x="260" y="120" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_End_di" bpmnElement="Flow_End">
        <di:waypoint x="360" y="120" />
        <di:waypoint x="412" y="120" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""

PROMPT = (
    "My Camunda 8 cluster is already running locally (don't start a new one). "
    "I need a job worker for it, but this environment has **no npm** — I can't "
    "install any packages. Write a worker in plain Node.js using only built-in "
    "modules (no `package.json`, no `node_modules`, no `@camunda8` SDK).\n\n"
    "Save this exact BPMN as `NoSdkWorkerDemo.bpmn` (process id `NoSdkWorkerDemo`, "
    "one service task with job type `process-order`):\n\n"
    "```xml\n" + FIXTURE_BPMN + "```\n\n"
    "Then:\n"
    "1. Write the zero-dependency worker that handles the `process-order` job type "
    "and completes each job.\n"
    "2. Deploy `NoSdkWorkerDemo.bpmn` to the running cluster.\n"
    "3. Start the worker in the background and leave it running — do not stop it.\n"
    "4. Start a process instance and confirm it runs to completion.\n"
)


@task
def camunda_job_workers(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=[
            Sample(id="no-sdk-worker-completes", input=PROMPT),
        ],
        solver=with_artifact_collection(build_agent(agent, skill_dirs)),
        scorer=[
            worker_is_zero_dependency(),
            process_deployed_on_cluster("NoSdkWorkerDemo"),
            cpt_scorer(project_dir="/skills/camunda-job-workers/cpt-verifier"),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-cpt-verifier.yaml")),
        metadata=METADATA.model_dump(),
        # time_limit covers the whole sample; Inspect reserves half for scoring,
        # so 720s leaves 360s for the CPT scorer's `mvn test` (two methods).
        time_limit=720,
        token_limit=700_000,
        message_limit=60,
    )
