"""Fail if SKILL.md body exceeds 5000 words (excludes YAML frontmatter)."""

from __future__ import annotations

from pathlib import Path

from . import Finding

LIMIT = 5000


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    return parts[2]


def check(skill_dir: Path, repo_root: Path) -> list[Finding]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return []
    body = _strip_frontmatter(skill_md.read_text(encoding="utf-8"))
    words = len(body.split())
    if words > LIMIT:
        return [
            Finding(
                rule="body_word_count",
                skill=skill_dir.name,
                severity="error",
                message=f"SKILL.md body has {words} words (limit {LIMIT})",
                location=str(skill_md.relative_to(repo_root)),
            )
        ]
    return []
