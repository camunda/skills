"""camunda-process-test outcome eval: test-spec-first Markdown planning."""

from __future__ import annotations

import re

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-process-test"], max_sandboxes=1)
SPEC_PATH = "/workspace/TESTING.md"
TOOLS = ("ListUsers", "Search_Recipe", "Jokes_API", "Activity_0x3prgn")


def _artifact(state: TaskState) -> str:
    artifacts = state.store.get("artifacts") or {}
    value = artifacts.get(SPEC_PATH, "")
    return value if isinstance(value, str) else ""


def _section(markdown: str, heading_pattern: str) -> str:
    lines = markdown.splitlines()
    matches: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        heading = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if heading and re.fullmatch(
            heading_pattern, heading.group(2), re.IGNORECASE
        ):
            matches.append((index, heading))
    if not matches:
        return ""
    index, heading = min(matches, key=lambda match: len(match[1].group(1)))
    level = len(heading.group(1))
    end = len(lines)
    for next_index in range(index + 1, len(lines)):
        next_heading = re.match(r"^(#{2,6})\s+", lines[next_index])
        if next_heading and len(next_heading.group(1)) <= level:
            end = next_index
            break
    return "\n".join(lines[index + 1 : end]).strip()


def _table_rows(section: str) -> list[str]:
    return [
        line
        for line in section.splitlines()
        if line.strip().startswith("|")
        and "---" not in line
        and not re.search(r"\|\s*(ID|Layer|#|Artifact)\s*\|", line, re.I)
    ]


@scorer(metrics=[mean(), stderr()])
def test_spec_complete() -> Scorer:
    """Score a process-specific Markdown test specification."""

    async def score(state: TaskState, target: Target) -> Score:
        markdown = _artifact(state)
        if not markdown:
            return Score(value=0.0, explanation=f"missing {SPEC_PATH}")

        failures: list[str] = []
        sections = {
            "strategy": _section(markdown, r".*(?:strategy|test layers).*"),
            "requirements": _section(
                markdown, r".*(?:requirements|traceability|acceptance criteria).*"
            ),
            "thresholds": _section(markdown, r".*coverage thresholds.*"),
            "e2e": _section(markdown, r".*(?:end-to-end|e2e).*"),
            "run": _section(
                markdown,
                r".*(?:running|how to run|run instructions|commands.*prerequisites).*",
            ),
            "artifacts": _section(markdown, r".*(?:artifacts|links|where tests live).*"),
            "approval": _section(
                markdown, r".*(?:approval|open questions|decisions needed).*"
            ),
        }
        for name, content in sections.items():
            if not content:
                failures.append(f"missing {name} section")

        strategy = sections["strategy"].lower()
        layer_patterns = {
            "process": r"\bprocess\b",
            "segment integration": r"\bsegment.{0,10}integration\b|point integration",
            "process integration": r"\bprocess integration\b|whole-process",
        }
        for layer, pattern in layer_patterns.items():
            if not re.search(pattern, strategy):
                failures.append(f"strategy does not distinguish {layer} tests")
        if not all(term in strategy for term in ("purpose", "external", "run")):
            failures.append(
                "strategy omits purpose, isolation/external systems, or cadence"
            )

        requirement_rows = _table_rows(sections["requirements"])
        requirement_ids = set(
            re.findall(r"\b(?:PR|SIR|PIR)-\d+\b", sections["requirements"])
        )
        if len(requirement_ids) < 7 or len(requirement_rows) < 7:
            failures.append("fewer than 7 traceable requirements")
        for term in ("requirement", "layer", "scenario", "evidence"):
            if term not in sections["requirements"].lower():
                failures.append(f"requirements matrix lacks {term}")

        thresholds = sections["thresholds"]
        if len(re.findall(r"\b\d{1,3}%(?=\s|[|,.;)]|$)", thresholds)) < 3:
            failures.append("coverage thresholds lack numeric per-layer gates")
        if not re.search(
            r"user.{0,20}(tunable|adjust|approve)|agreed|approval", thresholds, re.I
        ):
            failures.append("coverage thresholds are not explicitly user-tunable")
        for term in ("target", "gate", "report"):
            if term not in thresholds.lower():
                failures.append(f"coverage thresholds lack {term}")

        e2e = sections["e2e"]
        e2e_scenarios = max(
            len(_table_rows(e2e)),
            len(re.findall(r"(?im)^#{3,6}\s+scenario\b", e2e)),
        )
        if e2e_scenarios < 3:
            failures.append("fewer than 3 plain-language E2E scenarios")
        for term in ("expected outcome", "terminal", "requirement"):
            if term not in e2e.lower():
                failures.append(f"E2E catalogue lacks {term}")
        if not re.search(r"reject|not satisfied", e2e, re.I) or not re.search(
            r"follow.?up|approve|satisfied", e2e, re.I
        ):
            failures.append("E2E catalogue omits feedback retry then approval")
        missing_tools = [tool for tool in TOOLS if tool not in markdown]
        if missing_tools:
            failures.append(f"canonical tools missing: {missing_tools}")

        run = sections["run"]
        commands = re.findall(r"mvn(?:w)?\s+test\b[^\n`]*", run, re.I)
        if len(commands) < 3 or not re.search(r"integration|e2e", run, re.I):
            failures.append("run instructions omit process or integration commands")
        if "prerequisite" not in run.lower() and "requires" not in run.lower():
            failures.append("run instructions omit prerequisites")
        if "report" not in run.lower():
            failures.append("run instructions omit report locations")

        artifacts = sections["artifacts"]
        artifact_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", artifacts)
        if len(artifact_links) < 2:
            failures.append("artifact section has fewer than 2 Markdown links")
        if any(target.strip() in {"", "#"} for target in artifact_links):
            failures.append("artifact section contains placeholder links")
        if not all(term in artifacts.lower() for term in ("bpmn", "spec")):
            failures.append("artifact section does not link the BPMN and test spec")

        approval = sections["approval"]
        if not re.search(
            r"do not implement|before implementation|approval required", approval, re.I
        ):
            failures.append("spec lacks an explicit pre-implementation approval gate")
        if not re.search(r"open question|decision", approval, re.I):
            failures.append("spec lacks unresolved questions/decisions")
        if not re.search(r"\b(draft|approved|status)\b", approval, re.I):
            failures.append("spec lacks approval status")

        return Score(
            value=0.0 if failures else 1.0,
            explanation="; ".join(failures)
            or (
                f"complete test specification: {len(requirement_ids)} requirements, "
                f"{e2e_scenarios} E2E scenarios"
            ),
            metadata={
                "requirements": sorted(requirement_ids),
                "e2e_scenarios": e2e_scenarios,
            },
        )

    return score


PROMPT = """
Use the camunda-process-test skill to create the test specification for the
canonical process at `/fixture/ai-agent-chat-with-tools.bpmn`. This is
test-spec-first planning: write only `/workspace/TESTING.md`; do not create test
code, a Maven project, JSON scenarios, or reports.

The Markdown must be useful for an arbitrary-process workflow and specific
enough that a user can review and iterate on it before approving implementation.
Include:

1. A high-level layered strategy separating deterministic process tests,
   segment/point integration tests, and whole-process integration/E2E tests.
   State each layer's purpose, isolation/external-system boundary, acceptance
   signal, and execution cadence.
2. A requirement traceability matrix with stable IDs (PR, SIR, PIR), business
   requirement, test layer, named scenario/test, evidence/assertions, dependency
   or status, and comments. Explain assertion philosophy and out-of-scope items.
3. Numeric target and machine-gate coverage thresholds for every layer, report
   source, current rationale, and a clear statement that thresholds are
   user-tunable and must be approved.
4. At least three realistic E2E scenarios in plain business language, including
   inputs/context, expected outcome, terminal element, expected tool set,
   requirement ID, and determinism/retry policy.
5. Exact commands and prerequisites for running each layer, plus report paths.
6. Markdown links to the source BPMN, this spec, planned test artifacts, CPT
   documentation, and any fixture/dependency documentation. Every artifact
   entry must use `[descriptive label](target)` Markdown link syntax; do not
   list a plain or backticked path in place of a link, and never use `#` or an
   empty target as a placeholder.
7. Assumptions, open questions/decisions, and an explicit `DRAFT` human approval
   gate saying not to implement tests until the user approves the requirements,
   scenarios, dependencies, and thresholds.

Process topology:
- Process ID: `ai-agent-chat-with-tools`.
- The `AI_Agent` ad-hoc subprocess can answer with no tool or invoke four tools:
  `ListUsers`, `Search_Recipe`, `Jokes_API`, `Activity_0x3prgn`.
- `User_Feedback` asks whether the response is satisfactory.
- Satisfied feedback reaches `Event_0i39jej`; rejected feedback supplies
  follow-up input and loops through `AI_Agent` again.
- Required realistic journey: first response invokes two tools, the user rejects
  it with follow-up input, the second response invokes the other two tools, then
  the user approves and the process completes. Do not assert tool order.
- Mandatory CI must be credential-free and deterministic; live endpoints/model
  runs are optional and documented separately.

Use repository-relative links where future artifacts do not exist yet and label
them `planned`. Save only the polished Markdown specification to
`/workspace/TESTING.md`, then stop for human review.
"""

SAMPLES = [Sample(id="agentic-test-specification", input=PROMPT)]


@task
def camunda_process_test(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            test_spec_complete(),
            assert_skill_loaded("camunda-process-test", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-advisory.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=900,
        token_limit=250_000,
        message_limit=30,
    )
