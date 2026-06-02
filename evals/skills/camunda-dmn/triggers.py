"""Trigger eval for camunda-dmn — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        excluded_skills=["camunda-development"],
        positive=[
            Positive(
                "decision-table",
                "I need a decision table that picks a shipping method based on package weight and destination region.",
            ),
            Positive(
                "collect-hit-policy",
                "Set up a decision table that returns all matching discounts for an order, not just the first one.",
            ),
        ],
        negative=[
            Negative(
                "llm-routing",
                "I want an LLM to decide whether to escalate a support ticket and dynamically pick which tool to call.",
                should_load=["camunda-ai-agents"],
            ),
        ],
    )
