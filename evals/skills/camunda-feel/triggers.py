"""Trigger eval for camunda-feel — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        positive=[
            Positive(
                "gateway-condition",
                "What FEEL expression do I put on a sequence flow so it's taken only when the variable `amount` is greater than 1000?",
            ),
            Positive(
                "date-arithmetic",
                "How do I add 3 days to a date variable in a Camunda expression?",
            ),
            Positive(
                "list-filter",
                "I have a list of order items in a variable. What's the FEEL to sum the `price` field across all of them?",
            ),
        ],
        negative=[
            Negative(
                "install-cli",
                "I need a CLI to talk to my Camunda 8 cluster — how do I set it up?",
                should_load=["camunda-c8ctl"],
            ),
        ],
    )
