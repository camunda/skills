"""Unit tests for the Copilot model preflight (``evals-copilot-models``)."""

from __future__ import annotations

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
