# Test-plan-first workflow

Create a concise Markdown test plan before implementing tests. The plan states
the guarantees each applicable suite must provide, so assertions follow from
reviewed requirements instead of being invented during implementation.

Use `TESTING.md` beside the process or test harness unless the repository has an
established acceptance document. For a completed example, see
[test-plan-example.md](test-plan-example.md).

## Choose only applicable suites

There is no one-size-fits-all test pyramid. The version-controlled test plan
records which contracts matter, what evidence proves them, which dependencies
are real or mocked, and which manual checks are policy requirements.

Always include **Process tests**. Add another suite only when the process shape
or requested outcome gives it a distinct contract:

| Suite | Include when | Omit when |
|---|---|---|
| Process tests | Always: BPMN routing, reachability, decisions, and end states need deterministic evidence. | Never. |
| Point integration tests | The process invokes connectors, workers, agents, decisions, or other dependencies whose isolated contract or selection behavior needs proof. | The process has no integration boundary, or that boundary is fully tested outside this project and no process-side contract is requested. |
| Process integration tests | A named business outcome depends on multiple real or production-like components working together. | Deterministic process tests prove the requested outcome and no cross-component behavior remains to verify. |
| Manual tests | A policy, human judgment, visual/user-task experience, physical side effect, or live behavior cannot be fully automated. | Every required guarantee has reliable automated evidence and no policy requires manual acceptance. |

Do not add empty or speculative suites. Explain a non-obvious omission in one
sentence under the strategy or run section.

## Plan structure

```markdown
# <Process name> test plan

<One paragraph: which progressively broader questions the applicable suites answer.>

## Process tests

- **Verifies:** <routing and reachability guarantees>
- **Required evidence:** <measurable automated gate>
- **Dependencies:** <refer to the Dependency choices table below>

| ID | Test | Guarantee |
|---|---|---|
| P-1 | `process/<outcome>` | <single observable guarantee> |

## Dependency choices

For each external dependency used by an automated suite, record the chosen
boundary. Ask the user to choose when it is not already clear.

| Dependency | Choice | Test setup and what the suite proves |
|---|---|---|
| <connector, worker, or service> | Mock / Local service / Real service | <what runs for real, what is replaced, and the guarantee> |

- **Mock:** replace the connector/worker integration; proves process behavior
  around an assumed result, not the integration implementation.
- **Local service:** run the production integration against a local stub or
  fake service; proves integration behavior without calling the real service.
- **Real service:** call the actual external dependency; record credentials,
  network, side effects, costs, and whether it is optional or a required gate.

## Point integration tests
<!-- Include only when an isolated integration contract applies. -->

- **Verifies:** <selection or stable dependency contract>
- **Required evidence:** <measurable path/contract gate>
- **Dependencies:** <refer to the Dependency choices table below>

| ID | Test | Guarantee |
|---|---|---|
| S-1 | `segment/<contract>` | <single observable guarantee> |

<State live-worker race, cancellation, side-effect, credential, or network
limitations when they apply.>

## Process integration tests
<!-- Include only when a cross-component business outcome applies. -->

- **Verifies:** <named whole-process outcome>
- **Required evidence:** <measurable automated gate>
- **Dependencies:** <refer to the Dependency choices table below>
- **Boundary:** <what this suite deliberately does not prove>

| ID | Test | Guarantee |
|---|---|---|
| PI-1 | `process-integration/<outcome>` | <single business guarantee> |

## Manual tests
<!-- Include only when policy or non-automatable behavior requires it. -->

- **Verifies:** <human-observable behavior, such as user-task look and feel>
- **Required evidence:** <policy-required checks and cadence>
- **Dependencies:** <what is real or simulated>

| ID | Test | Steps and pass condition |
|---|---|---|
| M-1 | <journey> | <brief steps and observable pass condition> |

## Run and inspect

Prerequisites: <runtime, credentials, local fixtures, and environment>.

<Exact command or product workflow for every automated suite. Distinguish
required CI, policy-required manual checks, and optional live development.>

Reports:

- Interactive coverage: `<absolute-or-repository-relative output>`
- Machine coverage: `<output>`
- JUnit/results: `<output>`
- Integration/manual evidence: <system of record>

## Artifacts

- [Source BPMN](...)
- [Test plan](...)
- [Applicable test sources](...)
- [Camunda Process Test documentation](https://docs.camunda.io/docs/apis-tools/testing/getting-started/)

## Open decisions

<Business outcomes, dependencies, thresholds, or manual policy that still need
clarification. Resolve material choices with the user before relying on the
plan to implement tests.>

## CPT runtime

<For CPT remote mode, name the disposable, test-owned runtime. CPT clears its
data between test runs. Never configure it against a shared cluster. If safe
ownership cannot be confirmed, mark remote execution BLOCKED and do not run it.
See [CPT remote runtime documentation](https://docs.camunda.io/docs/apis-tools/testing/configuration/#remote-runtime).>
```

## Writing guarantees that produce assertions

Keep language direct. Each test row should contain one guarantee with an
observable subject, behavior, and boundary:

- Good: `A rejected review returns to correction; later approval completes.`
- Good: `The payment connector returns a success status and required receipt fields.`
- Bad: `Test the happy path.`
- Bad: `The integration works correctly.`

The implementation must be able to derive assertions from each guarantee:
visited route or terminal state, gateway/decision outcome, expected unordered
tool set, stable response shape, boundary event, or human-observable pass
condition. Never assert exact generated wording, volatile payload values, or
incidental tool order unless the plan identifies them as contractual.

## Evidence gates and isolation

Use concrete totals or percentages derived from the process, not example
numbers copied from another plan. For a new deterministic suite, propose 100%
of reachable BPMN elements and sequence flows as the default goal, then record
the user's chosen goal. This skill describes the selected test suite; it does
not establish Camunda 7-to-8 migration parity. Report unreachable elements
separately instead of silently counting them as covered.

For every suite:

1. State the automated or policy-required evidence gate.
2. For each external dependency, record whether the test mocks the integration,
   runs it against a local service, or calls the real service. Ask the user
   which they prefer when unclear.
3. Separate required offline CI from optional live-development execution.
4. State known races or side effects. Observing a live worker activation before
   cancellation does not guarantee the worker made no external request.
5. Mark blocked, disabled, or unimplemented evidence honestly.
6. If using CPT remote mode, identify a disposable, test-owned runtime. CPT
   deletes runtime data between test runs; never run it against a shared
   cluster. If safety is uncertain, mark execution blocked.

Process completion alone is not enough evidence for a connector contract or
business outcome.

## Native CPT versus Test Studio assertions

When a required guarantee needs a native CPT assertion that Test Studio cannot
edit or display, stop and ask the user to choose:

- **Assertion power:** keep the stronger native CPT assertion, such as
  `ASSERT_VARIABLE` with a `satisfiesExpression` *(8.10+)* when the project's
  CPT version supports it, and accept that the scenario is managed outside
  Test Studio. On earlier versions, use a compatible Java assertion.
- **Business visibility:** use a Test Studio-compatible assertion, such as
  `ASSERT_VARIABLES` for variable presence, and explicitly reduce the
  guarantee. Presence does not prove non-empty text, shape, exclusivity, or
  semantic quality.
- **Hybrid:** keep visible importable scenarios for business review and add
  stronger managed CPT tests for the full contract. Files intended for Test
  mode must include the top-level `processId`. Check the target Modeler
  version, process shape, and supported instructions before promising import,
  editing, or execution support.

Record the selected strategy beside the affected suite in `TESTING.md`,
including the retained or reduced guarantee and where each test runs. Never
silently downgrade an assertion or claim a shape/exclusivity guarantee from an
existence check. Do not force this choice when every planned assertion is
natively supported by both surfaces.

## Interactive planning

1. Inspect the BPMN, forms, decisions, workers/connectors, and existing tests.
2. Before planning remote execution, explain CPT remote mode clears runtime
   data between test runs; establish that any remote runtime is disposable and
   test-owned, or mark that execution blocked.
3. Draft only the applicable suites.
4. Present the guarantees, evidence gates, isolation boundaries, manual policy,
   dependency choices, unresolved decisions, and any native-CPT versus
   Test Studio assertion tradeoff.
5. Ask one focused question at a time, including the preferred boundary for
   each external dependency when unclear; revise the plan.
6. Record resolved requirements in the version-controlled plan. Continue with
   implementation when requested; if planning alone was requested, deliver the
   plan and stop.

If planning is the request, the Markdown plan is the deliverable.

## Report handoff and maintenance

Run instructions must identify machine-readable results and the interactive
report. After a test run, surface the absolute interactive report path
immediately; open it only in a supported interactive local environment.

Update the plan when the BPMN, forms, decisions, prompts/models, integrations,
fixtures, evidence gates, or manual policy changes. Keep links
repository-relative where practical and never present planned evidence as
passing.
