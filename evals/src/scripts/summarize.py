"""Render a Markdown summary of an eval run. Non-gating signal.

Always: a headline verdict and the run's model + token usage (total tokens
with an `[I/CW/CR/O]` input / cache-write / cache-read / output split), an
outcome table (pass + tokens vs committed baseline), a trigger routing table,
and a with/without-skill delta when an
``evals:compare`` run provides both arms. ``--detail`` adds a per-eval token
column to those tables — the job-summary deep dive, omitted from the lean PR
comment.

Tables are column-aligned so the raw output is readable on a CLI; GitHub
renders them identically. Consumed by ``.github/workflows/eval.yml`` (PR
comment + ``$GITHUB_STEP_SUMMARY``) and ``eval-nightly.yml`` (job summary).
The workflow prepends its own hidden find-comment marker for the PR comment.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from core.metrics import (
    USAGE_FIELDS,
    model_id,
    scenario_id,
    task_arg,
    token_usage,
)
from scripts.pass_fail import _cost_checks, _load_baseline, _outcome_rows


def _fmt(n: float) -> str:
    n = round(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """A GitHub-flavored Markdown table with columns padded to align in plain
    text — readable on a CLI, rendered identically by GitHub."""
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"

    return [
        line(headers),
        "| " + " | ".join("-" * w for w in widths) + " |",
        *(line(r) for r in rows),
    ]


def _verdict(passed: int, total: int) -> str:
    if total == 0:
        return "—"
    icon = "✅" if passed == total else "⚠️"
    return f"{icon} {passed}/{total} ({passed / total:.0%})"


def _token_cell(cost_checks: list[dict] | None) -> str:
    if cost_checks is None:
        return "— no baseline"
    graded = [c for c in cost_checks if "baseline" in c]
    if not graded:
        return "— regen baseline"
    observed = sum(c["tokens"] for c in graded)
    base = sum(c["baseline"] for c in graded)
    pct = (observed - base) / base * 100 if base else 0.0
    over = [c for c in graded if not c["pass"]]
    icon = "🔴" if over else "✅"
    return f"{icon} {_fmt(observed)} ({pct:+.0f}% vs {_fmt(base)})"


def _usage(u: dict[str, float]) -> str:
    """Token breakdown: total tokens [I, CW, CR, O] (their sum)."""
    i, cw, cr, o = (round(u[f]) for f in USAGE_FIELDS)
    return f"{i + cw + cr + o:,} tokens [I: {i:,}, CW: {cw:,}, CR: {cr:,}, O: {o:,}]"


def render(log_dir: Path, detail: bool = False) -> str:
    """Render the run summary as Markdown.

    ``detail`` adds a per-eval token-usage column to the outcome and trigger
    tables — the job-summary deep dive, omitted from the lean PR comment.
    """
    infos = list_eval_logs(str(log_dir))
    if not infos:
        return "### 🧪 Eval results\n\n_No eval logs found._"

    # rows carry their gating-arm usage dict so --detail can append a token column
    triggers: list[tuple] = []  # (skill, passed, total, usage)
    results: list[tuple] = []  # (name, passed, total, cost, usage)
    outcomes: dict[str, dict[str, float]] = {}  # name -> {arm: rate} for the delta
    grand = dict.fromkeys(USAGE_FIELDS, 0.0)  # run-wide token total (every arm)
    models: set[str] = set()

    for info in infos:
        log = read_eval_log(getattr(info, "name", str(info)))
        name = scenario_id(log) or "(unknown)"
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
            results.append((name, passed, total, cost_checks, u))

    def green(items) -> int:
        return sum(1 for it in items if it[1] == it[2] and it[2])

    tg_ok, rs_ok = green(triggers), green(results)
    all_ok = tg_ok == len(triggers) and rs_ok == len(results)
    headline = (
        "✅ all passed"
        if all_ok
        else f"⚠️ {len(triggers) - tg_ok + len(results) - rs_ok} need attention"
    )

    model_str = " · ".join(f"`{m}`" for m in sorted(models)) if models else "—"

    out = [
        "### 🧪 Eval results",
        "",
        f"**Triggers {tg_ok}/{len(triggers)} · Outcomes {rs_ok}/{len(results)}** — "
        f"{headline}. Non-blocking signal (doesn't block merge).",
        "",
        f"Model {model_str} · {_usage(grand)}",
        "_I input · CW cache-write · CR cache-read · O output._",
    ]

    if results:
        out += ["", "#### Outcome evals"]
        out += _table(
            ["Eval", "Outcome", "Tokens vs baseline"] + (["Tokens"] if detail else []),
            [
                [name, _verdict(passed, total), _token_cell(cost)]
                + ([_usage(u)] if detail else [])
                for name, passed, total, cost, u in sorted(results, key=lambda r: r[0])
            ],
        )

    if triggers:
        out += ["", "#### Trigger evals (skill routing)"]
        out += _table(
            ["Skill", "Routing"] + (["Tokens"] if detail else []),
            [
                [skill, _verdict(passed, total)] + ([_usage(u)] if detail else [])
                for skill, passed, total, u in sorted(triggers, key=lambda t: t[0])
            ],
        )

    deltas = [
        f"- **{name}**: with-skill {a['with_skill']:.0%} vs without-skill "
        f"{a['without_skill']:.0%} (Δ {a['with_skill'] - a['without_skill']:+.0%})"
        for name, a in sorted(outcomes.items())
        if "with_skill" in a and "without_skill" in a
    ]
    if deltas:
        out += ["", "#### Skill impact (with vs without)", *deltas]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", required=True, type=Path)
    parser.add_argument(
        "--detail",
        action="store_true",
        help="add the per-eval token-usage table (job summary surface)",
    )
    args = parser.parse_args()
    # Trailing newline: the CI step feeds this into a `name<<DELIM` heredoc in
    # $GITHUB_OUTPUT; without it the closing delimiter glues onto the last line.
    sys.stdout.write(render(args.log_dir, detail=args.detail) + "\n")


if __name__ == "__main__":
    main()
