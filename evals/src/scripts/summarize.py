"""Render a Markdown summary of an eval run. Non-gating signal.

Always: a headline verdict and the run's model + token usage (total tokens with
an `[I/CW/CR/O]` input / cache-write / cache-read / output split), an outcome
table (pass + the gated **I+O** tokens vs committed baseline), a trigger routing
table, and a with/without-skill delta when an ``evals:compare`` run provides both
arms. ``--detail`` adds a per-eval token-split column plus a per-sample breakdown
(I+O / turns / tool-calls / duration vs baseline) — the job-summary deep dive,
omitted from the lean PR comment.

Tables are column-aligned so the raw output is readable on a CLI; GitHub renders
them identically. Consumed by ``.github/workflows/eval.yml`` (PR comment +
``$GITHUB_STEP_SUMMARY``) and ``eval-nightly.yml`` (job summary). The workflow
prepends its own hidden find-comment marker for the PR comment.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from core.metrics import (
    USAGE_FIELDS,
    eval_name,
    eval_source_path,
    model_id,
    task_arg,
    token_usage,
)
from core.paths import EVALS_ROOT
from scripts.pass_fail import (
    CEILING_MULTIPLIER,
    _baseline_io,
    _cost_checks,
    _io,
    _load_baseline,
    _outcome_rows,
)

REPO_ROOT = EVALS_ROOT.parent


def _fmt(n: float) -> str:
    n = round(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


def _table(
    headers: list[str], rows: list[list[str]], align: list[str] | None = None
) -> list[str]:
    """A GitHub-flavored Markdown table with columns padded to align in plain
    text — readable on a CLI, rendered identically by GitHub. ``align`` is a
    per-column ``l``/``c``/``r`` list (default all left); it both pads the cells
    and sets the Markdown separator (``---:`` / ``:--:`` / ``---``)."""
    align = align or ["l"] * len(headers)
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]

    def pad(c: str, w: int, a: str) -> str:
        return c.rjust(w) if a == "r" else c.center(w) if a == "c" else c.ljust(w)

    def line(cells: list[str]) -> str:
        return (
            "| "
            + " | ".join(pad(c, w, a) for c, w, a in zip(cells, widths, align))
            + " |"
        )

    def sep(w: int, a: str) -> str:
        return (
            f"-{'-' * (w - 1)}:"
            if a == "r"
            else f":{'-' * (w - 2)}:"
            if a == "c"
            else "-" * w
        )

    return [
        line(headers),
        "| " + " | ".join(sep(w, a) for w, a in zip(widths, align)) + " |",
        *(line(r) for r in rows),
    ]


def _verdict(passed: int, total: int) -> str:
    if total == 0:
        return "—"
    icon = "✅" if passed == total else "⚠️"
    return f"{icon} {passed}/{total}"


def _token_cell(cost_checks: list[dict] | None) -> str:
    """The outcome-table cost cell: summed observed I+O vs summed baseline I+O."""
    if cost_checks is None:
        return "— no baseline"
    graded = [c for c in cost_checks if "baseline" in c]
    # Passing samples with no baseline entry (e.g. newly added) — flag them so a
    # partial comparison is never silently presented as complete.
    no_base = sum(1 for c in cost_checks if "note" in c)
    hint = f" · {no_base} no baseline" if no_base else ""
    if not graded:
        return "— regenerate baseline" + hint
    observed = sum(c["io"] for c in graded)
    base = sum(c["baseline"] for c in graded)
    pct = (observed - base) / base * 100 if base else 0.0
    over = [c for c in graded if not c["pass"]]
    icon = "🔴" if over else "✅"
    return f"{icon} `{_fmt(observed)}` ({pct:+.0f}% vs `{_fmt(base)}`){hint}"


def _over_ceiling(obs_io: float, base: dict | None) -> bool:
    b = _baseline_io(base) if isinstance(base, dict) else None
    return isinstance(b, (int, float)) and obs_io > b * CEILING_MULTIPLIER


def _io_detail(obs_io: float, base: dict | None) -> str:
    """Per-sample observed I+O, backticked, with Δ% vs baseline when it moved
    (≥5%); a bare value otherwise, or ``(new)`` with no baseline."""
    b = _baseline_io(base) if isinstance(base, dict) else None
    if not isinstance(b, (int, float)):
        return f"`{_fmt(obs_io)}` (new)"
    pct = (obs_io - b) / b * 100 if b else 0.0
    return f"`{_fmt(obs_io)}` {pct:+.0f}%" if abs(pct) >= 5 else f"`{_fmt(obs_io)}`"


def _count_detail(obs: float, base: dict | None, key: str) -> str:
    """Per-sample observed turns/tool-calls, backticked, with the Δ vs baseline
    when it changed; a bare value otherwise."""
    obs = round(obs)
    b = base.get(key) if base else None
    if isinstance(b, (int, float)) and round(b) != obs:
        return f"`{obs}` {obs - round(b):+d}"
    return f"`{obs}`"


def _dur_detail(obs_s: float, base: dict | None) -> str:
    """Per-sample wall time in seconds, backticked, with Δ% vs baseline when it
    moved (≥10%). Diagnostic only — runner-noisy, never gates."""
    obs = round(obs_s)
    b = base.get("duration_s") if base else None
    if not isinstance(b, (int, float)) or not b:
        return f"`{obs}s`"
    pct = (obs - b) / b * 100
    return f"`{obs}s` {pct:+.0f}%" if abs(pct) >= 10 else f"`{obs}s`"


def _usage(u: dict[str, float]) -> str:
    """Token breakdown: total tokens [I, CW, CR, O] (their sum)."""
    i, cw, cr, o = (round(u[f]) for f in USAGE_FIELDS)
    return f"{i + cw + cr + o:,} tokens [I: {i:,}, CW: {cw:,}, CR: {cr:,}, O: {o:,}]"


def _split(u: dict[str, float], base: dict | None = None) -> str:
    """Per-eval token split as a backticked (monospace) I·CW·CR·O cell.

    With a baseline split, appends Δ% on the **cache** categories (CW/CR) when
    they moved ≥10% — the diagnostic the cost gate (I+O only) doesn't surface, so
    a cache-read blow-up is visible even though it never gates. I and O carry no
    Δ here; their movement is the gated quantity shown in the I+O column.
    """

    def cache(cat: str, val: float) -> str:
        val = round(val)
        b = base.get(cat) if base else None
        if isinstance(b, (int, float)) and b and abs((val - b) / b * 100) >= 10:
            return f"{val:,} ({(val - b) / b * 100:+.0f}%)"
        return f"{val:,}"

    i, cw, cr, o = (round(u[f]) for f in USAGE_FIELDS)
    return (
        f"`I {i:,} · CW {cache('cache_write', cw)} · "
        f"CR {cache('cache_read', cr)} · O {o:,}`"
    )


def _name_cell(name: str, blob_base: str | None, is_trigger: bool) -> str:
    """The eval name in backticks, linked to its source `.py` when ``blob_base``
    (a `…/blob/<ref>` URL prefix) is given — i.e. in CI, not on a local CLI."""
    cell = f"`{name}`"
    if blob_base:
        path = eval_source_path(name, is_trigger)
        if path:
            cell = f"[{cell}]({blob_base}/{path.relative_to(REPO_ROOT).as_posix()})"
    return cell


def render(
    log_dir: Path,
    detail: bool = False,
    blob_base: str | None = None,
    run_url: str | None = None,
) -> str:
    """Render the run summary as Markdown.

    ``detail`` adds a per-eval token-split (I·CW·CR·O) column and a per-sample
    breakdown (I+O / turns / tool-calls / duration, each with its Δ vs baseline)
    — the job-summary deep dive, omitted from the lean PR comment. ``blob_base``
    (a ``…/blob/<ref>`` URL) links each eval name to its source; ``run_url``
    appends a footer pointing at the run (used by the PR comment).
    """
    infos = list_eval_logs(str(log_dir))
    if not infos:
        return "### 🧪 Eval results\n\n_No eval logs found._"

    # rows carry their gating-arm usage dict so --detail can append a token column
    triggers: list[tuple] = []  # (skill, passed, total, usage)
    results: list[tuple] = []  # (name, passed, total, cost, split, base_split, samples)
    outcomes: dict[str, dict[str, float]] = {}  # name -> {arm: rate} for the delta
    grand = dict.fromkeys(USAGE_FIELDS, 0.0)  # run-wide token total (every arm)
    models: set[str] = set()

    # Job-retry resilience: the summarize step merges every attempt's per-job log
    # artifact, so re-running a failed job leaves two logs for the same eval×arm.
    # Keep only the newest per (eval_name, arm) — else the table doubles the row
    # and the headline double-counts that eval's tokens. Logs are timestamp-
    # prefixed, so the greatest filename is the latest run.
    latest: dict[tuple[str, str], tuple[str, object]] = {}
    for info in infos:
        iname = getattr(info, "name", str(info))
        log = read_eval_log(iname)
        key = (eval_name(log) or "(unknown)", task_arg(log, "arm") or "with_skill")
        if key not in latest or iname > latest[key][0]:
            latest[key] = (iname, log)

    for _iname, log in sorted(latest.values(), key=lambda v: v[0]):
        name = eval_name(log) or "(unknown)"
        is_trigger = name.startswith("trigger-")
        arm = task_arg(log, "arm") or "with_skill"
        rows, _ = _outcome_rows(log, 1.0)
        passed = sum(1 for r in rows if r["pass"])
        total = len(rows)
        outcomes.setdefault(name, {})[arm] = passed / total if total else 0.0

        models.add(model_id(log) or "?")
        u = token_usage(log)
        for f in USAGE_FIELDS:
            grand[f] += u[f]

        if is_trigger:
            triggers.append((name[len("trigger-") :], passed, total, u))
        elif arm != "without_skill":  # the gating arm; compare arm goes in the delta
            baseline = _load_baseline(name)
            cost_checks = (
                _cost_checks(rows, baseline, arm)[0] if baseline is not None else None
            )
            arm_samples = ((baseline or {}).get(arm) or {}).get("samples") or {}
            # Per-eval split from the reduced rows (median per sample), not the
            # raw token_usage(log) sum — so it's epoch-robust and comparable to
            # the baseline's per-sample medians. The baseline split sums the
            # nested tokens.* across the arm's samples; None when no baseline.
            live_split = {f: sum(r.get(f, 0.0) for r in rows) for f in USAGE_FIELDS}
            base_split = (
                {
                    f: sum(
                        t.get(f, 0)
                        for s in arm_samples.values()
                        if isinstance((t := s.get("tokens")), dict)
                    )
                    for f in USAGE_FIELDS
                }
                if arm_samples
                else None
            )
            samples_detail = [
                {
                    "id": r["sample_id"],
                    "io": _io(r) or 0.0,
                    "turns": r["turns"],
                    "tool_calls": r["tool_calls"],
                    "duration_s": r["duration_s"],
                    "base": b
                    if isinstance((b := arm_samples.get(r["sample_id"])), dict)
                    else None,
                }
                for r in sorted(rows, key=lambda r: r["sample_id"])
            ]
            results.append(
                (
                    name,
                    passed,
                    total,
                    cost_checks,
                    live_split,
                    base_split,
                    samples_detail,
                )
            )

    def outcome_ok(it) -> bool:
        return it[1] == it[2] and it[2]

    def cost_regressed(cost) -> bool:
        return bool(cost) and any(not c.get("pass", True) for c in cost)

    # Displayed counts are outcome/routing only (they line up with the ✅ cells
    # in the tables). The headline, though, is the quality-gate verdict: a cost
    # overage (🔴 token cell) counts toward "need attention" even when the
    # outcome scorers passed — otherwise the lean comment could read "all passed"
    # while the gate failed on cost. Counted per eval so an outcome+cost failure
    # isn't double-counted.
    tg_ok = sum(1 for it in triggers if outcome_ok(it))
    rs_ok = sum(1 for it in results if outcome_ok(it))
    attention = sum(1 for it in triggers if not outcome_ok(it)) + sum(
        1 for it in results if not outcome_ok(it) or cost_regressed(it[3])
    )
    headline = "✅ all passed" if attention == 0 else f"⚠️ {attention} need attention"

    model_str = " · ".join(f"`{m}`" for m in sorted(models)) if models else "—"

    out = [
        "### 🧪 Eval results",
        "",
        f"**Triggers {tg_ok}/{len(triggers)} · Outcomes {rs_ok}/{len(results)}** — "
        f"{headline}. Non-blocking signal (doesn't block merge).",
        "",
        f"Model {model_str} · {_usage(grand)}",
        "_I input · CW cache-write · CR cache-read · O output. Cost gate keys on "
        "I+O; CW/CR are diagnostic._",
    ]

    if results:
        out += ["", "#### Outcome evals"]
        out += _table(
            ["Eval", "Outcome", "I+O (vs baseline)"]
            + (["Token split (I·CW·CR·O)"] if detail else []),
            [
                [
                    _name_cell(name, blob_base, False),
                    _verdict(passed, total),
                    _token_cell(cost),
                ]
                + ([_split(split, base_split)] if detail else [])
                for name, passed, total, cost, split, base_split, _ in sorted(
                    results, key=lambda r: r[0]
                )
            ],
            ["l", "c", "r"] + (["l"] if detail else []),
        )

    if detail and results:
        out += ["", "#### Per-sample detail"]
        out += _table(
            ["Eval · Sample", "I+O (vs baseline)", "Turns", "Tools", "Duration"],
            [
                [
                    f"{'🔴 ' if _over_ceiling(s['io'], s['base']) else ''}"
                    f"{name.removeprefix('camunda-')} · `{s['id']}`",
                    _io_detail(s["io"], s["base"]),
                    _count_detail(s["turns"], s["base"], "turns"),
                    _count_detail(s["tool_calls"], s["base"], "tool_calls"),
                    _dur_detail(s["duration_s"], s["base"]),
                ]
                for name, _p, _t, _c, _ls, _bs, samples in sorted(
                    results, key=lambda r: r[0]
                )
                for s in samples
            ],
            ["l", "r", "r", "r", "r"],
        )
        out += [
            "",
            "_Δ is vs the committed baseline; a bare number means within ±5% (I+O), "
            "±10% (duration), or unchanged (turns/tools). “(new)” = no baseline yet. "
            "Only I+O gates; duration is diagnostic._",
        ]

    if triggers:
        out += ["", "#### Trigger evals (skill routing)"]
        out += _table(
            ["Skill", "Routing"],
            [
                [_name_cell(skill, blob_base, True), _verdict(passed, total)]
                for skill, passed, total, _u in sorted(triggers, key=lambda t: t[0])
            ],
            ["l", "c"],
        )

    deltas = [
        f"- {_name_cell(name, blob_base, False)}: with-skill {a['with_skill']:.0%} "
        f"vs without-skill {a['without_skill']:.0%} "
        f"(Δ {a['with_skill'] - a['without_skill']:+.0%})"
        for name, a in sorted(outcomes.items())
        if "with_skill" in a and "without_skill" in a
    ]
    if deltas:
        out += ["", "#### Skill impact (with vs without)", *deltas]

    if run_url:
        out += ["", f"[Per-eval token usage and full logs → run summary]({run_url})"]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", required=True, type=Path)
    parser.add_argument(
        "--detail",
        action="store_true",
        help="add the per-eval token column + per-sample breakdown (job summary surface)",
    )
    parser.add_argument(
        "--blob-base",
        help="URL prefix (…/blob/<ref>) to link each eval name to its source .py",
    )
    parser.add_argument(
        "--run-url",
        help="append a footer linking to this URL (PR-comment surface)",
    )
    args = parser.parse_args()
    body = render(
        args.log_dir,
        detail=args.detail,
        blob_base=args.blob_base,
        run_url=args.run_url,
    )
    # Trailing newline: the CI step feeds this into a `name<<DELIM` heredoc in
    # $GITHUB_OUTPUT; without it the closing delimiter glues onto the last line.
    sys.stdout.write(body + "\n")


if __name__ == "__main__":
    main()
