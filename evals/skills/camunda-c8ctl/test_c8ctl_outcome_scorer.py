"""Unit tests for the camunda-c8ctl outcome scorer (sandbox faked)."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

from inspect_ai.util import ExecResult


def _load_outcomes() -> ModuleType:
    path = Path(__file__).with_name("outcomes.py")
    spec = importlib.util.spec_from_file_location("camunda_c8ctl_outcomes", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_outcomes = _load_outcomes()


class _Sandbox:
    def __init__(self, result: ExecResult):
        self.result = result
        self.calls: list[list[str]] = []

    async def exec(self, cmd, **kwargs):
        self.calls.append(cmd)
        return self.result


def _score(monkeypatch, result: ExecResult):
    sb = _Sandbox(result)
    monkeypatch.setattr(_outcomes, "sandbox", lambda: sb)
    state = SimpleNamespace(metadata={"check": "installed"})
    score = asyncio.run(_outcomes.c8ctl_outcome()(state, None))
    return score, sb


def test_installed_resolves_via_npm_prefix(monkeypatch):
    # Seen in CI: agents install to ~/.npm-global (no write access to the
    # system prefix) and extend PATH in ~/.bashrc, which `exec` never reads.
    score, sb = _score(
        monkeypatch,
        ExecResult(True, 0, "/home/agent/.npm-global/bin/c8ctl\nc8ctl v4.6.1\n", ""),
    )
    assert score.value == 1.0
    assert score.metadata["path"] == "/home/agent/.npm-global/bin/c8ctl"
    [cmd] = sb.calls
    assert cmd[:2] == ["bash", "-c"]
    assert "npm config get prefix" in cmd[2] and "c8ctl --version" in cmd[2]


def test_not_installed_fails(monkeypatch):
    score, _ = _score(monkeypatch, ExecResult(False, 1, "", ""))
    assert score.value == 0.0
