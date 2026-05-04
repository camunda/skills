"""Unit tests for path relativization."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paths import is_machine_path, relativize_grading  # noqa: E402


def test_relativize_simple_dict():
    obj = {"file": "/work/it-7/outputs/answer.feel"}
    out = relativize_grading("/work/it-7", obj)
    assert out == {"file": "outputs/answer.feel"}


def test_relativize_workspace_root_itself():
    obj = {"root": "/work/it-7"}
    out = relativize_grading("/work/it-7", obj)
    assert out == {"root": ""}


def test_relativize_unrelated_path_unchanged():
    obj = {"file": "/etc/hosts", "tmpfs": "/var/tmp/foo"}
    out = relativize_grading("/work/it-7", obj)
    assert out == obj


def test_relativize_nested_structure():
    obj = {
        "results": [
            {"path": "/work/it-7/with_skill/case-1/grading.json", "ok": True},
            {"path": "/work/it-7/without_skill/case-1/grading.json", "ok": False},
        ],
        "count": 2,
        "root": "/work/it-7",
    }
    out = relativize_grading("/work/it-7", obj)
    assert out == {
        "results": [
            {"path": "with_skill/case-1/grading.json", "ok": True},
            {"path": "without_skill/case-1/grading.json", "ok": False},
        ],
        "count": 2,
        "root": "",
    }


def test_relativize_macos_users():
    obj = {"file": "/Users/alice/work/eval/it-3/answer.feel"}
    out = relativize_grading("/Users/alice/work/eval/it-3", obj)
    assert out == {"file": "answer.feel"}


def test_relativize_normalizes_double_slashes():
    obj = {"file": "/work/it-7//outputs//answer.feel"}
    out = relativize_grading("/work/it-7", obj)
    assert out == {"file": "outputs/answer.feel"}


def test_is_machine_path():
    assert is_machine_path("/home/user/x")
    assert is_machine_path("/Users/alice/x")
    assert is_machine_path("C:\\Users\\bob")
    assert not is_machine_path("relative/path")
    assert not is_machine_path("/etc/hosts")
    assert not is_machine_path(123)  # non-string returns False
