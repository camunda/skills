"""Trigger eval for camunda-connectors — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        # Hide the meta-router (camunda-development) so this tests the leaf skill.
        excluded_skills=["camunda-development"],
        positive=[
            Positive(
                "slack-notification",
                "Send a Slack notification to my team's channel when a process hits an error path. Slack is already connected — what's the simplest way?",
                should_not_load=[
                    "camunda-connectors-development",
                    "camunda-job-workers",
                ],
            ),
            Positive(
                "public-rest-get",
                "Call the public weather API (HTTPS GET, JSON, no auth) from a BPMN service task.",
            ),
        ],
        negative=[
            Negative(
                "reusable-custom",
                "We need a reusable connector that signs JWTs with our internal HSM and is shared across 8 teams with one retry policy.",
                should_load=["camunda-connectors-development"],
            ),
        ],
    )
