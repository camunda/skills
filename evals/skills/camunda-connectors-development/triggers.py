"""Trigger eval for camunda-connectors-development — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        excluded_skills=["camunda-development"],
        positive=[
            Positive(
                "reusable-outbound",
                "Build a reusable outbound connector for our internal customer-data API (custom HSM-signed JWT) that every team consumes by name.",
            ),
            Positive(
                "custom-inbound-webhook",
                "Our payments vendor pushes settlement events to a webhook with a custom HMAC scheme; each event should start a process. Build the connector.",
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
