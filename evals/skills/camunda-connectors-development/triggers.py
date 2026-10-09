"""Trigger eval for camunda-connectors-development — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        # Hide the meta-router (camunda-development) so this tests the leaf skill.
        excluded_skills=["camunda-development"],
        also_run_when_changed=[
            "camunda-bpmn",
            "camunda-ai-agents",
            "camunda-connectors",
        ],
        positive=[
            Positive(
                "reusable-outbound",
                "Build a reusable outbound connector for our internal customer-data API (custom HSM-signed JWT) that every team consumes by name.",
            ),
            Positive(
                "custom-inbound-webhook",
                "Our payments vendor pushes settlement events to a webhook with a custom HMAC scheme; each event should start a process. Build the connector.",
            ),
            Positive(
                "connectors-java-template-generation",
                "In camunda/connectors, implement provider steps for AI Agent v2 element templates through Java connector metadata and Groovy generation scripts. "
                "Update the generator tests for conditional UI fields and prepare the implementation for PR review.",
                should_not_load=[
                    "camunda-bpmn",
                    "camunda-ai-agents",
                    "camunda-connectors",
                ],
            ),
            Positive(
                "explicit-connector-development-review-fixes",
                "/camunda-connectors-development In camunda/connectors, address the PR review issues in our Java connector metadata and Groovy element-template generator: "
                "simplify duplicated backend metadata and tests and resolve review-readiness gaps.",
                should_not_load=[
                    "camunda-bpmn",
                    "camunda-ai-agents",
                    "camunda-connectors",
                ],
            ),
        ],
        negative=[
            Negative(
                "ootb-slack",
                "Just send a Slack notification using our existing Slack setup when the process finishes.",
                should_load=["camunda-connectors"],
            ),
        ],
    )
