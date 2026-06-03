"""Trigger eval for camunda-forms — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        positive=[
            Positive(
                "build-form",
                "Create a Camunda form for a user task with a name field, an email field, and an approval checkbox.",
            ),
            Positive(
                "form-validation",
                "Add a required-field rule and a dropdown of priority levels to my user task form.",
            ),
        ],
        negative=[
            Negative(
                "feel-default",
                "Write the FEEL expression that computes the number of days between two date variables.",
                should_load=["camunda-feel"],
            ),
        ],
    )
