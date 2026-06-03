"""Trigger eval for camunda-bpmn — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        positive=[
            Positive(
                "create-process",
                "Create a BPMN process with a user task to review an invoice, followed by a service task that records the decision.",
            ),
            Positive(
                "boundary-timer",
                "Add a 5-minute timer boundary event to the review task that cancels it and routes to an escalation path.",
            ),
        ],
        negative=[
            Negative(
                "install-cli",
                "Install the c8ctl CLI and point it at my running cluster.",
                should_load=["camunda-c8ctl"],
            ),
            Negative(
                "deploy-and-start",
                "Deploy my process to the cluster and start a new instance with the variables orderAmount=500 and region=EU.",
                should_load=["camunda-process-mgmt"],
            ),
        ],
    )
