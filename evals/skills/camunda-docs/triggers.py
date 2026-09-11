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
            Negative(
                "author-bpmn",
                "Create a BPMN process for invoice approval with a review task and an approval gateway.",
                should_load=["camunda-bpmn"],
            ),
            Negative(
                "author-dmn",
                "Create a DMN decision table that selects a shipping method from package weight and destination.",
                should_load=["camunda-dmn"],
            ),
            Negative(
                "configure-connector",
                "Apply a REST connector template to a BPMN service task and configure its request URL.",
                should_load=["camunda-connectors"],
            ),
            Negative(
                "operate-process",
                "Deploy my BPMN process to the cluster and start an instance with these variables.",
                should_load=["camunda-process-mgmt"],
            ),
        ],
    )
