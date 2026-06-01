"""Render a Markdown summary of an eval run for the PR comment.

Non-gating signal. A headline verdict, then two tables — trigger evals (skill
routing) and result evals (outcome + tokens vs committed baseline) — plus a
with/without-skill delta when an ``evals:compare`` run provides both arms.
Consumed by ``.github/workflows/eval.yml``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from core.metrics import scenario_id, task_arg
from scripts.pass_fail import _cost_checks, _load_baseline, _outcome_rows

MARKER = "<!-- camunda-skills-eval-comment -->"


def _fmt(n: float) -> str:
    n = round(n)
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


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


def render(log_dir: Path) -> str:
    infos = list_eval_logs(str(log_dir))
    if not infos:
        return f"{MARKER}\n### 🧪 Eval results\n\n_No eval logs found._"

    triggers: list[tuple[str, int, int]] = []  # (skill, passed, total)
    results: list[
        tuple[str, int, int, list[dict] | None]
    ] = []  # (name, passed, total, cost)
    outcomes: dict[str, dict[str, float]] = {}  # name -> {arm: rate} for the delta

    for info in infos:
        log = read_eval_log(getattr(info, "name", str(info)))
        name = scenario_id(log) or "(unknown)"
        arm = task_arg(log, "arm") or "with_skill"
        rows, _ = _outcome_rows(log, 1.0)
        passed = sum(1 for r in rows if r["pass"])
        total = len(rows)
        outcomes.setdefault(name, {})[arm] = passed / total if total else 0.0

        if name.startswith("trigger-"):
            triggers.append((name[len("trigger-") :], passed, total))
        elif arm != "without_skill":  # the gating arm; compare arm goes in the delta
            baseline = _load_baseline(name)
            cost_checks = (
                _cost_checks(rows, baseline, arm)[0] if baseline is not None else None
            )
            results.append((name, passed, total, cost_checks))

    def green(items) -> int:
        return sum(1 for it in items if it[1] == it[2] and it[2])

    tg_ok, rs_ok = green(triggers), green(results)
    all_ok = tg_ok == len(triggers) and rs_ok == len(results)
    headline = (
        "✅ all passed"
        if all_ok
        else f"⚠️ {len(triggers) - tg_ok + len(results) - rs_ok} need attention"
    )

    out = [
        MARKER,
        "### 🧪 Eval results",
        "",
        f"**Triggers {tg_ok}/{len(triggers)} · Results {rs_ok}/{len(results)}** — "
        f"{headline}. Non-blocking signal (doesn't block merge).",
    ]

    if results:
        out += [
            "",
            "#### Result evals",
            "| Eval | Outcome | Tokens vs baseline |",
            "|---|---|---|",
        ]
        for name, passed, total, cost in sorted(results):
            out.append(f"| {name} | {_verdict(passed, total)} | {_token_cell(cost)} |")

    if triggers:
        out += [
            "",
            "#### Trigger evals (skill routing)",
            "| Skill | Routing |",
            "|---|---|",
        ]
        for skill, passed, total in sorted(triggers):
            out.append(f"| {skill} | {_verdict(passed, total)} |")

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
    args = parser.parse_args()
    # Trailing newline: the CI step feeds this into a `name<<DELIM` heredoc in
    # $GITHUB_OUTPUT; without it the closing delimiter glues onto the last line.
    sys.stdout.write(render(args.log_dir) + "\n")


if __name__ == "__main__":
    main()
