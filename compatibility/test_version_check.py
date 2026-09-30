import json
import shutil
from pathlib import Path

import version_check


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def copy_version_root(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir(parents=True)
    shutil.copy(REPOSITORY_ROOT / "plugin.json", root / "plugin.json")
    shutil.copy(REPOSITORY_ROOT / "version.txt", root / "version.txt")
    shutil.copytree(REPOSITORY_ROOT / ".claude-plugin", root / ".claude-plugin")
    shutil.copytree(REPOSITORY_ROOT / ".github" / "plugin", root / ".github" / "plugin")
    return root


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_passes_on_matching_manifests(tmp_path: Path) -> None:
    root = copy_version_root(tmp_path)
    assert version_check.main(["--root", str(root)]) == 0


def test_rejects_missing_manifest(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    (root / ".claude-plugin" / "plugin.json").unlink()

    assert version_check.main(["--root", str(root)]) == 1
    assert "manifest does not exist" in capsys.readouterr().err


def test_rejects_missing_version_field(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    path = root / ".claude-plugin" / "plugin.json"
    document = read_json(path)
    assert isinstance(document, dict)
    del document["version"]
    write_json(path, document)

    assert version_check.main(["--root", str(root)]) == 1
    assert "version field is missing" in capsys.readouterr().err


def test_rejects_version_drift(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    path = root / ".claude-plugin" / "plugin.json"
    document = read_json(path)
    assert isinstance(document, dict)
    document["version"] = "0.0.0"
    write_json(path, document)

    assert version_check.main(["--root", str(root)]) == 1
    assert "!= source-of-truth" in capsys.readouterr().err


def test_rejects_invalid_semver_leading_zero_major(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    path = root / "plugin.json"
    document = read_json(path)
    assert isinstance(document, dict)
    document["version"] = "01.2.3"
    write_json(path, document)

    assert version_check.main(["--root", str(root)]) == 1
    assert "expected a semantic version" in capsys.readouterr().err


def test_rejects_invalid_semver_leading_zero_prerelease(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    path = root / "plugin.json"
    document = read_json(path)
    assert isinstance(document, dict)
    document["version"] = "1.2.3-01"
    write_json(path, document)

    assert version_check.main(["--root", str(root)]) == 1
    assert "expected a semantic version" in capsys.readouterr().err


def test_rejects_invalid_semver_empty_prerelease_identifier(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    path = root / "plugin.json"
    document = read_json(path)
    assert isinstance(document, dict)
    document["version"] = "1.2.3-alpha..1"
    write_json(path, document)

    assert version_check.main(["--root", str(root)]) == 1
    assert "expected a semantic version" in capsys.readouterr().err


def test_accepts_valid_semver_with_prerelease_and_build(tmp_path: Path) -> None:
    root = copy_version_root(tmp_path)
    version = "1.2.3-alpha.1+build.123"
    for manifest in (
        root / "plugin.json",
        root / ".claude-plugin" / "plugin.json",
        root / ".claude-plugin" / "marketplace.json",
        root / ".github" / "plugin" / "marketplace.json",
    ):
        document = read_json(manifest)
        assert isinstance(document, dict)
        if "version" in document:
            document["version"] = version
        if "metadata" in document and isinstance(document["metadata"], dict):
            document["metadata"]["version"] = version
        if "plugins" in document and isinstance(document["plugins"], list):
            for plugin in document["plugins"]:
                if isinstance(plugin, dict) and "version" in plugin:
                    plugin["version"] = version
        write_json(manifest, document)

    (root / "version.txt").write_text(version + "\n", encoding="utf-8")

    assert version_check.main(["--root", str(root)]) == 0


def test_rejects_version_txt_drift(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    (root / "version.txt").write_text("0.0.0\n", encoding="utf-8")

    assert version_check.main(["--root", str(root)]) == 1
    err = capsys.readouterr().err
    assert "version.txt" in err
    assert "!= source-of-truth" in err


def test_rejects_missing_version_txt(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    (root / "version.txt").unlink()

    assert version_check.main(["--root", str(root)]) == 1
    assert "version file does not exist" in capsys.readouterr().err


def test_rejects_invalid_semver_version_txt(tmp_path: Path, capsys: object) -> None:
    root = copy_version_root(tmp_path)
    (root / "version.txt").write_text("not-a-version\n", encoding="utf-8")

    assert version_check.main(["--root", str(root)]) == 1
    assert "expected a semantic version" in capsys.readouterr().err
