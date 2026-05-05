"""Smoke tests for the static report generator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report import render_index, render_iteration  # noqa: E402


def _scaffold_iteration(root: Path, skill: str, n: int, with_bpmn: bool = False) -> Path:
    it = root / "evals" / skill / f"iteration-{n}"
    (it / "with_skill" / "case-a" / "outputs").mkdir(parents=True)
    (it / "without_skill" / "case-a" / "outputs").mkdir(parents=True)
    (it / "with_skill" / "case-a" / "outputs" / "answer.feel").write_text(
        "if amount > 1000 then amount * 0.85 else amount", encoding="utf-8"
    )
    (it / "without_skill" / "case-a" / "outputs" / "answer.feel").write_text(
        "amount * 0.85", encoding="utf-8"
    )
    if with_bpmn:
        bpmn = '<?xml version="1.0"?><definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"/>'
        (it / "with_skill" / "case-a" / "outputs" / "process.bpmn").write_text(bpmn, encoding="utf-8")
    (it / "with_skill" / "case-a" / "grading.json").write_text(
        json.dumps(
            {
                "summary": {"passed": 2, "total": 2},
                "expectations": [
                    {"text": "uses if-then-else", "passed": True, "evidence": "ok"},
                    {"text": "applies discount", "passed": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    (it / "with_skill" / "case-a" / "eval_metadata.json").write_text(
        json.dumps({"prompt": "Write a discount expression"}), encoding="utf-8"
    )
    (it / "summary.json").write_text(
        json.dumps(
            {
                "skill": skill,
                "iteration": it.name,
                "generated_at": "2026-05-04T12:00:00+00:00",
                "git_head": "abc123",
                "status": "test",
                "triggers": {"f1": 0.91},
                "quality": {
                    "with_skill": {"pass_rate": 0.88, "n_cases": 1, "n_trials": 3},
                    "without_skill": {"pass_rate": 0.42, "n_cases": 1, "n_trials": 3},
                    "delta_pp": 46.0,
                },
            }
        ),
        encoding="utf-8",
    )
    return it


def test_render_iteration_text_only(tmp_path):
    it = _scaffold_iteration(tmp_path, "camunda-feel", 1)
    out = render_iteration(it, tmp_path)
    assert out.name == "report.html"
    html = out.read_text(encoding="utf-8")
    # Core structural assertions.
    assert "camunda-feel" in html
    assert "iteration-1" in html
    assert "case-a" in html
    assert "Write a discount expression" in html
    # Both arms render.
    assert "with_skill" in html and "without_skill" in html
    # FEEL content embedded as text (escaped).
    assert "amount &gt; 1000" in html
    # Grading rendered.
    assert "Assertions (2/2)" in html
    # Summary stats present.
    assert "0.91" in html  # F1
    assert "46.00" in html  # delta_pp
    # No BPMN -> no bpmn-js script tag.
    assert "bpmn-viewer" not in html


def test_render_iteration_with_bpmn_includes_cdn(tmp_path):
    it = _scaffold_iteration(tmp_path, "camunda-bpmn", 1, with_bpmn=True)
    out = render_iteration(it, tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "bpmn-viewer.production.min.js" in html
    assert "integrity=\"sha384-" in html
    assert "data-bpmn=" in html


def test_render_index(tmp_path):
    _scaffold_iteration(tmp_path, "camunda-feel", 1)
    _scaffold_iteration(tmp_path, "camunda-feel", 2)
    skill_dir = tmp_path / "evals" / "camunda-feel"
    out = render_index(skill_dir)
    assert out.name == "index.html"
    html = out.read_text(encoding="utf-8")
    assert "iteration-1" in html and "iteration-2" in html
    assert 'href="iteration-1/report.html"' in html
    assert 'href="iteration-2/report.html"' in html


def test_render_index_empty(tmp_path):
    skill_dir = tmp_path / "evals" / "camunda-feel"
    skill_dir.mkdir(parents=True)
    out = render_index(skill_dir)
    html = out.read_text(encoding="utf-8")
    assert "No iterations yet" in html


def test_iteration_navigation_links(tmp_path):
    _scaffold_iteration(tmp_path, "camunda-feel", 1)
    it2 = _scaffold_iteration(tmp_path, "camunda-feel", 2)
    _scaffold_iteration(tmp_path, "camunda-feel", 3)
    html = render_iteration(it2, tmp_path).read_text(encoding="utf-8")
    assert "../iteration-1/report.html" in html
    assert "../iteration-3/report.html" in html
    assert "../index.html" in html
