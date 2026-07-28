"""camunda-forms outcome eval: author valid Camunda form JSON with required fields.

Deterministic, machine-checkable scoring. Each sample asks for a single
`/workspace/form.form` artifact and the scorer validates:
- required top-level Camunda form metadata
- valid JSON structure (`components` list)
- unique component ids / variable keys
- sample-specific field requirements (types, keys, validation, options, layout)
"""

from __future__ import annotations

import json
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-forms"], max_sandboxes=10)

SAVE = (
    "\n\nSave ONLY the final Camunda Form JSON to /workspace/form.form "
    "(no markdown fences, no commentary)."
)

SAMPLES = [
    Sample(
        id="approval-fields",
        input=(
            "Create a Camunda form with id `customer-approval-form` for a user task. "
            "Include these input fields exactly:\n"
            "1. textfield id `Field_CustomerName`, key `customerName`, label `Customer name`, required true, layout.row `row_0`\n"
            "2. textfield id `Field_CustomerEmail`, key `customerEmail`, label `Customer email`, required true, "
            "pattern `^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$`, layout.row `row_0`\n"
            "3. checkbox id `Field_Approved`, key `approved`, label `Approved`, layout.row `row_1`"
            + SAVE
        ),
        metadata={
            "form_id": "customer-approval-form",
            "required_components": [
                {
                    "id": "Field_CustomerName",
                    "type": "textfield",
                    "key": "customerName",
                    "label": "Customer name",
                    "layout_row": "row_0",
                    "validate": {"required": True},
                },
                {
                    "id": "Field_CustomerEmail",
                    "type": "textfield",
                    "key": "customerEmail",
                    "label": "Customer email",
                    "layout_row": "row_0",
                    "validate": {
                        "required": True,
                        "pattern": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$",
                    },
                },
                {
                    "id": "Field_Approved",
                    "type": "checkbox",
                    "key": "approved",
                    "label": "Approved",
                    "layout_row": "row_1",
                },
            ],
        },
    ),
    Sample(
        id="priority-dropdown",
        input=(
            "Create a Camunda form with id `ticket-priority-form`. Include exactly these input fields:\n"
            "1. textfield id `Field_TicketTitle`, key `ticketTitle`, label `Ticket title`, required true, layout.row `row_0`\n"
            "2. select id `Field_Priority`, key `priority`, label `Priority`, required true, layout.row `row_1`, "
            "and static values [{label:'Low',value:'low'},{label:'Medium',value:'medium'},{label:'High',value:'high'}]"
            + SAVE
        ),
        metadata={
            "form_id": "ticket-priority-form",
            "required_components": [
                {
                    "id": "Field_TicketTitle",
                    "type": "textfield",
                    "key": "ticketTitle",
                    "label": "Ticket title",
                    "layout_row": "row_0",
                    "validate": {"required": True},
                },
                {
                    "id": "Field_Priority",
                    "type": "select",
                    "key": "priority",
                    "label": "Priority",
                    "layout_row": "row_1",
                    "validate": {"required": True},
                    "values": [
                        {"label": "Low", "value": "low"},
                        {"label": "Medium", "value": "medium"},
                        {"label": "High", "value": "high"},
                    ],
                },
            ],
        },
    ),
]


def _flatten_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for component in components:
        flattened.append(component)
        nested = component.get("components")
        if isinstance(nested, list):
            flattened.extend(_flatten_components(nested))
    return flattened


@scorer(metrics=[mean(), stderr()])
def form_outcome() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        result = await sb.exec(["cat", "/workspace/form.form"], timeout=10)
        if result.returncode != 0:
            return Score(value=0.0, explanation="/workspace/form.form not created")

        try:
            form = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return Score(value=0.0, explanation=f"invalid JSON: {exc}")

        expected_form_id = (state.metadata or {}).get("form_id")
        required_components = (state.metadata or {}).get("required_components", [])

        required_top_level = {
            "executionPlatform": "Camunda Cloud",
            "executionPlatformVersion": "8.8.0",
            "schemaVersion": 18,
            "type": "default",
        }

        for key, expected in required_top_level.items():
            if form.get(key) != expected:
                return Score(
                    value=0.0,
                    explanation=f"top-level {key!r} mismatch: expected {expected!r}, got {form.get(key)!r}",
                )

        if not isinstance(form.get("exporter"), dict):
            return Score(value=0.0, explanation="missing or invalid exporter object")

        if form.get("id") != expected_form_id:
            return Score(
                value=0.0,
                explanation=f"form id mismatch: expected {expected_form_id!r}, got {form.get('id')!r}",
            )

        components = form.get("components")
        if not isinstance(components, list):
            return Score(value=0.0, explanation="components must be a list")

        flattened = _flatten_components(components)

        ids = [c.get("id") for c in flattened if isinstance(c.get("id"), str)]
        if len(ids) != len(set(ids)):
            return Score(value=0.0, explanation="component ids are not unique")

        keys = [
            c.get("key")
            for c in flattened
            if isinstance(c.get("key"), str)
            and c.get("type")
            not in {"text", "html", "image", "separator", "button", "group", "spacer"}
        ]
        if len(keys) != len(set(keys)):
            return Score(value=0.0, explanation="component keys are not unique")

        by_id = {c.get("id"): c for c in flattened if isinstance(c.get("id"), str)}

        for expected in required_components:
            component = by_id.get(expected["id"])
            if component is None:
                return Score(
                    value=0.0, explanation=f"missing component {expected['id']}"
                )

            for field in ("type", "key", "label"):
                if (
                    expected.get(field) is not None
                    and component.get(field) != expected[field]
                ):
                    return Score(
                        value=0.0,
                        explanation=(
                            f"component {expected['id']} {field} mismatch: expected "
                            f"{expected[field]!r}, got {component.get(field)!r}"
                        ),
                    )

            layout = component.get("layout") or {}
            if layout.get("row") != expected.get("layout_row"):
                return Score(
                    value=0.0,
                    explanation=(
                        f"component {expected['id']} layout.row mismatch: expected "
                        f"{expected.get('layout_row')!r}, got {layout.get('row')!r}"
                    ),
                )

            expected_validate = expected.get("validate")
            if expected_validate:
                validate = component.get("validate") or {}
                for key, value in expected_validate.items():
                    if validate.get(key) != value:
                        return Score(
                            value=0.0,
                            explanation=(
                                f"component {expected['id']} validate.{key} mismatch: "
                                f"expected {value!r}, got {validate.get(key)!r}"
                            ),
                        )

            expected_values = expected.get("values")
            if (
                expected_values is not None
                and component.get("values") != expected_values
            ):
                return Score(
                    value=0.0,
                    explanation=(
                        f"component {expected['id']} values mismatch: expected "
                        f"{expected_values!r}, got {component.get('values')!r}"
                    ),
                )

        return Score(
            value=1.0,
            explanation=(
                f"form validated: id={form.get('id')}, components={len(flattened)}"
            ),
        )

    return score


@task
def camunda_forms(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            form_outcome(),
            assert_skill_loaded("camunda-forms", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-advisory.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=180,
        token_limit=120_000,
        message_limit=40,
    )
