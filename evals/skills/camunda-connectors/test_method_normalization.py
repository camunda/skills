from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_outcomes() -> ModuleType:
    path = Path(__file__).with_name("outcomes.py")
    spec = importlib.util.spec_from_file_location("camunda_connectors_outcomes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_outcomes = _load_outcomes()


@pytest.mark.parametrize("value", ["GET", '"GET"', '="GET"'])
def test_accepts_get_method_literal_forms(value: str) -> None:
    assert _outcomes._normalize_http_method(value) == "GET"


@pytest.mark.parametrize("value", ['="POST"', "=GET", '="G E T"'])
def test_rejects_non_get_method_values(value: str) -> None:
    assert _outcomes._normalize_http_method(value) != "GET"
