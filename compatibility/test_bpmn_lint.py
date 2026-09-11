from pathlib import Path

import pytest

from adapters.bpmn_lint import validate_bpmn


FIXTURE = Path(__file__).with_name("fixtures") / "process.bpmn"


def copy_fixture(tmp_path: Path) -> Path:
    artifact = tmp_path / "process.bpmn"
    artifact.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return artifact


def test_rejects_flow_nodes_with_dangling_references(tmp_path: Path) -> None:
    artifact = copy_fixture(tmp_path)
    content = artifact.read_text(encoding="utf-8").replace(
        "<bpmn:incoming>Flow_1</bpmn:incoming>",
        "<bpmn:incoming>Missing</bpmn:incoming>",
        1,
    )
    artifact.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="incoming references"):
        validate_bpmn(artifact)


def test_rejects_unsupported_process_elements(tmp_path: Path) -> None:
    artifact = copy_fixture(tmp_path)
    content = artifact.read_text(encoding="utf-8").replace(
        '    <bpmn:sequenceFlow id="Flow_1"',
        '    <bpmn:bogus id="Bogus" name="Bogus" />\n'
        '    <bpmn:sequenceFlow id="Flow_1"',
        1,
    )
    artifact.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported process element"):
        validate_bpmn(artifact)


def test_rejects_elements_reusing_definitions_id(tmp_path: Path) -> None:
    artifact = copy_fixture(tmp_path)
    content = artifact.read_text(encoding="utf-8").replace(
        'id="StartEvent_1"',
        'id="Definitions_1"',
        1,
    )
    artifact.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate BPMN id"):
        validate_bpmn(artifact)
