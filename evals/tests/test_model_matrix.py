"""Unit tests for the model-comparison pieces: lint-attempt extraction, the
``--models`` matrix specs, and the ``evals-model-matrix`` aggregation."""

from __future__ import annotations

import json

from types import SimpleNamespace as NS

from core.lint_attempts import lint_attempts
from core.registry import EvalTarget
from scripts.build_matrix import build_model_specs, parse_models
from scripts.model_matrix import aggregate, collect_runs, render_markdown

_ids = iter(range(10_000))


def _call(command: str | None = None, **arguments):
    if command is not None:
        arguments = {"action": "type_submit", "input": command, **arguments}
    call_id = f"c{next(_ids)}"
    return NS(id=call_id, arguments=arguments)


def _turn(call, output: str) -> list:
    return [
        NS(role="assistant", tool_calls=[call], text=""),
        NS(role="tool", tool_call_id=call.id, text=output),
    ]


def _transcript(*turns) -> list:
    msgs = []
    for call, output in turns:
        msgs += _turn(call, output)
    return msgs


BPMN_DIRTY = '{"errorCount": 1, "warningCount": 2, "issues": []}'
BPMN_CLEAN = '{"errorCount": 0, "warningCount": 0, "issues": []}'


class TestLintAttempts:
    def test_counts_runs_until_first_clean(self):
        msgs = _transcript(
            (_call("c8ctl bpmn lint --json process.bpmn"), BPMN_DIRTY),
            (_call("sed -i 's/a/b/' process.bpmn"), ""),
            (_call("c8ctl bpmn lint --json process.bpmn"), BPMN_CLEAN),
            (_call("c8ctl bpmn lint --json process.bpmn"), BPMN_CLEAN),
        )
        res = lint_attempts(msgs)
        assert res.attempts_to_clean == 2
        assert res.reached_clean
        assert res.by_validator() == {"bpmn": 3}

    def test_never_clean_counts_all_runs(self):
        msgs = _transcript(
            (_call("c8ctl bpmn lint --json p.bpmn"), BPMN_DIRTY),
            (_call("c8ctl bpmn lint --json p.bpmn"), BPMN_DIRTY),
        )
        res = lint_attempts(msgs)
        assert res.attempts_to_clean == 2
        assert not res.reached_clean

    def test_dry_run_and_unrelated_commands_ignored(self):
        msgs = _transcript(
            (_call("c8ctl --dry-run bpmn lint --json p.bpmn"), '{"dryRun": true}'),
            (_call('echo \'{"extends": "dmnlint:recommended"}\' > .dmnlintrc'), ""),
            (_call("cat > validate-form.cjs << 'EOF'\n...\nEOF"), ""),
            (_call("ls /workspace"), "p.bpmn"),
        )
        res = lint_attempts(msgs)
        assert not res.applicable
        assert res.attempts_to_clean is None

    def test_read_output_folds_into_previous_run(self):
        msgs = _transcript(
            (_call("c8ctl bpmn lint --json p.bpmn"), ""),
            (_call(action="read"), BPMN_CLEAN),
        )
        assert lint_attempts(msgs).attempts_to_clean == 1

    def test_read_after_other_command_not_folded(self):
        msgs = _transcript(
            (_call("c8ctl bpmn lint --json p.bpmn"), BPMN_DIRTY),
            (_call("cat p.bpmn"), ""),
            (_call(action="read"), BPMN_CLEAN),
        )
        assert not lint_attempts(msgs).reached_clean

    def test_dmn_and_form_validators(self):
        msgs = _transcript(
            (
                _call("npx --yes dmnlint decision.dmn"),
                "decision.dmn\n  D1  error  Element is missing label/name  label-required\n\n"
                "✖ 1 problem (1 error, 0 warnings)",
            ),
            (_call("npx --yes dmnlint decision.dmn"), ""),
            (_call("node validate-form.cjs review.form"), '[{"keyword": "required"}]'),
            (_call("node validate-form.cjs review.form"), "Valid ✓"),
        )
        res = lint_attempts(msgs)
        assert res.by_validator() == {"dmn": 2, "form": 2}
        assert [r.verdict for r in res.runs] == ["dirty", "clean", "dirty", "clean"]
        assert res.attempts_to_clean == 2

    def test_inline_form_schema_validation(self):
        # Shape observed from claude-sonnet-5.5 under Copilot CLI.
        cmd = (
            "cd /tmp && npm i ajv @bpmn-io/form-json-schema@1.18.0 >/dev/null 2>&1; "
            "node -e \"const s=require('@bpmn-io/form-json-schema'); console.log(v(d))\""
        )
        msgs = _transcript(
            (
                NS(id="f1", arguments={"command": cmd}),
                "false\n<shellId: 0 completed with exit code 0>",
            ),
            (
                NS(id="f2", arguments={"command": cmd}),
                "true\n<shellId: 1 completed with exit code 0>",
            ),
        )
        res = lint_attempts(msgs)
        assert res.by_validator() == {"form": 2}
        assert res.attempts_to_clean == 2 and res.reached_clean

    def test_bash_tool_command_key(self):
        call = NS(id="b1", arguments={"command": "c8ctl bpmn lint --json p.bpmn"})
        assert lint_attempts(_turn(call, BPMN_CLEAN)).attempts_to_clean == 1


class TestCopilotReadBashContinuations:
    """Copilot's bash returns long-running output later via read_bash."""

    def _bash(self, call_id, command, output, **extra):
        return NS(
            id=call_id, function="bash", arguments={"command": command, **extra}
        ), output

    def _read(self, call_id, shell_id, output):
        return NS(
            id=call_id,
            function="read_bash",
            arguments={"shellId": shell_id, "delay": 10},
        ), output

    def test_delayed_clean_result_via_reported_shell_id(self):
        msgs = _transcript(
            self._bash(
                "c1", "npx --yes dmnlint d.dmn", "<shellId: 4 is still running>"
            ),
            self._bash("c2", "ls", "d.dmn\n<shellId: 5 completed with exit code 0>"),
            self._read("c3", "4", "<shellId: 4 completed with exit code 0>"),
        )
        [run] = lint_attempts(msgs).runs
        assert run.verdict == "clean"

    def test_delayed_dirty_result_via_explicit_shell_id(self):
        msgs = _transcript(
            self._bash("c1", "c8ctl bpmn lint --json p.bpmn", "", shellId="lint"),
            self._read("c2", "lint", BPMN_DIRTY),
        )
        assert lint_attempts(msgs).runs[0].verdict == "dirty"

    def test_read_of_unrelated_shell_is_ignored(self):
        msgs = _transcript(
            self._bash(
                "c1", "npx --yes dmnlint d.dmn", "<shellId: 4 is still running>"
            ),
            self._read("c2", "9", "<shellId: 9 completed with exit code 0>"),
        )
        assert lint_attempts(msgs).runs[0].verdict == "unknown"


class TestLintMatchingReviewCases:
    """Regression cases from the PR #130 review."""

    HELPER = (
        "cat > validate-form.cjs << 'EOF'\n"
        "const file = process.argv[2];\n"
        "if (!file) { console.error('Usage: node validate-form.cjs <path>'); "
        "process.exit(1); }\n"
        "EOF"
    )

    def _runs(self, command, output="", call_id=None):
        call = NS(id=call_id or f"r{next(_ids)}", arguments={"command": command})
        return lint_attempts(_turn(call, output)).runs

    def test_helper_heredoc_is_not_a_run(self):
        assert self._runs(self.HELPER) == []

    def test_heredoc_then_real_run_counts_once(self):
        runs = self._runs(self.HELPER + "\nnode validate-form.cjs a.form", "Valid ✓")
        assert [(r.validators, r.verdict) for r in runs] == [(("form",), "clean")]

    def test_quoted_mentions_are_not_runs(self):
        assert self._runs('echo "next: c8ctl bpmn lint --json p.bpmn"') == []

    def test_dry_run_does_not_hide_real_lint_in_same_call(self):
        cmd = "c8ctl --dry-run bpmn lint --json p.bpmn && c8ctl bpmn lint --json p.bpmn"
        runs = self._runs(cmd, '{"dryRun": true}\n' + BPMN_DIRTY)
        assert [(r.validators, r.verdict) for r in runs] == [(("bpmn",), "dirty")]

    def test_dmn_failures_and_missing_results_are_unknown(self):
        cmd = "npx --yes dmnlint d.dmn"
        assert (
            self._runs(cmd, "sh: 1: dmnlint: Permission denied")[0].verdict == "unknown"
        )
        assert self._runs(cmd, "some unexpected banner")[0].verdict == "unknown"
        # No tool result at all (the call never returned).
        msgs = [
            NS(role="assistant", tool_calls=[NS(id="x1", arguments={"command": cmd})])
        ]
        assert lint_attempts(msgs).runs[0].verdict == "unknown"

    def test_dmn_exit_code_evidence(self):
        cmd = "npx --yes dmnlint d.dmn"
        assert (
            self._runs(cmd, "<shellId: 0 completed with exit code 0>")[0].verdict
            == "clean"
        )
        assert (
            self._runs(cmd, "<shellId: 0 completed with exit code 1>")[0].verdict
            == "dirty"
        )
        assert (
            self._runs(cmd, "<shellId: 0 completed with exit code 2>")[0].verdict
            == "unknown"
        )

    def test_package_install_is_not_a_run(self):
        ok = "<shellId: 0 completed with exit code 0>"
        assert self._runs("npm install --no-save dmnlint", ok) == []
        assert self._runs("npm i -g @camunda8/cli && echo done", ok) == []
        assert self._runs("pnpm add dmnlint", ok) == []

    def test_wrapped_invocations_are_runs(self):
        for cmd in (
            "npx --yes dmnlint d.dmn",
            "npx -p dmnlint dmnlint d.dmn",
            "npm exec -- dmnlint d.dmn",
            "CI=1 ./node_modules/.bin/dmnlint d.dmn",
            "cd /workspace && (dmnlint d.dmn)",
        ):
            assert [r.validators for r in self._runs(cmd, "")] == [("dmn",)], cmd
        runs = self._runs("npx @camunda8/cli bpmn lint --json p.bpmn", BPMN_CLEAN)
        assert [r.validators for r in runs] == [("bpmn",)]

    def test_documented_dmn_directory_pipeline(self):
        # Verbatim from skills/camunda-dmn/references/dmnlint.md.
        cmd = (
            r"find path/to/dir -type d \( -name .git -o -name node_modules -o -name "
            r"target -o -name build -o -name .gradle -o -name .mvn -o -name .idea "
            r"-o -name .settings -o -name .snapshots \) -prune -o -type f -name "
            r"'*.dmn' -print0 | xargs -0 -n1 npx --yes dmnlint"
        )
        [run] = self._runs(cmd, "<shellId: 0 completed with exit code 0>")
        assert (run.validators, run.verdict) == (("dmn",), "clean")

    def test_other_runner_wrappers(self):
        for cmd in (
            "ls *.dmn | xargs -n 1 -P 4 dmnlint",
            "find . -name '*.dmn' -exec npx --yes dmnlint {} \\;",
            "find . -name '*.form' -execdir node validate-form.cjs {} +",
        ):
            assert len(self._runs(cmd, "")) == 1, cmd
        # xargs feeding something else isn't a run.
        assert self._runs("ls | xargs -n1 cat", "") == []

    def test_every_validator_in_a_call_must_be_clean(self):
        cmd = "c8ctl bpmn lint --json p.bpmn; node validate-form.cjs p.form"
        dirty_form = BPMN_CLEAN + '\n[{"instancePath": "", "keyword": "required"}]'
        [run] = self._runs(cmd, dirty_form)
        assert run.validators == ("bpmn", "form") and run.verdict == "dirty"
        [run] = self._runs(cmd, BPMN_CLEAN + "\nValid ✓")
        assert run.verdict == "clean"
        msgs = _turn(NS(id="m1", arguments={"command": cmd}), dirty_form)
        assert lint_attempts(msgs).by_validator() == {"bpmn": 1, "form": 1}

    def test_form_failure_beats_earlier_success(self):
        out = 'Valid ✓\n[{"instancePath": "/components/0", "keyword": "required"}]'
        cmd = "node validate-form.cjs a.form; node validate-form.cjs b.form"
        assert self._runs(cmd, out)[0].verdict == "dirty"


class TestModelSpecs:
    def _targets(self):
        return [
            EvalTarget(
                id="skill:camunda-bpmn",
                kind="outcome",
                skills=["camunda-bpmn"],
                path="skills/camunda-bpmn/outcomes.py",
            ),
            EvalTarget(
                id="trigger:camunda-bpmn",
                kind="trigger",
                skills=["camunda-bpmn"],
                path="skills/camunda-bpmn/triggers.py",
                task="trigger_eval",
            ),
        ]

    def test_parse_models(self):
        assert parse_models(" a/x, b/y ,a/x\nc/z ") == ["a/x", "b/y", "c/z"]
        assert parse_models("") == []

    def test_outcome_x_model_with_epochs(self):
        specs = build_model_specs(
            self._targets(), ["anthropic/claude-a", "anthropic/claude-b"], epochs=3
        )
        assert [s["model"] for s in specs] == [
            "anthropic/claude-a",
            "anthropic/claude-b",
        ]
        assert all(s["arm"] == "with_skill" for s in specs)
        assert all("-T agent=copilot_cli" in s["targs"] for s in specs)
        assert all("--epochs 3" in s["limit"] for s in specs)
        assert specs[0]["slug"] == "skill-camunda-bpmn-anthropic-claude-a"
        assert len({s["slug"] for s in specs}) == len(specs)


def _sample(sid, epoch, *, passed=True, messages=(), error=None, copilot=None):
    return NS(
        id=sid,
        epoch=epoch,
        error=error,
        total_time=300.0,
        model_usage={},
        store={"copilot": copilot} if copilot is not None else {},
        messages=list(messages),
        scores={
            "gate": NS(value=1.0 if passed else 0.0, metadata={}),
            "assert_skill_loaded": NS(value=0.0, metadata={"gating": False}),
        },
    )


def _copilot(model="claude-sonnet-5.5", credits=2.0, duration=60.0):
    return {
        "requested_model": model,
        "model": model,
        "models_used": [model],
        "ai_credits": credits,
        "premium_requests": 1,
        "tokens": {
            "input": 100,
            "cache_write": 1000,
            "cache_read": 10_000,
            "output": 50,
        },
        "agent_duration_s": duration,
    }


def _log(samples, task="camunda_bpmn", copilot_model="claude-sonnet-5.5"):
    return NS(
        eval=NS(
            model="none/none",
            task=task,
            task_args={"arm": "with_skill", "agent": "copilot_cli"},
            metadata={"copilot_model": copilot_model},
        ),
        samples=samples,
    )


class TestAggregation:
    def test_collect_and_aggregate(self):
        lint_msgs = _transcript(
            (_call("c8ctl bpmn lint --json p.bpmn"), BPMN_DIRTY),
            (_call("c8ctl bpmn lint --json p.bpmn"), BPMN_CLEAN),
        )
        log = _log(
            [
                _sample("a", 1, messages=lint_msgs, copilot=_copilot(credits=2.0)),
                _sample("a", 2, passed=False, copilot=_copilot(credits=4.0)),
                # Errored before Copilot ran: no record, grouped via log metadata.
                _sample("b", 1, error="boom"),
            ]
        )
        runs = collect_runs(log)
        assert [r["passed"] for r in runs] == [True, False, False]
        assert {r["model"] for r in runs} == {"claude-sonnet-5.5"}
        # Agent time, not sample time, when Copilot recorded it.
        assert runs[0]["duration_s"] == 60.0
        assert runs[2]["duration_s"] == 300.0

        [cell] = aggregate(runs)
        assert cell["eval"] == "camunda-bpmn"
        assert (cell["runs"], cell["samples"], cell["passed"], cell["errored"]) == (
            3,
            2,
            1,
            1,
        )
        assert cell["lint"]["applicable_runs"] == 1
        assert cell["lint"]["median_attempts"] == 2
        assert cell["lint"]["clean_rate"] == 1.0
        assert cell["ai_credits"] == {"median": 3.0, "total": 6.0}
        assert cell["premium_requests"]["total"] == 2

        md = render_markdown([cell], ["claude-sonnet-5.5"])
        assert "33% (1/3)" in md
        assert "2 (100% clean)" in md
        assert "3.00 cr" in md

    def test_column_per_model_and_triggers_skipped(self):
        assert collect_runs(_log([_sample("a", 1)], task="trigger_camunda_bpmn")) == []
        runs = collect_runs(_log([_sample("a", 1, copilot=_copilot("gpt-6.1-sol"))]))
        runs += collect_runs(
            _log([_sample("a", 1, copilot=_copilot("gemini-4-argon"))])
        )
        cells = aggregate(runs)
        assert sorted(c["model"] for c in cells) == ["gemini-4-argon", "gpt-6.1-sol"]
        md = render_markdown(cells, ["gpt-6.1-sol", "gemini-4-argon"])
        header = next(line for line in md.splitlines() if line.startswith("| eval"))
        # Columns follow the requested --models order, not alphabetical.
        assert header.index("gpt-6.1-sol") < header.index("gemini-4-argon")


def test_retried_job_keeps_only_newest_log():
    from scripts.model_matrix import select_latest

    old = _log([_sample("a", 1, passed=False, copilot=_copilot())])
    new = _log([_sample("a", 1, passed=True, copilot=_copilot())])
    other = _log(
        [_sample("a", 1, copilot=_copilot("gpt-6.1-sol"))], copilot_model="gpt-6.1-sol"
    )
    kept = select_latest(
        [
            ("logs/2026-10-29T01-00_camunda-bpmn_x.eval", old),
            ("logs/2026-10-29T02-00_camunda-bpmn_y.eval", new),
            ("logs/2026-10-29T01-30_camunda-bpmn_z.eval", other),
        ]
    )
    assert kept == [other, new]
    cells = aggregate([r for log in kept for r in collect_runs(log)])
    sonnet = next(c for c in cells if c["model"] == "claude-sonnet-5.5")
    assert (sonnet["runs"], sonnet["passed"]) == (1, 1)


def test_partial_usage_tokens_are_unknown_not_zero():
    partial = {**_copilot(credits=5.0), "partial": True}
    partial["tokens"] = {f: None for f in partial["tokens"]}
    runs = collect_runs(
        _log(
            [
                _sample("a", 1, copilot=_copilot(credits=1.0)),
                _sample("a", 2, copilot=_copilot(credits=3.0)),
                _sample("a", 3, copilot=partial),
            ]
        )
    )
    [cell] = aggregate(runs)
    # Medians over the two complete runs only (150 I+O each), not dragged to 0.
    assert cell["tokens_median"]["io"] == 150
    assert cell["tokens_median"]["input"] == 100
    assert cell["partial_usage_runs"] == 1
    # Checkpoint credits still count.
    assert cell["ai_credits"]["median"] == 3.0
    md = render_markdown([cell], ["claude-sonnet-5.5"])
    assert "†" in md and "1 run(s) were interrupted" in md


def test_overall_lint_median_is_pooled_across_evals():
    one = _transcript((_call("c8ctl bpmn lint --json p.bpmn"), BPMN_CLEAN))
    nine = _transcript(
        *[(_call("c8ctl bpmn lint --json p.bpmn"), BPMN_DIRTY)] * 8,
        (_call("c8ctl bpmn lint --json p.bpmn"), BPMN_CLEAN),
    )
    runs = collect_runs(
        _log([_sample("a", e, messages=one, copilot=_copilot()) for e in (1, 2, 3)])
    ) + collect_runs(
        _log([_sample("b", 1, messages=nine, copilot=_copilot())], task="camunda_dmn")
    )
    cells = aggregate(runs)
    assert sorted(c["lint"]["median_attempts"] for c in cells) == [1, 9]
    overall = render_markdown(cells, ["claude-sonnet-5.5"]).split("### Pass rate")[0]
    row = next(line for line in overall.splitlines() if line.startswith("| claude"))
    # Pooled runs [1, 1, 1, 9] -> median 1; a median of medians would give 5.
    assert row.split("|")[3].strip() == "1"


def test_errors_are_summarised_and_flagged():
    from scripts.model_matrix import error_summary, model_errors

    err = NS(
        message='RuntimeError(\'copilot exited 1: Error: Model "x" from --model '
        "flag is not available.\\n')"
    )
    assert error_summary(NS(error=err)) == (
        'copilot exited 1: Error: Model "x" from --model flag is not available.'
    )
    assert error_summary(NS(error=None)) is None

    bad = [_sample("a", e, error=err) for e in (1, 2)]
    cells = aggregate(collect_runs(_log(bad)))
    md = render_markdown(cells, ["claude-sonnet-5.5"])
    assert "Every run errored (2/2)" in md
    assert "### Errors" in md and "not available" in md
    assert (
        model_errors(cells, ["claude-sonnet-5.5"])["claude-sonnet-5.5"]["errored"] == 2
    )

    mixed = cells + aggregate(
        collect_runs(
            _log(
                [_sample("a", 1, copilot=_copilot("gpt-6.1-sol"))],
                copilot_model="gpt-6.1-sol",
            )
        )
    )
    md = render_markdown(mixed, ["claude-sonnet-5.5", "gpt-6.1-sol"])
    assert "2 of 3 runs errored" in md


def test_no_error_section_when_nothing_errored():
    cells = aggregate(collect_runs(_log([_sample("a", 1, copilot=_copilot())])))
    md = render_markdown(cells, ["claude-sonnet-5.5"])
    assert "### Errors" not in md and "errored (" not in md


def test_model_top_error_ranks_full_counts_across_evals():
    # Reviewer's case: per eval, three eval-specific errors x4 and a shared
    # timeout x3. Truncating each eval to its top 3 would drop the timeout,
    # though its 6 occurrences make it the model's most common error.
    from scripts.model_matrix import model_errors

    def errored(task, msgs):
        samples, epoch = [], 0
        for msg, n in msgs:
            for _ in range(n):
                epoch += 1
                samples.append(_sample("s", epoch, error=NS(message=msg)))
        return collect_runs(_log(samples, task=task))

    runs = errored(
        "camunda_bpmn", [("bpmn-a", 4), ("bpmn-b", 4), ("bpmn-c", 4), ("timeout", 3)]
    ) + errored(
        "camunda_dmn", [("dmn-a", 4), ("dmn-b", 4), ("dmn-c", 4), ("timeout", 3)]
    )
    cells = aggregate(runs)
    assert all(c["error_counts"]["timeout"] == 3 for c in cells)
    top = model_errors(cells, ["claude-sonnet-5.5"])["claude-sonnet-5.5"]["top"]
    assert top == [("timeout", 6)]


class TestCliExitCodes:
    """`evals-model-matrix --fail-if-all-errored` end to end, logs mocked."""

    def _main(self, monkeypatch, tmp_path, logs, extra=()):
        import sys

        import inspect_ai.log

        from scripts import model_matrix

        infos = [NS(name=f"logs/2026-10-29T0{i}-00_x.eval") for i in range(len(logs))]
        by_name = {info.name: log for info, log in zip(infos, logs)}
        monkeypatch.setattr(inspect_ai.log, "list_eval_logs", lambda _d: infos)
        monkeypatch.setattr(inspect_ai.log, "read_eval_log", lambda i: by_name[i.name])
        md, js = tmp_path / "m.md", tmp_path / "m.json"
        monkeypatch.setattr(
            sys,
            "argv",
            ["evals-model-matrix", "--log-dir", "x", "--out-md", str(md),
             "--out-json", str(js), *extra],
        )  # fmt: skip
        try:
            model_matrix.main()
            code = 0
        except SystemExit as e:
            code = e.code
        return code, md, js

    def _err(self):
        return NS(message="RuntimeError('copilot exited 1: boom')")

    def test_all_errored_exits_2_after_writing_outputs(self, monkeypatch, tmp_path):
        logs = [
            _log(
                [_sample("a", 1, error=self._err()), _sample("a", 2, error=self._err())]
            )
        ]
        code, md, js = self._main(
            monkeypatch, tmp_path, logs, ["--fail-if-all-errored"]
        )
        assert code == 2
        assert "Every run errored (2/2)" in md.read_text()
        assert json.loads(js.read_text())["cells"][0]["errored"] == 2

    def test_mixed_and_successful_runs_exit_normally(self, monkeypatch, tmp_path):
        mixed = [
            _log(
                [
                    _sample("a", 1, error=self._err()),
                    _sample("a", 2, copilot=_copilot()),
                ]
            )
        ]
        ok = [_log([_sample("a", 1, copilot=_copilot())])]
        for logs in (mixed, ok):
            code, md, js = self._main(
                monkeypatch, tmp_path, logs, ["--fail-if-all-errored"]
            )
            assert code == 0 and md.exists() and js.exists()

    def test_flag_off_never_fails(self, monkeypatch, tmp_path):
        logs = [_log([_sample("a", 1, error=self._err())])]
        code, _, _ = self._main(monkeypatch, tmp_path, logs)
        assert code == 0


def test_error_summary_preserves_non_ascii_and_escapes():
    from scripts.model_matrix import error_summary

    def summary(message):
        return error_summary(NS(error=NS(message=message)))

    assert summary("RuntimeError('cannot open café.dmn — invalid expression')") == (
        "cannot open café.dmn — invalid expression"
    )
    # Escapes in the repr are decoded; whitespace runs collapse.
    assert summary("RuntimeError('a\\nb\\tc')") == "a b c"
    assert summary('ValueError("it\'s broken")') == "it's broken"
    # Not a parseable literal: the original message is kept.
    assert summary("RuntimeError('unterminated)") == "RuntimeError('unterminated)"
    assert summary("plain failure") == "plain failure"


def test_errors_table_escapes_pipes_but_json_keeps_raw_message():
    msg = "command failed: a | b"
    cells = aggregate(collect_runs(_log([_sample("a", 1, error=NS(message=msg))])))
    assert cells[0]["error_counts"] == {msg: 1}
    md = render_markdown(cells, ["claude-sonnet-5.5"])
    row = next(line for line in md.splitlines() if "command failed" in line)
    assert "command failed: a \\| b" in row
    # Model / errored / message: the escaped pipe doesn't add a column.
    assert len(row.replace("\\|", "").strip("|").split("|")) == 3
