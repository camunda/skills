#!/usr/bin/env python3
"""Check the repository-level skills portability contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.parse import unquote, urlsplit
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
import yaml

SPEC_URL = "https://agentskills.io/specification"
SPEC_REVISION_OR_AUDIT_DATE = "2026-09-11"
PORTABILITY_SCHEMA_URL = (
    "https://raw.githubusercontent.com/camunda/skills/main/"
    "compatibility/portability.schema.json"
)
SKILL_NAME = re.compile(r"(?=.{1,64}\Z)[a-z0-9]+(?:-[a-z0-9]+)*\Z")
RESERVED_SKILL_NAMES = frozenset({"anthropic", "claude"})
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GENERIC_DIFFERENCE = "Tool names, model configuration, and credential setup can vary by harness."
OPTIONAL_FRONTMATTER_KEYS = {"license", "compatibility", "metadata", "allowed-tools"}
MARKDOWN_LINK_START = re.compile(r"!?\[[^\]]*\]\(")
MARKDOWN_LINK_DEFINITION = re.compile(
    r"(?m)^[ \t]{0,3}\[([^\]\n]+)\]:[ \t]*(.*)$"
)
MARKDOWN_REFERENCE_LINK = re.compile(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]")
MARKDOWN_SHORTCUT_LINK = re.compile(
    r"(?<![!\w\]])\[([^\]\n]+)\](?![\[(}:])"
)
MARKDOWN_URI_AUTOLINK = re.compile(
    r"<([A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*)>"
)
MARKDOWN_FENCE_START = re.compile(r"[ \t]{0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)")
EXTERNAL_URL = re.compile(r"https?://[^\s<>()\[\]]+", re.IGNORECASE)
FORBIDDEN_LOCAL_REFERENCE = re.compile(
    r"(?<![\w])(?:skills/[a-z0-9-]+/|(?:README|CONTRIBUTING|evals|compatibility|\.github)/"
    r"|/(?:Users|home)/)"
)


def load_json(path: Path, errors: list[str]) -> Any:
    if not path.is_file():
        errors.append(f"{path}: file does not exist")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"{path}: invalid JSON ({error})")
        return None


def validate_schema(document: Any, schema: Any, label: str, errors: list[str]) -> None:
    if document is None:
        return
    if not isinstance(schema, dict):
        errors.append(f"{label}: schema must be a JSON object")
        return
    try:
        Draft202012Validator.check_schema(schema)
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


def is_valid_skill_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and SKILL_NAME.fullmatch(value) is not None
        and value not in RESERVED_SKILL_NAMES
    )


def status(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or value not in {
        "portable",
        "portable-with-adapter",
        "harness-specific",
    }:
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
        PORTABILITY_SCHEMA_URL,
        f"{label}.$schema",
        errors,
    )
    if not isinstance(sidecar["skillDirectory"], str):
        errors.append(f"{label}.skillDirectory: expected a string")
    if not is_valid_skill_name(sidecar["skillName"]):
        errors.append(f"{label}.skillName: invalid or reserved skill name")
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
                if not isinstance(declaration["status"], str) or declaration["status"] not in {
                    "native",
                    "adapter-required",
                    "unsupported",
                    "not-tested",
                }:
                    errors.append(f"{harness_label}.status: invalid harness status")
                non_empty_strings(declaration["differences"], f"{harness_label}.differences", errors)
        harness_statuses = {
            declaration.get("status")
            for declaration in harnesses.values()
            if isinstance(declaration, dict)
        }
        if sidecar["status"] == "portable":
            non_native = [
                harness_name
                for harness_name, declaration in harnesses.items()
                if not isinstance(declaration, dict)
                or declaration.get("status") != "native"
            ]
            if non_native:
                errors.append(
                    f"{label}.status: portable requires native harness declarations; "
                    f"non-native={sorted(non_native)}"
                )
        elif (
            sidecar["status"] == "portable-with-adapter"
            and "adapter-required" not in harness_statuses
        ):
            errors.append(
                f"{label}.status: portable-with-adapter requires an "
                "adapter-required harness declaration"
            )
        elif (
            sidecar["status"] == "harness-specific"
            and "unsupported" not in harness_statuses
        ):
            errors.append(
                f"{label}.status: harness-specific requires an "
                "unsupported harness declaration"
            )

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
    except (OSError, UnicodeError) as error:
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

    required_keys = {"name", "description"}
    allowed_keys = required_keys | OPTIONAL_FRONTMATTER_KEYS
    missing = required_keys - set(metadata)
    if missing:
        errors.append(f"{path}: frontmatter missing keys {sorted(missing)}")
    extra = [key for key in metadata if key not in allowed_keys]
    if extra:
        errors.append(
            f"{path}: frontmatter has unsupported keys "
            f"{sorted(str(key) for key in extra)}"
        )

    frontmatter_name = metadata.get("name")
    if not is_valid_skill_name(frontmatter_name):
        errors.append(f"{path}: frontmatter name is invalid or reserved")
    elif frontmatter_name != name:
        errors.append(f"{path}: frontmatter name must be {name!r}")

    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{path}: frontmatter description must be a non-empty string")
    elif len(description) > 1024:
        errors.append(f"{path}: frontmatter description must be at most 1024 characters")

    license_value = metadata.get("license")
    if "license" in metadata and (
        not isinstance(license_value, str) or not license_value.strip()
    ):
        errors.append(f"{path}: frontmatter license must be a non-empty string")

    compatibility = metadata.get("compatibility")
    if "compatibility" in metadata:
        if not isinstance(compatibility, str) or not compatibility.strip():
            errors.append(f"{path}: frontmatter compatibility must be a non-empty string")
        elif len(compatibility) > 500:
            errors.append(
                f"{path}: frontmatter compatibility must be at most 500 characters"
            )

    metadata_value = metadata.get("metadata")
    if "metadata" in metadata and (
        not isinstance(metadata_value, dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in metadata_value.items()
        )
    ):
        errors.append(
            f"{path}: frontmatter metadata must map strings to strings"
        )

    allowed_tools = metadata.get("allowed-tools")
    if "allowed-tools" in metadata and (
        not isinstance(allowed_tools, str) or not allowed_tools.strip()
    ):
        errors.append(f"{path}: frontmatter allowed-tools must be a non-empty string")

    body = content[frontmatter.end() :].strip()
    if not body:
        errors.append(f"{path}: skill body must not be empty")


def _strip_markdown_code_spans(content: str) -> str:
    masked: list[str] = []
    index = 0
    while index < len(content):
        if index == 0 or content[index - 1] == "\n":
            opening = MARKDOWN_FENCE_START.match(content, index)
            if opening:
                fence = opening.group(1)
                closing_pattern = re.compile(
                    rf"^[ \t]{{0,3}}{re.escape(fence[0])}"
                    rf"{{{len(fence)},}}[ \t]*(?:\r?\n|$)",
                    re.MULTILINE,
                )
                closing = closing_pattern.search(content, opening.end())
                end = closing.end() if closing else len(content)
                code_fence = content[index:end]
                masked.append(
                    "".join("\n" if character == "\n" else " " for character in code_fence)
                )
                index = end
                continue

        if content[index] != "`":
            masked.append(content[index])
            index += 1
            continue

        fence_start = index
        while index < len(content) and content[index] == "`":
            index += 1
        fence = content[fence_start:index]
        closing = content.find(fence, index)
        if closing == -1:
            masked.append(content[fence_start:])
            break

        code_span = content[fence_start : closing + len(fence)]
        masked.append("".join("\n" if character == "\n" else " " for character in code_span))
        index = closing + len(fence)
    return "".join(masked)


def _link_destination(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith("<"):
        closing = raw.find(">", 1)
        return raw[1:closing] if closing != -1 else raw
    for index, character in enumerate(raw):
        if character.isspace():
            return raw[:index]
    return raw


def _reference_label(value: str) -> str:
    return " ".join(value.split()).casefold()


def _markdown_link_targets(content: str) -> tuple[list[str], list[str]]:
    masked = _strip_markdown_code_spans(content)
    targets: list[str] = []
    missing_references: list[str] = []

    def add_target(target: str) -> None:
        if target and target not in targets:
            targets.append(target)

    definitions: dict[str, str] = {}
    for match in MARKDOWN_LINK_DEFINITION.finditer(masked):
        target = _link_destination(match.group(2))
        definitions[_reference_label(match.group(1))] = target
        add_target(target)

    for match in MARKDOWN_LINK_START.finditer(masked):
        start = match.end()
        if start >= len(masked):
            continue

        if masked[start] == "<":
            closing = masked.find(">", start + 1)
            if closing == -1:
                continue
            raw = masked[start : closing + 1]
        else:
            depth = 0
            cursor = start
            while cursor < len(masked):
                character = masked[cursor]
                if character == "\\":
                    cursor += 2
                    continue
                if character == "(":
                    depth += 1
                elif character == ")":
                    if depth == 0:
                        break
                    depth -= 1
                cursor += 1
            if cursor >= len(masked):
                continue
            raw = masked[start:cursor]

        add_target(_link_destination(raw))

    for match in MARKDOWN_REFERENCE_LINK.finditer(masked):
        label = match.group(2) or match.group(1)
        target = definitions.get(_reference_label(label))
        if target is None:
            if label not in missing_references:
                missing_references.append(label)
        else:
            add_target(target)

    for match in MARKDOWN_SHORTCUT_LINK.finditer(masked):
        add_target(definitions.get(_reference_label(match.group(1)), ""))

    for match in MARKDOWN_URI_AUTOLINK.finditer(masked):
        add_target(match.group(1))

    return targets, missing_references


def check_skill_self_containment(
    skill_directory: Path, errors: list[str]
) -> None:
    """Reject local references that escape a distributable skill package."""

    try:
        package_root = skill_directory.resolve()
    except (OSError, RuntimeError) as error:
        errors.append(f"{skill_directory}: cannot resolve package directory ({error})")
        return

    for path in sorted(skill_directory.rglob("*")):
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as error:
            errors.append(f"{path}: cannot resolve package path ({error})")
            continue
        try:
            resolved.relative_to(package_root)
        except ValueError:
            errors.append(f"{path}: symlink escapes the skill package")
            continue

        if not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            errors.append(f"{path}: cannot read referenced content ({error})")
            continue

        masked_content = _strip_markdown_code_spans(content)
        targets, missing_references = _markdown_link_targets(masked_content)
        for label in missing_references:
            errors.append(
                f"{path}: rule=content.reference-exists local link does not "
                f"resolve: [{label}]"
            )
        for target in targets:
            if target.startswith("#"):
                continue
            try:
                parsed = urlsplit(target)
            except ValueError as error:
                errors.append(
                    f"{path}: rule=content.self-contained invalid local link "
                    f"destination {target!r} ({error})"
                )
                continue
            is_file_url = parsed.scheme.casefold() == "file"
            if (parsed.scheme and not is_file_url) or (
                parsed.netloc and not is_file_url
            ):
                continue
            target_path = unquote(parsed.path)
            if is_file_url and parsed.netloc:
                target_path = f"//{parsed.netloc}{target_path}"
            if not target_path:
                continue
            try:
                candidate = (path.parent / target_path).resolve()
            except (OSError, RuntimeError) as error:
                errors.append(
                    f"{path}: rule=content.self-contained cannot resolve local "
                    f"link destination {target!r} ({error})"
                )
                continue
            try:
                candidate.relative_to(package_root)
            except ValueError:
                errors.append(
                    f"{path}: rule=content.self-contained local link escapes "
                    f"the skill package: {target!r}"
                )
                continue
            if not candidate.exists():
                errors.append(
                    f"{path}: rule=content.reference-exists local link does not "
                    f"resolve: {target!r}"
                )

        for line_number, line in enumerate(masked_content.splitlines(), start=1):
            line_without_urls = EXTERNAL_URL.sub("", line)
            if FORBIDDEN_LOCAL_REFERENCE.search(line_without_urls):
                errors.append(
                    f"{path}:{line_number}: rule=content.self-contained "
                    "references a repository-level or external local path"
                )


def skill_error_rule(error: str) -> str:
    explicit_rule = re.search(r"\brule=([a-z0-9.-]+)", error)
    if explicit_rule:
        return explicit_rule.group(1)
    if "skill body" in error:
        return "content.body"
    if "frontmatter" in error:
        return "metadata.frontmatter"
    if "skill entrypoint" in error or "SKILL.md" in error:
        return "layout.entrypoint"
    if "skills-index.json" in error:
        return "inventory.index"
    if "audit.json" in error:
        return "inventory.audit"
    if "portability.json" in error or "sidecar" in error:
        return "portability.sidecar"
    return "content.self-contained"


def format_skill_error(name: str, error: str) -> str:
    return f"skill={name} rule={skill_error_rule(error)}: {error}"


def check_index(index: Any, errors: list[str]) -> list[dict[str, Any]]:
    label = "compatibility/skills-index.json"
    keys = {"$schema", "schemaVersion", "specUrl", "specRevisionOrAuditDate", "skills"}
    if not has_keys(index, keys, label, errors):
        return []
    expect(index["$schema"], "./skills-index.schema.json", f"{label}.$schema", errors)
    expect(index["schemaVersion"], 1, f"{label}.schemaVersion", errors)
    expect(index["specUrl"], SPEC_URL, f"{label}.specUrl", errors)
    expect(
        index["specRevisionOrAuditDate"],
        SPEC_REVISION_OR_AUDIT_DATE,
        f"{label}.specRevisionOrAuditDate",
        errors,
    )

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
        if not is_valid_skill_name(name):
            errors.append(f"{entry_label}.name: invalid or reserved skill name")
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
    expect(
        audit["specRevisionOrAuditDate"],
        SPEC_REVISION_OR_AUDIT_DATE,
        f"{label}.specRevisionOrAuditDate",
        errors,
    )
    expect(
        audit["auditDate"],
        SPEC_REVISION_OR_AUDIT_DATE,
        f"{label}.auditDate",
        errors,
    )
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
        if not is_valid_skill_name(name):
            errors.append(f"{entry_label}.name: invalid or reserved skill name")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
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

    spec_date = SPEC_REVISION_OR_AUDIT_DATE
    if isinstance(index, dict):
        expect(
            index.get("specRevisionOrAuditDate"),
            spec_date,
            "canonical Agent Skills specification revision or audit date",
            errors,
        )
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

    global_errors_before_skills = bool(errors)
    skill_results: dict[str, bool] = {}
    for name, skill_directory in sorted(skill_directories.items()):
        skill_errors: list[str] = []
        if not is_valid_skill_name(name):
            skill_errors.append(f"{skill_directory}: directory name is invalid or reserved")
        if skill_directory.is_symlink():
            skill_errors.append(f"{skill_directory}: skill directory must not be a symlink")
        skill_markdown = skill_directory / "SKILL.md"
        if not skill_markdown.is_file():
            skill_errors.append(f"{skill_markdown}: required skill entrypoint does not exist")
        else:
            check_skill_frontmatter(skill_markdown, name, skill_errors)
        check_skill_self_containment(skill_directory, skill_errors)

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
            skill_errors.append(f"skills-index.json: entry for {name!r} has stale or mismatched paths")
        if not isinstance(audit_entry, dict) or any(
            audit_entry.get(field) != value for field, value in expected_audit.items()
        ):
            skill_errors.append(f"audit.json: entry for {name!r} has stale or mismatched paths")

        sidecar_path = skill_directory / "portability.json"
        sidecar = load_json(sidecar_path, skill_errors)
        validate_schema(sidecar, schemas["portability"], str(sidecar_path), skill_errors)
        check_sidecar(sidecar, str(sidecar_path.relative_to(root)), spec_date, skill_errors)
        if isinstance(sidecar, dict):
            expect(
                sidecar.get("skillDirectory"),
                f"skills/{name}",
                f"{sidecar_path}.skillDirectory",
                skill_errors,
            )
            expect(sidecar.get("skillName"), name, f"{sidecar_path}.skillName", skill_errors)
            if isinstance(index_entry, dict):
                expect(
                    index_entry.get("status"),
                    sidecar.get("status"),
                    f"{sidecar_path} and skills-index.json status",
                    skill_errors,
                )
            if isinstance(audit_entry, dict):
                expect(
                    audit_entry.get("status"),
                    sidecar.get("status"),
                    f"{sidecar_path} and audit.json status",
                    skill_errors,
                )
        if isinstance(index_entry, dict) and isinstance(audit_entry, dict):
            expect(
                audit_entry.get("status"),
                index_entry.get("status"),
                f"skills-index.json and audit.json status for {name!r}",
                skill_errors,
            )
        errors.extend(format_skill_error(name, error) for error in skill_errors)
        skill_results[name] = not skill_errors

    errors_before_global_post_checks = len(errors)

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

    global_checks_failed = global_errors_before_skills or (
        len(errors) > errors_before_global_post_checks
    )
    if global_checks_failed:
        skill_results = {name: False for name in skill_results}

    for name in sorted(skill_results):
        result = "passed" if skill_results[name] else "failed"
        print(f"Compatibility skill {name}: {result}")

    if errors:
        print("Compatibility conformance failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Compatibility conformance passed for {len(names)} skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
