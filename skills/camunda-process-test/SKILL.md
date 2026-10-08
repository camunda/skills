---
name: camunda-process-test
description: |
  Use this skill to draft test plans, then author, run, and maintain Camunda Process Test suites. Covers deterministic BPMN coverage, connector/tool integration tests, and whole-process business-outcome tests. Do not use it to author BPMN, DMN, FEEL, or forms, deploy live processes, or test UI/browser behavior.
---

# Camunda Process Test

**WORKFLOW SKILL**: specify requirements and acceptance criteria, plan segments, author scenarios, run the Maven test command, and close coverage gaps.

## DO NOT USE FOR:

Do not use this skill to author BPMN, DMN, FEEL, or forms, deploy to a live cluster, or test UI behavior. Route those tasks to **camunda-bpmn**, **camunda-dmn**, **camunda-feel**, **camunda-forms**, **camunda-process-mgmt**, or the relevant UI test framework.

Use this skill to describe and build Camunda Process Test suites for Camunda 8.8+ from a Markdown test specification. The specification is the source of truth for requirements, realistic outcomes, layer boundaries, coverage goals, dependency choices, and commands. This is a greenfield test-planning workflow, not a Camunda 7-to-8 migration-parity validator. For agentic or integration-heavy processes, choose among deterministic process, point-integration, and whole-process business-outcome suites as described in [references/three-layer-strategy.md](references/three-layer-strategy.md). These test the process runtime, not browser or UI behavior.

## Prerequisites

- Java 21+, Maven (or `./mvnw`), Docker runtime (OrbStack, Docker Desktop, or Rancher Desktop) — see [references/setup.md](references/setup.md)
- `camunda-process-test-spring` 8.8+ on the test classpath for Java fallback suites; the instruction-based `.test.json` format and 8.9-only APIs require 8.9+
- A working BPMN file (lint clean — see camunda-bpmn). DMN and form files referenced by the BPMN must also be present.

For a Node.js layout, set `NODE_RESOURCE_DIR` and run Maven from the generated `test/` directory as
described in [references/setup.md](references/setup.md). The Maven commands below are shell-neutral; the
Node.js POM reads the environment variable and standard Java layouts do not need it.

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
- **Deterministic process-test scope**: assertions are limited to reachability and routing. Do not assert service-task output unless the variable is the FEEL input to a downstream gateway you also test.
- **Integration-test scope**: assert only contracts specified in the test plan, such as stable connector/tool shape, status class, or required fields. Never assert volatile exact payloads or generated response wording.
- **Out of scope**: UI behavior, semantic answer quality, real LLM calls in the required CI path, and authenticated production dependencies.

## Workflow

### 1. Specify requirements

Before writing test code, create or update a Markdown test specification using [references/test-specification.md](references/test-specification.md). Prefer `TESTING.md` beside the process or its test harness; it records selected requirements, guarantees, evidence, and isolation boundaries in version control.

1. Inspect the BPMN, forms, decisions, integrations, existing tests, and project
   instructions.
2. Before planning CPT remote execution, explain that it clears runtime data
   between runs. Confirm the runtime is disposable and test-owned; otherwise
   mark remote execution blocked. See the test-specification reference.
3. Select applicable suites. Process tests are required; integration and manual
   suites depend on the process and requested outcomes. Avoid irrelevant suites.
4. For each suite, record what it verifies, measurable evidence, dependencies,
   isolation, and an `ID | Test | Guarantee` table.
5. For each external dependency, ask if unclear whether to mock the integration,
   run it against a local service, or call the real service. Record what the
   choice proves; do not assume real services are acceptable in CI.
6. Record commands, evidence locations, manual gates, and side-effect limits.
   If Test Studio cannot express a required CPT assertion, present the assertion
   power, business visibility, or hybrid choice; never silently weaken it.
7. Ask focused questions about unresolved choices that materially affect the
   plan. Record the answers in the version-controlled plan.
8. If planning alone was requested, stop; otherwise implement the plan.

The test suite must trace back to this specification. When later implementation evidence changes, update the requirement row and links rather than letting the Markdown drift.

### 2. Detect

Find the BPMN under test in priority order:

1. `src/main/resources/processes/`
2. `src/main/resources/bpmn/`
3. The resource directory declared by the project build (for example, a Node.js
   project may keep it at `resources/` while the test harness lives in `test/`).

Skip `target/`, `node_modules/`, `.git/`, `build/`. If multiple files match, list them and ask which to target.

Check `pom.xml` (or `test/pom.xml`) for `camunda-process-test-spring`. If missing, go to step 3.

If scenarios already exist, run a drift check before editing tests:

```bash
git diff <base-branch>...HEAD -- <bpmn-path>
```

Use the PR base branch or repository default branch as `<base-branch>` (often `main`).

Then classify current suite gaps:

- **Broken**: scenario references an `elementId` or `processDefinitionId` that no longer exists.
- **Stale**: IDs still exist, but branch-driving variables or assumptions no longer match gateway/DMN behavior.
- **Missing**: new branches, boundary events, or end events have no segment coverage.

Fix in this order: broken → stale → missing, then run `mvn test` and continue with coverage verification.

### 3. Setup (only if missing)

Follow [references/setup.md](references/setup.md): run the readiness preflight (Java, Maven/wrapper, Docker), add the CPT dependency, scaffold `src/test/java/io/camunda/tests/ProcessTest.java` and `src/test/resources/scenarios/` for CPT 8.9+, or use the Java fallback for CPT 8.8. Confirm with `mvn test-compile`.

### 4. Plan segments (set-cover, not per-element)

Plan the smallest useful set of segments **before** authoring anything. Apply [references/coverage-strategy.md](references/coverage-strategy.md) to the coverage goal recorded in the test specification:

1. Parse the BPMN: `processId`, element IDs and types, gateway outgoing flows + conditions, error / timer / escalation boundaries, end events, called DMN decisions (`<zeebe:calledDecision decisionId="…">`) and the DMN rules inside them.
2. **Enumerate candidate segments.** For every gateway branch, DMN rule, boundary event, and alternate end event, define one minimal candidate segment rooted at the nearest upstream decision point. For each candidate, **statically predict its full visited-element + sequence-flow set** by walking the BPMN forward from the root through the targeted branch to the next rejoin or end event.
3. **Greedy set-cover.** Repeatedly pick the candidate whose predicted set covers the largest number of still-uncovered IDs. Tie-break by shortest path (cheapest to author). Stop when the specified coverage goal is met.
4. **Diagnostic-isolation override (optional).** If two chosen segments share a root but exercise different failure modes (e.g. one fires a boundary event, the other completes the user task normally), keep both so a failure points at one cause cleanly. Apply only when the user is debugging a specific area; default is pure set-cover.
5. Print the segment plan as a table: `segment name | root | predicted IDs covered | guarantee added | end condition`. A test earns its place by adding coverage or proving a distinct guarantee in the plan; do not keep a scenario that adds neither.

**Example:** for a gateway with `approved` and `rejected` flows, plan segments that meet the chosen branch-coverage goal, predict visited IDs through the next join, and keep the smallest set that achieves that goal and any other guarantees in the plan.

When the request includes connectors, agent tools, or whole-process business outcomes, use only the applicable layers selected in the test specification. Follow [references/three-layer-strategy.md](references/three-layer-strategy.md) for those layers. Apply set-cover and leave-one-out checks within each selected layer, preserving evidence for every specified guarantee. Cross-layer overlap is expected because each layer proves a different contract.

### 5. Author

For CPT 8.9+, write one entry inside `src/test/resources/scenarios/<processId>.test.json` using [references/authoring.md](references/authoring.md). For CPT 8.8, use the Java fallback described in that reference instead of `.test.json`. Naming: `"<who/what> — <outcome>"`. Assertions: `ASSERT_ELEMENT_INSTANCES` on the elements the segment must visit, `ASSERT_PROCESS_INSTANCE` only when the segment runs to an end event.

For CPT 8.9+, use the Java fallback only when the segment needs Spring bean mocking, parameterized data tables, non-deterministic runtime races (`context.when().then()` *(8.9+)*), or assertions richer than the JSON instruction set offers. For CPT 8.8, Java tests are required because the instruction-based format is not available. See [references/test-context.md](references/test-context.md); Java tests are invisible to Web Modeler.

### 6. Run

Run Maven from the directory containing the relevant `pom.xml`. For a Node.js layout, use the
generated `test/` directory and keep `NODE_RESOURCE_DIR` set to the resolved resource directory
for this command and every retry, as described in [references/setup.md](references/setup.md).

```bash
mvn test
```

On failure, diagnose with [references/troubleshooting.md](references/troubleshooting.md). Distinguish **test problems** (variable typo, wrong element id, missing instruction) from **process problems** (wrong FEEL condition, wrong DMN rule, wrong error code). Fix the right side. Re-run. Stop after 3 repair cycles with no progress.

When the run exits — pass or fail — proceed straight to step 7 and inspect the coverage report against the goals in the plan.

### 7. Coverage check — compare with the plan

CPT emits a coverage report at `target/coverage-report/report.html` (per-process HTML; the page embeds the full coverage dataset in a `window.COVERAGE_DATA` JSON literal). Parse it:

Classify runs by process and layer before evaluating gates. The union computed
below is for combined presentation only; do not use it to evaluate an
individual layer's gate.

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
print(f"combined presentation coverage={covered}/{total}={100*covered/total:.2f}%")
print("covered_elements:", sorted(el))
print("covered_flows:", sorted(flows))
PY
```

Diff against the BPMN element + sequenceFlow id list (`grep -oE 'id="[A-Za-z0-9_]+"' <bpmn>`, exclude `_di`, `BPMNDiagram`, `BPMNPlane`, `Definitions_`, `ErrorDef_`, `TimerDef_`, `Signal_`, `Message_`).

**Surface the HTML report path to the user as soon as `mvn test` exits — pass or fail.** The agent already verifies coverage from the JSON data above; the HTML report is for the user to inspect. Print the absolute path (`target/coverage-report/report.html`) in the final reply so they can open it themselves. In an interactive local session you may additionally offer to open it on their behalf (`open` on macOS, `xdg-open` on Linux, `start` on Windows) — do not run that unprompted in a sandboxed / remote environment where it has no effect.

**Patch-loop on prediction misses — when full coverage is a plan requirement.** When selected as the coverage goal, set-cover planning in step 4 should reach it on the first authoring pass. If it does not, the gap is a *prediction miss*: the static walk for some candidate did not match runtime behavior. For each required but uncovered ID:

1. Classify the miss: element (visit it directly), or sequence flow (its source must be hit *and* the condition routing through it must be satisfied — usually a gateway branch the planner failed to attribute).
2. Re-run greedy set-cover restricted to the remaining uncovered ids. Add the chosen candidates (often one) to the scenario file.
3. For timer boundary events: use `INCREASE_TIME` with an ISO 8601 `duration` greater than the timer cycle (e.g. `"PT25H"` for `R/PT24H`). The boundary fires; the outgoing path's job is created; complete it with `COMPLETE_JOB`.
4. For message boundary events: `PUBLISH_MESSAGE` instruction with matching name + correlationKey.
5. Re-run step 6 (`mvn test`) → step 7. Each iteration should strictly reduce the uncovered set; if it does not, the planner's path prediction is wrong — fix the prediction logic in [references/coverage-strategy.md](references/coverage-strategy.md), do not paper over with more scenarios.

Hard blockers that terminate the loop:

- Same set of ids uncovered after 2 consecutive iterations — surface the list and stop.
- An uncovered element is dead code (no inbound flow, or its inbound condition is unsatisfiable) — flag as a BPMN defect, point at camunda-bpmn, stop.
- Test infrastructure failure repeats (Docker down, deploy parse error) — stop and route to [references/troubleshooting.md](references/troubleshooting.md).

Do not report a selected coverage goal as met while IDs remain uncovered and no hard blocker applies.

> **Note**: in early 8.9 SNAPSHOT releases the report generator may throw `IllegalStateException: Report resources not found` and skip the HTML output. Tests still pass. Walk the BPMN against scenarios from source to confirm coverage in that case.

Classify coverage runs by process and layer before evaluating gates. Calculate each per-layer gate documented in the test specification only from runs assigned to that layer; never let integration runs fill gaps in deterministic process coverage. Retain the distinction in the machine-readable report. A combined union across selected layers may be shown for presentation, but is not a gate. When full deterministic coverage is a selected goal, include a regression check where deterministic runs cover 3/5 IDs and integration runs cover the other 2/5: combined coverage is 5/5, but the deterministic gate remains unmet.

Compare measured coverage with the **per-layer goals in the test specification**. For new deterministic suites, propose 100% reachable BPMN element and sequence-flow coverage as a default, then record the chosen goal. Do not treat that goal as evidence of migration parity or override another test suite's stated purpose. Treat unreachable elements as BPMN defects rather than silently counting them as covered.

### 8. Verify no redundancy slipped through

Verify the plan with a leave-one-out check. For each scenario, compare what the remaining scenarios prove against both the selected coverage goal and every guarantee in the plan. Keep the scenario if removing it loses needed coverage **or** leaves a planned guarantee without evidence. If it loses neither, it has not earned its place and should be removed. Two scenarios may cover the same IDs but prove different guarantees; retain both when both guarantees are in scope.

Also flag (cheap, do unconditionally):

- Scenario names that do not match `<who/what> — <outcome>` (e.g. `"test1"`, `"happy"`).
- Duplicated descriptions across scenarios.
- In deterministic routing tests, variable assertions on values that no gateway or DMN downstream consumes — data assertions are out of scope there. Preserve any distinct output or business-contract guarantee that the plan explicitly includes.

### 9. Report

Print the Surefire result line, the coverage percentage, the segment count, and any flagged duplicates.

```text
Tests run: 6, Failures: 0, Errors: 0, Skipped: 0
Coverage: 100% (24/24 elements)
Segments: 1 happy path + 5 secondary
Duplicates flagged: 0
```

For every selected layer, report its specified coverage or contract gate and the corresponding evidence. Include connector/tool path coverage when point-integration tests apply, named business outcomes when whole-process tests apply, and per-suite/per-scenario coverage. Produce machine-readable data and an interactive HTML report with BPMN element/sequence-flow highlighting. Keep required CI offline and credential-free; document live-dev commands separately.

## Maintenance workflows for existing suites

When tests already exist and the user asks to run, diagnose, or improve them (without generating a brand-new suite), use these focused workflows:

1. **Run and diagnose failures** — execute `mvn test` from the directory containing the relevant `pom.xml`; for a Node.js layout, run it from `test/` with `NODE_RESOURCE_DIR` set to the resolved resource directory for the initial run and every retry. Classify each failure as infrastructure/test/process, then fix in batches. Use [references/troubleshooting.md](references/troubleshooting.md) plus [references/run-and-diagnose.md](references/run-and-diagnose.md).
2. **Evaluate coverage gaps before writing new tests** — explain current suite coverage in business terms, list uncovered branches/boundaries/rules, and recommend the smallest next set of scenarios. See [references/evaluation.md](references/evaluation.md).
3. **Wire tests into CI** — configure CI to run CPT reliably and publish JUnit artifacts, with optional integration profile runs gated to trusted branches. See [references/ci.md](references/ci.md).

These workflows are complementary: evaluate gaps first, implement new scenarios, then run/diagnose locally and in CI.

## References

- [setup.md](references/setup.md) — Java, Maven, Docker prereqs; CPT dependency; test scaffold layout; Spring Boot 4.x pin
- [test-specification.md](references/test-specification.md) — required Markdown plan, traceability matrix, tunable thresholds, realistic scenarios, and maintenance rules
- [coverage-strategy.md](references/coverage-strategy.md) — segment selection rules per BPMN element type, including ad-hoc subprocess tool activation
- [authoring.md](references/authoring.md) — `.test.json` schema, full 8.9 instruction reference, Java fallback
- [test-context.md](references/test-context.md) — `CamundaProcessTestContext` Java API surface (job/decision/child-process mocking, time control, conditional behavior)
- [connectors-runtime.md](references/connectors-runtime.md) — enabling the Connectors runtime alongside Zeebe; WireMock pattern; inbound webhooks
- [three-layer-strategy.md](references/three-layer-strategy.md) — deterministic process, point-integration, and mocked/local business-outcome suites for connector- and agent-heavy processes
- [troubleshooting.md](references/troubleshooting.md) — failure diagnosis table (test problem vs. process problem)
- [run-and-diagnose.md](references/run-and-diagnose.md) — test-run execution loop and failure-batch repair strategy
- [evaluation.md](references/evaluation.md) — coverage-gap assessment and recommendation workflow
- [ci.md](references/ci.md) — CI pipeline patterns for CPT execution and test-report publishing
