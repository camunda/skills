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
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
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

_FORM_SCHEMA = json.loads(
    Path(__file__).with_name("form-schema.json").read_text(encoding="utf-8")
)
_FORM_SCHEMA_VALIDATOR = Draft7Validator(_FORM_SCHEMA)

_INPUT_TYPES = {
    "checkbox",
    "checklist",
    "datetime",
    "expression",
    "filepicker",
    "number",
    "radio",
    "select",
    "taglist",
    "textfield",
    "textarea",
}
_KEYLESS_TYPES = {
    "text",
    "html",
    "image",
    "separator",
    "button",
    "group",
    "spacer",
    "table",
    "iframe",
    "documentPreview",
}
_REQUIRED_COMPONENT_FIELDS = {
    **{
        component_type: ("id", "key", "label", "layout")
        for component_type in _INPUT_TYPES
    },
    "button": ("id", "label", "layout"),
    "documentPreview": ("id", "dataSource", "layout"),
    "dynamiclist": ("id", "key", "label", "components", "layout"),
    "expression": ("id", "key", "label", "expression", "computeOn", "layout"),
    "group": ("id", "label", "components", "layout"),
    "html": ("id", "content", "layout"),
    "iframe": ("id", "url", "layout"),
    "image": ("id", "source", "layout"),
    "separator": ("id", "layout"),
    "spacer": ("id", "layout"),
    "table": ("id", "dataSource", "layout"),
    "text": ("id", "text", "layout"),
}

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
    Sample(
        id="schema-safe-default-and-submit",
        input=(
            "Create a Camunda form with id `review-form`. Include exactly these components:\n"
            "1. textfield id `Field_ReviewerName`, key `reviewerName`, label `Reviewer name`, "
            "defaultValue `Ada`, layout.row `row_0`\n"
            "2. button id `Button_Submit`, label `Submit`, action `submit`, layout.row `row_1`; "
            "do not include a key on the button." + SAVE
        ),
        metadata={
            "form_id": "review-form",
            "required_components": [
                {
                    "id": "Field_ReviewerName",
                    "type": "textfield",
                    "key": "reviewerName",
                    "label": "Reviewer name",
                    "layout_row": "row_0",
                    "properties": {"defaultValue": "Ada"},
                },
                {
                    "id": "Button_Submit",
                    "type": "button",
                    "label": "Submit",
                    "layout_row": "row_1",
                    "properties": {"action": "submit"},
                    "absent_properties": ["key"],
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


def _validate_component_shapes(components: list[dict[str, Any]]) -> str | None:
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            return f"component at index {index} must be an object"

        component_type = component.get("type")
        if component_type == "submit":
            return (
                f"component {component.get('id')!r} uses invalid type 'submit'; "
                "use type 'button' with action 'submit'"
            )
        if component_type not in _REQUIRED_COMPONENT_FIELDS:
            return f"component {component.get('id')!r} has unsupported type {component_type!r}"

        missing_fields = [
            field
            for field in _REQUIRED_COMPONENT_FIELDS[component_type]
            if field not in component
        ]
        if missing_fields:
            return (
                f"component {component.get('id')!r} is missing required "
                f"properties: {', '.join(missing_fields)}"
            )

        if not isinstance(component.get("id"), str) or not component["id"]:
            return f"component at index {index} must have a non-empty string id"

        layout = component["layout"]
        if not isinstance(layout, dict):
            return f"component {component['id']!r} layout must be an object"
        if "row" not in layout:
            return f"component {component['id']!r} layout is missing required property: row"

        if component_type in _INPUT_TYPES:
            key = component.get("key")
            if not isinstance(key, str) or not key:
                return f"component {component['id']!r} key must be a non-empty string"

        if "label" in _REQUIRED_COMPONENT_FIELDS[component_type]:
            label = component.get("label")
            if not isinstance(label, str) or not label:
                return f"component {component['id']!r} label must be a non-empty string"

        if component_type in {"group", "dynamiclist"} and not isinstance(
            component["components"], list
        ):
            return f"component {component['id']!r} components must be a list"

        if "value" in component:
            return (
                f"component {component['id']!r} uses invalid value property; "
                "use defaultValue for an input default"
            )
        if component_type == "button" and "key" in component:
            return f"button {component['id']!r} must not define key"
    return None


def _validate_form_schema(form: Any) -> str | None:
    schema_errors = sorted(
        _FORM_SCHEMA_VALIDATOR.iter_errors(form),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        error = schema_errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "form"
        return f"schema validation failed at {path}: {error.message}"

    if not isinstance(form, dict):
        return "schema validation failed: form must be an object"

    components = form.get("components")
    if not isinstance(components, list):
        return "schema validation failed: components must be a list"

    shape_error = _validate_component_shapes(_flatten_components(components))
    if shape_error:
        return f"schema validation failed: {shape_error}"
    return None


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

        schema_error = _validate_form_schema(form)
        if schema_error:
            return Score(value=0.0, explanation=schema_error)

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

        exporter = form.get("exporter")
        if not isinstance(exporter, dict):
            return Score(value=0.0, explanation="missing or invalid exporter object")
        if not isinstance(exporter.get("name"), str) or not exporter["name"]:
            return Score(value=0.0, explanation="exporter.name is missing or empty")
        if "version" not in exporter:
            return Score(value=0.0, explanation="exporter.version is missing")

        if form.get("id") != expected_form_id:
            return Score(
                value=0.0,
                explanation=f"form id mismatch: expected {expected_form_id!r}, got {form.get('id')!r}",
            )

        components = form.get("components")
        if not isinstance(components, list):
            return Score(value=0.0, explanation="components must be a list")

        flattened = _flatten_components(components)

        missing_id = [
            str(i) for i, c in enumerate(flattened) if not isinstance(c.get("id"), str)
        ]
        if missing_id:
            return Score(
                value=0.0,
                explanation=f"components at indices {', '.join(missing_id)} have missing or non-string id",
            )

        ids = [c["id"] for c in flattened]
        if len(ids) != len(set(ids)):
            return Score(value=0.0, explanation="component ids are not unique")

        missing_key = [
            c["id"]
            for c in flattened
            if c.get("type") not in _KEYLESS_TYPES and not isinstance(c.get("key"), str)
        ]
        if missing_key:
            return Score(
                value=0.0,
                explanation=f"input components missing key: {missing_key}",
            )

        keys = [c["key"] for c in flattened if c.get("type") not in _KEYLESS_TYPES]
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

            for field, expected_value in expected.get("properties", {}).items():
                if component.get(field) != expected_value:
                    return Score(
                        value=0.0,
                        explanation=(
                            f"component {expected['id']} {field} mismatch: expected "
                            f"{expected_value!r}, got {component.get(field)!r}"
                        ),
                    )

            for field in expected.get("absent_properties", []):
                if field in component:
                    return Score(
                        value=0.0,
                        explanation=(
                            f"component {expected['id']} must not define {field}"
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
