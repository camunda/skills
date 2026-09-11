import json
import shutil
from pathlib import Path

import check


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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


def test_rejects_schema_invalid_sidecar(tmp_path: Path) -> None:
    root = copy_contract_root(tmp_path)
    name = first_skill_name(root)
    path = root / "skills" / name / "portability.json"
    sidecar = read_json(path)
    assert isinstance(sidecar, dict)
    sidecar["status"] = "invalid"
    write_json(path, sidecar)

    assert check.main(["--root", str(root)]) == 1


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
