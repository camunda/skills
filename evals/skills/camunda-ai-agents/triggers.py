"""Trigger eval for camunda-ai-agents — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        positive=[
            Positive(
                "ticket-triage-agent",
                "Build a BPMN node where an LLM decides whether to escalate or auto-respond to a support ticket, dynamically calling KB-search and customer-data tools and writing a reply.",
            ),
            Positive(
                "tool-loop-agent",
                "I want an AI agent in my process that picks which tool to call at runtime and loops until it's done.",
            ),
            Positive(
                "connectors-repo-agent-bpmn-example",
                "In camunda/connectors, model a BPMN example using the AI Agent Sub-process connector: an ad-hoc subprocess with KB-search and customer-data tools.",
            ),
        ],
        negative=[
            Negative(
                "deterministic-rules",
                "I have fixed business rules mapping package weight and region to a shipping method.",
                should_load=["camunda-dmn"],
            ),
            Negative(
                "connectors-agent-template-generator",
                "In camunda/connectors, update the Java-driven AI Agent v2 element templates and Groovy generation scripts to add provider steps and conditional UI fields. "
                "Simplify duplicated backend metadata and generator tests flagged in the PR review.",
            ),
        ],
    )
