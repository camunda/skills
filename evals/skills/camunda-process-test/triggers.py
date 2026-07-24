"""Trigger eval for camunda-process-test — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        positive=[
            Positive(
                "write-cpt",
                "Write a Camunda Process Test that drives my approval process to completion and asserts the output variables.",
            ),
            Positive(
                "full-coverage",
                "I need CPT tests that reach full BPMN coverage for my order-fulfilment flow, including the error paths.",
            ),
        ],
        negative=[
            Negative(
                "deploy-once",
                "Just deploy my process to the cluster and run it once so I can watch it execute.",
                should_load=["camunda-process-mgmt"],
            ),
        ],
    )
