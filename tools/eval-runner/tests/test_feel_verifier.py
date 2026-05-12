"""Tests for the feel-evaluate verifier.

We mock both ``shutil.which`` (so the test passes whether or not ``c8`` is on
the developer's PATH) and ``subprocess.run`` (so we don't actually call the
cluster engine). What we DO verify: skip semantics (no CLI, no output file,
unreachable cluster), the value-comparison rules, and the registry dispatch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verifiers import Result, discover, run_all  # noqa: E402
from verifiers import feel_evaluate as fe  # noqa: E402


@pytest.fixture
def outputs_dir(tmp_path):
    od = tmp_path / "outputs"
    od.mkdir()
    return od


@pytest.fixture
def repo_root(tmp_path):
    return tmp_path


def _verifier(context=None, expected=None, **kw):
    v = {"type": "feel-evaluate"}
    if context is not None:
        v["context"] = context
    if expected is not None:
        v["expected"] = expected
    v.update(kw)
    return v


def _case_with(verifiers_list):
    return {"id": "demo", "prompt": "x", "verifiers": verifiers_list}


# --- Skip paths -------------------------------------------------------------


def test_skips_when_c8_missing(outputs_dir, repo_root):
    with patch.object(fe.shutil, "which", return_value=None):
        r = fe.run(_verifier(expected=1), {"id": "x"}, outputs_dir, repo_root)
    assert r.skipped and r.skip_reason == "no-cli"
    assert r.passed is False


def test_skips_when_answer_file_missing(outputs_dir, repo_root):
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"):
        r = fe.run(_verifier(expected=1), {"id": "x"}, outputs_dir, repo_root)
    assert r.skipped and r.skip_reason == "no-output-file"


def test_skips_when_cluster_unreachable(outputs_dir, repo_root):
    (outputs_dir / "answer.feel").write_text("1 + 1")
    fake_proc = CompletedProcess(
        args=[], returncode=1, stdout="",
        stderr="error: ECONNREFUSED 127.0.0.1:26500",
    )
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", return_value=fake_proc):
        r = fe.run(_verifier(expected=2), {"id": "x"}, outputs_dir, repo_root)
    assert r.skipped and r.skip_reason == "no-cluster"


def test_no_active_profile_treated_as_skip(outputs_dir, repo_root):
    (outputs_dir / "answer.feel").write_text("1")
    fake_proc = CompletedProcess(
        args=[], returncode=1, stdout="",
        stderr="No active profile configured. Run `c8 add profile` first.",
    )
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", return_value=fake_proc):
        r = fe.run(_verifier(expected=1), {"id": "x"}, outputs_dir, repo_root)
    assert r.skipped and r.skip_reason == "no-cluster"


# --- Parse failures (real failures, not skips) -----------------------------


def test_parse_failure_reports_stderr(outputs_dir, repo_root):
    (outputs_dir / "answer.feel").write_text("1 + + 2")
    fake_proc = CompletedProcess(
        args=[], returncode=2, stdout="",
        stderr="Parsing error at line 1, column 5",
    )
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", return_value=fake_proc):
        r = fe.run(_verifier(expected=3), {"id": "x"}, outputs_dir, repo_root)
    assert not r.skipped
    assert r.passed is False
    assert "did not parse" in r.message
    assert "Parsing error" in r.details["stderr"]


# --- Successful evaluation, value comparisons -----------------------------


@pytest.mark.parametrize(
    "stdout,expected,want_pass",
    [
        ("1275", 1275, True),
        ("1275", 1276, False),
        ("1275.0", 1275, True),
        ("1275.5", 1275, False),       # int target, fractional actual
        ("0.85", 0.85, True),
        ("0.85", 0.85000001, True),    # within epsilon
        ("true", True, True),
        ("false", False, True),
        ("true", False, False),
        ("null", None, True),
        ('"foo"', "foo", True),
        ("foo", "foo", True),          # FEEL might or might not quote; accept both
        ("[1,2,3]", [1, 2, 3], True),
        ("[1,2]", [1, 2, 3], False),
        ('{"a":1}', {"a": 1}, True),
    ],
)
def test_compare_table(stdout, expected, want_pass, outputs_dir, repo_root):
    (outputs_dir / "answer.feel").write_text("placeholder")
    fake_proc = CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", return_value=fake_proc):
        r = fe.run(_verifier(expected=expected), {"id": "x"}, outputs_dir, repo_root)
    assert r.skipped is False
    assert r.passed is want_pass, f"expected {want_pass}, got {r.passed}: {r.message}"


def test_compare_strips_trailing_warning_block(outputs_dir, repo_root):
    """c8 feel evaluate appends a ⚠ warning block after the JSON result on stdout
    in some scopes (e.g. unresolved-name inside a filter closure). The trailer
    must not break the json.loads on the list/dict result."""
    (outputs_dir / "answer.feel").write_text(
        'employees[department = "Engineering" and salary > 80000].name'
    )
    stdout = (
        '[\n  "Alice",\n  "Dan"\n]\n\n'
        "⚠ 1 warning:\n  No variable found with name 'department'"
    )
    fake_proc = CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", return_value=fake_proc):
        r = fe.run(
            _verifier(expected=["Alice", "Dan"]),
            {"id": "x"}, outputs_dir, repo_root,
        )
    assert r.passed, r.message


def test_compare_records_actual_in_details(outputs_dir, repo_root):
    (outputs_dir / "answer.feel").write_text("1+1")
    fake_proc = CompletedProcess(args=[], returncode=0, stdout="2", stderr="")
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", return_value=fake_proc):
        r = fe.run(
            _verifier(context={"x": 1}, expected=2),
            {"id": "x"}, outputs_dir, repo_root,
        )
    assert r.passed
    assert r.details["expression"] == "1+1"
    assert r.details["context"] == {"x": 1}
    assert r.details["actual_stdout"] == "2"


def test_subprocess_command_omits_engine_local_by_default(outputs_dir, repo_root, monkeypatch):
    """Engine policy default: never invoke --engine local."""
    (outputs_dir / "answer.feel").write_text("1+1")
    monkeypatch.delenv("EVAL_FEEL_ENGINE", raising=False)
    captured = {}
    def capture(cmd, **kw):
        captured["cmd"] = cmd
        return CompletedProcess(args=cmd, returncode=0, stdout="2", stderr="")
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", side_effect=capture):
        r = fe.run(
            _verifier(context={"x": 1}, expected=2),
            {"id": "x"}, outputs_dir, repo_root,
        )
    assert "--engine" not in captured["cmd"], captured["cmd"]
    assert "local" not in captured["cmd"], captured["cmd"]
    assert r.details["engine"] == "cluster"


def test_eval_feel_engine_local_passes_flag(outputs_dir, repo_root, monkeypatch):
    """EVAL_FEEL_ENGINE=local opt-in adds --engine local to the command."""
    (outputs_dir / "answer.feel").write_text("1+1")
    monkeypatch.setenv("EVAL_FEEL_ENGINE", "local")
    captured = {}
    def capture(cmd, **kw):
        captured["cmd"] = cmd
        return CompletedProcess(args=cmd, returncode=0, stdout="2", stderr="")
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", side_effect=capture):
        r = fe.run(
            _verifier(context={"x": 1}, expected=2),
            {"id": "x"}, outputs_dir, repo_root,
        )
    assert captured["cmd"][-2:] == ["--engine", "local"]
    assert r.details["engine"] == "local"


def test_eval_feel_engine_cluster_explicit_no_flag(outputs_dir, repo_root, monkeypatch):
    """EVAL_FEEL_ENGINE=cluster is equivalent to default; no --engine flag."""
    (outputs_dir / "answer.feel").write_text("1+1")
    monkeypatch.setenv("EVAL_FEEL_ENGINE", "cluster")
    captured = {}
    def capture(cmd, **kw):
        captured["cmd"] = cmd
        return CompletedProcess(args=cmd, returncode=0, stdout="2", stderr="")
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", side_effect=capture):
        fe.run(
            _verifier(context={"x": 1}, expected=2),
            {"id": "x"}, outputs_dir, repo_root,
        )
    assert "--engine" not in captured["cmd"]


def test_eval_feel_engine_unrecognized_value_fails_loudly(outputs_dir, repo_root, monkeypatch):
    """Typos like EVAL_FEEL_ENGINE=loca should not silently fall back to cluster."""
    (outputs_dir / "answer.feel").write_text("1+1")
    monkeypatch.setenv("EVAL_FEEL_ENGINE", "loca")
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"):
        r = fe.run(
            _verifier(context={"x": 1}, expected=2),
            {"id": "x"}, outputs_dir, repo_root,
        )
    assert r.passed is False
    assert "unrecognized" in r.message.lower()


# --- Registry / dispatch ---------------------------------------------------


def test_feel_evaluate_registered():
    registry = discover()
    assert "feel-evaluate" in registry


def test_run_all_dispatches_each_verifier(outputs_dir, repo_root):
    (outputs_dir / "answer.feel").write_text("orderAmount * 0.85")
    case = _case_with([
        {"type": "feel-evaluate", "context": {"orderAmount": 1500}, "expected": 1275},
        {"type": "feel-evaluate", "context": {"orderAmount": 100}, "expected": 85},
    ])
    fake_proc = CompletedProcess(args=[], returncode=0, stdout="1275", stderr="")
    with patch.object(fe.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(fe.subprocess, "run", return_value=fake_proc):
        results = run_all(case, outputs_dir, repo_root)
    assert len(results) == 2
    assert results[0].passed is True
    # Second one fails because we always return 1275 from the fake.
    assert results[1].passed is False


def test_unknown_verifier_type_fails_loudly():
    case = _case_with([{"type": "made-up-verifier"}])
    results = run_all(case, Path("/tmp"), Path("/tmp"))
    assert len(results) == 1
    assert results[0].passed is False
    assert "unknown verifier type" in results[0].message


def test_verifier_exception_caught(outputs_dir, repo_root):
    case = _case_with([{"type": "feel-evaluate"}])
    with patch.object(fe.shutil, "which", side_effect=RuntimeError("boom")):
        results = run_all(case, outputs_dir, repo_root)
    assert results[0].passed is False
    assert "verifier raised" in results[0].message


def test_skipped_verifier_does_not_block_trial(outputs_dir, repo_root):
    """skipped=True with passed=False is the documented "couldn't check" state.

    The orchestrator in quality_eval treats skipped verifiers as not-blocking;
    this test pins that property at the Result level.
    """
    r = Result(type="feel-evaluate", passed=False, skipped=True,
               skip_reason="no-cli", message="no c8")
    assert r.skipped is True
    assert r.passed is False
