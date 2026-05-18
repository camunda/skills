---
name: camunda-dmn
description: |
  Use this skill to author and validate DMN (Decision Model and Notation) decisions for Camunda 8 — decision tables and literal expressions inside a Decision Requirements Diagram (DRD).

  Use for: creating new DMN files, editing decision tables (inputs, outputs, rules, hit policies), authoring decision literal expressions, linking decisions via informationRequirement, wiring a business rule task in BPMN to a DMN decision, validating decision files structurally with `npx dmnlint` and behaviourally by execution (CPT preferred, deploy fallback).

  Do not use for: writing FEEL syntax in detail (use camunda-feel), modelling the BPMN side of a business rule task (use camunda-bpmn), authoring CPT test scenarios that exercise the decision (use camunda-process-test), deploying DMN to a cluster outside the validation loop (use camunda-process-mgmt).

  **Workflow skill** — DRD planning, decision-table authoring, then a two-stage validation loop: `npx dmnlint` for structure, CPT or deploy for behaviour.
---

# Camunda DMN

Author executable DMN 1.3 decisions for Camunda 8.8+. DMN files (`.dmn`) hold one Decision Requirements Diagram with one or more decisions; each decision contains either a decision table or a literal expression. A BPMN business rule task references a decision by ID and gets the decision result back as a process variable.

## Prerequisites

- Camunda 8.8+ cluster — local via c8run is recommended for the behaviour validation loop; SaaS or Self-Managed work too
- Node.js + `npx` available for `dmnlint` (no install step — `npx --yes dmnlint` fetches on first run)
- For the CPT behaviour path: Java 21+, Maven, Docker — see **camunda-process-test**

## Cross-References

- **camunda-bpmn**: Use for the business rule task that calls the DMN decision (`<zeebe:calledDecision decisionId="..." resultVariable="..."/>`)
- **camunda-feel**: Use for FEEL syntax in input expressions, output entries, and literal expressions
- **camunda-process-test**: **Preferred behaviour validation path** — CPT runs the decision against an embedded Zeebe engine via the calling BPMN process. Fast feedback loop, no cluster needed.
- **camunda-process-mgmt**: Fallback behaviour validation — deploy and run on a real cluster (prefer local c8run; safety check before any shared cluster)
- **camunda-c8ctl**: Always pass `--profile=<name>` on deploy commands and confirm with the user before touching anything that isn't local c8run

## Instructions

### XML structure

Every DMN file declares the DMN 1.3 namespace and a `definitions` element (the Decision Requirements Graph) wrapping one or more `decision` elements:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             id="DinnerDecisions"
             name="Dinner Decisions"
             namespace="http://camunda.org/schema/1.0/dmn">
  <decision id="dish" name="Dish">
    <decisionTable id="decisionTable_dish" hitPolicy="UNIQUE">
      <!-- inputs, outputs, rules -->
    </decisionTable>
  </decision>
</definitions>
```

The default namespace `https://www.omg.org/spec/DMN/20191111/MODEL/` and the `namespace="http://camunda.org/schema/1.0/dmn"` attribute are mandatory for Camunda to recognise the file.

### IDs and names — strict rules

- **Decision ID**, **output `name`**, and decision table column names: alphanumeric and `_` only. No whitespace, no `-`, no other special characters. `camelCase` or `snake_case`; `kebab-case` is rejected because `-` is a FEEL operator.
- **`name` attributes** (the human-readable label shown in Modeler and lint output) can be any string. `dmnlint` flags missing `name` on every Decision, InputData, BusinessKnowledgeModel, KnowledgeSource, or DecisionService — set one even when an `id` already conveys intent.
- An ID that violates these rules silently breaks dependent decisions and BPMN references — the value comes back as `null` at runtime.

### Decision tables

A decision table consists of inputs (conditions), outputs (conclusions), rules (rows), and a hit policy.

**Inputs.** Each `input` clause has an `inputExpression` written in FEEL. The expression references a process variable available at evaluation time:

```xml
<input id="input_season" label="Season">
  <inputExpression id="inputExpression_season" typeRef="string">
    <text>season</text>
  </inputExpression>
</input>
```

`typeRef` is optional but recommended — it converts the evaluated input to the declared DMN data type (`string`, `number`, `boolean`, `date`, `time`, `dateTime`, `dayTimeDuration`, `yearMonthDuration`).

**Outputs.** Each `output` clause defines a result column with a `name` (referenced by BPMN, must follow the ID rules above) and an optional `typeRef`:

```xml
<output id="output_dish" label="Dish" name="desiredDish" typeRef="string"/>
```

If the table has only **one output**, omit `name` — the BPMN process accesses the result directly via the decision ID. If the table has **multiple outputs**, give each a unique `name`; BPMN then accesses them via `decisionId.outputName`.

**Rules.** Each `rule` is one row. Input entries are FEEL **unary tests** (e.g. `"Winter"`, `<= 8`, `[1..10]`, `not("Winter", "Spring")`, or `-` for "any value"). Output entries are full FEEL expressions:

```xml
<rule id="rule_winter_party">
  <inputEntry id="ie_season"><text>"Winter"</text></inputEntry>
  <inputEntry id="ie_guests"><text><![CDATA[<= 8]]></text></inputEntry>
  <outputEntry id="oe_dish"><text>"Roastbeef"</text></outputEntry>
</rule>
```

Wrap entries containing XML special characters (`<`, `>`, `&`) in `<![CDATA[...]]>` or escape them (`&lt;`, `&gt;`, `&amp;`).

**Output strings must be quoted.** `"HIGH"` is a FEEL string literal; bare `HIGH` is parsed as a variable reference and evaluates to `null` at runtime — no parse error, no lint warning, just a silently-broken decision. Always quote string output entries.

### Hit policies — Camunda-supported set

The hit policy goes on the `decisionTable` element: `<decisionTable id="..." hitPolicy="UNIQUE">`. Default is `UNIQUE` when omitted.

**Camunda 8 supports five hit policies** (the DMN spec defines more — Camunda does **not** support `PRIORITY` or `OUTPUT ORDER`):

| Hit policy | Single/multi result | Behaviour |
|---|---|---|
| `UNIQUE` (default) | single | Exactly one rule must match. More than one match is a runtime error. Best when the table is meant to partition the input space without overlap. |
| `ANY` | single | Multiple rules may match, but they must all produce the same output. Different outputs from overlapping rules → runtime error. Useful when several conditions converge on the same conclusion. |
| `FIRST` | single | Rules evaluated top-to-bottom; the first match wins. Use when overlap is intentional and the order encodes priority (e.g. "blocklist first, then accept rules"). |
| `RULE ORDER` | multi | All matching rules' outputs in rule order, as a list. |
| `COLLECT` | multi | All matching rules' outputs in arbitrary order, as a list. Can be combined with an aggregator: `aggregation="SUM" \| "MIN" \| "MAX" \| "COUNT"` — collapses the list to a single value. |

Pick `UNIQUE` first; switch to `FIRST` only when the table has hard-then-soft semantics, and `COLLECT` (with or without aggregator) when you genuinely want a list back. See [references/decision-tables.md](references/decision-tables.md) for worked examples per hit policy.

### Decision literal expressions

When a decision is a single FEEL expression rather than a table — for example, combining the outputs of two upstream decisions — use `literalExpression`:

```xml
<decision id="season" name="Season">
  <variable name="season" typeRef="string"/>
  <literalExpression>
    <text>if month(date) in [12, 1, 2] then "Winter" else "Other"</text>
  </literalExpression>
</decision>
```

The `variable` element declares the result name and type. The `text` inside `literalExpression` is full FEEL.

### Linking decisions (Decision Requirements Graph)

One decision can depend on another. Declare the dependency with `informationRequirement` → `requiredDecision`:

```xml
<decision id="beverages" name="Beverages">
  <informationRequirement>
    <requiredDecision href="#dish"/>
  </informationRequirement>
  <decisionTable id="decisionTable_beverages">
    <input id="input_dish" label="Dish">
      <inputExpression id="inputExpression_dish" typeRef="string">
        <text>dish</text>
      </inputExpression>
    </input>
    <!-- ... -->
  </decisionTable>
</decision>
```

The required decision is evaluated first; its result is then in scope under its decision ID (or `decisionId.outputName` for multi-output tables). Camunda only evaluates the **root decision** referenced from BPMN — required decisions are pulled in transparently. Duplicate `informationRequirement` edges to the same upstream decision are flagged by `dmnlint` (`no-duplicate-requirements`) — keep one.

### Wiring a business rule task in BPMN

The BPMN side is a service-of-decision: a `bpmn:businessRuleTask` with `zeebe:calledDecision`:

```xml
<bpmn:businessRuleTask id="DecideMenu" name="Decide menu">
  <bpmn:extensionElements>
    <zeebe:calledDecision decisionId="beverages" resultVariable="menuChoice"/>
  </bpmn:extensionElements>
  <!-- incoming/outgoing flows -->
</bpmn:businessRuleTask>
```

`decisionId` matches the DMN `decision id`. `resultVariable` is the process variable that receives the decision result. The structure of that variable depends on the hit policy — a single result for `UNIQUE`/`ANY`/`FIRST`, a list for `RULE ORDER`/`COLLECT` (or a scalar for `COLLECT` with aggregator).

**`resultVariable` overwrites.** The decision result lands in the process variable named by `resultVariable`. If that name matches an existing input variable, the input is **clobbered**. Pick a distinct result name (e.g. `discountPercent` not `customer`) so downstream activities can still read the input.

`<zeebe:calledDecision>` also accepts a `bindingType` attribute — `latest` (default), `deployment`, or `versionTag` — controlling which deployed version of the decision is resolved at runtime. See **camunda-bpmn** for the binding-type table; `deployment` is the right choice when BPMN and DMN are co-deployed.

See **camunda-bpmn** for the surrounding BPMN structure.

### Validation — two-stage loop

DMN validation has two layers, both required before declaring a file done.

#### Stage 1: structural lint — `dmnlint`

Camunda's CI/CD guide ([docs.camunda.io › modeler › web-modeler › integrate-web-modeler-in-ci-cd](https://docs.camunda.io/docs/components/modeler/web-modeler/integrate-web-modeler-in-ci-cd/#test-stage)) recommends `dmnlint` alongside `bpmnlint` for verifying decision files in CI — the same library Web Modeler uses for inline validation.

A DMN edit is **not structurally done** until `npx dmnlint` reports zero errors AND zero warnings. Treat this as the closing structural step of every DMN task.

1. Ensure a `.dmnlintrc` exists in the project root (idempotent):

   ```bash
   [ -f .dmnlintrc ] || echo '{ "extends": "dmnlint:recommended" }' > .dmnlintrc
   ```

2. Run the linter against the file you touched:

   ```bash
   npx --yes dmnlint path/to/decision.dmn
   ```

   For a directory of DMN files, pass the discovered file list explicitly so build directories (`target/`, `build/`, `node_modules/`, `.git/`) are skipped.

3. If output is non-empty, fix every reported issue and re-run. Common categories — see [references/dmnlint.md](references/dmnlint.md) for the full rule → fix mapping:

   - **label-required** — add a descriptive `name` attribute to the flagged element
   - **no-duplicate-requirements** — remove the duplicate `informationRequirement` / `knowledgeRequirement` / `authorityRequirement` edge

4. Loop until the linter is clean. Do not advance to stage 2 while warnings remain — they typically point at modelling oversights (unnamed decisions, broken DRG references) that will produce confusing incidents at evaluation time.

If a warning is genuinely a false positive, suppress it explicitly in `.dmnlintrc` and flag the suppression in your final message — never silently ignore.

#### Stage 2: behaviour validation — by execution

`dmnlint` catches structure, not runtime behaviour (FEEL errors, hit-policy violations, type mismatches, missing variables). Validate behaviour by **running the decision**.

**Path A — Camunda Process Test (preferred).** If the repo already has a CPT setup, that's the best feedback loop — fastest, no cluster, embedded Zeebe runs the decision via the calling BPMN business rule task. Write or extend a `.test.json` scenario that exercises the rules that matter (each `UNIQUE` partition, each `FIRST` cascade, each `COLLECT` aggregator path) and run `mvn test`.

See **camunda-process-test** for authoring scenarios and the segment-based coverage approach.

**Path B — deploy and start an instance.** For ad-hoc validation or projects without CPT, deploy the BPMN + DMN together and start an instance with representative input. The cluster parses both files and evaluates the decision (catching FEEL errors, hit-policy violations, type mismatches).

Cluster safety — prefer local c8run, always pass `--profile=` explicitly, confirm with the user before deploying to anything shared. See **camunda-process-mgmt** for the deploy-and-run flow and **camunda-c8ctl** for the cluster-safety rules.

```bash
c8ctl cluster status || c8ctl cluster start
c8ctl deploy decision.dmn process.bpmn --profile=local
c8ctl await pi --id MyProcess --variables '{"customer":{"tier":"gold"}}' --profile=local
```

If the instance raises an incident, inspect with `c8ctl search inc --state=ACTIVE` — `EXTRACT_VALUE_ERROR` points at a FEEL problem, `DECISION_EVALUATION_FAILED` at a hit-policy violation.

Iterate: fix the DMN, re-lint, redeploy, restart.

### Minimal worked example

A two-rule table that drives a business rule task:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             id="DiscountDecisions" name="Discount Decisions"
             namespace="http://camunda.org/schema/1.0/dmn">
  <decision id="discount" name="Discount">
    <decisionTable id="dt_discount" hitPolicy="UNIQUE">
      <input id="input_tier" label="Customer tier">
        <inputExpression id="ie_tier" typeRef="string">
          <text>customer.tier</text>
        </inputExpression>
      </input>
      <output id="output_discount" label="Discount %" name="discountPercent" typeRef="number"/>
      <rule id="rule_gold">
        <inputEntry id="ie_gold"><text>"gold"</text></inputEntry>
        <outputEntry id="oe_gold"><text>15</text></outputEntry>
      </rule>
      <rule id="rule_silver">
        <inputEntry id="ie_silver"><text>"silver"</text></inputEntry>
        <outputEntry id="oe_silver"><text>5</text></outputEntry>
      </rule>
    </decisionTable>
  </decision>
</definitions>
```

BPMN side:

```xml
<bpmn:businessRuleTask id="ApplyDiscount" name="Apply discount">
  <bpmn:extensionElements>
    <zeebe:calledDecision decisionId="discount" resultVariable="discountPercent"/>
  </bpmn:extensionElements>
</bpmn:businessRuleTask>
```

Validate: `npx --yes dmnlint discount.dmn` → clean → deploy both files together with `c8ctl deploy ./*.dmn ./*.bpmn` (see **camunda-process-mgmt**).

## References

For detailed reference material, read from `references/`:

- [decision-tables.md](references/decision-tables.md) — input clauses, output clauses, FEEL unary tests, hit-policy worked examples, COLLECT aggregators, decision table data types
- [feel-in-dmn.md](references/feel-in-dmn.md) — where FEEL appears in DMN, unary-tests grammar vs. full FEEL, variable scope across linked decisions
- [dmnlint.md](references/dmnlint.md) — `dmnlint:recommended` rule set, rule → fix mapping, `.dmnlintrc` shape, CI integration
