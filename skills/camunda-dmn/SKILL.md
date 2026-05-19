---
name: camunda-dmn
description: |
  Use this skill to author and validate DMN (Decision Model and Notation) decisions for Camunda 8 — decision tables and literal expressions inside a Decision Requirements Diagram (DRD).

  Use for: creating or editing `.dmn` files, picking the right hit policy, wiring a business rule task in BPMN to a DMN decision, validating decisions structurally (`npx dmnlint`) and behaviourally (CPT preferred, deploy fallback).

  Do not use for: writing FEEL syntax in detail (use camunda-feel), modelling the BPMN around a business rule task (use camunda-bpmn), authoring CPT test scenarios (use camunda-process-test).

  **Workflow skill** — author the decision, lint it, run it.
---

# Camunda DMN

Author executable DMN 1.3 decisions for Camunda 8.8+. A `.dmn` file holds one Decision Requirements Diagram with one or more decisions; each decision is either a decision table or a literal expression. A BPMN business rule task references a decision by ID and gets the result back as a process variable.

## Cross-References

- **camunda-bpmn**: Business rule task wiring (`<zeebe:calledDecision decisionId="..." resultVariable="..."/>`)
- **camunda-feel**: FEEL syntax inside input expressions, output entries, literal expressions
- **camunda-process-test**: Preferred behaviour validation — CPT exercises the decision via the calling BPMN
- **camunda-process-mgmt**: Fallback behaviour validation — deploy and run on a cluster (prefer local c8run)

## Authoring

A DMN file declares the DMN 1.3 namespace and wraps one or more `<decision>` elements:

```xml
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             id="DinnerDecisions" name="Dinner Decisions"
             namespace="http://camunda.org/schema/1.0/dmn">
  <decision id="dish" name="Dish">
    <decisionTable id="decisionTable_dish" hitPolicy="UNIQUE">
      <!-- inputs, outputs, rules -->
    </decisionTable>
  </decision>
</definitions>
```

The default namespace and the `namespace="http://camunda.org/schema/1.0/dmn"` attribute are mandatory.

A decision contains either a `<decisionTable>` (inputs / outputs / rules + hit policy) or a `<literalExpression>` (single FEEL expression — useful for combining upstream decisions). Multi-decision files link decisions with `<informationRequirement><requiredDecision href="#upstream"/></informationRequirement>`; Camunda evaluates only the root decision referenced from BPMN and pulls in required decisions transparently.

See [references/decision-tables.md](references/decision-tables.md) for the full XML of input/output clauses, unary-test grammar, worked examples per hit policy, COLLECT aggregators, type table, and DRG linking.

### ID and naming rules

- **Decision `id`**, **output `name`**, decision-table column names: alphanumeric + `_` only. No whitespace, no `-` (which is a FEEL operator), no other special characters. A violation silently breaks BPMN references — the resolved value is `null` at runtime.
- **`name` attributes** (Decision, InputData, BusinessKnowledgeModel, KnowledgeSource, DecisionService): any string. `dmnlint` flags missing `name` — set one even when `id` already conveys intent.
- **String output entries must be quoted.** `"HIGH"` is a string literal; bare `HIGH` parses as a variable reference and evaluates to `null` — no parse error, no lint warning.

### Hit policies (Camunda-supported set)

Set on the `decisionTable` element (default `UNIQUE`). Camunda 8 supports five; the DMN spec defines more — `PRIORITY` and `OUTPUT ORDER` are **not** supported.

| Hit policy | Result | Behaviour |
|---|---|---|
| `UNIQUE` | single | Exactly one rule must match; multi-match = runtime error. |
| `ANY` | single | Multiple may match, must all produce the same output; otherwise runtime error. |
| `FIRST` | single | Top-to-bottom; first match wins. |
| `RULE ORDER` | list | All matching rules' outputs, in rule order. |
| `COLLECT` | list / scalar | All matches in arbitrary order. With `aggregation="SUM" \| "MIN" \| "MAX" \| "COUNT"`, collapses to a single value. |

Default to `UNIQUE`. Use `FIRST` for hard-then-soft semantics (e.g. "blocklist first, then accept rules"). Use `COLLECT` when a list output is genuinely the goal. See [references/decision-tables.md](references/decision-tables.md) for worked examples per policy.

## Wiring the BPMN side

```xml
<bpmn:businessRuleTask id="ApplyDiscount" name="Apply discount">
  <bpmn:extensionElements>
    <zeebe:calledDecision decisionId="discount" resultVariable="discountPercent"/>
  </bpmn:extensionElements>
</bpmn:businessRuleTask>
```

`decisionId` matches the DMN `decision id`. `resultVariable` receives the result — single-result for `UNIQUE`/`ANY`/`FIRST`, list for `RULE ORDER`/`COLLECT` (or scalar with aggregator).

**`resultVariable` overwrites.** If the name matches an existing input variable, the input is clobbered — pick a distinct name (e.g. `discountPercent` not `customer`) so downstream activities can still read the input.

`<zeebe:calledDecision>` also accepts `bindingType` — `latest` (default), `deployment`, `versionTag`. See **camunda-bpmn** for the binding-type table; `deployment` is the right choice when BPMN and DMN are co-deployed.

## FEEL inside DMN

DMN uses FEEL in `inputExpression`, `inputEntry` (unary tests), `outputEntry`, and `literalExpression`. Unlike BPMN, **no `=` prefix** — every `text` element is parsed as FEEL.

Input entries use the **unary tests** subset: the input value is implicit, `< 5` means `? < 5`, comma-separated literals are OR, comma-separated comparisons are AND, ranges are `[1..10]` / `(1..10)`, `not(...)` negates, `-` matches anything.

See [references/feel-in-dmn.md](references/feel-in-dmn.md) for the unary-test grammar, what you cannot do in a unary test, variable scope across linked decisions, and DMN-specific FEEL features.

## Validation

Two layers — run both before declaring a file done.

**1. Structural lint.** A DMN edit is not structurally done until `npx dmnlint` reports zero issues.

```bash
[ -f .dmnlintrc ] || echo '{ "extends": "dmnlint:recommended" }' > .dmnlintrc
npx --yes dmnlint path/to/decision.dmn
```

Common rules: `label-required` (add a `name`), `no-duplicate-requirements` (drop the duplicate `informationRequirement` edge). See [references/dmnlint.md](references/dmnlint.md) for the full rule → fix mapping.

**2. Behaviour validation by execution.** `dmnlint` does not understand FEEL, hit-policy correctness, or type matches. Run the decision:

- Preferred — write or extend a CPT scenario that exercises each `UNIQUE` partition / `FIRST` cascade / `COLLECT` path. See **camunda-process-test**.
- Fallback — deploy `c8ctl deploy decision.dmn process.bpmn --profile=local` and start an instance with `c8ctl await pi --id MyProcess --variables '{...}' --profile=local`. Incidents surface as `EXTRACT_VALUE_ERROR` (FEEL problem) or `DECISION_EVALUATION_FAILED` (hit-policy violation). See **camunda-process-mgmt**.

A green BPMN-completes test only proves the decision didn't fail — not that the right rules fired. For *behavioural correctness* assertions (`assertThatDecision`, rule-ordinal matching per hit policy, DRG coverage), see [references/testing-decisions.md](references/testing-decisions.md).

## References

- [decision-tables.md](references/decision-tables.md) — input/output clause shapes, unary-test forms, worked examples per hit policy, decision-level `<variable>` rules, type table, pitfalls
- [feel-in-dmn.md](references/feel-in-dmn.md) — FEEL contexts in DMN, unary-tests vs full FEEL, scope across linked decisions
- [dmnlint.md](references/dmnlint.md) — `dmnlint:recommended` rules, rule → fix mapping, common pitfalls beyond what the linter catches
- [testing-decisions.md](references/testing-decisions.md) — `assertThatDecision`, rule-ordinal matching, strategy by hit policy, DRG coverage, mock-vs-test
