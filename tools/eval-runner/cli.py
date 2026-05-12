#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "click>=8.1",
#     "jsonschema>=4.21",
#     "claude-agent-sdk>=0.1.73",
#     "anyio>=4.0",
# ]
# ///
"""Eval-runner CLI: run / triggers / quality / compare / promote subcommands.

This is the foundation; subcommands have stub implementations that exercise
the iteration scaffolding and the path relativizer. Real model calls and
verifier dispatch land under Issues #6, #7, #8, #9.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import Baseline, diff, load as load_baseline, render_markdown  # noqa: E402
import quality_eval  # noqa: E402
import report as report_mod  # noqa: E402
import trigger_eval  # noqa: E402
from paths import relativize_grading  # noqa: E402
from verifiers import discover as discover_verifiers  # noqa: E402


def _repo_root(start: Path) -> Path:
    cur = start
    for _ in range(8):
        if (cur / ".git").exists() or (cur / "skills").is_dir():
            return cur
        cur = cur.parent
    return start


def _next_iteration_dir(repo_root: Path, skill: str) -> Path:
    base = repo_root / "evals" / skill
    base.mkdir(parents=True, exist_ok=True)
    existing = [
        int(p.name.split("-", 1)[1])
        for p in base.iterdir()
        if p.is_dir() and p.name.startswith("iteration-") and p.name.split("-", 1)[1].isdigit()
    ]
    n = (max(existing) + 1) if existing else 1
    out = base / f"iteration-{n}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _git_head(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _git_dirty(repo_root: Path) -> bool:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "status", "--porcelain"], text=True
        )
        return bool(out.strip())
    except Exception:  # noqa: BLE001
        return True


@click.group()
@click.option(
    "--repo-root",
    "repo_root_opt",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Override repo root (defaults to nearest ancestor with .git or skills/).",
)
@click.option(
    "--max-usd",
    type=float,
    default=None,
    help="Soft budget guard. Aborts before running if estimated cost exceeds this.",
)
@click.pass_context
def main(ctx: click.Context, repo_root_opt: Path | None, max_usd: float | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["repo_root"] = repo_root_opt or _repo_root(Path.cwd())
    ctx.obj["max_usd"] = max_usd


@main.command()
@click.option("--skill", required=True, help="Skill directory name, e.g. camunda-feel.")
@click.option("--runs", "trials", default=3, help="Trials per case.")
@click.option("--harness-model", default=quality_eval.DEFAULT_HARNESS_MODEL)
@click.option("--judge-model", default=quality_eval.DEFAULT_JUDGE_MODEL)
@click.option("--concurrency", default=4)
@click.option("--arm-max-usd", "arm_budget", type=float, default=1.0)
@click.option("--grader-max-usd", "grader_budget", type=float, default=0.5)
@click.option("--workers", default=5, help="Trigger-eval parallel workers.")
@click.option("--timeout", default=30, help="Trigger-eval per-query timeout seconds.")
@click.option("--skip-triggers", is_flag=True, help="Skip Tier-1 trigger eval.")
@click.option("--skip-quality", is_flag=True, help="Skip Tier-2 quality eval.")
@click.option("--dry-run", is_flag=True, help="Scaffold without calling any model.")
@click.pass_context
def run(
    ctx: click.Context, skill: str, trials: int,
    harness_model: str, judge_model: str, concurrency: int,
    arm_budget: float, grader_budget: float,
    workers: int, timeout: int,
    skip_triggers: bool, skip_quality: bool, dry_run: bool,
) -> None:
    """Run trigger + quality evals for SKILL and write iteration data."""
    repo_root: Path = ctx.obj["repo_root"]
    iteration_dir = _next_iteration_dir(repo_root, skill)

    summary: dict[str, Any] = {
        "skill": skill,
        "iteration": iteration_dir.name,
        "trials_per_case": trials,
        "verifiers_registered": sorted(discover_verifiers().keys()),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_head": _git_head(repo_root),
    }

    if dry_run:
        trigger_eval.run_dry(repo_root, skill, iteration_dir, trials)
        quality_eval.run_dry(repo_root, skill, iteration_dir, trials)
        summary["status"] = "dry-run"
    else:
        if not skip_triggers:
            t_summary = trigger_eval.run_live(
                repo_root, skill, iteration_dir,
                runs=trials, workers=workers, timeout=timeout, model=harness_model,
            )
            summary["triggers"] = {
                k: v for k, v in t_summary.items()
                if k in ("f1", "precision", "recall",
                         "positive_cases", "negative_cases")
            }
        if not skip_quality:
            q_summary = quality_eval.run_live(
                repo_root=repo_root, skill=skill, iteration_dir=iteration_dir,
                trials=trials, harness_model=harness_model,
                judge_model=judge_model, arm_max_budget_usd=arm_budget,
                grader_max_budget_usd=grader_budget, concurrency=concurrency,
            )
            summary["quality"] = q_summary["quality"]
            summary["model"] = q_summary["model"]
            summary["trials"] = q_summary["trials"]
        summary["status"] = "ok"

    (iteration_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    report_mod.render_iteration(iteration_dir, repo_root)
    report_mod.render_index(iteration_dir.parent)
    rel = iteration_dir.relative_to(repo_root)
    if dry_run:
        click.echo(f"[dry-run] scaffolded {rel}")
    else:
        click.echo(f"wrote {rel}/summary.json (open {rel}/report.html)")


@main.command()
@click.option("--skill", required=True)
@click.option("--runs", "trials", default=3)
@click.option("--workers", default=5, help="Parallel workers passed to run_eval.py.")
@click.option("--timeout", default=30, help="Per-query timeout seconds (passed through).")
@click.option("--model", default=None, help="Harness model id; default is the user's configured default.")
@click.option("--dry-run", is_flag=True)
@click.pass_context
def triggers(
    ctx: click.Context,
    skill: str,
    trials: int,
    workers: int,
    timeout: int,
    model: str | None,
    dry_run: bool,
) -> None:
    """Run trigger eval (Tier 1) only."""
    repo_root: Path = ctx.obj["repo_root"]
    iteration_dir = _next_iteration_dir(repo_root, skill)
    if dry_run:
        trigger_eval.run_dry(repo_root, skill, iteration_dir, trials)
        click.echo(f"[dry-run] {iteration_dir.relative_to(repo_root)}/triggers/")
        return
    summary = trigger_eval.run_live(
        repo_root, skill, iteration_dir,
        runs=trials, workers=workers, timeout=timeout, model=model,
    )
    click.echo(
        f"triggers: F1={summary['f1']:.2f} "
        f"precision={summary['precision']:.2f} recall={summary['recall']:.2f} "
        f"({summary['positive_cases']} positive + {summary['negative_cases']} negative)"
    )


@main.command()
@click.option("--skill", required=True)
@click.option("--runs", "trials", default=3)
@click.option("--harness-model", default=quality_eval.DEFAULT_HARNESS_MODEL)
@click.option("--judge-model", default=quality_eval.DEFAULT_JUDGE_MODEL)
@click.option("--concurrency", default=4, help="Max concurrent trials in flight.")
@click.option("--arm-max-usd", "arm_budget", type=float, default=1.0,
              help="Per-arm-run budget cap (USD).")
@click.option("--grader-max-usd", "grader_budget", type=float, default=0.5,
              help="Per-grader-run budget cap (USD).")
@click.option("--dry-run", is_flag=True)
@click.pass_context
def quality(
    ctx: click.Context, skill: str, trials: int,
    harness_model: str, judge_model: str, concurrency: int,
    arm_budget: float, grader_budget: float, dry_run: bool,
) -> None:
    """Run quality eval (Tier 2) only."""
    repo_root: Path = ctx.obj["repo_root"]
    iteration_dir = _next_iteration_dir(repo_root, skill)
    if dry_run:
        quality_eval.run_dry(repo_root, skill, iteration_dir, trials)
        report_mod.render_iteration(iteration_dir, repo_root)
        report_mod.render_index(iteration_dir.parent)
        click.echo(f"[dry-run] {iteration_dir.relative_to(repo_root)}")
        return
    summary = quality_eval.run_live(
        repo_root=repo_root, skill=skill, iteration_dir=iteration_dir,
        trials=trials, harness_model=harness_model, judge_model=judge_model,
        arm_max_budget_usd=arm_budget, grader_max_budget_usd=grader_budget,
        concurrency=concurrency,
    )
    summary["status"] = "ok"
    summary["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    summary["git_head"] = _git_head(repo_root)
    (iteration_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    report_mod.render_iteration(iteration_dir, repo_root)
    report_mod.render_index(iteration_dir.parent)
    q = summary["quality"]
    click.echo(
        f"quality: with={q['with_skill']['pass_rate']:.2f} "
        f"without={q['without_skill']['pass_rate']:.2f} "
        f"delta={q['delta_pp']:+.1f}pp "
        f"(cost ~${q['estimated_cost_usd']:.2f}); "
        f"report: {(iteration_dir / 'report.html').relative_to(repo_root)}"
    )


@main.command()
@click.option("--skill", required=True)
@click.option(
    "--iteration",
    "iteration_arg",
    default=None,
    help="Iteration directory to compare. Defaults to the latest under evals/<skill>/.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown"]),
    default="json",
    help="Output format. Use markdown to post into a PR comment.",
)
@click.pass_context
def compare(
    ctx: click.Context, skill: str, iteration_arg: str | None, fmt: str,
) -> None:
    """Diff a candidate iteration against the committed baseline."""
    repo_root: Path = ctx.obj["repo_root"]
    base = load_baseline(repo_root, skill)
    if base is None:
        if fmt == "markdown":
            click.echo(
                f"## {skill} — eval delta\n\n"
                f"_No baseline committed yet (`status: bootstrap`); "
                f"the first run on this skill establishes one._"
            )
        else:
            click.echo(json.dumps({"skill": skill, "status": "bootstrap"}, indent=2))
        sys.exit(0)
    iteration_dir = _resolve_iteration(repo_root, skill, iteration_arg)
    candidate_path = iteration_dir / "summary.json"
    if not candidate_path.exists():
        raise click.ClickException(f"no summary.json under {iteration_dir}")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    d = diff(base, candidate)
    if fmt == "markdown":
        click.echo(render_markdown(d))
    else:
        out = {
            "skill": skill,
            "iteration": iteration_dir.name,
            "with_skill_pass_rate_drop_pp": round(d.with_skill_pass_rate_drop_pp, 2),
            "trigger_f1_drop_pp": round(d.trigger_f1_drop_pp, 2),
            "delta_quality_pp": round(d.delta_quality_pp, 2),
            "noise_floor_pp": round(d.noise_floor_pp, 2),
            "status": "regression" if d.regression else ("warn" if d.warning else "ok"),
        }
        click.echo(json.dumps(out, indent=2))
    sys.exit(2 if d.regression else 0)


@main.command()
@click.option("--skill", required=True)
@click.option("--iteration", "iteration_arg", default=None)
@click.option("--force", is_flag=True, help="Promote even with a dirty worktree.")
@click.pass_context
def promote(ctx: click.Context, skill: str, iteration_arg: str | None, force: bool) -> None:
    """Snapshot a chosen iteration's summary into skills/<skill>/evals/baseline.json."""
    repo_root: Path = ctx.obj["repo_root"]
    if _git_dirty(repo_root) and not force:
        raise click.ClickException(
            "worktree is dirty; commit or stash, or pass --force."
        )
    iteration_dir = _resolve_iteration(repo_root, skill, iteration_arg)
    summary_path = iteration_dir / "summary.json"
    if not summary_path.exists():
        raise click.ClickException(f"no summary.json under {iteration_dir}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    quality = summary.get("quality", {})
    triggers_obj = summary.get("triggers", {})
    if not quality or not triggers_obj:
        raise click.ClickException(
            f"{summary_path}: missing quality/triggers blocks (live runs not yet "
            f"implemented; promote will be functional after Issue #7)."
        )

    n_cases = int(quality["with_skill"]["n_cases"])
    n_trials = int(quality["with_skill"]["n_trials"])
    noise_floor_pp = round(100.0 / max(n_cases * n_trials, 1), 2)

    baseline_obj = {
        "schema_version": 1,
        "skill": skill,
        "established_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "established_by": _git_head(repo_root),
        "source_iteration": str(iteration_dir.relative_to(repo_root)),
        "model": summary.get("model", {}),
        "trials_per_case": n_trials,
        "triggers": triggers_obj,
        "quality": quality,
        "regression_thresholds": {
            "with_skill_pass_rate_drop_pp": 5.0,
            "trigger_f1_drop_pp": 5.0,
            "sustained_runs": 2,
            "noise_floor_pp": noise_floor_pp,
        },
    }
    baseline_obj = relativize_grading(str(iteration_dir), baseline_obj)
    out = repo_root / "skills" / skill / "evals" / "baseline.json"
    out.write_text(json.dumps(baseline_obj, indent=2) + "\n", encoding="utf-8")
    click.echo(f"wrote {out.relative_to(repo_root)}")


def _resolve_iteration(repo_root: Path, skill: str, arg: str | None) -> Path:
    base = repo_root / "evals" / skill
    if arg:
        candidate = (base / arg) if not os.path.isabs(arg) else Path(arg)
        if not candidate.is_dir():
            raise click.ClickException(f"iteration not found: {candidate}")
        return candidate
    if not base.is_dir():
        raise click.ClickException(f"no iterations under {base}")
    iterations = sorted(
        (p for p in base.iterdir() if p.is_dir() and p.name.startswith("iteration-")),
        key=lambda p: int(p.name.split("-", 1)[1]) if p.name.split("-", 1)[1].isdigit() else -1,
    )
    if not iterations:
        raise click.ClickException(f"no iterations under {base}")
    return iterations[-1]


if __name__ == "__main__":
    main()
