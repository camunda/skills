"""Small deterministic BPMN validity check used by the mock c8ctl command."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

BPMN_NAMESPACE = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NAMESPACE = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NAMESPACE = "http://www.omg.org/spec/DD/20100524/DC"
DI_NAMESPACE = "http://www.omg.org/spec/DD/20100524/DI"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
ZEEBE_NAMESPACE = "http://camunda.org/schema/zeebe/1.0"
MODELER_NAMESPACE = "http://camunda.org/schema/modeler/1.0"

REQUIRED_NAMESPACES = {
    "bpmn": BPMN_NAMESPACE,
    "bpmndi": BPMNDI_NAMESPACE,
    "dc": DC_NAMESPACE,
    "di": DI_NAMESPACE,
    "xsi": XSI_NAMESPACE,
    "zeebe": ZEEBE_NAMESPACE,
    "modeler": MODELER_NAMESPACE,
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def validate_bpmn(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"{path} does not exist")

    try:
        root = None
        namespace_uris: set[str] = set()
        for event, value in ElementTree.iterparse(path, events=("start", "start-ns")):
            if event == "start-ns":
                _, uri = value
                namespace_uris.add(uri)
            elif root is None:
                root = value
    except (OSError, ElementTree.ParseError) as error:
        raise ValueError(f"{path} is not well-formed XML: {error}") from error

    if root is None or root.tag != f"{{{BPMN_NAMESPACE}}}definitions":
        raise ValueError("root element must be BPMN definitions")

    for uri in REQUIRED_NAMESPACES.values():
        if uri not in namespace_uris:
            raise ValueError(f"required namespace URI {uri!r} is not declared")

    definitions_id = root.get("id")
    if not definitions_id:
        raise ValueError("definitions must have an id")
    if not root.get("targetNamespace"):
        raise ValueError("definitions must have a targetNamespace")
    modeler_prefix = f"{{{MODELER_NAMESPACE}}}"
    if root.get(f"{modeler_prefix}executionPlatform") != "Camunda Cloud":
        raise ValueError("definitions must declare Camunda Cloud as the execution platform")
    if not root.get(f"{modeler_prefix}executionPlatformVersion"):
        raise ValueError("definitions must declare an execution platform version")

    processes = [element for element in root if element.tag == f"{{{BPMN_NAMESPACE}}}process"]
    if len(processes) != 1:
        raise ValueError("artifact must contain exactly one process")

    process = processes[0]
    process_id = process.get("id")
    if not process_id:
        raise ValueError("process must have an id")
    if process_id == definitions_id:
        raise ValueError(f"duplicate BPMN id: {process_id}")
    if process.get("isExecutable") != "true":
        raise ValueError("process must be executable")

    element_ids: set[str] = set()
    for element in root.iter():
        if not isinstance(element.tag, str) or not element.tag.startswith(
            f"{{{BPMN_NAMESPACE}}}"
        ):
            continue
        element_id = element.get("id")
        if element_id:
            if element_id in element_ids:
                raise ValueError(f"duplicate BPMN id: {element_id}")
            element_ids.add(element_id)

    flow_nodes = []
    flows = []
    for element in process:
        if not isinstance(element.tag, str):
            continue
        element_id = element.get("id")
        if not element_id:
            if local_name(element.tag) in {"extensionElements", "laneSet"}:
                continue
            raise ValueError(f"{local_name(element.tag)} must have an id")
        if local_name(element.tag) == "sequenceFlow":
            flows.append(element)
        else:
            if not element.get("name"):
                raise ValueError(f"{local_name(element.tag)} must have a name")
            flow_nodes.append(element)

    if not any(local_name(element.tag) == "startEvent" for element in flow_nodes):
        raise ValueError("process must contain a start event")
    if not any(local_name(element.tag) == "endEvent" for element in flow_nodes):
        raise ValueError("process must contain an end event")

    if not flows:
        raise ValueError("process must contain a sequence flow")
    flow_node_ids = {node.get("id") for node in flow_nodes}
    outgoing = {node_id: set() for node_id in flow_node_ids}
    incoming = {node_id: set() for node_id in flow_node_ids}
    for flow in flows:
        source = flow.get("sourceRef")
        target = flow.get("targetRef")
        if (
            source not in flow_node_ids
            or target not in flow_node_ids
        ):
            raise ValueError("sequence flow references an unknown element")
        outgoing[source].add(target)
        incoming[target].add(source)

    def reachable(
        starts: set[str | None], graph: dict[str | None, set[str | None]]
    ) -> set[str | None]:
        reached = set(starts)
        pending = list(starts)
        while pending:
            current = pending.pop()
            for neighbor in graph[current]:
                if neighbor not in reached:
                    reached.add(neighbor)
                    pending.append(neighbor)
        return reached

    start_ids = {
        node.get("id") for node in flow_nodes if local_name(node.tag) == "startEvent"
    }
    end_ids = {
        node.get("id") for node in flow_nodes if local_name(node.tag) == "endEvent"
    }
    reachable_from_start = reachable(start_ids, outgoing)
    can_reach_end = reachable(end_ids, incoming)
    disconnected = (flow_node_ids - reachable_from_start) | (flow_node_ids - can_reach_end)
    if disconnected:
        raise ValueError("all flow nodes must be on a complete start-to-end path")

    di_ids: set[str] = set()
    for element in root.iter():
        if not isinstance(element.tag, str) or not element.tag.startswith(
            f"{{{BPMNDI_NAMESPACE}}}"
        ):
            continue
        element_id = element.get("id")
        if not element_id:
            raise ValueError(f"{local_name(element.tag)} must have an id")
        if element_id in element_ids or element_id in di_ids:
            raise ValueError(f"duplicate BPMN DI id: {element_id}")
        di_ids.add(element_id)

    diagrams = [element for element in root.iter() if element.tag == f"{{{BPMNDI_NAMESPACE}}}BPMNDiagram"]
    if len(diagrams) != 1:
        raise ValueError("artifact must contain exactly one BPMN diagram")
    planes = [element for element in diagrams[0] if element.tag == f"{{{BPMNDI_NAMESPACE}}}BPMNPlane"]
    if len(planes) != 1 or planes[0].get("bpmnElement") != process_id:
        raise ValueError("BPMN diagram must contain one plane for the process")

    shapes = [
        element
        for element in planes[0]
        if element.tag == f"{{{BPMNDI_NAMESPACE}}}BPMNShape"
    ]
    shape_refs = [shape.get("bpmnElement") for shape in shapes]
    node_ids = {element.get("id") for element in flow_nodes}
    if None in shape_refs or len(shape_refs) != len(set(shape_refs)) or set(shape_refs) != node_ids:
        raise ValueError("BPMN diagram shapes must map one-to-one to process flow nodes")
    for shape in shapes:
        if not any(child.tag == f"{{{DC_NAMESPACE}}}Bounds" for child in shape):
            raise ValueError("every BPMN shape must have bounds")

    edges = [
        element
        for element in planes[0]
        if element.tag == f"{{{BPMNDI_NAMESPACE}}}BPMNEdge"
    ]
    edge_refs = [edge.get("bpmnElement") for edge in edges]
    flow_ids = {flow.get("id") for flow in flows}
    if None in edge_refs or len(edge_refs) != len(set(edge_refs)) or set(edge_refs) != flow_ids:
        raise ValueError("BPMN diagram edges must map one-to-one to sequence flows")
    for edge in edges:
        if sum(child.tag == f"{{{DI_NAMESPACE}}}waypoint" for child in edge) < 2:
            raise ValueError("every BPMN edge must have at least two waypoints")
