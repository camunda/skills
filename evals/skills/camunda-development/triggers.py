"""Trigger eval for camunda-development — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        also_run_when_changed=[
            "camunda-connectors",
            "camunda-connectors-development",
            "camunda-job-workers",
            "camunda-ai-agents",
        ],
        positive=[
            Positive(
                "connector-or-worker",
                "We have a high-throughput step that calls our Spring Boot service holding warm caches. Should I use a connector or a job worker here?",
            ),
            Positive(
                "unsure-integration-approach",
                "I need to integrate an external API into my process but I'm not sure whether to use an out-of-the-box connector, a custom connector, or a job worker. How should I decide?",
            ),
        ],
        negative=[
            Negative(
                "pure-feel",
                "What FEEL expression returns the number of days between two date variables?",
                should_load=["camunda-feel"],
            ),
        ],
    )
