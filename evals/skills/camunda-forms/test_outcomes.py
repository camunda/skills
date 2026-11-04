from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool
from inspect_ai.tool import ToolCall


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


def _score_fix_invalid_sample(
    monkeypatch: pytest.MonkeyPatch, form: dict[str, object]
) -> SimpleNamespace:
    sample = next(s for s in _outcomes.SAMPLES if s.id == "fix-invalid-existing-form")

    class _Sandbox:
        async def exec(self, cmd: list[str], **_: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=0, stdout=json.dumps(form))

    monkeypatch.setattr(_outcomes, "sandbox", lambda: _Sandbox())
    state = SimpleNamespace(metadata=sample.metadata)
    return asyncio.run(_outcomes.form_outcome()(state, None))


def test_fix_invalid_sample_plants_the_invalid_form() -> None:
    sample = next(s for s in _outcomes.SAMPLES if s.id == "fix-invalid-existing-form")

    assert (
        json.loads(sample.files["/workspace/form.form"])
        == _outcomes.INVALID_EXISTING_FORM
    )
    assert _outcomes._validate_form_schema(_outcomes.INVALID_EXISTING_FORM) is not None


def test_fix_invalid_sample_fails_when_only_extended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    form = copy.deepcopy(_outcomes.INVALID_EXISTING_FORM)
    form["components"][1]["layout"]["row"] = "row_2"
    form["components"].insert(
        1,
        {
            "type": "textarea",
            "id": "Field_Comments",
            "key": "comments",
            "label": "Comments",
            "layout": {"row": "row_1", "columns": None},
        },
    )

    score = _score_fix_invalid_sample(monkeypatch, form)

    assert score.value == 0.0
    assert "schema validation failed" in score.explanation


def test_fix_invalid_sample_passes_when_fixed_and_extended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    form = _valid_form()
    form["components"] = [
        {
            "type": "textfield",
            "id": "Field_ReviewerName",
            "key": "reviewerName",
            "label": "Reviewer name",
            "defaultValue": "Ada",
            "layout": {"row": "row_0", "columns": None},
        },
        {
            "type": "textarea",
            "id": "Field_Comments",
            "key": "comments",
            "label": "Comments",
            "layout": {"row": "row_1", "columns": None},
        },
        {
            "type": "button",
            "id": "Button_Submit",
            "label": "Submit",
            "action": "submit",
            "layout": {"row": "row_2", "columns": None},
        },
    ]

    score = _score_fix_invalid_sample(monkeypatch, form)

    assert score.value == 1.0, score.explanation


_REPO = Path(__file__).resolve().parents[3]
_VALIDATE = "node validate-form.cjs form.form"
# Real validate-form.cjs output for the planted form, step by step.
_AJV_FAILURE = '[\n  {\n    "instancePath": "/schemaVersion",\n    "message": "must be integer"\n  }\n]'
_SHAPE_FAILURE = (
    '[\n  "components[0]: use defaultValue instead of value on a component"\n]'
)
_PARSE_FAILURE = (
    'Cannot read/parse form.form: Unexpected token \'}\', "{"components": [}" '
    "is not valid JSON"
)
_MISSING_FILE = (
    "Cannot read/parse form.form: ENOENT: no such file or directory, open 'form.form'"
)
_PASS = "Valid \u2713\nroot@sandbox:/workspace# "

_call_ids = iter(range(10_000))


def _shell(command: str, output: str, function: str = "bash_session") -> list:
    call_id = f"call{next(_call_ids)}"
    arguments = (
        {"action": "type_submit", "input": command}
        if function == "bash_session"
        else {"command": command}
    )
    return [
        ChatMessageAssistant(
            content="",
            tool_calls=[ToolCall(id=call_id, function=function, arguments=arguments)],
        ),
        ChatMessageTool(content=output, tool_call_id=call_id, function=function),
    ]


def _fix_loop_score(*turns: list, requires: bool = True) -> object:
    messages = [m for turn in turns for m in turn]
    state = SimpleNamespace(metadata={"requires_fix_loop": requires}, messages=messages)
    return asyncio.run(_outcomes.form_fix_loop()(state, None))


def test_fix_invalid_sample_requires_the_fix_loop() -> None:
    sample = next(s for s in _outcomes.SAMPLES if s.id == "fix-invalid-existing-form")

    assert sample.metadata["requires_fix_loop"] is True


@pytest.mark.parametrize("function", ["bash_session", "bash", "Bash"])
def test_fix_loop_passes_on_failed_then_passing_validation(function: str) -> None:
    score = _fix_loop_score(
        _shell(_VALIDATE, _AJV_FAILURE, function),
        _shell(_VALIDATE, _SHAPE_FAILURE, function),
        _shell(_VALIDATE, _PASS, function),
    )

    assert score.value == 1.0, score.explanation


def test_fix_loop_counts_a_json_parse_failure() -> None:
    score = _fix_loop_score(_shell(_VALIDATE, _PARSE_FAILURE), _shell(_VALIDATE, _PASS))

    assert score.value == 1.0, score.explanation


def test_fix_loop_accepts_quoted_validator_arguments() -> None:
    quoted = 'node "validate-form.cjs" "form.form"'
    score = _fix_loop_score(_shell(quoted, _AJV_FAILURE), _shell(quoted, _PASS))

    assert score.value == 1.0, score.explanation


def test_fix_loop_accepts_a_recovery_inside_one_shell_call() -> None:
    command = f"{_VALIDATE}; sed -i 's/\"18\"/18/' form.form; {_VALIDATE}"
    score = _fix_loop_score(_shell(command, f"{_AJV_FAILURE}\n{_PASS}"))

    assert score.value == 1.0, score.explanation


@pytest.mark.parametrize(
    ("outputs", "reason"),
    [
        ((), "validator never ran"),
        ((_PASS,), "never reported a failure"),
        ((_MISSING_FILE, _PASS), "never reported a failure"),
        ((_AJV_FAILURE,), "did not pass"),
        ((_AJV_FAILURE, _PASS, _SHAPE_FAILURE), "did not pass"),
    ],
    ids=[
        "no-validation",
        "success-only",
        "missing-file",
        "failure-only",
        "ends-failing",
    ],
)
def test_fix_loop_fails_without_a_completed_loop(
    outputs: tuple[str, ...], reason: str
) -> None:
    score = _fix_loop_score(*(_shell(_VALIDATE, o) for o in outputs))

    assert score.value == 0.0
    assert reason in score.explanation


@pytest.mark.parametrize(
    ("command", "path"),
    [
        ("cat skills/camunda-forms/SKILL.md", "skills/camunda-forms/SKILL.md"),
        ("cat validate-form.cjs", "skills/camunda-forms/SKILL.md"),
    ],
    ids=["read-skill", "read-helper"],
)
def test_fix_loop_ignores_shell_reads_of_validator_text(
    command: str, path: str
) -> None:
    text = (_REPO / path).read_text(encoding="utf-8")
    assert "Valid \u2713" in text and "FAILED: " in text

    score = _fix_loop_score(_shell(command, text), _shell(_VALIDATE, _PASS))

    assert score.value == 0.0
    assert "never reported a failure" in score.explanation


def test_fix_loop_does_not_apply_to_other_samples() -> None:
    assert _fix_loop_score(_shell(_VALIDATE, _PASS), requires=False) is None
