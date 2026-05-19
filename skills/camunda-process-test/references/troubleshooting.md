# CPT troubleshooting

Diagnose `mvn test` failures. Each row classifies the failure as a **test problem** (fix the scenario) or a **process problem** (fix the BPMN, DMN, form, or worker). Confusing the two costs hours.

## Quick triage

| Failure | Likely root cause | Class | Fix |
|---------|-------------------|-------|-----|
| Spring context fails to start | Docker not running | Infra | Start Docker. Re-run. No code change. |
| `Cannot connect to the Docker daemon at unix:///…/docker.sock` after `docker info` prints a Client section | Docker CLI installed but daemon stopped — exit code 0 from `docker info` is misleading because the client section alone returns success | Infra | Check daemon-up explicitly: `docker info --format '{{.ServerVersion}}'` returns a version string only when the daemon is reachable. Start the runtime (Docker Desktop / OrbStack / Rancher) and re-run. |
| `processId not found` | Wrong process id in `processDefinitionSelector` | Test | Re-read `<bpmn:process id="…">` and update the scenario. |
| `elementId not found` | Wrong element id in `elementSelector` / `jobSelector` / `userTaskSelector` | Test | Re-read the `id` attribute on the BPMN element. |
| `FileNotFoundException` for BPMN / DMN / form on deploy | `classpath:` prefix in `@TestDeployment` | Test | Remove `classpath:` — CPT adds it internally. |
| `FORM_NOT_FOUND` incident | `.form` file missing from `@TestDeployment` | Test | Add the form file (no `classpath:`). |
| Test times out on a service task | No `COMPLETE_JOB` instruction for the task | Test | Add `COMPLETE_JOB` with the right `elementId`. |
| Test times out on a user task | No `COMPLETE_USER_TASK` instruction | Test | Add `COMPLETE_USER_TASK`. |
| Wrong end event reached | Variable name or value drives the wrong branch | **Investigate** | Read the FEEL condition on the gateway and the `CREATE_PROCESS_INSTANCE` variables. Either the variable name in the test is wrong **or** the FEEL in the BPMN uses the wrong identifier. |
| `THROW_BPMN_ERROR_FROM_JOB` doesn't trigger boundary | `errorCode` mismatch between the instruction and `<bpmn:error errorCode="…">` | Test or process | Compare the two strings exactly. Whichever is the typo wins. |
| `IS_COMPLETED` on process fails, an element is `IS_ACTIVE` | A waiting element has no instruction telling it to proceed | Test | Add `COMPLETE_JOB` / `COMPLETE_USER_TASK` / `THROW_BPMN_ERROR_FROM_JOB` for the active element. |
| `ClientStatusException INVALID_ARGUMENT` on deploy mentioning "must appear before" / `cvc-complex-type` | BPMN file violates BPMN20 XSD element ordering | Process | Out of scope here — run `c8ctl bpmn lint` and fix the BPMN (camunda-bpmn). |
| `Failed to parse DMN: Unable to parse model` on deploy | DMN file is not valid DMN 1.3 | Process | Out of scope — fix the DMN. Optionally remove the DMN from `@TestDeployment` temporarily to unblock unrelated tests. |
| `ClientStatusException` on deploy mentioning a `.form` file | Form fails JSON-Schema validation | Process | Fix the form (camunda-forms). |
| `BPMN error code mismatch` | `THROW_BPMN_ERROR_FROM_JOB errorCode` does not match `<bpmn:error errorCode>` | Test | Match exactly. Case-sensitive. |
| Assertion failed on variable value | Value mismatch | **Investigate** | If the variable feeds a downstream gateway or DMN, fix whichever side is wrong. If nothing reads the variable, the assertion itself is out of scope — remove it. |
| `IllegalStateException: Report resources not found in classpath` | Known SNAPSHOT bug in CPT coverage report generator | Infra | Non-blocking. Tests pass. Ignore until a GA release fixes it. |
| DMN behaves wrong but no incident; process completes normally with wrong outputs | BPMN-completes tests can't catch wrong DMN outputs unless a downstream gateway consumes them | Test | Add `ASSERT_DECISION` (JSON) or `CamundaAssert.assertThatDecision(...)` (Java) — see authoring.md § Instructions for DMN, and **camunda-dmn** § testing-decisions for what to assert per hit policy. |
| `DECISION_EVALUATION_ERROR: expected '<typeRef>' but found '[...]'` | Decision-table `<variable typeRef="string"/>` declared but the hit policy returns a list (RULE ORDER / COLLECT without aggregator) | Process | Drop the decision-level `<variable>` element on the decision table, or remove its `typeRef`. See **camunda-dmn** § Decision-level `<variable>` declarations. |

## Repair discipline

1. Diagnose **every** failure first. Do not start fixing until the full list is classified.
2. Group fixes by class. Test problems batch into one commit; process problems batch into another. Mixed commits make later reviews hard.
3. Re-run `mvn test` once per batch. Three repair cycles without progress means the diagnosis is wrong — stop and re-read.
4. Never silence a failure by deleting the scenario. If a scenario is genuinely redundant, the deduplication pass in the main workflow handles it — not the repair loop.

## When in doubt

- For a routing mismatch (`Wrong end event reached`, gateway not hit): run `c8ctl feel evaluate '<condition>' --vars '<scenario variables>'` to confirm what the condition resolves to. See camunda-feel.
- For a deploy-time XSD error: run `c8ctl bpmn lint <file>`. See camunda-bpmn.
- For a hung instance: list active elements at the failure point and identify which one needs an instruction.
