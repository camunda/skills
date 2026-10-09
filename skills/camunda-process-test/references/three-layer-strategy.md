# Three-layer CPT strategy

Use this structure when a process contains connectors, agent tools, or business outcomes that cannot be proved by routing coverage alone. Deterministic process tests are always required. Add point-integration and whole-process business-outcome layers only when their contracts apply, keep their artifacts separate, and combine evidence from every selected layer in one report. These layers test the process runtime, not browser or UI behavior.

| Layer | Contract | Required CI dependency |
|---|---|---|
| Deterministic process | BPMN reachability and routing | Mocked workers; no network or credentials |
| Point integration | One connector/tool path in isolation | Local stub or mocked dependency |
| Whole-process outcome | Named business outcome across the process | Local/mocked dependencies and controlled agent outcomes |

## Deterministic process tests

- Reach 100% of all reachable BPMN elements and sequence flows.
- Cover every gateway outcome, loop, end state, no-tool response, and agent tool.
- Control agent and connector jobs deterministically. Never call a model or external endpoint.
- Keep canonical intent in importable CPT JSON when the instruction format can express it. Use Java only for orchestration or assertions that JSON cannot express.
- Treat unreachable elements as BPMN defects. Name them; do not silently remove them from the denominator.

## Point integration tests

Create the point-integration scenarios needed to prove the guarantees in the
test plan. Do not require one scenario per connector/tool unless that is the
chosen goal:

1. Start immediately before the integration element.
2. Stop at the earliest useful assertion boundary after it.
3. Assert the intended element completed.
4. If the plan requires proving that unrelated tools did not activate, first
   wait for a positive checkpoint that shows the tool-selection window is
   complete (for example, the agent turn has completed or moved to the next
   modeled step). Only then assert absence. CPT's
   `hasNotActivatedElements(...)` assertion does not wait; checking it before
   that checkpoint can pass before a late tool activation.
5. Assert only a stable contract or shape, never exact volatile content.

For each external dependency, ask whether the user wants to mock the
integration, run the production integration against a local stub/fake service,
or call the real service. Record the choice in the plan. A mock proves process
behavior around an assumed result, not the integration's implementation. A
local service exercises the production integration without an external call.
Calling the real service needs an explicit network/credential/side-effect
decision and is usually optional rather than a required CI gate.

When a plan claims that no extra tool activated, include a delayed/late
activation case when that race is possible, and verify the negative assertion
is made only after the modeled selection window is complete.

## Whole-process business-outcome tests

- Name the expected business outcome.
- Prefer one scenario per process end state.
- For agentic requests, declare the expected tool **set** and assert every member was reached. Do not require tool order unless order is a business contract.
- Exercise feedback/retry topology where modeled: reject a result, provide follow-up input, then approve and complete.
- Do not assert exact generated wording or semantic answer quality.
- Run with controlled agent results and local/mocked integrations in required CI.

## Redundancy

Run leave-one-out analysis independently within each selected layer, during both initial segment selection and pruning. A scenario is redundant only when removing it loses neither BPMN coverage nor evidence for a specified guarantee. Keep scenarios that prove distinct contracts, even when they visit the same IDs. Cross-layer overlap is valid because process, integration, and business-outcome assertions have different isolation boundaries. Explain any deliberate diagnostic overlap within one layer.

## Combined report

After the selected automated suites run, emit:

- total reachable process element and sequence-flow coverage;
- connector/tool paths covered versus total, when point-integration tests apply;
- Whole-process path count and named outcomes, when that layer applies;
- per-suite and per-scenario/run coverage;
- machine-readable coverage data;
- interactive HTML with completed-element and taken-flow BPMN highlighting.

Open the HTML report after a passing local interactive run. If opening is unavailable, immediately print its absolute path.

## Live extension points

Document optional commands or Maven profiles for live endpoints, authenticated dependencies, or real models. Keep these profiles outside the default lifecycle so `mvn test` remains repeatable, offline, and credential-free.
