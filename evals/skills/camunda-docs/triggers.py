"""Trigger eval for camunda-docs — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        positive=[
            Positive(
                "verify-rest-endpoint",
                "I want to confirm the exact REST API endpoint to create a process instance in Camunda 8.8 — check the official docs.",
            ),
            Positive(
                "verify-version-support",
                "Confirm against the official Camunda documentation whether multi-instance markers are supported on call activities.",
            ),
        ],
        negative=[
            Negative(
                "build-form",
                "Build a user task form with a name field, an email field, and an approval checkbox.",
                should_load=["camunda-forms"],
            ),
        ],
    )
