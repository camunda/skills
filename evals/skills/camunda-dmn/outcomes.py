"""camunda-dmn outcome eval: author lintable DMN decision tables with expected logic."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-dmn"])

DMN_NS = "https://www.omg.org/spec/DMN/20191111/MODEL/"
CAMUNDA_NAMESPACE = "http://camunda.org/schema/1.0/dmn"
NS = {"dmn": DMN_NS}

SAVE = "\n\nSave the DMN file to /workspace/decision.dmn."

SAMPLES = [
    Sample(
        id="shipping-method-unique",
        input=(
            "Create one DMN 1.3 decision table in a file named decision.dmn. "
            "Use decision id shippingMethod, name 'Shipping Method', hit policy UNIQUE. "
            "One input: packageWeight (number). One output: method (string). "
            "Rules (mutually exclusive): packageWeight < 2 -> \"LETTER\"; "
            "2 <= packageWeight <= 20 -> \"PARCEL\"; "
            "packageWeight > 20 -> \"FREIGHT\"." + SAVE
        ),
        metadata={"check": "shipping-method-unique"},
    ),
    Sample(
        id="discount-collect-sum",
        input=(
            "Create one DMN 1.3 decision table in a file named decision.dmn. "
            "Use decision id totalDiscount, name 'Total Discount', hit policy COLLECT with SUM aggregation. "
            "Inputs: customerType (string), amount (number). Output: discount (number). "
            "Rules: customerType = \"VIP\" -> 10; amount > 1000 -> 5; amount > 5000 -> 15." + SAVE
        ),
        metadata={"check": "discount-collect-sum"},
    ),
]


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split())


def _rule_pairs(table: ET.Element) -> set[tuple[tuple[str, ...], str]]:
    pairs: set[tuple[tuple[str, ...], str]] = set()
    for rule in table.findall("dmn:rule", NS):
        inputs = tuple(
            _normalize(entry.findtext("dmn:text", default="", namespaces=NS)) or "-"
            for entry in rule.findall("dmn:inputEntry", NS)
        )
        output = _normalize(
            (rule.find("dmn:outputEntry", NS) or ET.Element("x")).findtext(
                "dmn:text", default="", namespaces=NS
            )
        )
        pairs.add((inputs, output))
    return pairs


def _input_names(table: ET.Element) -> tuple[str, ...]:
    names: list[str] = []
    for inp in table.findall("dmn:input", NS):
        expr = inp.find("dmn:inputExpression", NS)
        text = ""
        if expr is not None:
            text = expr.findtext("dmn:text", default="", namespaces=NS)
        names.append(_normalize(text))
    return tuple(names)


def _validate_common(root: ET.Element) -> str | None:
    if _tag_name(root.tag) != "definitions":
        return "root element is not <definitions>"
    if root.attrib.get("namespace") != CAMUNDA_NAMESPACE:
        return "definitions@namespace is missing or not camunda dmn namespace"
    decision_tables = root.findall("dmn:decision/dmn:decisionTable", NS)
    if len(decision_tables) != 1:
        return f"expected exactly one decisionTable, found {len(decision_tables)}"
    return None


@scorer(metrics=[mean(), stderr()])
def dmn_outcome() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        sb = sandbox()
        read = await sb.exec(["cat", "/workspace/decision.dmn"], timeout=10)
        if read.returncode != 0:
            return Score(value=0.0, explanation="/workspace/decision.dmn not created")

        try:
            root = ET.fromstring(read.stdout)
        except ET.ParseError as exc:
            return Score(value=0.0, explanation=f"invalid XML: {exc}")

        common_error = _validate_common(root)
        if common_error:
            return Score(value=0.0, explanation=common_error)

        lint = await sb.exec(
            ["npx", "--yes", "dmnlint", "/workspace/decision.dmn"], timeout=60
        )
        if lint.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"dmnlint failed:\n{(lint.stdout + lint.stderr).strip()[-800:]}",
            )

        table = root.find("dmn:decision/dmn:decisionTable", NS)
        decision = root.find("dmn:decision", NS)
        if table is None or decision is None:
            return Score(value=0.0, explanation="missing decision or decisionTable")

        check = (state.metadata or {}).get("check")
        if check == "shipping-method-unique":
            if decision.attrib.get("id") != "shippingMethod":
                return Score(value=0.0, explanation="expected decision id shippingMethod")
            if table.attrib.get("hitPolicy") != "UNIQUE":
                return Score(value=0.0, explanation="expected hitPolicy UNIQUE")
            if _input_names(table) != ("packageWeight",):
                return Score(
                    value=0.0,
                    explanation="expected one input expression: packageWeight",
                )
            expected = {
                (("< 2",), '"LETTER"'),
                (("[2..20]",), '"PARCEL"'),
                (("> 20",), '"FREIGHT"'),
            }
            actual = _rule_pairs(table)
            if expected - actual:
                return Score(
                    value=0.0,
                    explanation=f"missing expected rules: {sorted(expected - actual)}",
                )
            return Score(
                value=1.0,
                explanation="UNIQUE table and expected shipping rules found",
            )

        if check == "discount-collect-sum":
            if decision.attrib.get("id") != "totalDiscount":
                return Score(value=0.0, explanation="expected decision id totalDiscount")
            if table.attrib.get("hitPolicy") != "COLLECT":
                return Score(value=0.0, explanation="expected hitPolicy COLLECT")
            if table.attrib.get("aggregation") != "SUM":
                return Score(value=0.0, explanation="expected COLLECT aggregation SUM")
            if _input_names(table) != ("customerType", "amount"):
                return Score(
                    value=0.0,
                    explanation="expected input expressions customerType, amount",
                )
            expected = {
                (("\"VIP\"", "-"), "10"),
                (("-", "> 1000"), "5"),
                (("-", "> 5000"), "15"),
            }
            actual = _rule_pairs(table)
            if expected - actual:
                return Score(
                    value=0.0,
                    explanation=f"missing expected rules: {sorted(expected - actual)}",
                )
            return Score(
                value=1.0,
                explanation="COLLECT/SUM table and expected discount rules found",
            )

        return Score(value=0.0, explanation=f"unknown check: {check!r}")

    return score


@task
def camunda_dmn(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        # submit=False: decision.dmn is the deliverable; score from the file.
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            dmn_outcome(),
            assert_skill_loaded("camunda-dmn", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=300,
        token_limit=120_000,
        message_limit=50,
    )
