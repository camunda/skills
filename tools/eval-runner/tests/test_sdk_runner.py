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
        captured["cwd"] = options.cwd
        captured["add_dirs"] = list(options.add_dirs)
        captured["env"] = options.env
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
    # cwd is an isolated /tmp/eval-trial-* dir, not the repo or the trial
    # dir under it. This confines stray absolute-path writes to /tmp.
    assert "/tmp/" in captured["cwd"] or "eval-trial-" in captured["cwd"]
    assert str(tmp_path) not in captured["cwd"], (
        "isolated workdir must be outside the repo root"
    )
    # add_dirs scopes the agent to that same isolated workdir.
    assert captured["add_dirs"] == [captured["cwd"]]
    # IS_SANDBOX=1 so claude -p runs under root in CI sandboxes.
    assert captured["env"] == {"IS_SANDBOX": "1"}


def test_isolated_workdir_creates_skills_bridge(tmp_path):
    skills = tmp_path / "skills"
    for name in ("alpha", "beta"):
        d = skills / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n")

    with sdk_runner.isolated_workdir(tmp_path, ["alpha", "beta"]) as workdir:
        bridge = workdir / ".claude" / "skills"
        assert (bridge / "alpha").is_symlink()
        assert (bridge / "beta").is_symlink()
        assert (bridge / "alpha").resolve() == (skills / "alpha").resolve()
        # Outputs dir pre-created so the agent doesn't need to mkdir.
        assert (workdir / "outputs").is_dir()
        # workdir is in /tmp, not under the repo.
        assert str(tmp_path) not in str(workdir)


def test_isolated_workdir_filters_to_allowed(tmp_path):
    for name in ("alpha", "beta", "gamma"):
        d = tmp_path / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n")
    with sdk_runner.isolated_workdir(tmp_path, ["alpha"]) as workdir:
        bridge = workdir / ".claude" / "skills"
        assert (bridge / "alpha").is_symlink()
        assert not (bridge / "beta").exists()
        assert not (bridge / "gamma").exists()


def test_isolated_workdir_bridges_examples_when_present(tmp_path):
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "demo.bpmn").write_text("<bpmn:definitions/>")
    (tmp_path / "skills" / "alpha").mkdir(parents=True)
    (tmp_path / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: x\n---\n")
    with sdk_runner.isolated_workdir(tmp_path, ["alpha"]) as workdir:
        assert (workdir / "examples").is_symlink()
        # Eval prompts reference paths like "examples/foo.bpmn" relative to cwd.
        assert (workdir / "examples" / "demo.bpmn").read_text() == "<bpmn:definitions/>"


def test_isolated_workdir_skips_examples_when_absent(tmp_path):
    (tmp_path / "skills" / "alpha").mkdir(parents=True)
    (tmp_path / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: x\n---\n")
    with sdk_runner.isolated_workdir(tmp_path, ["alpha"]) as workdir:
        # No examples/ in repo -> none bridged. Doesn't crash.
        assert not (workdir / "examples").exists()


def test_copy_outputs_round_trip(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "answer.feel").write_text("1 + 1")
    (src / "subdir").mkdir()
    (src / "subdir" / "nested.txt").write_text("hi")
    sdk_runner._copy_outputs(src, dst)
    assert (dst / "answer.feel").read_text() == "1 + 1"
    assert (dst / "subdir" / "nested.txt").read_text() == "hi"


def test_copy_outputs_handles_missing_src(tmp_path):
    dst = tmp_path / "dst"
    sdk_runner._copy_outputs(tmp_path / "does-not-exist", dst)
    assert not dst.exists()


# --- Leak detection --------------------------------------------------------


def test_snapshot_returns_empty_for_absent_dirs(tmp_path):
    snap = sdk_runner.snapshot_leak_state((tmp_path / "absent",))
    assert snap == {tmp_path / "absent": set()}


def test_check_leaks_flags_new_files(tmp_path):
    leaky = tmp_path / "leaky"
    snap = sdk_runner.snapshot_leak_state((leaky,))
    leaky.mkdir()
    (leaky / "answer.feel").write_text("1+1")
    report = sdk_runner.check_leaks(snap, (leaky,))
    assert leaky in report.new_paths
    assert not report.empty
    assert leaky not in report.paths   # listed under new_paths, not paths


def test_check_leaks_silent_when_unchanged(tmp_path):
    leaky = tmp_path / "leaky"
    leaky.mkdir()
    (leaky / "old.txt").write_text("pre-existing")
    snap = sdk_runner.snapshot_leak_state((leaky,))
    # Nothing happens during the (mock) trial.
    report = sdk_runner.check_leaks(snap, (leaky,))
    assert report.empty is False  # pre-existing content still surfaces
    assert leaky in report.paths   # but as cruft, not new
    assert leaky not in report.new_paths


def test_check_leaks_empty_when_dirs_clean(tmp_path):
    clean = tmp_path / "clean"
    snap = sdk_runner.snapshot_leak_state((clean,))
    report = sdk_runner.check_leaks(snap, (clean,))
    assert report.empty
    assert report.to_dict() == {"paths": [], "new_paths": []}


def test_default_leak_paths_include_home_outputs(monkeypatch):
    monkeypatch.setenv("HOME", "/some/home")
    paths = sdk_runner._default_leak_scan_paths()
    assert Path("/some/home/outputs") in paths
    # Common alternates also included.
    assert Path("/root/outputs") in paths
    assert Path("/tmp/outputs") in paths


def test_default_leak_paths_dedupe(monkeypatch):
    """If $HOME is /root, /root/outputs shouldn't appear twice."""
    monkeypatch.setenv("HOME", "/root")
    paths = sdk_runner._default_leak_scan_paths()
    # The literal Path objects may differ but their resolutions should not.
    resolved = [p.resolve(strict=False) for p in paths]
    assert len(resolved) == len(set(resolved))


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
