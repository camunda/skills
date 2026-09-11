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


@pytest.mark.parametrize(
    ("component", "expected_message"),
    [
        (
            {
                "type": "textfield",
                "id": "Field_Name",
                "key": "name",
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
    error = _outcomes._validate_component_shapes(
        [
            {
                "type": "textfield",
                "id": "Field_Name",
                "key": "name",
                "defaultValue": "Ada",
            },
            {
                "type": "button",
                "id": "Button_Submit",
                "label": "Submit",
                "action": "submit",
            },
        ]
    )

    assert error is None
