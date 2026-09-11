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
