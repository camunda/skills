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
            Positive(
                "xor-safe-default",
                "Model an approve/reject exclusive gateway so an unexpected or missing decision safely follows a default reject branch instead of causing a runtime incident.",
            ),
            Positive(
                "connectors-repo-bpmn-fixture",
                "In camunda/connectors, edit the BPMN integration-test fixture: add a timer boundary event to the service task and an escalation end event.",
            ),
            Positive(
                "explicit-bpmn-in-connectors-repo",
                "/camunda-bpmn In camunda/connectors, create a BPMN example process with a start event, a connector service task, and an end event.",
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
            Negative(
                "connectors-post-review-fixes",
                "Repository: camunda/connectors. We are editing Java-driven/generated AI Agent v2 element templates and Groovy generation scripts. "
                "The PR review found duplicated backend metadata and tests, plus review-readiness gaps. Address these issues.",
            ),
            Negative(
                "connectors-publish-template-pr",
                "In camunda/connectors, the Java metadata and Groovy generation-script changes for AI Agent v2 element templates are complete. "
                "Create a PR describing the provider-selection UI behavior and the generator tests.",
            ),
        ],
    )
