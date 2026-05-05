"""Tests for sdk_runner.py.

The SDK call itself is mocked — we don't spend API credits in unit tests.
What we DO verify: skill-load detection rules, the bridge symlink helper,
transcript serialization, and the skill_name-from-path extractor.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sdk_runner  # noqa: E402


def test_skill_name_from_read_path_repo_layout():
    assert sdk_runner._skill_name_from_read_path("skills/camunda-feel/SKILL.md") == "camunda-feel"


def test_skill_name_from_read_path_canonical_layout():
    assert (
        sdk_runner._skill_name_from_read_path(
            "/home/user/repo/.claude/skills/camunda-bpmn/SKILL.md"
        )
        == "camunda-bpmn"
    )


def test_skill_name_from_read_path_unrelated():
    assert sdk_runner._skill_name_from_read_path("/etc/hosts") is None
    assert sdk_runner._skill_name_from_read_path("README.md") is None
    assert sdk_runner._skill_name_from_read_path("SKILL.md") is None


def test_ensure_skills_bridged_creates_symlinks(tmp_path):
    skills = tmp_path / "skills"
    for name in ("alpha", "beta"):
        d = skills / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n")
    sdk_runner.ensure_skills_bridged(tmp_path)
    bridge = tmp_path / ".claude" / "skills"
    assert (bridge / "alpha").is_symlink()
    assert (bridge / "beta").is_symlink()
    assert (bridge / "alpha").resolve() == (skills / "alpha").resolve()


def test_ensure_skills_bridged_is_idempotent(tmp_path):
    skills = tmp_path / "skills" / "alpha"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: alpha\ndescription: x\n---\n")
    sdk_runner.ensure_skills_bridged(tmp_path)
    sdk_runner.ensure_skills_bridged(tmp_path)  # second call must not raise
    bridge = tmp_path / ".claude" / "skills" / "alpha"
    assert bridge.is_symlink()


def test_ensure_skills_bridged_replaces_stale_link(tmp_path):
    skills = tmp_path / "skills" / "alpha"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: alpha\ndescription: x\n---\n")
    bridge = tmp_path / ".claude" / "skills"
    bridge.mkdir(parents=True)
    (bridge / "alpha").symlink_to(tmp_path / "wrong-target")
    sdk_runner.ensure_skills_bridged(tmp_path)
    assert (bridge / "alpha").resolve() == skills.resolve()


def test_all_skill_names_skips_dirs_without_skill_md(tmp_path):
    (tmp_path / "skills" / "real").mkdir(parents=True)
    (tmp_path / "skills" / "real" / "SKILL.md").write_text("---\nname: real\ndescription: x\n---\n")
    (tmp_path / "skills" / "bogus").mkdir()  # no SKILL.md
    assert sdk_runner.all_skill_names(tmp_path) == ["real"]


# --- Run-arm with mocked SDK ----------------------------------------------


@pytest.mark.asyncio
async def test_run_arm_detects_skill_loads(tmp_path, monkeypatch):
    pytest.importorskip("anyio")

    skills = tmp_path / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: demo\ndescription: x\n---\n")
    other = tmp_path / "skills" / "other"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("---\nname: other\ndescription: x\n---\n")

    from claude_agent_sdk import (  # noqa: WPS433
        AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
    )

    async def fake_query(prompt: str, options):
        # First message: agent invokes the Skill tool to load demo.
        yield AssistantMessage(
            content=[
                ToolUseBlock(id="t1", name="Skill", input={"skill": "demo"}),
                ToolUseBlock(id="t2", name="Read",
                             input={"file_path": ".claude/skills/other/SKILL.md"}),
                TextBlock(text="here is the answer"),
            ],
            model="claude-opus-4-7",
        )
        yield ResultMessage(
            subtype="success",
            duration_ms=1234,
            duration_api_ms=1100,
            is_error=False,
            num_turns=2,
            session_id="abc",
            stop_reason="end_turn",
            total_cost_usd=0.0123,
            usage={"input_tokens": 100, "output_tokens": 50},
        )

    monkeypatch.setattr(sdk_runner, "query", fake_query)

    case_dir = tmp_path / "evals" / "demo" / "iteration-1" / "with_skill" / "case-a"
    res = await sdk_runner.run_arm(
        repo_root=tmp_path,
        prompt="do the thing",
        target_skill="demo",
        arm="with_skill",
        case_id="case-a",
        trial=1,
        outputs_dir=case_dir / "outputs",
        transcript_path=case_dir / "transcript.jsonl",
        max_budget_usd=1.0,
    )
    assert res.skill_loads_via_tool == ["demo"]
    assert res.skill_loads_via_read == ["other"]
    assert res.cost_usd == 0.0123
    assert res.total_tokens == 150
    assert res.num_turns == 2
    assert res.is_error is False
    assert "here is the answer" in res.raw_text
    assert (case_dir / "transcript.jsonl").is_file()


@pytest.mark.asyncio
async def test_run_arm_filters_target_in_without_arm(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    for name in ("demo", "sibling"):
        d = skills / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n")

    captured: dict = {}

    from claude_agent_sdk import ResultMessage  # noqa: WPS433

    async def fake_query(prompt: str, options):
        captured["skills"] = options.skills
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=0, session_id="x", total_cost_usd=0.0,
        )

    monkeypatch.setattr(sdk_runner, "query", fake_query)

    case_dir = tmp_path / "out"
    await sdk_runner.run_arm(
        repo_root=tmp_path,
        prompt="hi",
        target_skill="demo",
        arm="without_skill",
        case_id="c", trial=1,
        outputs_dir=case_dir / "outputs",
        transcript_path=case_dir / "transcript.jsonl",
    )
    assert captured["skills"] == ["sibling"]


@pytest.mark.asyncio
async def test_run_arm_rejects_invalid_arm(tmp_path):
    with pytest.raises(ValueError, match="arm must be"):
        await sdk_runner.run_arm(
            repo_root=tmp_path, prompt="x", target_skill="demo", arm="bogus",
            case_id="c", trial=1,
            outputs_dir=tmp_path / "o", transcript_path=tmp_path / "t.jsonl",
        )


def test_total_tokens_handles_missing_usage():
    from claude_agent_sdk import ResultMessage  # noqa: WPS433
    rm = ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
        num_turns=0, session_id="x", usage=None,
    )
    assert sdk_runner._total_tokens(rm) is None
    assert sdk_runner._total_tokens(None) is None
