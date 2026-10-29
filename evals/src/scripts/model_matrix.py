"""Render a skill × model comparison matrix from a directory of eval logs.

Consumes the ``.eval`` logs of a model-comparison run (``eval-models.yml``:
outcome evals, ``with_skill`` arm, the GitHub Copilot CLI agent, one log per
target × Copilot model) and reports, per (eval, model) cell:

- **pass rate** — share of sample×epoch runs where every gating scorer scored
  1.0 (an errored run counts as a fail);
- **lint attempts** — median validator runs until the first clean result
  (``core.lint_attempts``), plus the share of runs that ever got clean;
  ``—`` when the eval's agent never runs a validator (e.g. FEEL, docs);
- **cost** — median Copilot AI credits and premium requests per run, plus the
  token split (I/CW/CR/O), from the agent's ``state.store["copilot"]`` record;
- **skill loaded** — share of runs where the agent loaded the skill under
  test (the diagnostic ``assert_skill_loaded`` score);
- **time** — median agent wall-clock per run (the Copilot session only, not
  sandbox setup or scoring).

Logs from Inspect-native agents (``react``) have no Copilot record; they fall
back to Inspect's own token usage and sample time, with no credit figures.

Informational only: no gate, no baseline. Emits Markdown (stdout or
``--out-md``) and the raw cells as JSON (``--out-json``) for trend tracking.

    evals-model-matrix --log-dir logs/ [--models m1,m2]
                       [--out-md matrix.md] [--out-json matrix.json]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import datetime, timezone
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from statistics import median

from core.lint_attempts import lint_attempts
from core.metrics import (
    USAGE_FIELDS,
    _USAGE_SOURCE,
    eval_name,
    gating_by_scorer,
    model_id,
    sample_duration_s,
    score_to_float,
    task_arg,
)
from scripts.build_matrix import parse_models
from scripts.summarize import _table as summarize_table

# ---------------------------------------------------------------- collection


def _sample_passed(sample, gating: dict[str, bool]) -> bool:
    if getattr(sample, "error", None):
        return False
    scores = getattr(sample, "scores", None) or {}
    gated = [
        score_to_float(getattr(s, "value", 0))
        for name, s in scores.items()
        if gating.get(name, True)
    ]
    return bool(gated) and all(v >= 1.0 for v in gated)


def _inspect_tokens(sample, model: str | None) -> dict[str, float]:
    """Token split from Inspect's own usage, for the model under test only."""
    usage = getattr(sample, "model_usage", None) or {}
    picked = [u for k, u in usage.items() if model is None or k == model]
    return {
        f: float(sum(getattr(u, _USAGE_SOURCE[f], 0) or 0 for u in picked))
        for f in USAGE_FIELDS
    }


def _log_metadata(log) -> dict:
    eval_meta = getattr(log, "eval", None)
    return (getattr(eval_meta, "metadata", None) or {}) if eval_meta else {}


# `SomeError('…')` — the repr Inspect stores; group 1 is the quoted literal.
_ERROR_WRAPPER = re.compile(r"^\w+(?:Error|Exception)\((['\"].*['\"])\)$", re.DOTALL)


def error_summary(sample) -> str | None:
    """A short, groupable form of a sample's error (``None`` if it didn't error)."""
    err = getattr(sample, "error", None)
    if not err:
        return None
    msg = str(getattr(err, "message", err)).strip()
    m = _ERROR_WRAPPER.match(msg)
    if m:
        # Parse the Python string literal (handles escapes, keeps non-ASCII);
        # keep the original message if it isn't one.
        try:
            literal = ast.literal_eval(m.group(1))
        except (ValueError, SyntaxError):
            literal = None
        if isinstance(literal, str):
            msg = literal
    msg = " ".join(msg.split())
    return msg[:200] + ("…" if len(msg) > 200 else "")


def log_key(log) -> tuple[str, str, str]:
    """(eval, model, arm) — one job of the model-comparison matrix."""
    return (
        eval_name(log) or "(unknown)",
        _log_metadata(log).get("copilot_model") or model_id(log) or "(unknown)",
        task_arg(log, "arm", "with_skill") or "with_skill",
    )


def select_latest(named_logs: Iterable[tuple[str, object]]) -> list[object]:
    """Newest log per ``log_key``.

    The workflow merges every attempt's per-job log artifact, so a re-run job
    leaves two logs for the same eval×model×arm; counting both would double
    its samples and mix stale failures into the rates. Logs are timestamp-
    prefixed, so the greatest filename is the latest run (as in
    ``scripts.summarize``). Cells that weren't re-run keep their only log.
    """
    latest: dict[tuple[str, str, str], tuple[str, object]] = {}
    for name, log in named_logs:
        key = log_key(log)
        if key not in latest or name > latest[key][0]:
            latest[key] = (name, log)
    return [log for _, log in sorted(latest.values(), key=lambda v: v[0])]


def collect_runs(log) -> list[dict]:
    """One row per sample×epoch in an outcome-eval log (empty for triggers)."""
    name = eval_name(log)
    if not name or name.startswith("trigger-"):
        return []
    log_model = _log_metadata(log).get("copilot_model") or model_id(log)
    arm = task_arg(log, "arm", "with_skill")
    gating = gating_by_scorer(log)
    runs: list[dict] = []
    for sample in getattr(log, "samples", None) or []:
        copilot = (getattr(sample, "store", None) or {}).get("copilot") or {}
        lint = lint_attempts(getattr(sample, "messages", None) or [])
        if copilot:
            model = copilot.get("requested_model") or log_model
            # Missing measurements stay None (excluded from medians), never 0.
            raw_tokens = copilot.get("tokens") or {}
            tokens = {
                f: None if raw_tokens.get(f) is None else float(raw_tokens[f])
                for f in USAGE_FIELDS
            }
            duration = copilot.get("agent_duration_s")
        else:
            model = log_model
            tokens = _inspect_tokens(sample, model_id(log))
            duration = None
        skill = (getattr(sample, "scores", None) or {}).get("assert_skill_loaded")
        runs.append(
            {
                "eval": name,
                "model": model or "(unknown)",
                "models_used": copilot.get("models_used") or [],
                "arm": arm,
                "sample_id": str(sample.id),
                "epoch": getattr(sample, "epoch", 1),
                "passed": _sample_passed(sample, gating),
                "errored": bool(getattr(sample, "error", None)),
                "error": error_summary(sample),
                # Inspect limit that ended the sample (time, message, ...).
                "limit": getattr(getattr(sample, "limit", None), "type", None),
                "skill_loaded": (
                    None if skill is None else score_to_float(skill.value) >= 1.0
                ),
                "tokens": tokens,
                "partial_usage": bool(copilot.get("partial")),
                "ai_credits": copilot.get("ai_credits"),
                "premium_requests": copilot.get("premium_requests"),
                "duration_s": duration
                if duration is not None
                else sample_duration_s(sample),
                "lint_applicable": lint.applicable,
                "lint_attempts": lint.attempts_to_clean,
                "lint_reached_clean": lint.reached_clean,
                "lint_by_validator": lint.by_validator(),
            }
        )
    return runs


# --------------------------------------------------------------- aggregation


def _med(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return median(values) if values else None


def _sum(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) if values else None


def _add(tokens: dict, fields) -> float | None:
    """Sum of token fields, or None if any is unknown."""
    values = [tokens.get(f) for f in fields]
    return None if any(v is None for v in values) else sum(values)


def _rate(flags: list) -> float | None:
    flags = [f for f in flags if f is not None]
    return sum(flags) / len(flags) if flags else None


def aggregate(runs: list[dict]) -> list[dict]:
    """Reduce runs to one cell per (eval, model)."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in runs:
        groups.setdefault((r["eval"], r["model"]), []).append(r)

    cells: list[dict] = []
    for (name, model), rs in sorted(groups.items()):
        linted = [r for r in rs if r["lint_applicable"]]
        by_validator: dict[str, int] = {}
        for r in linted:
            for k, v in r["lint_by_validator"].items():
                by_validator[k] = by_validator.get(k, 0) + v
        cells.append(
            {
                "eval": name,
                "model": model,
                "models_used": sorted({m for r in rs for m in r["models_used"]}),
                "runs": len(rs),
                "samples": len({r["sample_id"] for r in rs}),
                "passed": sum(r["passed"] for r in rs),
                "errored": sum(r["errored"] for r in rs),
                # Full counts, so per-model rollups rank errors correctly;
                # truncate only for display.
                "error_counts": dict(
                    Counter(r["error"] for r in rs if r["error"]).most_common()
                ),
                "limit_hits": dict(
                    Counter(r["limit"] for r in rs if r["limit"]).most_common()
                ),
                # Interrupted runs: credits from usage checkpoints, tokens unknown.
                "partial_usage_runs": sum(r["partial_usage"] for r in rs),
                "pass_rate": sum(r["passed"] for r in rs) / len(rs),
                "skill_load_rate": _rate([r["skill_loaded"] for r in rs]),
                "lint": {
                    "applicable_runs": len(linted),
                    # Per-run distribution, so cross-eval medians can be pooled.
                    "attempts": [r["lint_attempts"] for r in linted],
                    "median_attempts": _med([r["lint_attempts"] for r in linted]),
                    "max_attempts": max(
                        (r["lint_attempts"] for r in linted), default=None
                    ),
                    "clean_rate": (
                        sum(r["lint_reached_clean"] for r in linted) / len(linted)
                        if linted
                        else None
                    ),
                    "validator_runs": by_validator,
                },
                "tokens_median": {
                    **{f: _med([r["tokens"][f] for r in rs]) for f in USAGE_FIELDS},
                    "io": _med([_add(r["tokens"], ("input", "output")) for r in rs]),
                    "total": _med([_add(r["tokens"], USAGE_FIELDS) for r in rs]),
                },
                "ai_credits": {
                    "median": _med([r["ai_credits"] for r in rs]),
                    "total": _sum([r["ai_credits"] for r in rs]),
                },
                "premium_requests": {
                    "median": _med([r["premium_requests"] for r in rs]),
                    "total": _sum([r["premium_requests"] for r in rs]),
                },
                "duration_s": {
                    "median": _med([r["duration_s"] for r in rs]),
                    "total": _sum([r["duration_s"] for r in rs]),
                },
            }
        )
    return cells


# ----------------------------------------------------------------- rendering


def _tok(n: float | None) -> str:
    if n is None:
        return "—"
    n = round(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


def _credits(n: float | None) -> str:
    if n is None:
        return "n/a"
    return f"{n:.2f}" if n < 100 else f"{n:.0f}"


def _num(n: float | None) -> str:
    return "—" if n is None else f"{n:g}"


def _dur(s: float | None) -> str:
    if s is None:
        return "—"
    s = round(s)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    return summarize_table(headers, rows, ["l"] + ["r"] * (len(headers) - 1))


def _ordered_models(cells: list[dict], preferred: list[str]) -> list[str]:
    seen = {c["model"] for c in cells}
    head = [m for m in preferred if m in seen]
    return head + sorted(seen - set(head))


def _grid(cells, models, fmt) -> list[str]:
    by_key = {(c["eval"], c["model"]): c for c in cells}
    evals = sorted({c["eval"] for c in cells})
    rows = [
        [e] + [fmt(by_key[(e, m)]) if (e, m) in by_key else "—" for m in models]
        for e in evals
    ]
    return _table(["eval", *models], rows)


def _cell_lint(c: dict) -> str:
    lint = c["lint"]
    if not lint["applicable_runs"]:
        return "—"
    return f"{_num(lint['median_attempts'])} ({_pct(lint['clean_rate'])} clean)"


def _overall(cells: list[dict], models: list[str]) -> list[str]:
    rows = []
    for m in models:
        cs = [c for c in cells if c["model"] == m]
        runs = sum(c["runs"] for c in cs)
        passed = sum(c["passed"] for c in cs)
        # Median over the pooled per-run attempts, not a median of per-eval
        # medians (which over-weights evals with few validating runs).
        pooled = [a for c in cs for a in c["lint"]["attempts"] if a is not None]
        rows.append(
            [
                m,
                f"{passed / runs:.0%} ({passed}/{runs})" if runs else "—",
                _num(median(pooled)) if pooled else "—",
                _credits(_sum([c["ai_credits"]["total"] for c in cs])),
                _num(_sum([c["premium_requests"]["total"] for c in cs])),
                _dur(_sum([c["duration_s"]["total"] for c in cs])),
            ]
        )
    return _table(
        [
            "model",
            "pass rate",
            "median lint attempts",
            "total AI credits",
            "total premium requests",
            "total agent time",
        ],
        rows,
    )


def _error_banner(cells: list[dict]) -> list[str]:
    runs = sum(c["runs"] for c in cells)
    errored = sum(c["errored"] for c in cells)
    if not errored:
        return []
    if errored == runs:
        return [
            f"> [!CAUTION]\n> **Every run errored ({errored}/{runs})** — the tables "
            "below carry no signal. See **Errors**.",
            "",
        ]
    return [
        f"> [!WARNING]\n> **{errored} of {runs} runs errored** (counted as "
        "fails). See **Errors**.",
        "",
    ]


def model_errors(cells: list[dict], models: list[str]) -> dict[str, dict]:
    """Per model: errored/total runs and its most common error messages."""
    out: dict[str, dict] = {}
    for m in models:
        cs = [c for c in cells if c["model"] == m]
        counts: Counter = Counter()
        for c in cs:
            for msg, n in c["error_counts"].items():
                counts[msg] += n
        out[m] = {
            "runs": sum(c["runs"] for c in cs),
            "errored": sum(c["errored"] for c in cs),
            "top": counts.most_common(1),
        }
    return out


def _md_cell(text: str) -> str:
    """Escape a value for a Markdown table cell (display only; JSON keeps the
    raw message). A bare `|` would otherwise start a new column."""
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _errors_section(cells: list[dict], models: list[str]) -> list[str]:
    per_model = model_errors(cells, models)
    rows = [
        [m, f"{e['errored']}/{e['runs']}", _md_cell(e["top"][0][0]) if e["top"] else ""]
        for m, e in per_model.items()
        if e["errored"]
    ]
    if not rows:
        return []
    return [
        "### Errors",
        "",
        "Runs that errored (an agent or sandbox failure, not a wrong answer). "
        "Per-eval messages are in `model-matrix.json` (`error_counts`).",
        "",
        *summarize_table(["model", "errored", "most common error"], rows),
        "",
    ]


def _limit_note(cells: list[dict]) -> list[str]:
    hits: Counter = Counter()
    for c in cells:
        hits.update(c["limit_hits"])
    if not hits:
        return []
    kinds = ", ".join(f"{k}: {n}" for k, n in hits.most_common())
    return [
        f"> [!NOTE]\n> **{sum(hits.values())} run(s) were stopped by an Inspect "
        f"limit** ({kinds}) and scored on whatever they had produced. See the "
        "*limits hit* column in the detail tables.",
        "",
    ]


def _partial_note(cells: list[dict]) -> list[str]:
    n = sum(c["partial_usage_runs"] for c in cells)
    if not n:
        return []
    return [
        f"_{n} run(s) were interrupted before Copilot wrote final usage: their "
        "credits come from the last usage checkpoint and their tokens are "
        "unknown (excluded from token medians). Marked `†` below._",
        "",
    ]


def render_markdown(cells: list[dict], models: list[str]) -> str:
    if not cells:
        return "## Model comparison\n\n_No outcome-eval logs found._\n"
    epochs = max((c["runs"] // max(c["samples"], 1) for c in cells), default=1)
    out = [
        "## Model comparison",
        "",
        f"Outcome evals, `with_skill` arm, GitHub Copilot CLI agent, ~{epochs} "
        "epoch(s) per sample. Each cell aggregates every sample×epoch run; "
        "medians are per run. Small n — read differences as indicative, not "
        "significant.",
        "",
        *_error_banner(cells),
        *_limit_note(cells),
        "### Overall",
        "",
        *_overall(cells, models),
        "",
        *_partial_note(cells),
        *_errors_section(cells, models),
        "### Pass rate",
        "",
        "Runs where every gating scorer passed (errors count as fails). The "
        "detail tables add how often the agent loaded the skill under test.",
        "",
        *_grid(
            cells,
            models,
            lambda c: f"{c['pass_rate']:.0%} ({c['passed']}/{c['runs']})",
        ),
        "",
        "### Linter attempts",
        "",
        "Median validator runs (`c8ctl bpmn lint`, `dmnlint`, `validate-form.cjs`) "
        "until the first clean result, and the share of runs that ever got clean. "
        "`—` = the agent ran no validator.",
        "",
        *_grid(cells, models, _cell_lint),
        "",
        "### Cost",
        "",
        "Median Copilot AI credits per run, with median input+output tokens. "
        "Premium requests are in the detail tables. `†` = includes interrupted "
        "runs whose tokens are unknown (excluded from token medians) and whose "
        "credits come from Copilot's last usage checkpoint.",
        "",
        *_grid(
            cells,
            models,
            lambda c: (
                f"{_credits(c['ai_credits']['median'])} cr · "
                f"{_tok(c['tokens_median']['io'])} I+O"
                + (" †" if c["partial_usage_runs"] else "")
            ),
        ),
        "",
        "### Time",
        "",
        "Median agent wall-clock per run (the Copilot session; excludes sandbox "
        "setup and scoring; runner-noisy).",
        "",
        *_grid(cells, models, lambda c: _dur(c["duration_s"]["median"])),
        "",
        "<details><summary>Per-eval detail</summary>",
        "",
    ]
    for name in sorted({c["eval"] for c in cells}):
        by_model = {c["model"]: c for c in cells if c["eval"] == name}
        rows = []
        for m in models:
            c = by_model.get(m)
            if c is None:
                continue
            t = c["tokens_median"]
            rows.append(
                [
                    m,
                    f"{c['passed']}/{c['runs']}",
                    str(c["errored"]),
                    str(c["partial_usage_runs"]),
                    ", ".join(f"{k} {n}" for k, n in c["limit_hits"].items()) or "0",
                    _pct(c["skill_load_rate"]),
                    _cell_lint(c),
                    "/".join(_tok(t[f]) for f in USAGE_FIELDS),
                    _credits(c["ai_credits"]["median"]),
                    _num(c["premium_requests"]["median"]),
                    _dur(c["duration_s"]["median"]),
                ]
            )
        out += [
            f"#### {name}",
            "",
            *_table(
                [
                    "model",
                    "passed",
                    "errored",
                    "partial usage",
                    "limits hit",
                    "skill loaded",
                    "lint attempts",
                    "tokens I/CW/CR/O",
                    "AI credits",
                    "premium req.",
                    "time",
                ],
                rows,
            ),
            "",
        ]
    out += ["</details>", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------- main


def main() -> None:
    from inspect_ai.log import list_eval_logs, read_eval_log

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument(
        "--models", default="", help="comma-separated column order (optional)"
    )
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument(
        "--fail-if-all-errored",
        action="store_true",
        help="exit 2 (after writing outputs) when every run errored",
    )
    args = parser.parse_args()

    named_logs: list[tuple[str, object]] = []
    for info in list_eval_logs(args.log_dir):
        try:
            named_logs.append((info.name, read_eval_log(info)))
        except Exception as e:  # a corrupt log shouldn't sink the whole matrix
            print(f"warning: skipping {info.name}: {e}", file=sys.stderr)

    runs: list[dict] = []
    for log in select_latest(named_logs):
        runs.extend(collect_runs(log))

    cells = aggregate(runs)
    models = _ordered_models(cells, parse_models(args.models))
    md = render_markdown(cells, models)

    if args.out_md:
        args.out_md.write_text(md)
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "models": models,
                    "cells": cells,
                },
                indent=2,
            )
        )

    errors = model_errors(cells, models)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for m, e in errors.items():
            if e["runs"] and e["errored"] == e["runs"]:
                top = e["top"][0][0] if e["top"] else "unknown error"
                print(f"::warning title=All {m} runs errored::{top}")
    total = sum(e["runs"] for e in errors.values())
    if (
        args.fail_if_all_errored
        and total
        and total == sum(e["errored"] for e in errors.values())
    ):
        sys.exit(2)


if __name__ == "__main__":
    main()
