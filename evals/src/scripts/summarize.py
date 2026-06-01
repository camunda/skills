"""Render a Markdown summary of an eval run for the PR comment.

Non-gating signal: one row per eval log (outcome pass-rate + token-budget
status), plus a with/without-skill delta when both arms of an eval are present.
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


def _token_cell(cost_checks: list[dict] | None) -> str:
    if cost_checks is None:
        return "— (no baseline)"
    graded = [c for c in cost_checks if "ceiling" in c]
    if not graded:
        return "— (no baseline)"
    over = [c for c in graded if not c["pass"]]
    return f"🔴 {len(over)}/{len(graded)} over budget" if over else f"✅ {len(graded)} within budget"


def render(log_dir: Path) -> str:
    infos = list_eval_logs(str(log_dir))
    if not infos:
        return f"{MARKER}\n### 🧪 Eval results\n\n_No eval logs found._"

    head = [
        MARKER,
        "### 🧪 Eval results",
        "",
        "_Non-blocking signal — outcome + token budget vs committed baseline._",
        "",
        "| Eval | Arm | Outcome | Token budget |",
        "|---|---|---|---|",
    ]
    # outcome pass-rate per (eval, arm) for the with/without delta.
    outcomes: dict[str, dict[str, float]] = {}

    for info in infos:
        log = read_eval_log(getattr(info, "name", str(info)))
        name = scenario_id(log) or "(unknown)"
        arm = task_arg(log, "arm") or "—"
        rows, _ = _outcome_rows(log, 1.0)
        passed = sum(1 for r in rows if r["pass"])
        rate = passed / len(rows) if rows else 0.0
        outcomes.setdefault(name, {})[arm] = rate

        baseline = _load_baseline(name)
        cost_checks = None
        if baseline is not None:
            cost_checks, _ = _cost_checks(rows, baseline, arm)
        verdict = "✅" if passed == len(rows) and rows else "⚠️"
        head.append(
            f"| {name} | {arm} | {verdict} {passed}/{len(rows)} | {_token_cell(cost_checks)} |"
        )

    deltas = [
        f"- **{name}**: with-skill {a['with_skill']:.0%} vs without-skill "
        f"{a['without_skill']:.0%} (Δ {a['with_skill'] - a['without_skill']:+.0%})"
        for name, a in sorted(outcomes.items())
        if "with_skill" in a and "without_skill" in a
    ]
    if deltas:
        head += ["", "**Skill impact (with vs without):**", *deltas]
    return "\n".join(head)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", required=True, type=Path)
    args = parser.parse_args()
    # Trailing newline: the CI step feeds this into a `name<<DELIM` heredoc in
    # $GITHUB_OUTPUT; without it the closing delimiter glues onto the last line.
    sys.stdout.write(render(args.log_dir) + "\n")


if __name__ == "__main__":
    main()
