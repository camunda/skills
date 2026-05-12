"""Tests for the bpmn-lint verifier.

Mocks ``shutil.which`` and ``subprocess.run`` so tests are offline.
"""

from __future__ import annotations

import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verifiers import discover, run_all  # noqa: E402
from verifiers import bpmn_lint as bl  # noqa: E402


@pytest.fixture
def outputs_dir(tmp_path):
    od = tmp_path / "outputs"
    od.mkdir()
    return od


@pytest.fixture
def repo_root(tmp_path):
    return tmp_path


def _verifier(**kw):
    return {"type": "bpmn-lint", **kw}


# --- Skip paths -------------------------------------------------------------


def test_skips_when_c8_missing(outputs_dir, repo_root):
    with patch.object(bl.shutil, "which", return_value=None):
        r = bl.run(_verifier(), {"id": "x"}, outputs_dir, repo_root)
    assert r.skipped and r.skip_reason == "no-cli"


def test_skips_when_answer_file_missing(outputs_dir, repo_root):
    with patch.object(bl.shutil, "which", return_value="/usr/bin/c8"):
        r = bl.run(_verifier(), {"id": "x"}, outputs_dir, repo_root)
    assert r.skipped and r.skip_reason == "no-output-file"


def test_skips_when_answer_file_empty(outputs_dir, repo_root):
    (outputs_dir / "process.bpmn").write_text("")
    with patch.object(bl.shutil, "which", return_value="/usr/bin/c8"):
        r = bl.run(_verifier(), {"id": "x"}, outputs_dir, repo_root)
    assert r.skipped and r.skip_reason == "no-output-file"


def test_respects_answer_file_override(outputs_dir, repo_root):
    (outputs_dir / "approval.bpmn").write_text("<bpmn:definitions/>")
    fake = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    captured: dict = {}
    def capture(cmd, **kw):
        captured["cmd"] = cmd
        return fake
    with patch.object(bl.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(bl.subprocess, "run", side_effect=capture):
        r = bl.run(
            _verifier(answer_file="approval.bpmn"),
            {"id": "x"}, outputs_dir, repo_root,
        )
    assert r.passed
    assert "approval.bpmn" in captured["cmd"][3]


# --- Pass + fail paths ------------------------------------------------------


def test_clean_lint_passes(outputs_dir, repo_root):
    (outputs_dir / "process.bpmn").write_text("<bpmn:definitions/>")
    fake = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch.object(bl.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(bl.subprocess, "run", return_value=fake):
        r = bl.run(_verifier(), {"id": "x"}, outputs_dir, repo_root)
    assert r.passed
    assert "lint clean" in r.message


def test_lint_violations_fail_with_summary(outputs_dir, repo_root):
    (outputs_dir / "process.bpmn").write_text("<bpmn:definitions/>")
    stdout = (
        "/tmp/process.bpmn\n"
        "   Process_1   error  Process is missing end event   end-event-required\n"
        "   StartEvent_1   error  Element is not connected     no-disconnected\n"
        "\n"
        "✖ 2 problems (2 errors, 0 warnings)"
    )
    fake = CompletedProcess(args=[], returncode=1, stdout=stdout, stderr="")
    with patch.object(bl.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(bl.subprocess, "run", return_value=fake):
        r = bl.run(_verifier(), {"id": "x"}, outputs_dir, repo_root)
    assert not r.passed
    assert not r.skipped
    assert "2 problems" in r.message
    assert "report" in r.details
    assert "end-event-required" in r.details["report"]


def test_parse_failure_summarizes_first_line(outputs_dir, repo_root):
    (outputs_dir / "process.bpmn").write_text("<not-valid/>")
    fake = CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr="✗ Failed to bpmn lint: Failed to parse BPMN: failed to parse document as <bpmn:Definitions>",
    )
    with patch.object(bl.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(bl.subprocess, "run", return_value=fake):
        r = bl.run(_verifier(), {"id": "x"}, outputs_dir, repo_root)
    assert not r.passed
    assert "Failed to bpmn lint" in r.message
    assert "Failed to parse BPMN" in r.message


# --- CLI invocation -------------------------------------------------------


def test_quiet_flag_is_used(outputs_dir, repo_root):
    """--quiet is what makes the CLI exit-code reliable; never drop it."""
    (outputs_dir / "process.bpmn").write_text("<bpmn:definitions/>")
    captured: dict = {}
    def capture(cmd, **kw):
        captured["cmd"] = cmd
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    with patch.object(bl.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(bl.subprocess, "run", side_effect=capture):
        bl.run(_verifier(), {"id": "x"}, outputs_dir, repo_root)
    assert "--quiet" in captured["cmd"]


# --- Registry / dispatch ---------------------------------------------------


def test_bpmn_lint_registered():
    registry = discover()
    assert "bpmn-lint" in registry


def test_run_all_dispatches_bpmn_lint(outputs_dir, repo_root):
    (outputs_dir / "process.bpmn").write_text("<bpmn:definitions/>")
    case = {"id": "demo", "verifiers": [{"type": "bpmn-lint"}]}
    fake = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch.object(bl.shutil, "which", return_value="/usr/bin/c8"), \
         patch.object(bl.subprocess, "run", return_value=fake):
        results = run_all(case, outputs_dir, repo_root)
    assert len(results) == 1
    assert results[0].type == "bpmn-lint"
    assert results[0].passed is True
