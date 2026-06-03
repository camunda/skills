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
        ],
        negative=[
            Negative(
                "deterministic-rules",
                "I have fixed business rules mapping package weight and region to a shipping method.",
                should_load=["camunda-dmn"],
            ),
        ],
    )
