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

### 6. Coverage check — exit gate

CPT emits a coverage report under `target/camunda-process-test/coverage/` (HTML + JSON). Parse the JSON and list uncovered elements.

If coverage is < 100%, loop back to step 3: define one more segment per uncovered element. Do not declare the suite done while elements remain uncovered.

> **Note**: in 8.9 SNAPSHOT releases the report generator may throw `IllegalStateException: Report resources not found`. Tests still pass. Treat as advisory until a GA release ships — manually walk the BPMN against scenarios to confirm coverage in that case.

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
- [authoring.md](references/authoring.md) — `.test.json` schema, instruction reference, Java fallback
- [coverage-strategy.md](references/coverage-strategy.md) — segment selection rules per BPMN element type
- [troubleshooting.md](references/troubleshooting.md) — failure diagnosis table (test problem vs. process problem)
