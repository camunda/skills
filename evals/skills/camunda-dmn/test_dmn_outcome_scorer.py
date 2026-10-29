"""Unit tests for the camunda-dmn outcome scorer's lint step (sandbox faked)."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

from inspect_ai.util import ExecResult


def _load_outcomes() -> ModuleType:
    path = Path(__file__).with_name("outcomes.py")
    spec = importlib.util.spec_from_file_location("camunda_dmn_outcomes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_outcomes = _load_outcomes()

DMN = f"""<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
    id="d" name="D" namespace="{_outcomes.CAMUNDA_NAMESPACE}">
  <decision id="shippingMethod" name="Shipping method">
    <decisionTable id="t" hitPolicy="UNIQUE"/>
  </decision>
</definitions>"""


class _Sandbox:
    def __init__(self, lint: ExecResult):
        self.lint = lint
        self.calls: list[tuple[list[str], dict]] = []

    async def exec(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if cmd[:1] == ["cat"]:
            return ExecResult(True, 0, DMN, "")
        return self.lint


def _score(monkeypatch, lint: ExecResult):
    sb = _Sandbox(lint)
    monkeypatch.setattr(_outcomes, "sandbox", lambda: sb)
    state = SimpleNamespace(metadata={"check": "shipping-method-unique"})
    return asyncio.run(_outcomes.dmn_outcome()(state, None)), sb


def test_lint_uses_scorer_owned_config_outside_workspace(monkeypatch):
    # Seen in CI: agents create .dmnlintrc to lint, then delete it as cleanup,
    # so linting from /workspace failed with "Could not locate .dmnlintrc".
    _, sb = _score(monkeypatch, ExecResult(True, 0, "", ""))
    [lint_cmd] = [cmd for cmd, _ in sb.calls if cmd[:1] != ["cat"]]
    assert lint_cmd == ["bash", "-c", _outcomes.DMNLINT_WITH_SCORER_CONFIG]
    script = lint_cmd[2]
    assert "mktemp -d" in script and 'cd "$d"' in script
    assert "dmnlint:recommended" in script
    assert "npx --yes dmnlint /workspace/decision.dmn" in script


def test_lint_failure_fails_the_sample(monkeypatch):
    out = "shippingMethod  error  Element is missing label/name  label-required"
    score, _ = _score(monkeypatch, ExecResult(False, 1, out, ""))
    assert score.value == 0.0
    assert "label-required" in score.explanation
