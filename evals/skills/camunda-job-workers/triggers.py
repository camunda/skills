"""Trigger eval for camunda-job-workers — does this prompt route here?"""

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
                "typescript-worker",
                "Our backend is all Node.js/TypeScript and we don't want a JVM. Implement a Camunda 8 job worker for a new pricing step in our Node service.",
            ),
            Positive(
                "spring-streaming-worker",
                "Embed a streaming Zeebe job worker in our existing Spring Boot credit-decisioning service so jobs activate directly into it.",
            ),
        ],
        negative=[
            Negative(
                "ootb-rest",
                "Call a public REST API with no auth from a service task — nothing custom.",
                should_load=["camunda-connectors"],
            ),
        ],
    )
