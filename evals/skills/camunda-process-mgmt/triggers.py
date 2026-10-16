"""Trigger eval for camunda-process-mgmt — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        positive=[
            Positive(
                "deploy-and-run",
                "Deploy order.bpmn to my cluster and start an instance with these variables.",
            ),
            Positive(
                "resolve-incident",
                "An instance is stuck on an incident — help me inspect it and resolve it on the cluster.",
            ),
            Positive(
                "unnamed-stuck-case",
                "Order 4711 has been stuck in our fulfilment workflow for two days. Find out which step it's stuck on and get it moving again.",
            ),
        ],
        negative=[
            Negative(
                "app-deploy",
                "Deploy our Spring Boot app to Kubernetes with a Helm chart.",
            ),
            Negative(
                "author-bpmn",
                "Design a new BPMN process for invoice approval with a review user task and an approval gateway.",
                should_load=["camunda-bpmn"],
            ),
        ],
    )
