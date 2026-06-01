"""camunda-development result eval: does it route to the right integration path?

Each sample is an open-ended Camunda 8 integration question; the agent
recommends an approach (no implementation). `model_graded_qa` judges the
final text against the per-sample rubric in `Sample.target` (strict pass/fail).
Skill-load is diagnostic. The without-skill arm drops every skill, so the
with/without delta shows whether the skill suite improves routing.

Runs in a Docker sandbox (compose-advisory, no cluster). Judge model defaults
to Inspect's grader; override with `--model-role grader=<id>`.
"""

from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import model_graded_qa

from core.agents import AgentKind, build_agent
from core.metadata import BaselineConfig, ScenarioMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = ScenarioMetadata(
    skills=[
        "camunda-development",
        "camunda-connectors",
        "camunda-connectors-development",
        "camunda-job-workers",
        "camunda-ai-agents",
    ],
    baseline=BaselineConfig(exclude="all"),
)

# Strict pass/fail (no partial credit) — routing has one right answer.
_GRADER = """\
Background — do not penalize the submission for mentioning any of these,
they are all real: c8ctl (the official Camunda 8 CLI), Camunda 8 element /
connector templates, Zeebe streaming gRPC job workers (Java / Spring / TS),
and the AI Agent connector on an ad-hoc subprocess.

The criterion contains the canonical correct recommendation plus anti-patterns
the submission must NOT adopt as its primary recommendation. Mentioning an
anti-pattern as a "you could also..." aside is fine; recommending it as the
main approach fails.

Reason step by step about whether the submission matches the canonical
recommendation and avoids every anti-pattern as its primary recommendation,
then end with exactly one line:

GRADE: C  -- or --  GRADE: I
"""

_ADVISORY = (
    "\n\nI'm scoping this — just answer in writing with your recommended "
    "approach. No code, no commands, no BPMN files; I'll implement it myself "
    "once I know the right path."
)

_RAW = [
    Sample(
        id="slack-notification",
        input=(
            "I want to send a Slack notification to my team's channel when a "
            "process hits an error path. We've already got Slack set up — "
            "what's the simplest way to wire this up?"
        ),
        target=(
            "Canonical answer: use the OOTB Slack connector via its element "
            "template — drop it on a service task or error end event, point it "
            "at the existing Slack workspace, no custom code.\n\n"
            "Anti-patterns:\n"
            "- Build a custom Java connector from scratch.\n"
            "- Write a custom job worker that calls the Slack API.\n"
            "- Use a generic REST connector when an OOTB Slack template exists."
        ),
        metadata={"expected_skill": "camunda-connectors"},
    ),
    Sample(
        id="public-rest-api",
        input=(
            "I need to call the public weather API (api.weather.gov, returns "
            "JSON) from a BPMN service task. Standard HTTPS, no auth, just an "
            "HTTP GET."
        ),
        target=(
            "Canonical answer: use the OOTB REST connector via its element "
            "template — configure GET, the URL, and a result expression. No "
            "custom code needed.\n\n"
            "Anti-patterns:\n"
            "- Build a custom Java connector.\n"
            "- Write a custom job worker just to make an HTTP call."
        ),
        metadata={"expected_skill": "camunda-connectors"},
    ),
    Sample(
        id="reusable-internal-api",
        input=(
            "We have an internal customer-data API that 8+ BPMN processes "
            "across multiple teams need to call. It uses a JWT signed by our "
            "internal HSM with a custom claims set, and we want the same retry "
            "policy everywhere. Want this reusable so every team doesn't "
            "reinvent it."
        ),
        target=(
            "Canonical answer: build a custom outbound connector via the "
            "Connectors SDK (or a JSON-only template on the HTTP protocol "
            "connector if the custom logic is light enough). Ship it as a "
            "reusable element template that every team consumes by name.\n\n"
            "Anti-patterns:\n"
            "- One job worker per team / per process — defeats reusability.\n"
            "- OOTB REST connector — the HSM-signed JWT and shared retry "
            "policy need bespoke code.\n"
            "- Inline scripting in each BPMN that touches the API."
        ),
        metadata={"expected_skill": "camunda-connectors-development"},
    ),
    Sample(
        id="custom-inbound-webhook",
        input=(
            "Our payments vendor pushes settlement events to a webhook URL we "
            "expose. We want each event to start a new BPMN instance carrying "
            "the event payload. The webhook signature uses a custom HMAC "
            "scheme we have to verify per request."
        ),
        target=(
            "Canonical answer: build a custom inbound connector via the "
            "Connectors SDK — the inbound runtime handles the webhook "
            "lifecycle and the connector code verifies the custom HMAC "
            "signature before correlating the start event.\n\n"
            "Anti-patterns:\n"
            "- Poll the vendor from a job worker — they push, polling is the "
            "wrong direction.\n"
            "- Generic webhook connector — the custom HMAC needs code.\n"
            "- Stand up a separate service that calls the Camunda REST API to "
            "start instances."
        ),
        metadata={"expected_skill": "camunda-connectors-development"},
    ),
    Sample(
        id="spring-embedded-throughput",
        input=(
            "We have a high-throughput credit-decisioning step. About 500 BPMN "
            "instances/sec hit it, p99 latency must stay under 50ms. The "
            "decisioning logic lives in our existing Spring Boot service — it "
            "holds warm DB pools, an in-memory feature store, and an ML model "
            "loaded at boot. We need that BPMN step to stream jobs directly "
            "into our service, with concurrency we control on our side."
        ),
        target=(
            "Canonical answer: embed a Zeebe streaming job worker (gRPC) in "
            "the existing Spring Boot service via the Camunda Spring Boot "
            "starter. Configure max-jobs-active and concurrency on the worker; "
            "jobs activate directly into the running process so the warm pools "
            "/ feature store / model stay shared, and the connector-runtime "
            "latency hop is gone.\n\n"
            "Anti-patterns:\n"
            "- OOTB or custom HTTP connector — the connector-runtime hop burns "
            "the latency budget and can't share the warm caches.\n"
            "- Stand up a separate microservice that consumes jobs and calls "
            "back into the Spring service over HTTP."
        ),
        metadata={"expected_skill": "camunda-job-workers"},
    ),
    Sample(
        id="ts-node-stack",
        input=(
            "Our backend is all Node.js — Express services, business logic in "
            "TypeScript, ops team only hosts Node apps. We don't want to spin "
            "up a JVM service just for Camunda integration. There's a new BPMN "
            "pricing step that needs to consult our pricing engine; how should "
            "we wire it up without leaving our Node.js stack?"
        ),
        target=(
            "Canonical answer: implement a Camunda 8 job worker in TypeScript "
            "inside (or next to) the existing Node service. The Camunda 8 "
            "TypeScript SDK runs a worker process directly from the Node "
            "runtime — no JVM dependency, no extra hosting surface, and the "
            "worker can call straight into the pricing engine.\n\n"
            "Anti-patterns:\n"
            "- Custom outbound connector — the connector runtime is JVM-based; "
            "contradicts the explicit 'no JVM service' constraint.\n"
            "- OOTB REST connector — pushes the integration outside the Node "
            "service and loses the in-process call to the pricing engine.\n"
            "- Stand up a separate microservice just to consume jobs."
        ),
        metadata={"expected_skill": "camunda-job-workers"},
    ),
    Sample(
        id="ai-agent-ticket-triage",
        input=(
            "I want a BPMN node that takes an incoming support ticket, decides "
            "whether to escalate or auto-respond, can call our internal "
            "KB-search and customer-data tools dynamically, and writes a "
            "reply. The decision-making and tool selection should be LLM-driven."
        ),
        target=(
            "Canonical answer: use the AI Agent connector on an ad-hoc "
            "subprocess. The agent's tools are modeled as sub-flows or "
            "connector calls (KB-search, customer-data) exposed via fromAi() "
            "parameters; the LLM picks which tool to call and when, and the "
            "ad-hoc subprocess loops until the agent is done.\n\n"
            "Anti-patterns:\n"
            "- Hard-coded gateway decisions — the routing must be LLM-driven.\n"
            "- Custom job worker that calls an LLM and parses output by hand — "
            "the AI Agent connector exists for this.\n"
            "- DMN decision table — deterministic rules, not LLM-driven tool "
            "selection."
        ),
        metadata={"expected_skill": "camunda-ai-agents"},
    ),
]

_SAMPLES = [
    Sample(id=s.id, input=(s.input or "") + _ADVISORY, target=s.target, metadata=s.metadata)
    for s in _RAW
]


@task
def camunda_development(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.baseline.exclude)
    return Task(
        dataset=_SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            assert_skill_loaded("camunda-development", gating=False),
            model_graded_qa(instructions=_GRADER),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-advisory.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=180,
        token_limit=200_000,
        message_limit=40,
    )
