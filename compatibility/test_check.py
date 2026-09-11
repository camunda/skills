import json
import shutil
from pathlib import Path

import check


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE_FIXTURES = REPOSITORY_ROOT / "evals" / "fixtures" / "conformance"


def copy_contract_root(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    shutil.copytree(REPOSITORY_ROOT / "compatibility", root / "compatibility")
    shutil.copytree(REPOSITORY_ROOT / "skills", root / "skills")
    return root


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def first_skill_name(root: Path) -> str:
    index = read_json(root / "compatibility" / "skills-index.json")
    assert isinstance(index, dict)
    skills = index["skills"]
    assert isinstance(skills, list) and skills
    first = skills[0]
    assert isinstance(first, dict)
    name = first["name"]
    assert isinstance(name, str)
    return name


def test_rejects_duplicate_inventory_entries(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    path = root / "compatibility" / "skills-index.json"
    index = read_json(path)
    assert isinstance(index, dict)
    skills = index["skills"]
    assert isinstance(skills, list) and skills
    skills.append(skills[0].copy())
    write_json(path, index)

    assert check.main(["--root", str(root)]) == 1


def test_rejects_stale_inventory_paths(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    path = root / "compatibility" / "skills-index.json"
    index = read_json(path)
    assert isinstance(index, dict)
    skills = index["skills"]
    assert isinstance(skills, list) and skills
    skills[0]["skillDirectory"] = "skills/stale"
    write_json(path, index)

    assert check.main(["--root", str(root)]) == 1


def test_rejects_missing_sidecar_declaration(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    (root / "skills" / name / "portability.json").unlink()

    assert check.main(["--root", str(root)]) == 1


def test_rejects_malformed_inventory_status(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    path = root / "compatibility" / "skills-index.json"
    index = read_json(path)
    assert isinstance(index, dict)
    index["skills"][0]["status"] = "maybe"
    write_json(path, index)

    assert check.main(["--root", str(root)]) == 1


def test_rejects_unpinned_specification_date(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    path = root / "compatibility" / "skills-index.json"
    index = read_json(path)
    assert isinstance(index, dict)
    index["specRevisionOrAuditDate"] = "latest"
    write_json(path, index)

    assert check.main(["--root", str(root)]) == 1


def test_rejects_omitted_skill_from_inventory(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    path = root / "compatibility" / "skills-index.json"
    index = read_json(path)
    assert isinstance(index, dict)
    index["skills"].pop()
    write_json(path, index)

    assert check.main(["--root", str(root)]) == 1


def test_rejects_invalid_frontmatter(tmp_path: Path, capsys: object) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    path = root / "skills" / name / "SKILL.md"
    content = path.read_text(encoding="utf-8").replace(
        f"name: {name}",
        "name: invalid name",
        1,
    )
    path.write_text(content, encoding="utf-8")

    assert check.main(["--root", str(root)]) == 1
    assert f"skill={name} rule=metadata.frontmatter" in capsys.readouterr().err


def test_rejects_external_skill_reference(tmp_path: Path, capsys: object) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    path = root / "skills" / name / "SKILL.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n[outside](../README.md)\n",
        encoding="utf-8",
    )

    assert check.main(["--root", str(root)]) == 1
    assert f"skill={name} rule=content.self-contained" in capsys.readouterr().err


def test_rejects_file_url_escaping_skill_package(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "README.md").write_text(
        "[secret](file:///etc/passwd)\n"
        "[outside](file:../README.md)\n"
        "<file:///var/log/system.log>\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert len(errors) == 3
    assert all("content.self-contained" in error for error in errors)


def test_reports_each_checked_skill(tmp_path: Path, capsys: object) -> None:
    root = copy_contract_root(tmp_path)

    assert check.main(["--root", str(root)]) == 0
    output = capsys.readouterr().out
    names = {
        line.removeprefix("Compatibility skill ").removesuffix(": passed")
        for line in output.splitlines()
        if line.startswith("Compatibility skill ")
    }
    assert names == {
        path.name for path in (root / "skills").iterdir() if path.is_dir()
    }


def test_valid_conformance_fixture_has_valid_metadata() -> None:
    errors: list[str] = []
    path = CONFORMANCE_FIXTURES / "valid" / "SKILL.md"

    check.check_skill_frontmatter(path, "fixture-skill", errors)

    assert errors == []


def test_invalid_conformance_fixture_has_invalid_metadata() -> None:
    errors: list[str] = []
    path = CONFORMANCE_FIXTURES / "invalid-frontmatter" / "SKILL.md"

    check.check_skill_frontmatter(path, "fixture-skill", errors)

    assert errors


def test_rejects_invalid_utf8_skill_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_bytes(b"\xff")
    errors: list[str] = []

    check.check_skill_frontmatter(path, "fixture-skill", errors)

    assert len(errors) == 1
    assert "cannot read" in errors[0]
    assert check.skill_error_rule(errors[0]) == "metadata.frontmatter"


def test_formats_unreadable_skill_frontmatter_as_metadata(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    (root / "skills" / name / "SKILL.md").write_bytes(b"\xff")

    assert check.main(["--root", str(root)]) == 1
    output = capsys.readouterr().err
    assert f"skill={name} rule=metadata.frontmatter" in output
    assert f"skill={name} rule=layout.entrypoint" not in output


def test_valid_conformance_fixture_allows_container_reference_definitions() -> None:
    errors: list[str] = []
    package = CONFORMANCE_FIXTURES / "valid"

    check.check_skill_self_containment(package, errors)

    assert errors == []


def test_invalid_conformance_fixture_has_external_reference() -> None:
    errors: list[str] = []
    package = CONFORMANCE_FIXTURES / "invalid-reference"

    check.check_skill_self_containment(package, errors)

    assert any("content.self-contained" in error for error in errors)


def test_invalid_conformance_fixture_has_missing_reference() -> None:
    errors: list[str] = []
    package = CONFORMANCE_FIXTURES / "invalid-reference"

    check.check_skill_self_containment(package, errors)

    assert any("content.reference-exists" in error for error in errors)


def test_invalid_conformance_fixture_has_missing_reference_definition() -> None:
    errors: list[str] = []
    package = CONFORMANCE_FIXTURES / "invalid-reference"

    check.check_skill_self_containment(package, errors)

    assert any("missing-reference.md" in error for error in errors)


def test_allows_markdown_link_titles_balanced_destinations_and_urls(
    tmp_path: Path,
) -> None:
    package = tmp_path / "skill"
    references = package / "references"
    references.mkdir(parents=True)
    (references / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (references / "guide_(v1).md").write_text("# Guide\n", encoding="utf-8")
    (references / "guide_(escaped).md").write_text("# Guide\n", encoding="utf-8")
    (package / "README.md").write_text(
        '[guide](references/guide.md "Guide")\n'
        "[guide](references/guide_(v1).md)\n"
        r"[guide](references/guide_\(escaped\).md)" "\n"
        "https://example.test/(skills/example/)\n"
        "[guide][guide-reference]\n"
        "[guide] [guide-reference]\n"
        '[guide-reference]: references/guide.md "Reference title"\n'
        "`[missing](missing.md)`\n"
        "https://example.test/skills/foo/\n"
        "HTTPS://example.test/skills/foo/\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert errors == []


def test_ignores_repository_references_in_indented_and_nested_code_blocks(
    tmp_path: Path,
) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "README.md").write_text(
        "    [missing](missing.md)\n"
        "    skills/example/\n"
        "\n"
        "> ```text\n"
        "> [missing](missing.md)\n"
        "> skills/example/\n"
        "> ```\n"
        "\n"
        "> ```text\n"
        "> [missing](missing.md)\n"
        "> skills/example/\n"
        ">```\n"
        "\n"
        "- ```text\n"
        "  [missing](missing.md)\n"
        "  skills/example/\n"
        "  ```\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert errors == []


def test_ignores_repository_references_in_multiline_code_fences(
    tmp_path: Path,
) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "README.md").write_text(
        "```text\n"
        "skills/example/\n"
        ".github/workflows/example.yml\n"
        "/home/example/file.md\n"
        "```\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert errors == []


def test_ignores_non_file_uri_references_in_plain_text(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "README.md").write_text(
        "ftp://host/skills/example/\n"
        "<custom+scheme://host/compatibility/example>\n"
        "[file](file:../README.md)\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert len(errors) == 1
    assert "file:../README.md" in errors[0]


def test_reports_invalid_percent_encoded_nul_link(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "README.md").write_text("[invalid](%00)\n", encoding="utf-8")

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert len(errors) == 1
    assert "cannot resolve local link destination" in errors[0]


def test_ignores_repository_references_in_tilde_code_fences(
    tmp_path: Path,
) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "README.md").write_text(
        "~~~text\n"
        "[missing](missing.md)\n"
        "skills/example/\n"
        ".github/workflows/example.yml\n"
        "/home/example/file.md\n"
        "~~~\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert errors == []


def test_rejects_unresolved_reference_definition(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "README.md").write_text(
        "[missing][not-defined]\n"
        "[spaced missing] [not-defined-spaced]\n"
        "[also missing][]\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert len(errors) == 3
    assert all("content.reference-exists" in error for error in errors)
    assert any("[not-defined]" in error for error in errors)
    assert any("[not-defined-spaced]" in error for error in errors)
    assert any("[also missing]" in error for error in errors)


def test_rejects_link_with_balanced_bracket_label() -> None:
    errors: list[str] = []
    package = CONFORMANCE_FIXTURES / "invalid-reference"

    check.check_skill_self_containment(package, errors)

    assert any("missing-balanced.md" in error for error in errors)
    assert any("missing-nested-reference.md" in error for error in errors)


def test_treats_unmatched_backtick_as_literal(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "README.md").write_text(
        "` [outside](../README.md)\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert any("local link escapes the skill package" in error for error in errors)


def test_reports_symlink_loop_during_package_and_candidate_resolution(
    tmp_path: Path,
) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    loop = package / "loop"
    loop.symlink_to(loop, target_is_directory=True)
    (package / "README.md").write_text(
        "[loop](loop/target.md)\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check.check_skill_self_containment(package, errors)

    assert any("cannot resolve package path" in error for error in errors)
    assert any("cannot resolve local link destination" in error for error in errors)


def test_skips_symlinked_entrypoint_and_sidecar_reads(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    skill_directory = root / "skills" / name
    unreadable_entrypoint = tmp_path / "unreadable-SKILL.md"
    unreadable_entrypoint.write_bytes(b"\xff")
    unreadable_sidecar = tmp_path / "unreadable-portability.json"
    unreadable_sidecar.write_bytes(b"\xff")
    (skill_directory / "SKILL.md").unlink()
    (skill_directory / "SKILL.md").symlink_to(unreadable_entrypoint)
    (skill_directory / "portability.json").unlink()
    (skill_directory / "portability.json").symlink_to(unreadable_sidecar)

    assert check.main(["--root", str(root)]) == 1
    output = capsys.readouterr().err
    assert f"skill={name} rule=layout.entrypoint" in output
    assert f"skill={name} rule=portability.sidecar" in output
    assert f"skill={name} rule=metadata.frontmatter" not in output
    assert "invalid JSON" not in output


def test_classifies_empty_skill_body_as_content(tmp_path: Path) -> None:
    errors: list[str] = []
    path = CONFORMANCE_FIXTURES / "valid" / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    frontmatter = content.split("---", 2)
    empty_body = f"---{frontmatter[1]}---\n"

    temporary_path = tmp_path / "empty-body-test.md"
    temporary_path.write_text(empty_body, encoding="utf-8")
    check.check_skill_frontmatter(temporary_path, "fixture-skill", errors)

    assert errors == [f"{temporary_path}: skill body must not be empty"]
    assert check.skill_error_rule(errors[0]) == "content.body"


def test_rejects_schema_invalid_sidecar(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    path = root / "skills" / name / "portability.json"
    sidecar = read_json(path)
    assert isinstance(sidecar, dict)
    sidecar["status"] = "invalid"
    write_json(path, sidecar)

    assert check.main(["--root", str(root)]) == 1


def test_rejects_reserved_skill_names(tmp_path: Path, capsys: object) -> None:
    for reserved_name in ("claude", "anthropic"):
        root = copy_contract_root(tmp_path / reserved_name)
        name = first_skill_name(root)
        sidecar_path = root / "skills" / name / "portability.json"
        sidecar = read_json(sidecar_path)
        assert isinstance(sidecar, dict)
        sidecar["skillName"] = reserved_name
        write_json(sidecar_path, sidecar)

        assert check.main(["--root", str(root)]) == 1
        assert "invalid or reserved skill name" in capsys.readouterr().err


def test_rejects_sidecar_skill_name_mismatch(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    path = root / "skills" / name / "portability.json"
    sidecar = read_json(path)
    assert isinstance(sidecar, dict)
    sidecar["skillName"] = "different-skill"
    write_json(path, sidecar)

    assert check.main(["--root", str(root)]) == 1


def test_rejects_invalid_utf8_json(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    path = root / "compatibility" / "skills-index.json"
    path.write_bytes(b"\xff")

    assert check.main(["--root", str(root)]) == 1


def test_rejects_portable_status_with_adapter_required_harness(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    sidecar_path = root / "skills" / name / "portability.json"
    sidecar = read_json(sidecar_path)
    assert isinstance(sidecar, dict)
    sidecar["status"] = "portable"
    sidecar["harnesses"]["copilot"]["status"] = "adapter-required"
    write_json(sidecar_path, sidecar)

    for inventory_name in ("skills-index.json", "audit.json"):
        inventory_path = root / "compatibility" / inventory_name
        inventory = read_json(inventory_path)
        assert isinstance(inventory, dict)
        for entry in inventory["skills"]:
            if entry["name"] == name:
                entry["status"] = "portable"
        write_json(inventory_path, inventory)

    assert check.main(["--root", str(root)]) == 1
    assert "portable requires native harness declarations" in capsys.readouterr().err


def test_rejects_portable_with_adapter_without_adapter(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    sidecar_path = root / "skills" / name / "portability.json"
    sidecar = read_json(sidecar_path)
    assert isinstance(sidecar, dict)
    for declaration in sidecar["harnesses"].values():
        declaration["status"] = "native"
    write_json(sidecar_path, sidecar)

    assert check.main(["--root", str(root)]) == 1
    assert (
        "portable-with-adapter requires an adapter-required harness declaration"
        in capsys.readouterr().err
    )


def test_rejects_harness_specific_without_unsupported(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    sidecar_path = root / "skills" / name / "portability.json"
    sidecar = read_json(sidecar_path)
    assert isinstance(sidecar, dict)
    sidecar["status"] = "harness-specific"
    for declaration in sidecar["harnesses"].values():
        declaration["status"] = "native"
    write_json(sidecar_path, sidecar)

    for inventory_name in ("skills-index.json", "audit.json"):
        inventory_path = root / "compatibility" / inventory_name
        inventory = read_json(inventory_path)
        assert isinstance(inventory, dict)
        for entry in inventory["skills"]:
            if entry["name"] == name:
                entry["status"] = "harness-specific"
        write_json(inventory_path, inventory)

    assert check.main(["--root", str(root)]) == 1
    assert (
        "harness-specific requires an unsupported harness declaration"
        in capsys.readouterr().err
    )


def test_marks_skills_failed_for_global_pre_skill_errors(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    index_path = root / "compatibility" / "skills-index.json"
    index = read_json(index_path)
    assert isinstance(index, dict)
    index["skills"].append(index["skills"][0].copy())
    write_json(index_path, index)

    assert check.main(["--root", str(root)]) == 1
    output = capsys.readouterr().out
    skill_lines = [
        line for line in output.splitlines() if line.startswith("Compatibility skill ")
    ]
    assert skill_lines
    assert all(line.endswith(": failed") for line in skill_lines)


def test_marks_skills_failed_for_global_post_skill_errors(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    (root / "compatibility" / "adapters" / "mock-claude").unlink()

    assert check.main(["--root", str(root)]) == 1
    output = capsys.readouterr().out
    skill_lines = [
        line for line in output.splitlines() if line.startswith("Compatibility skill ")
    ]
    assert skill_lines
    assert all(line.endswith(": failed") for line in skill_lines)


def test_classifies_invalid_skill_directory_name(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    (root / "skills" / name).rename(root / "skills" / "invalid_name")

    assert check.main(["--root", str(root)]) == 1
    assert "skill=invalid_name rule=layout.skill-directory" in capsys.readouterr().err


def test_classifies_symlinked_skill_directory(
    tmp_path: Path, capsys: object
) -> None:
    root = copy_contract_root(tmp_path)
    linked_target = tmp_path / "linked-target"
    linked_target.mkdir()
    (linked_target / "SKILL.md").write_bytes(b"\xff")
    (root / "skills" / "linked").symlink_to(
        linked_target,
        target_is_directory=True,
    )

    assert check.main(["--root", str(root)]) == 1
    output = capsys.readouterr().err
    assert "skill=linked rule=layout.skill-directory" in output
    assert "skill=linked rule=metadata.frontmatter" not in output
