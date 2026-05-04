"""Delegate frontmatter / naming validation to the skills-ref library."""

from __future__ import annotations

from pathlib import Path

from skills_ref.validator import validate as skills_ref_validate

from . import Finding


def check(skill_dir: Path, repo_root: Path) -> list[Finding]:
    skill_md = skill_dir / "SKILL.md"
    findings: list[Finding] = []
    errors = skills_ref_validate(skill_dir)
    for err in errors:
        findings.append(
            Finding(
                rule="skills_ref",
                skill=skill_dir.name,
                severity="error",
                message=str(err),
                location=str(skill_md.relative_to(repo_root)),
            )
        )
    return findings
