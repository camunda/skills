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
- **camunda-dmn**: Use when a DMN decision is the unit under test — CPT exercises it via the calling business rule task; pair with `npx dmnlint` for structural checks.
- **camunda-job-workers**: Use when the handler code that backs a service task is itself under test — CPT drives BPMN reachability; worker unit tests drive handler behaviour.
- **camunda-connectors-development**: Use when a custom connector is the unit under test — CPT exercises it from the BPMN side; SDK-side tests cover the connector class directly.
- **camunda-ai-agents**: Use when testing an AI Agent Sub-process — drives the BPMN shape that `COMPLETE_JOB_AD_HOC_SUB_PROCESS` and `context.when().then()` orchestrate.
- **camunda-process-mgmt**: CPT runs against an **embedded** Zeebe engine — it does **not** use the c8ctl-managed cluster or any profile. No `c8ctl` call deploys a process under test.

## Scope boundaries

- **In scope**: BPMN reachability (every element visited at least once), gateway-branch selection, DMN rule selection, error-boundary firing, timer / escalation boundary firing, end-event selection.
- **Out of scope**: asserting data values produced by service tasks, external system payloads, UI behavior, and agent / LLM output — **except** AI Agent Sub-process outputs asserted with LLM-as-Judge (`hasVariableSatisfiesJudge` *(8.9+)*; JSON `ASSERT_VARIABLE` + `satisfiesJudge` *(8.10+)*) or semantic similarity *(8.10+)*. Do not write data-value `ASSERT_VARIABLE` assertions on service-task output unless the variable is the FEEL input to a downstream gateway you also test.

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

### 3. Plan segments (set-cover, not per-element)

Plan the minimum number of segments **before** authoring anything. Apply [references/coverage-strategy.md](references/coverage-strategy.md):

1. Parse the BPMN: `processId`, element IDs and types, gateway outgoing flows + conditions, error / timer / escalation boundaries, end events, called DMN decisions (`<zeebe:calledDecision decisionId="…">`) and the DMN rules inside them.
2. **Enumerate candidate segments.** For every gateway branch, DMN rule, boundary event, and alternate end event, define one minimal candidate segment rooted at the nearest upstream decision point. For each candidate, **statically predict its full visited-element + sequence-flow set** by walking the BPMN forward from the root through the targeted branch to the next rejoin or end event.
3. **Greedy set-cover.** Repeatedly pick the candidate whose predicted set covers the largest number of still-uncovered ids. Tie-break by shortest path (cheapest to author). Stop when the union covers every id.
4. **Diagnostic-isolation override (optional).** If two chosen segments share a root but exercise different failure modes (e.g. one fires a boundary event, the other completes the user task normally), keep both so a failure points at one cause cleanly. Apply only when the user is debugging a specific area; default is pure set-cover.
5. Print the segment plan as a table: `segment name | root | predicted ids covered | end condition`. Authoring then implements exactly this list — no speculative scenarios that may be deduped later.

### 4. Author

For each segment, write one entry inside `src/test/resources/scenarios/<processId>.test.json` using [references/authoring.md](references/authoring.md). Naming: `"<who/what> — <outcome>"`. Assertions: `ASSERT_ELEMENT_INSTANCES` on the elements the segment must visit, `ASSERT_PROCESS_INSTANCE` only when the segment runs to an end event.

Use the Java fallback only when the segment needs Spring bean mocking, parameterized data tables, non-deterministic runtime races (`context.when().then()` *(8.9+)*), or assertions richer than the JSON instruction set offers — see [references/test-context.md](references/test-context.md). For AI Agent Sub-process outputs, use LLM-as-Judge (Java `hasVariableSatisfiesJudge` *(8.9+)*, JSON `ASSERT_VARIABLE` + `satisfiesJudge` *(8.10+)*) or semantic similarity *(8.10+)* — see [references/authoring.md § Agentic evaluation assertions](references/authoring.md#agentic-evaluation-assertions-810) and [references/judge-configuration.md](references/judge-configuration.md). Accept that Java tests are invisible to Web Modeler.

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

**Surface the HTML report path to the user as soon as `mvn test` exits — pass or fail.** The agent already verifies coverage from the JSON data above; the HTML report is for the user to inspect. Print the absolute path (`target/coverage-report/report.html`) in the final reply so they can open it themselves. In an interactive local session you may additionally offer to open it on their behalf (`open` on macOS, `xdg-open` on Linux, `start` on Windows) — do not run that unprompted in a sandboxed / remote environment where it has no effect.

**Patch-loop on prediction misses — default behavior.** Set-cover planning in step 3 should reach 100% on the first authoring pass. When it does not, the gap is a *prediction miss*: the static walk for some candidate did not match runtime behavior. For each uncovered id:

1. Classify the miss: element (visit it directly), or sequence flow (its source must be hit *and* the condition routing through it must be satisfied — usually a gateway branch the planner failed to attribute).
2. Re-run greedy set-cover restricted to the remaining uncovered ids. Add the chosen candidates (often one) to the scenario file.
3. For timer boundary events: use `INCREASE_TIME` with an ISO 8601 `duration` greater than the timer cycle (e.g. `"PT25H"` for `R/PT24H`). The boundary fires; the outgoing path's job is created; complete it with `COMPLETE_JOB`.
4. For message boundary events: `PUBLISH_MESSAGE` instruction with matching name + correlationKey.
5. Re-run step 5 (`mvn test`) → step 6. Each iteration should strictly reduce the uncovered set; if it does not, the planner's path prediction is wrong — fix the prediction logic in [references/coverage-strategy.md](references/coverage-strategy.md), do not paper over with more scenarios.

Hard blockers that terminate the loop:

- Same set of ids uncovered after 2 consecutive iterations — surface the list and stop.
- An uncovered element is dead code (no inbound flow, or its inbound condition is unsatisfiable) — flag as a BPMN defect, point at camunda-bpmn, stop.
- Test infrastructure failure repeats (Docker down, deploy parse error) — stop and route to [references/troubleshooting.md](references/troubleshooting.md).

Do not declare the suite done while ids remain uncovered and no hard blocker applies.

> **Note**: in early 8.9 SNAPSHOT releases the report generator may throw `IllegalStateException: Report resources not found` and skip the HTML output. Tests still pass. Walk the BPMN against scenarios from source to confirm coverage in that case.

### 7. Verify no redundancy slipped through

Set-cover planning in step 3 should produce a non-redundant suite by construction. Verify with a leave-one-out check against the runtime coverage data: for each scenario, compute the union of all *other* scenarios' covered ids; if removing the scenario loses zero ids, it is redundant and the planner has a bug — fix the planner, then drop the scenario.

Also flag (cheap, do unconditionally):

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

- [setup.md](references/setup.md) — Java, Maven, Docker prereqs; CPT dependency; test scaffold layout; Spring Boot 4.x pin
- [coverage-strategy.md](references/coverage-strategy.md) — segment selection rules per BPMN element type, including ad-hoc subprocess tool activation
- [authoring.md](references/authoring.md) — `.test.json` schema, full 8.9 instruction reference, Java fallback
- [test-context.md](references/test-context.md) — `CamundaProcessTestContext` Java API surface (job/decision/child-process mocking, time control, conditional behavior)
- [connectors-runtime.md](references/connectors-runtime.md) — enabling the Connectors runtime alongside Zeebe; WireMock pattern; inbound webhooks
- [troubleshooting.md](references/troubleshooting.md) — failure diagnosis table (test problem vs. process problem)
- [judge-configuration.md](references/judge-configuration.md) — LLM-as-Judge *(8.9+)* and semantic-similarity *(8.10+)* model configuration for agentic evaluation assertions
