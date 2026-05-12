"""Validate evals.json, triggers.json, and baseline.json against JSON schemas."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from . import Finding

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

FILES = (
    ("evals.json", "evals.schema.json", True),
    ("triggers.json", "triggers.schema.json", False),
    ("baseline.json", "baseline.schema.json", False),
)


def _load_schema(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def check(skill_dir: Path, repo_root: Path) -> list[Finding]:
    evals_dir = skill_dir / "evals"
    if not evals_dir.is_dir():
        return []
    findings: list[Finding] = []
    for filename, schema_name, required in FILES:
        path = evals_dir / filename
        if not path.exists():
            if required:
                findings.append(
                    Finding(
                        rule="evals_schema",
                        skill=skill_dir.name,
                        severity="error",
                        message=f"missing required file {filename}",
                        location=str(evals_dir.relative_to(repo_root)),
                    )
                )
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            findings.append(
                Finding(
                    rule="evals_schema",
                    skill=skill_dir.name,
                    severity="error",
                    message=f"invalid JSON: {e.msg}",
                    location=f"{path.relative_to(repo_root)}:{e.lineno}",
                )
            )
            continue
        validator = _load_schema(schema_name)
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
            pointer = "/" + "/".join(str(p) for p in err.absolute_path)
            findings.append(
                Finding(
                    rule="evals_schema",
                    skill=skill_dir.name,
                    severity="error",
                    message=f"{pointer}: {err.message}",
                    location=str(path.relative_to(repo_root)),
                )
            )
    return findings
