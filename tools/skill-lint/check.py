#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "skills-ref @ git+https://github.com/agentskills/agentskills.git@2d3e01f590f68bee2cb76a3200823e93b2cc9eaa#subdirectory=skills-ref",
#     "jsonschema>=4.21",
#     "click>=8.1",
# ]
# ///
"""Entrypoint for `skill-lint check`.

JSON output schema (per finding):
    {"rule": str, "skill": str, "severity": "error"|"warn"|"skip",
     "message": str, "location": "path[:line]" | null}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

# Allow `uv run check.py` from inside tools/skill-lint/ as well as
# `uv run tools/skill-lint/check.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rules import Finding, discover_rules  # noqa: E402


def _repo_root(start: Path) -> Path:
    cur = start
    for _ in range(8):
        if (cur / ".git").exists() or (cur / "skills").is_dir():
            return cur
        cur = cur.parent
    return start


def _list_skills(repo_root: Path, skill_filter: str | None) -> list[Path]:
    skills_root = repo_root / "skills"
    if not skills_root.is_dir():
        return []
    skills = sorted(p for p in skills_root.iterdir() if p.is_dir())
    if skill_filter:
        skills = [s for s in skills if s.name == skill_filter]
    return skills


@click.command()
@click.option("--skill", "skill_filter", default=None, help="Lint a single skill by name.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format.",
)
@click.option(
    "--repo-root",
    "repo_root_opt",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Override repo root (defaults to nearest ancestor with .git or skills/).",
)
def main(skill_filter: str | None, fmt: str, repo_root_opt: Path | None) -> None:
    repo_root = repo_root_opt or _repo_root(Path.cwd())
    skills = _list_skills(repo_root, skill_filter)
    if not skills:
        msg = (
            f"no skill named {skill_filter!r} under {repo_root / 'skills'}"
            if skill_filter
            else f"no skills found under {repo_root / 'skills'}"
        )
        click.echo(msg, err=True)
        sys.exit(2)

    rules = discover_rules()
    findings: list[Finding] = []
    for skill_dir in skills:
        for _name, rule_fn in rules:
            findings.extend(rule_fn(skill_dir, repo_root))

    errors = [f for f in findings if f.severity == "error"]

    if fmt == "json":
        payload = [
            {
                "rule": f.rule,
                "skill": f.skill,
                "severity": f.severity,
                "message": f.message,
                "location": f.location,
            }
            for f in findings
        ]
        click.echo(json.dumps(payload, indent=2))
    else:
        for f in findings:
            click.echo(f.text_line())
        ok = len(skills)
        click.echo(
            f"\n{ok} skill(s) checked, {len(rules)} rule(s), "
            f"{len(errors)} error(s), {len(findings) - len(errors)} non-error finding(s)"
        )

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
