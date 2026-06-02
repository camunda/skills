"""Render a Markdown summary of an eval run. Non-gating signal.

Always: a headline verdict and the run's model + token usage (total tokens
with an `[I/CW/CR/O]` input / cache-write / cache-read / output split), an
outcome table (pass + tokens vs committed baseline), a trigger routing table,
and a with/without-skill delta when an
``evals:compare`` run provides both arms. ``--detail`` adds a per-eval token
column plus a per-sample breakdown (tokens/turns/tool-calls vs baseline) — the
job-summary deep dive, omitted from the lean PR comment.

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
    eval_source_path,
    model_id,
    scenario_id,
    task_arg,
    token_usage,
)
from core.paths import EVALS_ROOT
from scripts.pass_fail import (
    CEILING_MULTIPLIER,
    _cost_checks,
    _load_baseline,
    _outcome_rows,
)

REPO_ROOT = EVALS_ROOT.parent


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
    # Passing samples with no baseline entry (e.g. newly added) — flag them so a
    # partial comparison is never silently presented as complete.
    no_base = sum(1 for c in cost_checks if "note" in c)
    hint = f" · {no_base} no baseline" if no_base else ""
    if not graded:
        return "— regen baseline" + hint
    observed = sum(c["tokens"] for c in graded)
    base = sum(c["baseline"] for c in graded)
    pct = (observed - base) / base * 100 if base else 0.0
    over = [c for c in graded if not c["pass"]]
    icon = "🔴" if over else "✅"
    return f"{icon} {_fmt(observed)} ({pct:+.0f}% vs {_fmt(base)}){hint}"


def _tok_detail(obs: float, base: dict | None) -> str:
    """Per-sample observed tokens with Δ% vs baseline (🔴 if over the ceiling)."""
    if base and isinstance(base.get("tokens"), (int, float)):
        b = base["tokens"]
        pct = (obs - b) / b * 100 if b else 0.0
        over = "🔴 " if obs > b * CEILING_MULTIPLIER else ""
        return f"{over}{_fmt(obs)} ({pct:+.0f}%)"
    return f"{_fmt(obs)} (no baseline)"


def _count_detail(obs: float, base: dict | None, key: str) -> str:
    """Per-sample observed turns/tool-calls with the delta vs baseline."""
    obs = round(obs)
    if base and isinstance(base.get(key), (int, float)):
        return f"{obs} ({obs - round(base[key]):+d})"
    return str(obs)


def _usage(u: dict[str, float]) -> str:
    """Token breakdown: total tokens [I, CW, CR, O] (their sum)."""
    i, cw, cr, o = (round(u[f]) for f in USAGE_FIELDS)
    return f"{i + cw + cr + o:,} tokens [I: {i:,}, CW: {cw:,}, CR: {cr:,}, O: {o:,}]"


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

    ``detail`` adds a per-eval token-usage column and a per-sample breakdown
    (tokens/turns/tool-calls vs baseline, with explicit "no baseline" rows) —
    the job-summary deep dive, omitted from the lean PR comment. ``blob_base``
    (a ``…/blob/<ref>`` URL) links each eval name to its source; ``run_url``
    appends a footer pointing at the run (used by the PR comment).
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
            arm_samples = ((baseline or {}).get(arm) or {}).get("samples") or {}
            samples_detail = [
                {
                    "id": r["sample_id"],
                    "tokens": r["tokens"],
                    "turns": r["turns"],
                    "tool_calls": r["tool_calls"],
                    "base": b
                    if isinstance((b := arm_samples.get(r["sample_id"])), dict)
                    else None,
                }
                for r in sorted(rows, key=lambda r: r["sample_id"])
            ]
            results.append((name, passed, total, cost_checks, u, samples_detail))

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
                [
                    _name_cell(name, blob_base, False),
                    _verdict(passed, total),
                    _token_cell(cost),
                ]
                + ([_usage(u)] if detail else [])
                for name, passed, total, cost, u, _ in sorted(
                    results, key=lambda r: r[0]
                )
            ],
        )

    if detail and results:
        out += ["", "#### Per-sample detail"]
        out += _table(
            ["Eval", "Sample", "Tokens", "Turns", "Tool calls"],
            [
                [
                    _name_cell(name, blob_base, False),
                    f"`{s['id']}`",
                    _tok_detail(s["tokens"], s["base"]),
                    _count_detail(s["turns"], s["base"], "turns"),
                    _count_detail(s["tool_calls"], s["base"], "tool_calls"),
                ]
                for name, _p, _t, _c, _u, samples in sorted(results, key=lambda r: r[0])
                for s in samples
            ],
        )

    if triggers:
        out += ["", "#### Trigger evals (skill routing)"]
        out += _table(
            ["Skill", "Routing"] + (["Tokens"] if detail else []),
            [
                [_name_cell(skill, blob_base, True), _verdict(passed, total)]
                + ([_usage(u)] if detail else [])
                for skill, passed, total, u in sorted(triggers, key=lambda t: t[0])
            ],
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
