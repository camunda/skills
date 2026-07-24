# Testing decision behaviour

"Deploy and run the BPMN" verifies the decision doesn't *fail*; it does not verify the *right* rules fired or the outputs match expectations. A decision that returns the wrong dish for every season will pass any BPMN-completes test if the downstream gateway only checks "is the value non-null". This reference covers how to actually assert decision behaviour.

The mechanics described here live in **camunda-process-test** — see its `authoring.md` for the JSON instructions and Java surface. This file teaches *what to assert per hit policy and DRG shape*; the test skill teaches *how* to wire it up.

## Standalone evaluation — no BPMN

Evaluate a decision directly, without a process instance. The leaf decision in a DRD auto-evaluates upstream decisions linked via `informationRequirement`, so one call exercises the whole DRD.

Java (CPT or production code):

```java
var response = camundaClient.newEvaluateDecisionCommand()
    .decisionId("dish")
    .variables(Map.of("season", "Winter"))
    .send().join();
```

JSON instruction *(`.test.json` grammar, 8.9+)*:

```json
{
  "type": "EVALUATE_DECISION",
  "decisionDefinitionSelector": { "decisionDefinitionId": "dish" },
  "variables": { "season": "Winter" }
}
```

Pair with an assertion (`ASSERT_DECISION` in JSON, `CamundaAssert.assertThatDecision(...)` in Java).

## Decision-instance assertions

```java
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.assertions.DecisionSelectors;

CamundaAssert.assertThatDecision(DecisionSelectors.byId("season"))
    .isEvaluated()
    .hasOutput("Winter")
    .hasMatchedRules(1);
```

`DecisionSelectors`: `byId`, `byName`, `byProcessInstanceKey`, `byResponse` (for the standalone variant). The Java decision-assertion API shipped with CPT itself (8.8+).

JSON equivalent *(`.test.json` grammar, 8.9+)*:

```json
{
  "type": "ASSERT_DECISION",
  "decisionSelector": { "decisionDefinitionId": "season" },
  "output": "Winter",
  "matchedRules": [1]
}
```

### Rule numbering

`hasMatchedRules` takes **1-based ordinals** matching the order of rules in the decision table — not BPMN `id`s. The first `<rule>` in the XML is rule 1.

- `UNIQUE` / `ANY` / `FIRST` → single ordinal (`hasMatchedRules(2)`).
- `COLLECT` / `RULE ORDER` → all matched ordinals (`hasMatchedRules(1, 2, 4)`).

The API does not surface this 1-based convention in its types; the assertion error tells you only "expected X, got Y", so plan rule order with this in mind.

## Strategy by hit policy

| Hit policy | What to write | Assertion shape |
|---|---|---|
| `UNIQUE` | One scenario per rule, plus one no-match scenario if the table doesn't partition the full input space. | `.hasOutput(value).hasMatchedRules(N)` |
| `ANY` | One scenario per group of overlapping rules that produce the same output. | `.hasOutput(value).hasMatchedRules(a, b, ...)` |
| `FIRST` | One scenario per priority layer that exercises the cascade — the first rule's input, the second rule's input *with the first rule's input absent*, and so on. | `.hasOutput(value).hasMatchedRules(N)` |
| `RULE ORDER` / `COLLECT` (list) | One scenario per input partition that produces a distinct list. | `.hasOutput([list]).hasMatchedRules(a, b, c)` |
| `COLLECT` with aggregator | One scenario per distinct aggregated value. | `.hasOutput(scalar).hasMatchedRules(a, b, c)` |

A "no-match" scenario uses `.hasNoMatchedRules()` (Java) or `noMatchedRules: true` (JSON).

## DRG coverage

For a chained DRG — `B requires A` via `informationRequirement` — write one scenario per UNIQUE branch in `A`. Each scenario then exercises the downstream rules in `B` tied to that branch. Two `ASSERT_DECISION` blocks per scenario:

```json
{ "type": "EVALUATE_DECISION",
  "decisionDefinitionSelector": { "decisionDefinitionId": "beverages" },
  "variables": { "season": "Winter" } },
{ "type": "ASSERT_DECISION",
  "decisionSelector": { "decisionDefinitionId": "season" },
  "output": "Winter", "matchedRules": [1] },
{ "type": "ASSERT_DECISION",
  "decisionSelector": { "decisionDefinitionId": "beverages" },
  "output": "Mulled wine", "matchedRules": [2] }
```

The leaf evaluation pulls the upstream in transparently; both decision instances are assertable.

## Mocking vs testing

`processTestContext.mockDmnDecision(decisionId, output)` replaces a real DMN evaluation with a fixed output. Two distinct uses:

- **Mock**: in a BPMN flow test where DMN logic is not the unit under test — keeps the BPMN scenario stable when a rule changes.
- **Test**: with `assertThatDecision` against the real DMN — validates the rules themselves.

Use both. Mock the DMN in BPMN-flow tests so they don't break when rules change; assert the DMN directly in decision-focused tests so wrong outputs surface as test failures, not silent process completion.

## Format suggestion

DMN scenarios fit naturally in the JSON instruction format — inputs and expected matched rules are tabular, the audience (analysts maintaining rules) is closer to JSON than Java. Java is still fine when parameterized fixtures or shared expected-value computation help. Both work — match the format to the team.
