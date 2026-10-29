"""Unit tests for the Copilot model preflight (``evals-copilot-models``)."""

from __future__ import annotations

import http.client
import io
import json
import sys

import pytest

from scripts import copilot_models
from scripts.copilot_models import check, render, selectable

CATALOGUE = [
    {"id": "claude-sonnet-5.5", "vendor": "Anthropic", "model_picker_enabled": True,
     "policy": {"state": "enabled"}, "capabilities": {"type": "chat"}},
    {"id": "gemini-4-argon", "vendor": "Google", "model_picker_enabled": True,
     "policy": {"state": "disabled"}, "capabilities": {"type": "chat"}},
    {"id": "grok-4.7", "vendor": "xAI", "model_picker_enabled": True,
     "capabilities": {"type": "chat"}},
    {"id": "gpt-4o", "vendor": "OpenAI", "model_picker_enabled": False,
     "policy": {"state": "enabled"}, "capabilities": {"type": "chat"}},
    {"id": "text-embedding-3-small", "model_picker_enabled": True,
     "capabilities": {"type": "embeddings"}},
]  # fmt: skip


def test_selectable_respects_picker_policy_and_type():
    # No policy block = unrestricted; disabled policy, hidden-from-picker, and
    # non-chat models are out.
    assert sorted(selectable(CATALOGUE)) == ["claude-sonnet-5.5", "grok-4.7"]


def test_check_reports_unavailable_ids_and_accepts_auto():
    available = selectable(CATALOGUE)
    assert check(["claude-sonnet-5.5", "auto"], available) == []
    assert check(["gemini-4-argon", "gpt-4o", "nope"], available) == [
        "gemini-4-argon",
        "gpt-4o",
        "nope",
    ]


def test_render_marks_requested_and_shows_policy():
    md = render(CATALOGUE, ["claude-sonnet-5.5"])
    assert "| `claude-sonnet-5.5` | Anthropic | enabled | ✅ |" in md
    assert "| `gemini-4-argon` | Google | disabled |  |" in md
    assert "gpt-4o" not in md and "text-embedding" not in md


def test_unreadable_catalogue_exits_3(monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "t")
    monkeypatch.setattr(sys, "argv", ["evals-copilot-models", "--check", "x"])
    for exc in (
        ConnectionResetError("reset by peer"),
        TimeoutError("timed out"),
        http.client.IncompleteRead(b"{", 512),
        ValueError("bad json"),
    ):

        def boom(token, exc=exc):
            raise exc

        monkeypatch.setattr(copilot_models, "fetch_models", boom)
        with pytest.raises(SystemExit) as e:
            copilot_models.main()
        assert e.value.code == 3, exc


def _run(monkeypatch, check_ids):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "t")
    monkeypatch.setattr(sys, "argv", ["evals-copilot-models", "--check", check_ids])
    try:
        copilot_models.main()
    except SystemExit as e:
        return e.code
    return 0


def test_truncated_response_body_is_unreadable_not_unavailable(monkeypatch):
    """A body that ends before Content-Length raises IncompleteRead mid-read."""

    class Truncated(io.BytesIO):
        def read(self, *a):
            raise http.client.IncompleteRead(b'{"data": [', 4096)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        copilot_models.urllib.request, "urlopen", lambda *a, **k: Truncated()
    )
    assert _run(monkeypatch, "claude-sonnet-5.5") == copilot_models.EXIT_UNREADABLE


def test_unavailable_models_exit_2_distinct_from_crashes(monkeypatch):
    class Ok(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    body = json.dumps({"data": CATALOGUE}).encode()
    monkeypatch.setattr(
        copilot_models.urllib.request, "urlopen", lambda *a, **k: Ok(body)
    )
    assert _run(monkeypatch, "claude-sonnet-5.5") == 0
    assert _run(monkeypatch, "gemini-4-argon") == copilot_models.EXIT_UNAVAILABLE == 2
    # 1 is what any uncaught exception exits with; it must not mean "unavailable".
    assert 1 not in (copilot_models.EXIT_UNAVAILABLE, copilot_models.EXIT_UNREADABLE)
