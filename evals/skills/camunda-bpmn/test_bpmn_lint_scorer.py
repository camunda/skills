from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from scorers import bpmn_lint

PATH = "/workspace/process.bpmn"
WITH_CAMUNDA = {
    "extends": ["bpmnlint:recommended", "plugin:camunda-compat/camunda-cloud-8-8"]
}
WITHOUT_CAMUNDA = {"extends": ["bpmnlint:recommended"]}
CLEAN = {"issues": [], "errorCount": 0, "warningCount": 0}
ONE_WARNING = {
    "issues": [
        {
            "rule": "superfluous-gateway",
            "elementId": "Gateway_1",
            "message": "Gateway is superfluous. It only has one source and target.",
            "category": "warning",
        }
    ],
    "errorCount": 0,
    "warningCount": 1,
}
ONE_ERROR = {
    "issues": [
        {
            "rule": "label-required",
            "elementId": "EndEvent_1",
            "message": "Element is missing label/name",
            "category": "error",
        }
    ],
    "errorCount": 1,
    "warningCount": 0,
}


def _result(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        success=returncode == 0, returncode=returncode, stdout=stdout, stderr=stderr
    )


class FakeSandbox:
    """Answers like c8ctl: exit 1 only on errors, ``--json`` on stdout.

    ``workspace_rc`` stands in for a ``.bpmnlintrc`` in the default working
    directory: any c8ctl call not run from ``/`` sees its relaxed results.
    ``ignores_dry_run`` mimics c8ctl < 3.1.0, which lints for real on ``--dry-run``.
    """

    def __init__(
        self,
        files: dict[str, tuple[dict, dict | str]],
        workspace_rc: tuple[dict, dict] | None = None,
        ignores_dry_run: bool = False,
    ) -> None:
        self.files = files
        self.workspace_rc = workspace_rc
        self.ignores_dry_run = ignores_dry_run

    async def exec(self, cmd: list[str], cwd: str | None = None, **_: object):
        if cmd[0] == "find":
            return _result(0, "\n".join(self.files))
        dry_run, lint = self.files[cmd[-1]]
        if self.workspace_rc and cwd != "/":
            dry_run, lint = self.workspace_rc
        if "--dry-run" in cmd and not self.ignores_dry_run:
            return _result(0, json.dumps({"dryRun": True, "config": dry_run}))
        if isinstance(lint, str):
            return _result(1, "", lint)
        report = json.dumps({"file": cmd[-1], **lint})
        return _result(1 if lint["errorCount"] else 0, report)


def _score(monkeypatch: pytest.MonkeyPatch, sandbox: FakeSandbox):
    monkeypatch.setattr(bpmn_lint, "sandbox", lambda: sandbox)
    return asyncio.run(bpmn_lint.bpmn_lint_clean()(None, None))


def test_clean_file_with_camunda_ruleset_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score(monkeypatch, FakeSandbox({PATH: (WITH_CAMUNDA, CLEAN)}))

    assert score.value == 1.0


def test_errors_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    score = _score(monkeypatch, FakeSandbox({PATH: (WITH_CAMUNDA, ONE_ERROR)}))

    assert score.value == 0.0
    assert "label-required" in score.explanation


def test_warnings_fail_even_though_lint_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score(monkeypatch, FakeSandbox({PATH: (WITH_CAMUNDA, ONE_WARNING)}))

    assert score.value == 0.0
    assert "1 warning" in score.explanation


def test_missing_execution_platform_version_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = _score(monkeypatch, FakeSandbox({PATH: (WITHOUT_CAMUNDA, CLEAN)}))

    assert score.value == 0.0
    assert "executionPlatformVersion" in score.explanation


def test_workspace_bpmnlintrc_cannot_relax_the_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = FakeSandbox(
        {PATH: (WITH_CAMUNDA, ONE_ERROR)}, workspace_rc=(WITH_CAMUNDA, CLEAN)
    )

    assert _score(monkeypatch, sandbox).value == 0.0


def test_c8ctl_that_ignores_dry_run_is_reported_as_too_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = FakeSandbox({PATH: (WITH_CAMUNDA, CLEAN)}, ignores_dry_run=True)

    score = _score(monkeypatch, sandbox)

    assert score.value == 0.0
    assert "3.1.0" in score.explanation
    assert "executionPlatformVersion" not in score.explanation


def test_unparseable_lint_output_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox = FakeSandbox(
        {PATH: (WITH_CAMUNDA, "Failed to parse BPMN: unexpected end")}
    )

    assert _score(monkeypatch, sandbox).value == 0.0


def test_names_the_failing_file_among_several(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = "/workspace/sub/bad.bpmn"
    sandbox = FakeSandbox(
        {PATH: (WITH_CAMUNDA, CLEAN), bad: (WITH_CAMUNDA, ONE_WARNING)}
    )

    score = _score(monkeypatch, sandbox)

    assert score.value == 0.0
    assert score.explanation.startswith("1/2 BPMN file(s) failed lint")
    assert bad in score.explanation
