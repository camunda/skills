"""Every name in SKILL.md's ## Cross-References section must resolve to a real skill."""

from __future__ import annotations

import re
from pathlib import Path

from . import Finding

HEADING_RE = re.compile(r"^##\s+Cross-References\b", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)
NAME_RE = re.compile(r"\*\*([a-z][a-z0-9-]*)\*\*")


def _section_text(body: str) -> str | None:
    m = HEADING_RE.search(body)
    if not m:
        return None
    start = m.end()
    rest = body[start:]
    m2 = NEXT_HEADING_RE.search(rest)
    return rest[: m2.start()] if m2 else rest


def check(skill_dir: Path, repo_root: Path) -> list[Finding]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return []
    text = skill_md.read_text(encoding="utf-8")
    section = _section_text(text)
    if section is None:
        return []
    skills_root = skill_dir.parent
    known = {p.name for p in skills_root.iterdir() if p.is_dir()}
    findings: list[Finding] = []
    # Compute line offset for the section to report file:line.
    section_start = HEADING_RE.search(text).end()
    line_offset = text.count("\n", 0, section_start) + 1
    for match in NAME_RE.finditer(section):
        name = match.group(1)
        if name == skill_dir.name:
            continue
        if not name.startswith("camunda-"):
            # Only enforce for repo-local names; ignore generic emphasis.
            continue
        if name not in known:
            line_in_section = section.count("\n", 0, match.start())
            findings.append(
                Finding(
                    rule="dead_xrefs",
                    skill=skill_dir.name,
                    severity="error",
                    message=f"unknown skill referenced: {name}",
                    location=f"{skill_md.relative_to(repo_root)}:{line_offset + line_in_section}",
                )
            )
    return findings
