---
name: camunda-process-test
description: |
  Use this skill to author and run Camunda Process Test (CPT) suites that cover every BPMN gateway branch, DMN rule, and error boundary to 100%.

  Use for: scaffolding the `camunda-process-test-spring` harness, planning the minimum set of test segments for full element coverage, authoring `.test.json` instruction-based scenarios, running `mvn test`, parsing the CPT coverage report, deduplicating redundant segments.

  Do not use for: authoring the BPMN (use camunda-bpmn), writing FEEL or DMN expressions (use camunda-feel), deploying to a live cluster (use camunda-process-mgmt), UI or E2E tests against Operate or Tasklist.

  **Workflow skill** — segment-based authoring loop covering `mvn test`, coverage report parsing, and scenario deduplication.
---

# Camunda Process Test

Author and run Camunda Process Test suites for Camunda 8.8+ that reach **100% BPMN element coverage** with the minimum number of test segments. Test assertions are limited to reachability and routing — CPT exercises that the engine traverses the right elements, not the data values produced by service tasks or external systems.

## Prerequisites

- Java 21+, Maven (or `./mvnw`), Docker runtime (OrbStack, Docker Desktop, or Rancher Desktop) — see [references/setup.md](references/setup.md)
- `camunda-process-test-spring` 8.9+ on the test classpath (instruction-based JSON format requires 8.9)
- A working BPMN file (lint clean — see camunda-bpmn). DMN and form files referenced by the BPMN must also be present.

## Cross-References

- **camunda-bpmn**: Run `c8ctl bpmn lint` on the process under test before authoring scenarios — failing lints surface as deploy-time `@TestDeployment` failures.
- **camunda-feel**: Use when a gateway condition or DMN entry is unclear; FEEL semantics drive which segment hits which branch.
- **camunda-process-mgmt**: CPT runs against an **embedded** Zeebe engine — it does **not** use the c8ctl-managed cluster or any profile. No `c8ctl` call deploys a process under test.

## Scope boundaries

- **In scope**: BPMN reachability (every element visited at least once), gateway-branch selection, DMN rule selection, error-boundary firing, timer / escalation boundary firing, end-event selection.
- **Out of scope**: asserting data values produced by service tasks, external system payloads, UI behavior, agent / LLM output. Do not write `ASSERT_VARIABLE` instructions on service-task output unless the variable is the FEEL input to a downstream gateway you also test.

## Workflow

### 1. Detect

Find the BPMN under test in priority order:

1. `src/main/resources/processes/`
2. `src/main/resources/bpmn/`
3. `../resources/` (Node.js layouts where the test harness lives in `test/`)

Skip `target/`, `node_modules/`, `.git/`, `build/`. If multiple files match, list them and ask which to target.

Check `pom.xml` (or `test/pom.xml`) for `camunda-process-test-spring`. If missing, go to step 2.

### 2. Setup (only if missing)

Follow [references/setup.md](references/setup.md): verify Java 21+, Maven, Docker; add the CPT dependency; scaffold `src/test/java/io/camunda/tests/ProcessTest.java` and `src/test/resources/scenarios/`. Confirm with `mvn test-compile`.

### 3. Plan segments

Apply [references/coverage-strategy.md](references/coverage-strategy.md):

1. Parse the BPMN: `processId`, element IDs and types, gateway outgoing flows + conditions, error / timer / escalation boundaries, end events, called DMN decisions (`<zeebe:calledDecision decisionId="…">`) and the DMN rules inside them.
2. Pick **one happy-path segment** from start event to the most common end event — this seeds coverage of the spine.
3. For every element still uncovered, define one **minimal segment** rooted at the nearest upstream decision point (gateway, DMN, error boundary) and ending at the next element that rejoins the happy path. Do not always run to the end event.
4. Print the segment plan as a table: segment name | root | covered elements | end condition.

### 4. Author

For each segment, write one entry inside `src/test/resources/scenarios/<processId>.test.json` using [references/authoring.md](references/authoring.md). Naming: `"<who/what> — <outcome>"`. Assertions: `ASSERT_ELEMENT_INSTANCES` on the elements the segment must visit, `ASSERT_PROCESS_INSTANCE` only when the segment runs to an end event.

Use the Java fallback (covered in the same `authoring.md`) only when the segment needs Spring bean mocking, parameterized data tables, or assertions richer than the JSON instruction set offers — accept that Java tests are invisible to Web Modeler.

### 5. Run

```bash
mvn test
```

On failure, diagnose with [references/troubleshooting.md](references/troubleshooting.md). Distinguish **test problems** (variable typo, wrong element id, missing instruction) from **process problems** (wrong FEEL condition, wrong DMN rule, wrong error code). Fix the right side. Re-run. Stop after 3 repair cycles with no progress.

When the run exits — pass or fail — proceed straight to step 6 and open the coverage report.

### 6. Coverage check — exit gate (100% loop)

CPT emits a coverage report at `target/coverage-report/report.html` (per-process HTML; the page embeds the full coverage dataset in a `window.COVERAGE_DATA` JSON literal). Parse it:

```bash
python3 - <<'PY'
import re, json
html = open("target/coverage-report/report.html").read()
# Balanced-brace extraction. Walk character by character, but track string
# state so braces inside JSON strings (e.g. inside a description) don't
# unbalance the counter.
m = re.search(r"window\.COVERAGE_DATA\s*=\s*", html)
start = html.index("{", m.end())
depth = 0; in_str = False; esc = False; end = start
for k, ch in enumerate(html[start:], start):
    if in_str:
        if esc: esc = False
        elif ch == "\\": esc = True
        elif ch == '"': in_str = False
    else:
        if ch == '"': in_str = True
        elif ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = k + 1
                break
data = json.loads(html[start:end])
el = set(); flows = set(); total = None
for s in data["suites"]:
    for r in s["runs"]:
        for c in r["coverages"]:
            el.update(c.get("completedElements", []))
            flows.update(c.get("takenSequenceFlows", []))
            total = c.get("totalElementCount", total)
covered = len(el) + len(flows)
print(f"coverage={covered}/{total}={100*covered/total:.2f}%")
print("covered_elements:", sorted(el))
print("covered_flows:", sorted(flows))
PY
```

Diff against the BPMN element + sequenceFlow id list (`grep -oE 'id="[A-Za-z0-9_]+"' <bpmn>`, exclude `_di`, `BPMNDiagram`, `BPMNPlane`, `Definitions_`, `ErrorDef_`, `TimerDef_`, `Signal_`, `Message_`).

**Open the HTML report in the user's browser as soon as `mvn test` exits — pass or fail.** Default command (macOS):

```bash
REPORT="target/coverage-report/report.html"
[ -f "$REPORT" ] && open "$REPORT"
```

On Linux substitute `xdg-open`; on Windows substitute `start`. Default behavior, not opt-in — every run ends with the report visible.

**Auto-loop to 100% — default behavior.** If aggregate coverage `(covered elements + covered sequence flows) / totalElementCount` is < 100%:

1. For each uncovered id, classify: element (visit it directly), or sequence flow (its source must be hit *and* the condition routing through it must be satisfied — usually means a non-happy gateway branch).
2. Define one additional segment per uncovered id using [references/coverage-strategy.md](references/coverage-strategy.md). Group ids that share a root onto one segment.
3. For timer boundary events: use `INCREASE_TIME` with an ISO 8601 `duration` greater than the timer cycle (e.g. `"PT25H"` for `R/PT24H`). The boundary fires; the outgoing path's job is created; complete it with `COMPLETE_JOB`.
4. For message boundary events: `PUBLISH_MESSAGE` instruction with matching name + correlationKey.
5. Re-run step 5 (`mvn test`) → step 6 (coverage check). Repeat.

Hard blockers that terminate the loop:

- Same set of ids uncovered after 3 consecutive iterations — surface the list and stop.
- An uncovered element is dead code (no inbound flow, or its inbound condition is unsatisfiable) — flag as a BPMN defect, point at camunda-bpmn, stop.
- Test infrastructure failure repeats (Docker down, deploy parse error) — stop and route to [references/troubleshooting.md](references/troubleshooting.md).

Do not declare the suite done while ids remain uncovered and no hard blocker applies.

> **Note**: in early 8.9 SNAPSHOT releases the report generator may throw `IllegalStateException: Report resources not found` and skip the HTML output. Tests still pass. Walk the BPMN against scenarios manually to confirm coverage in that case.

### 7. Deduplication pass

Re-read every scenario. For each, compute the set of elements visited and the gateway branches taken. Flag any scenario whose visited set is a strict subset of another's **and** whose branch choices are identical on the overlap — that scenario is redundant; propose removing it.

Also flag:

- Scenario names that do not match `<who/what> — <outcome>` (e.g. `"test1"`, `"happy"`).
- Duplicated descriptions across scenarios.
- `ASSERT_VARIABLE` instructions on variables that no gateway or DMN downstream consumes — data assertions are out of scope.

### 8. Report

Print the Surefire result line, the coverage percentage, the segment count, and any flagged duplicates.

```text
Tests run: 6, Failures: 0, Errors: 0, Skipped: 0
Coverage: 100% (24/24 elements)
Segments: 1 happy path + 5 secondary
Duplicates flagged: 0
```

## References

- [setup.md](references/setup.md) — Java, Maven, Docker prereqs; CPT dependency; test scaffold layout
- [coverage-strategy.md](references/coverage-strategy.md) — segment selection rules per BPMN element type
- [authoring.md](references/authoring.md) — `.test.json` schema, instruction reference, Java fallback
- [troubleshooting.md](references/troubleshooting.md) — failure diagnosis table (test problem vs. process problem)
