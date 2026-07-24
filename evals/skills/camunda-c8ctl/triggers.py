"""Trigger eval for camunda-c8ctl — does this prompt route here?"""

from pathlib import Path

from inspect_ai import Task, task

from core.triggers import Negative, Positive, build_trigger_eval


@task
def trigger_eval() -> Task:
    return build_trigger_eval(
        Path(__file__).parent.name,
        positive=[
            Positive(
                "install-cli",
                "I need a command-line tool to talk to my Camunda 8 cluster — how do I install and configure it?",
            ),
            Positive(
                "start-local-cluster",
                "Spin up a local Camunda 8 cluster on my machine so I can experiment.",
            ),
        ],
        negative=[
            Negative(
                "author-dmn",
                "I need a decision table that picks a shipping method based on weight and destination region.",
                should_load=["camunda-dmn"],
            ),
        ],
    )
