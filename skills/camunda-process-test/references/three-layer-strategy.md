# Three-layer CPT strategy

Use this structure when a process contains connectors, agent tools, or business outcomes that cannot be proved by routing coverage alone. Deterministic process tests are always required. Add point-integration and process-integration/E2E layers only when their contracts apply, keep their artifacts separate, and combine evidence from every selected layer in one report.

| Layer | Contract | Required CI dependency |
|---|---|---|
| Deterministic process | BPMN reachability and routing | Mocked workers; no network or credentials |
| Point integration | One connector/tool path in isolation | Local stub or mocked dependency |
| Process integration/E2E | Named end-to-end business outcome | Local/mocked dependencies and controlled agent outcomes |

## Deterministic process tests

- Reach 100% of all reachable BPMN elements and sequence flows.
- Cover every gateway outcome, loop, end state, no-tool response, and agent tool.
- Control agent and connector jobs deterministically. Never call a model or external endpoint.
- Keep canonical intent in importable CPT JSON when the instruction format can express it. Use Java only for orchestration or assertions that JSON cannot express.
- Treat unreachable elements as BPMN defects. Name them; do not silently remove them from the denominator.

## Point integration tests

Create one isolated scenario for every connector or tool path:

1. Start immediately before the integration element.
2. Stop at the earliest useful assertion boundary after it.
3. Assert the intended element completed.
4. Assert unrelated tools and feedback paths did not activate.
5. Assert only a stable contract or shape, never exact volatile content.

The required CI path uses a local stub, fake server, or connector/job mock. If a real unauthenticated or configured endpoint is useful during development, put it behind an explicit live profile and document it separately; it is never a required pass gate.

## Process integration/E2E tests

- Name the expected business outcome.
- Prefer one scenario per process end state.
- For agentic requests, declare the expected tool **set** and assert every member was reached. Do not require tool order unless order is a business contract.
- Exercise feedback/retry topology where modeled: reject a result, provide follow-up input, then approve and complete.
- Do not assert exact generated wording or semantic answer quality.
- Run with controlled agent results and local/mocked integrations in required CI.

## Redundancy

Run leave-one-out analysis independently per layer. Removing a scenario must lose either coverage or contract evidence. Cross-layer overlap is valid because process, integration, and business-outcome assertions have different isolation boundaries. Explain any deliberate diagnostic overlap within one layer.

## Combined report

After the selected automated suites run, emit:

- total reachable process element and sequence-flow coverage;
- connector/tool paths covered versus total, when point-integration tests apply;
- E2E path count and named outcomes, when process-integration/E2E tests apply;
- per-suite and per-scenario/run coverage;
- machine-readable coverage data;
- interactive HTML with completed-element and taken-flow BPMN highlighting.

Open the HTML report after a passing local interactive run. If opening is unavailable, immediately print its absolute path.

## Live extension points

Document optional commands or Maven profiles for live endpoints, authenticated dependencies, or real models. Keep these profiles outside the default lifecycle so `mvn test` remains repeatable, offline, and credential-free.
