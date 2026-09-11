from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_outcomes() -> ModuleType:
    path = Path(__file__).with_name("outcomes.py")
    spec = importlib.util.spec_from_file_location("camunda_forms_outcomes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_outcomes = _load_outcomes()


def _valid_form() -> dict[str, object]:
    return {
        "components": [
            {
                "type": "textfield",
                "id": "Field_Name",
                "key": "name",
                "label": "Name",
                "layout": {"row": "row_0", "columns": None},
            },
            {
                "type": "button",
                "id": "Button_Submit",
                "label": "Submit",
                "action": "submit",
                "layout": {"row": "row_1", "columns": None},
            },
        ],
        "executionPlatform": "Camunda Cloud",
        "executionPlatformVersion": "8.8.0",
        "exporter": {"name": "Camunda Modeler", "version": "5.34.0"},
        "schemaVersion": 18,
        "id": "review-form",
        "type": "default",
    }


@pytest.mark.parametrize(
    ("component", "expected_message"),
    [
        (
            {
                "type": "textfield",
                "id": "Field_Name",
                "key": "name",
                "label": "Name",
                "layout": {"row": "row_0", "columns": None},
                "value": "Ada",
            },
            "uses invalid value property",
        ),
        (
            {"type": "submit", "id": "Button_Submit"},
            "uses invalid type 'submit'",
        ),
        (
            {
                "type": "button",
                "id": "Button_Submit",
                "label": "Submit",
                "key": "submit",
                "layout": {"row": "row_0", "columns": None},
            },
            "must not define key",
        ),
    ],
    ids=["component-value", "submit-component-type", "button-key"],
)
def test_rejects_invalid_component_shapes(
    component: dict[str, object], expected_message: str
) -> None:
    error = _outcomes._validate_component_shapes([component])

    assert error is not None
    assert expected_message in error


def test_accepts_schema_safe_default_and_submit_button() -> None:
    form = _valid_form()
    form["components"] = [
        {
            "type": "textfield",
            "id": "Field_Name",
            "key": "name",
            "label": "Name",
            "defaultValue": "Ada",
            "layout": {"row": "row_0", "columns": None},
        },
        {
            "type": "button",
            "id": "Button_Submit",
            "label": "Submit",
            "action": "submit",
            "layout": {"row": "row_1", "columns": None},
        },
    ]

    assert _outcomes._validate_form_schema(form) is None


@pytest.mark.parametrize(
    "component",
    [
        {
            "type": "textarea",
            "id": "Field_Comments",
            "key": "comments",
            "label": "Comments",
            "rows": 5,
            "layout": {"row": "row_0", "columns": None},
        },
        {
            "type": "iframe",
            "id": "Iframe_Preview",
            "url": "https://example.com/preview",
            "title": "Preview",
            "layout": {"row": "row_0", "columns": None},
        },
    ],
    ids=["textarea-rows", "iframe-title"],
)
def test_accepts_documented_component_extensions(
    component: dict[str, object],
) -> None:
    form = _valid_form()
    form["components"] = [component]

    assert _outcomes._validate_form_schema(form) is None


@pytest.mark.parametrize(
    ("component", "expected_message"),
    [
        (
            {
                "type": "textfield",
                "id": "Field_Name",
                "key": "name",
                "label": "Name",
            },
            "missing required properties: layout",
        ),
        (
            {
                "type": "button",
                "id": "Button_Submit",
                "action": "submit",
                "layout": {"row": "row_0", "columns": None},
            },
            "missing required properties: label",
        ),
    ],
    ids=["missing-layout", "missing-button-label"],
)
def test_rejects_incomplete_component_schema(
    component: dict[str, object], expected_message: str
) -> None:
    form = _valid_form()
    form["components"] = [component]

    error = _outcomes._validate_form_schema(form)

    assert error is not None
    assert expected_message in error


def test_accepts_complete_form_schema() -> None:
    assert _outcomes._validate_form_schema(_valid_form()) is None
