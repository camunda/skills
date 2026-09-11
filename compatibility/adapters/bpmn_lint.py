"""Small deterministic BPMN validity check used by the mock c8ctl command."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

BPMN_NAMESPACE = "http://www.omg.org/spec/BPMN/20100524/MODEL"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def validate_bpmn(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"{path} does not exist")

    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise ValueError(f"{path} is not well-formed XML: {error}") from error

    if root.tag != f"{{{BPMN_NAMESPACE}}}definitions":
        raise ValueError("root element must be BPMN definitions")

    processes = [element for element in root if local_name(element.tag) == "process"]
    if len(processes) != 1:
        raise ValueError("artifact must contain exactly one process")

    process = processes[0]
    if not process.get("id"):
        raise ValueError("process must have an id")

    element_ids = {
        element.get("id")
        for element in process
        if element.get("id")
    }
    if not any(local_name(element.tag) == "startEvent" for element in process):
        raise ValueError("process must contain a start event")
    if not any(local_name(element.tag) == "endEvent" for element in process):
        raise ValueError("process must contain an end event")

    flows = [element for element in process if local_name(element.tag) == "sequenceFlow"]
    if not flows:
        raise ValueError("process must contain a sequence flow")
    for flow in flows:
        if flow.get("sourceRef") not in element_ids or flow.get("targetRef") not in element_ids:
            raise ValueError("sequence flow references an unknown element")
