#!/usr/bin/env python3
"""Check the repository-level skills portability contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
import yaml

SPEC_URL = "https://agentskills.io/specification"
SKILL_NAME = re.compile(r"(?=.{1,64}\Z)[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GENERIC_DIFFERENCE = "Tool names, model configuration, and credential setup can vary by harness."


def load_json(path: Path, errors: list[str]) -> Any:
    if not path.is_file():
        errors.append(f"{path}: file does not exist")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{path}: invalid JSON ({error})")
        return None


def validate_schema(document: Any, schema: Any, label: str, errors: list[str]) -> None:
    if document is None or schema is None:
        return
    try:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        validation_errors = sorted(
            validator.iter_errors(document),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
    except SchemaError as error:
        errors.append(f"{label}: invalid schema ({error.message})")
        return

    for validation_error in validation_errors:
        location = ".".join(str(part) for part in validation_error.absolute_path) or "<root>"
        errors.append(
            f"{label}: schema validation failed at {location}: "
            f"{validation_error.message}"
        )


def has_keys(value: Any, expected: set[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label}: expected an object")
        return False
    actual = set(value)
    missing = expected - actual
    extra = actual - expected
    if missing:
        errors.append(f"{label}: missing keys {sorted(missing)}")
    if extra:
        errors.append(f"{label}: unexpected keys {sorted(extra)}")
    return not missing and not extra


def expect(value: Any, expected: Any, label: str, errors: list[str]) -> None:
    if value != expected:
        errors.append(f"{label}: expected {expected!r}, got {value!r}")


def non_empty_strings(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and bool(item) for item in value
    ):
        errors.append(f"{label}: expected a non-empty list of strings")


def status(value: Any, label: str, errors: list[str]) -> None:
    if value not in {"portable", "portable-with-adapter", "harness-specific"}:
        errors.append(f"{label}: invalid repository status {value!r}")


def check_sidecar(sidecar: Any, label: str, spec_date: Any, errors: list[str]) -> None:
    keys = {
        "$schema",
        "skillDirectory",
        "skillName",
        "status",
        "agentSkillsSpec",
        "harnesses",
        "limitations",
        "differences",
    }
    if not has_keys(sidecar, keys, label, errors):
        return

    expect(
        sidecar["$schema"],
        "../../compatibility/portability.schema.json",
        f"{label}.$schema",
        errors,
    )
    if not isinstance(sidecar["skillDirectory"], str):
        errors.append(f"{label}.skillDirectory: expected a string")
    if not isinstance(sidecar["skillName"], str) or not SKILL_NAME.fullmatch(
        sidecar["skillName"]
    ):
        errors.append(f"{label}.skillName: invalid skill name")
    status(sidecar["status"], f"{label}.status", errors)

    specification = sidecar["agentSkillsSpec"]
    if has_keys(
        specification,
        {"specUrl", "specRevisionOrAuditDate"},
        f"{label}.agentSkillsSpec",
        errors,
    ):
        expect(specification["specUrl"], SPEC_URL, f"{label}.agentSkillsSpec.specUrl", errors)
        expect(
            specification["specRevisionOrAuditDate"],
            spec_date,
            f"{label}.agentSkillsSpec.specRevisionOrAuditDate",
            errors,
        )

    harnesses = sidecar["harnesses"]
    if isinstance(harnesses, dict):
        expect(
            set(harnesses),
            {"claude", "copilot", "generic"},
            f"{label}.harnesses names",
            errors,
        )
        for harness_name, declaration in harnesses.items():
            harness_label = f"{label}.harnesses.{harness_name}"
            if has_keys(declaration, {"status", "differences"}, harness_label, errors):
                if declaration["status"] not in {
                    "native",
                    "adapter-required",
                    "unsupported",
                    "not-tested",
                }:
                    errors.append(f"{harness_label}.status: invalid harness status")
                non_empty_strings(declaration["differences"], f"{harness_label}.differences", errors)

    non_empty_strings(sidecar["limitations"], f"{label}.limitations", errors)
    non_empty_strings(sidecar["differences"], f"{label}.differences", errors)
    if (
        isinstance(sidecar["differences"], list)
        and GENERIC_DIFFERENCE in sidecar["differences"]
    ):
        errors.append(f"{label}.differences: replace the generic portability claim with a skill-specific difference")


def check_skill_frontmatter(path: Path, name: str, errors: list[str]) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"{path}: cannot read ({error})")
        return

    frontmatter = re.match(r"^---\s*\n(.*?)\n---(?:\s|$)", content, re.DOTALL)
    if not frontmatter:
        errors.append(f"{path}: missing YAML frontmatter")
        return

    try:
        metadata = yaml.safe_load(frontmatter.group(1))
    except yaml.YAMLError as error:
        errors.append(f"{path}: invalid YAML frontmatter ({error})")
        return
    if not isinstance(metadata, dict):
        errors.append(f"{path}: frontmatter must be a YAML object")
        return

    has_keys(metadata, {"name", "description"}, f"{path}: frontmatter", errors)

    frontmatter_name = metadata.get("name")
    if not isinstance(frontmatter_name, str) or not SKILL_NAME.fullmatch(frontmatter_name):
        errors.append(f"{path}: frontmatter name is invalid")
    elif frontmatter_name != name:
        errors.append(f"{path}: frontmatter name must be {name!r}")

    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{path}: frontmatter description must be a non-empty string")
    elif len(description) > 1024:
        errors.append(f"{path}: frontmatter description must be at most 1024 characters")


def check_index(index: Any, errors: list[str]) -> list[dict[str, Any]]:
    label = "compatibility/skills-index.json"
    keys = {"$schema", "schemaVersion", "specUrl", "specRevisionOrAuditDate", "skills"}
    if not has_keys(index, keys, label, errors):
        return []
    expect(index["$schema"], "./skills-index.schema.json", f"{label}.$schema", errors)
    expect(index["schemaVersion"], 1, f"{label}.schemaVersion", errors)
    expect(index["specUrl"], SPEC_URL, f"{label}.specUrl", errors)
    if not isinstance(index["specRevisionOrAuditDate"], str) or not index[
        "specRevisionOrAuditDate"
    ]:
        errors.append(f"{label}.specRevisionOrAuditDate: expected a non-empty string")

    entries = index["skills"]
    if not isinstance(entries, list) or not entries:
        errors.append(f"{label}.skills: expected a non-empty list")
        return []

    result: list[dict[str, Any]] = []
    names: set[str] = set()
    entry_keys = {"name", "skillDirectory", "skillMarkdown", "sidecar", "status"}
    for number, entry in enumerate(entries, start=1):
        entry_label = f"{label}.skills[{number}]"
        if not has_keys(entry, entry_keys, entry_label, errors):
            continue
        name = entry["name"]
        if not isinstance(name, str) or not SKILL_NAME.fullmatch(name):
            errors.append(f"{entry_label}.name: invalid skill name")
            continue
        if name in names:
            errors.append(f"{entry_label}.name: duplicate skill name {name!r}")
        names.add(name)
        for field in ("skillDirectory", "skillMarkdown", "sidecar"):
            if not isinstance(entry[field], str):
                errors.append(f"{entry_label}.{field}: expected a string")
        status(entry["status"], f"{entry_label}.status", errors)
        result.append(entry)
    return result


def check_audit(audit: Any, errors: list[str]) -> list[dict[str, Any]]:
    label = "compatibility/audit.json"
    keys = {
        "$schema",
        "schemaVersion",
        "specUrl",
        "specRevisionOrAuditDate",
        "auditDate",
        "skills",
    }
    if not has_keys(audit, keys, label, errors):
        return []
    expect(audit["$schema"], "./audit.schema.json", f"{label}.$schema", errors)
    expect(audit["schemaVersion"], 1, f"{label}.schemaVersion", errors)
    expect(audit["specUrl"], SPEC_URL, f"{label}.specUrl", errors)
    if not isinstance(audit["specRevisionOrAuditDate"], str) or not audit[
        "specRevisionOrAuditDate"
    ]:
        errors.append(f"{label}.specRevisionOrAuditDate: expected a non-empty string")
    if not isinstance(audit["auditDate"], str) or not DATE.fullmatch(audit["auditDate"]):
        errors.append(f"{label}.auditDate: expected an ISO date")

    entries = audit["skills"]
    if not isinstance(entries, list) or not entries:
        errors.append(f"{label}.skills: expected a non-empty list")
        return []

    result: list[dict[str, Any]] = []
    names: set[str] = set()
    entry_keys = {"name", "skillDirectory", "sidecar", "status"}
    for number, entry in enumerate(entries, start=1):
        entry_label = f"{label}.skills[{number}]"
        if not has_keys(entry, entry_keys, entry_label, errors):
            continue
        name = entry["name"]
        if not isinstance(name, str) or not SKILL_NAME.fullmatch(name):
            errors.append(f"{entry_label}.name: invalid skill name")
            continue
        if name in names:
            errors.append(f"{entry_label}.name: duplicate skill name {name!r}")
        names.add(name)
        for field in ("skillDirectory", "sidecar"):
            if not isinstance(entry[field], str):
                errors.append(f"{entry_label}.{field}: expected a string")
        status(entry["status"], f"{entry_label}.status", errors)
        result.append(entry)
    return result


def check_contract(contract: Any, errors: list[str]) -> None:
    label = "compatibility/harness-smoke-contract.json"
    keys = {
        "$schema",
        "schemaVersion",
        "contractId",
        "discovery",
        "activation",
        "resultAssertions",
        "adapters",
    }
    if not has_keys(contract, keys, label, errors):
        return
    expect(contract["$schema"], "./harness-smoke-contract.schema.json", f"{label}.$schema", errors)
    expect(contract["schemaVersion"], 1, f"{label}.schemaVersion", errors)
    expect(
        contract["contractId"],
        "camunda-skills-harness-smoke-v1",
        f"{label}.contractId",
        errors,
    )

    discovery = contract["discovery"]
    discovery_keys = {
        "repositoryRoot",
        "skillEntrypointPattern",
        "requiredEntrypoint",
        "sidecarPattern",
        "discoveryResultField",
    }
    if has_keys(discovery, discovery_keys, f"{label}.discovery", errors):
        expect(discovery["repositoryRoot"], ".", f"{label}.discovery.repositoryRoot", errors)
        expect(
            discovery["skillEntrypointPattern"],
            "skills/<name>/SKILL.md",
            f"{label}.discovery.skillEntrypointPattern",
            errors,
        )
        expect(
            discovery["requiredEntrypoint"],
            "skills/camunda-bpmn/SKILL.md",
            f"{label}.discovery.requiredEntrypoint",
            errors,
        )
        expect(
            discovery["sidecarPattern"],
            "skills/<name>/portability.json",
            f"{label}.discovery.sidecarPattern",
            errors,
        )
        expect(
            discovery["discoveryResultField"],
            "discovered",
            f"{label}.discovery.discoveryResultField",
            errors,
        )

    activation = contract["activation"]
    activation_keys = {"fixturePath", "skillNameField", "promptField", "activationResultField"}
    if has_keys(activation, activation_keys, f"{label}.activation", errors):
        expect(
            activation["fixturePath"],
            "compatibility/fixtures/camunda-bpmn-smoke.json",
            f"{label}.activation.fixturePath",
            errors,
        )
        expect(activation["skillNameField"], "skillName", f"{label}.activation.skillNameField", errors)
        expect(activation["promptField"], "prompt", f"{label}.activation.promptField", errors)
        expect(
            activation["activationResultField"],
            "activated",
            f"{label}.activation.activationResultField",
            errors,
        )

    assertions = contract["resultAssertions"]
    if has_keys(
        assertions,
        {"required", "artifact", "toolCall"},
        f"{label}.resultAssertions",
        errors,
    ):
        required = assertions["required"]
        if has_keys(
            required,
            {"discovered", "activated"},
            f"{label}.resultAssertions.required",
            errors,
        ):
            expect(required["discovered"], True, f"{label}.resultAssertions.required.discovered", errors)
            expect(required["activated"], True, f"{label}.resultAssertions.required.activated", errors)

        artifact = assertions["artifact"]
        if has_keys(
            artifact,
            {"path", "required", "mustExist", "mustBeValid"},
            f"{label}.resultAssertions.artifact",
            errors,
        ):
            expect(artifact["path"], "process.bpmn", f"{label}.resultAssertions.artifact.path", errors)
            for field in ("required", "mustExist", "mustBeValid"):
                expect(
                    artifact[field],
                    True,
                    f"{label}.resultAssertions.artifact.{field}",
                    errors,
                )

        tool_call = assertions["toolCall"]
        if has_keys(
            tool_call,
            {"command", "match", "required", "mustExecute", "mustSucceed"},
            f"{label}.resultAssertions.toolCall",
            errors,
        ):
            expect(
                tool_call["command"],
                "c8ctl bpmn lint process.bpmn",
                f"{label}.resultAssertions.toolCall.command",
                errors,
            )
            expect(tool_call["match"], "exact", f"{label}.resultAssertions.toolCall.match", errors)
            for field in ("required", "mustExecute", "mustSucceed"):
                expect(tool_call[field], True, f"{label}.resultAssertions.toolCall.{field}", errors)

    adapters = contract["adapters"]
    if not has_keys(adapters, {"deterministicMocks", "liveCopilot"}, f"{label}.adapters", errors):
        return
    mocks = adapters["deterministicMocks"]
    mock_keys = {
        "required",
        "networkAccess",
        "credentialsRequired",
        "modelOutputRequired",
        "entryPoints",
        "passCondition",
    }
    if has_keys(mocks, mock_keys, f"{label}.adapters.deterministicMocks", errors):
        for field in ("required",):
            expect(mocks[field], True, f"{label}.adapters.deterministicMocks.{field}", errors)
        for field in ("networkAccess", "credentialsRequired", "modelOutputRequired"):
            expect(mocks[field], False, f"{label}.adapters.deterministicMocks.{field}", errors)
        entry_points = mocks["entryPoints"]
        if has_keys(
            entry_points,
            {"claude", "copilot"},
            f"{label}.adapters.deterministicMocks.entryPoints",
            errors,
        ):
            expect(
                entry_points["claude"],
                "compatibility/adapters/mock-claude",
                f"{label}.adapters.deterministicMocks.entryPoints.claude",
                errors,
            )
            expect(
                entry_points["copilot"],
                "compatibility/adapters/mock-copilot",
                f"{label}.adapters.deterministicMocks.entryPoints.copilot",
                errors,
            )
        if not isinstance(mocks["passCondition"], str) or not mocks["passCondition"]:
            errors.append(f"{label}.adapters.deterministicMocks.passCondition: expected text")

    live = adapters["liveCopilot"]
    live_keys = {"optional", "optIn", "allowedResults", "unavailableBehavior"}
    if has_keys(live, live_keys, f"{label}.adapters.liveCopilot", errors):
        expect(live["optional"], True, f"{label}.adapters.liveCopilot.optional", errors)
        if not isinstance(live["optIn"], str) or not live["optIn"]:
            errors.append(f"{label}.adapters.liveCopilot.optIn: expected text")
        expect(
            live["allowedResults"],
            ["passed", "failed", "skipped", "unavailable"],
            f"{label}.adapters.liveCopilot.allowedResults",
            errors,
        )
        if not isinstance(live["unavailableBehavior"], str) or not live["unavailableBehavior"]:
            errors.append(f"{label}.adapters.liveCopilot.unavailableBehavior: expected text")


def check_fixture(fixture: Any, errors: list[str]) -> None:
    label = "compatibility/fixtures/camunda-bpmn-smoke.json"
    keys = {"$schema", "fixtureId", "skillName", "prompt", "expected"}
    if not has_keys(fixture, keys, label, errors):
        return
    expect(
        fixture["$schema"],
        "../harness-smoke-fixture.schema.json",
        f"{label}.$schema",
        errors,
    )
    expect(fixture["fixtureId"], "camunda-bpmn-basic", f"{label}.fixtureId", errors)
    expect(fixture["skillName"], "camunda-bpmn", f"{label}.skillName", errors)
    expect(
        fixture["prompt"],
        "Create a minimal Camunda 8 process in process.bpmn and validate it.",
        f"{label}.prompt",
        errors,
    )
    expected = fixture["expected"]
    expected_keys = {
        "discovered",
        "activated",
        "artifact",
        "artifactSource",
        "artifactExists",
        "artifactValid",
        "toolCommand",
        "toolExecuted",
        "toolSucceeded",
    }
    if not has_keys(expected, expected_keys, f"{label}.expected", errors):
        return
    for field in ("discovered", "activated", "artifactExists", "artifactValid", "toolExecuted", "toolSucceeded"):
        expect(expected[field], True, f"{label}.expected.{field}", errors)
    expect(expected["artifact"], "process.bpmn", f"{label}.expected.artifact", errors)
    expect(
        expected["artifactSource"],
        "compatibility/fixtures/process.bpmn",
        f"{label}.expected.artifactSource",
        errors,
    )
    expect(
        expected["toolCommand"],
        "c8ctl bpmn lint process.bpmn",
        f"{label}.expected.toolCommand",
        errors,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    root = args.root.resolve()
    errors: list[str] = []

    compatibility = root / "compatibility"
    index = load_json(compatibility / "skills-index.json", errors)
    audit = load_json(compatibility / "audit.json", errors)
    contract = load_json(compatibility / "harness-smoke-contract.json", errors)
    fixture = load_json(compatibility / "fixtures" / "camunda-bpmn-smoke.json", errors)
    index_entries = check_index(index, errors)
    audit_entries = check_audit(audit, errors)
    check_contract(contract, errors)
    check_fixture(fixture, errors)

    schema_files = {
        "audit": "audit.schema.json",
        "contract": "harness-smoke-contract.schema.json",
        "fixture": "harness-smoke-fixture.schema.json",
        "portability": "portability.schema.json",
        "index": "skills-index.schema.json",
    }
    schemas = {
        name: load_json(compatibility / filename, errors)
        for name, filename in schema_files.items()
    }
    validate_schema(index, schemas["index"], "compatibility/skills-index.json", errors)
    validate_schema(audit, schemas["audit"], "compatibility/audit.json", errors)
    validate_schema(
        contract,
        schemas["contract"],
        "compatibility/harness-smoke-contract.json",
        errors,
    )
    validate_schema(
        fixture,
        schemas["fixture"],
        "compatibility/fixtures/camunda-bpmn-smoke.json",
        errors,
    )

    spec_date = index.get("specRevisionOrAuditDate") if isinstance(index, dict) else None
    if not isinstance(spec_date, str) or not spec_date:
        spec_date = None
    if isinstance(audit, dict):
        expect(audit.get("specRevisionOrAuditDate"), spec_date, "audit specification date", errors)

    skills_root = root / "skills"
    skill_directories = {
        path.name: path
        for path in skills_root.iterdir()
        if path.is_dir()
    } if skills_root.is_dir() else {}
    if not skill_directories:
        errors.append("skills: no skill directories were found")

    index_by_name = {entry.get("name"): entry for entry in index_entries}
    audit_by_name = {entry.get("name"): entry for entry in audit_entries}
    names = set(skill_directories)
    if set(index_by_name) != names:
        errors.append(
            f"skills-index.json skill set does not match checkout: "
            f"index={sorted(index_by_name)} checkout={sorted(names)}"
        )
    if set(audit_by_name) != names:
        errors.append(
            f"audit.json skill set does not match checkout: "
            f"audit={sorted(audit_by_name)} checkout={sorted(names)}"
        )

    actual_sidecars = {
        path.relative_to(root).as_posix()
        for path in skills_root.glob("*/portability.json")
    } if skills_root.is_dir() else set()
    expected_sidecars = {f"skills/{name}/portability.json" for name in names}
    if actual_sidecars != expected_sidecars:
        errors.append(
            f"sidecar set does not match checkout: "
            f"found={sorted(actual_sidecars)} expected={sorted(expected_sidecars)}"
        )

    for name, skill_directory in sorted(skill_directories.items()):
        skill_markdown = skill_directory / "SKILL.md"
        if not skill_markdown.is_file():
            errors.append(f"{skill_markdown}: required skill entrypoint does not exist")
        else:
            check_skill_frontmatter(skill_markdown, name, errors)

        expected_index = {
            "name": name,
            "skillDirectory": f"skills/{name}",
            "skillMarkdown": f"skills/{name}/SKILL.md",
            "sidecar": f"skills/{name}/portability.json",
        }
        expected_audit = {
            "name": name,
            "skillDirectory": f"skills/{name}",
            "sidecar": f"skills/{name}/portability.json",
        }
        index_entry = index_by_name.get(name)
        audit_entry = audit_by_name.get(name)
        if not isinstance(index_entry, dict) or any(
            index_entry.get(field) != value for field, value in expected_index.items()
        ):
            errors.append(f"skills-index.json: entry for {name!r} has stale or mismatched paths")
        if not isinstance(audit_entry, dict) or any(
            audit_entry.get(field) != value for field, value in expected_audit.items()
        ):
            errors.append(f"audit.json: entry for {name!r} has stale or mismatched paths")

        sidecar_path = skill_directory / "portability.json"
        sidecar = load_json(sidecar_path, errors)
        validate_schema(sidecar, schemas["portability"], str(sidecar_path), errors)
        check_sidecar(sidecar, str(sidecar_path.relative_to(root)), spec_date, errors)
        if isinstance(sidecar, dict):
            expect(sidecar.get("skillDirectory"), f"skills/{name}", f"{sidecar_path}.skillDirectory", errors)
            expect(sidecar.get("skillName"), name, f"{sidecar_path}.skillName", errors)
            if isinstance(index_entry, dict):
                expect(
                    index_entry.get("status"),
                    sidecar.get("status"),
                    f"{sidecar_path} and skills-index.json status",
                    errors,
                )
            if isinstance(audit_entry, dict):
                expect(
                    audit_entry.get("status"),
                    sidecar.get("status"),
                    f"{sidecar_path} and audit.json status",
                    errors,
                )
        if isinstance(index_entry, dict) and isinstance(audit_entry, dict):
            expect(
                audit_entry.get("status"),
                index_entry.get("status"),
                f"skills-index.json and audit.json status for {name!r}",
                errors,
            )

    if isinstance(contract, dict):
        discovery = contract.get("discovery")
        if isinstance(discovery, dict):
            required_entrypoint = discovery.get("requiredEntrypoint")
            if isinstance(required_entrypoint, str) and not (root / required_entrypoint).is_file():
                errors.append(f"{required_entrypoint}: required smoke entrypoint does not exist")
    if isinstance(fixture, dict):
        expected = fixture.get("expected")
        if isinstance(expected, dict):
            for field in ("artifactSource",):
                value = expected.get(field)
                if isinstance(value, str) and not (root / value).is_file():
                    errors.append(f"{value}: smoke fixture path does not exist")

    for adapter in (
        root / "compatibility" / "adapters" / "mock-claude",
        root / "compatibility" / "adapters" / "mock-copilot",
        root / "compatibility" / "adapters" / "c8ctl",
    ):
        if not adapter.is_file():
            errors.append(f"{adapter}: required executable does not exist")
        elif not adapter.stat().st_mode & 0o111:
            errors.append(f"{adapter}: required executable bit is not set")

    if errors:
        print("Compatibility conformance failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Compatibility conformance passed for {len(names)} skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
