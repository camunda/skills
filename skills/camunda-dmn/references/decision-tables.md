# Decision table reference

Detailed reference for decision-table authoring beyond the SKILL.md basics.

## Input clauses

An `input` defines one column of conditions. The `inputExpression` is a FEEL expression (full FEEL, not unary tests) evaluated once per evaluation; its result is then compared against each rule's `inputEntry`.

```xml
<input id="input_amount" label="Order amount">
  <inputExpression id="ie_amount" typeRef="number">
    <text>order.totalAmount</text>
  </inputExpression>
</input>
```

- `text` is the FEEL expression. It usually references a variable from the process scope; it can also be a derived expression (`order.totalAmount * exchangeRate`).
- `typeRef` declares the DMN data type. After evaluation, the result is converted to that type. Mismatches surface at evaluation time.
- `label` is a human-readable column header shown in Modeler. The input expression is what the engine uses.

A decision table with no inputs is legal — it always evaluates the same rule (useful for environment-flag decisions).

## Output clauses

```xml
<output id="output_discount" label="Discount %" name="discountPercent" typeRef="number"/>
```

- `name` is the result key. It must be alphanumeric + `_`. Required when the table has more than one output; if only one output, leave `name` off and the BPMN process accesses the value directly via the decision ID.
- `typeRef` validates output entries against the declared type.
- Order: list outputs in the order rules will produce values; rule `outputEntry` elements bind positionally to outputs.

When a multi-output table is referenced as a required decision, results are grouped under the decision ID: `dish.desiredDish`, `dish.preparationTime`.

## Input entries — FEEL unary tests

Input entries use the **unary tests** subset of FEEL. The implicit subject is the input value; the entry returns `true` if the value matches.

| Form | Matches when input is | Example |
|---|---|---|
| `"Winter"` | equal to `"Winter"` | exact string match |
| `42` | equal to `42` | exact number match |
| `<= 8` | less than or equal to 8 | comparison |
| `>= 18, < 65` | both: `>= 18 AND < 65` | comma = AND |
| `"a", "b"` | `"a"` OR `"b"` | list of literals = OR |
| `[1..10]` | in range 1 to 10 inclusive | closed range |
| `(0..100)` | greater than 0 AND less than 100 | open range |
| `[0..100)` | `>= 0` AND `< 100` | mixed open/closed |
| `not("a", "b")` | neither `"a"` nor `"b"` | negation over a list |
| `-` | always | wildcard |
| (empty `<text/>`) | always | XML form of wildcard |

Other forms:

- **Variable comparison**: `< someVariable` works if the variable is in scope.
- **FEEL function calls**: `starts with("PREFIX-")`, `contains(name, "smith")` (the implicit input fills the first argument when relevant — but explicit calls are clearer).
- **Date / duration**: `< date("2026-01-01")`, `>= duration("P30D")`.

The unary-tests grammar is narrower than full FEEL — see [feel-in-dmn.md](feel-in-dmn.md) for the exact subset.

## Output entries — full FEEL

Output entries are full FEEL expressions:

```xml
<outputEntry id="oe_invoice"><text>{ amount: input.amount * 1.19, currency: "EUR" }</text></outputEntry>
```

Any FEEL expression that evaluates to a value of the output's `typeRef` is valid: literals, variable references, arithmetic, function calls, contexts, lists. String literals **must** be quoted — bare identifiers are parsed as variable references.

## Hit policies — worked examples

### UNIQUE (default)

Use when the table partitions the input space without overlap.

```xml
<decisionTable id="dt_tier" hitPolicy="UNIQUE">
  <input id="i_age" label="Age">
    <inputExpression typeRef="number"><text>age</text></inputExpression>
  </input>
  <output id="o_tier" label="Tier" name="tier" typeRef="string"/>
  <rule><inputEntry><text><![CDATA[< 18]]></text></inputEntry><outputEntry><text>"minor"</text></outputEntry></rule>
  <rule><inputEntry><text>[18..64]</text></inputEntry><outputEntry><text>"adult"</text></outputEntry></rule>
  <rule><inputEntry><text><![CDATA[>= 65]]></text></inputEntry><outputEntry><text>"senior"</text></outputEntry></rule>
</decisionTable>
```

If two rules can both match (e.g. an off-by-one in ranges), the engine raises an incident at runtime. Treat `UNIQUE` as a contract.

### ANY

Multiple rules may match, but they must all return the same output. Useful when several conditions imply the same conclusion:

```xml
<decisionTable hitPolicy="ANY">
  <input label="Vacation days left"><inputExpression typeRef="number"><text>daysLeft</text></inputExpression></input>
  <input label="Probation"><inputExpression typeRef="boolean"><text>probation</text></inputExpression></input>
  <output name="approval" typeRef="string"/>
  <rule><inputEntry><text>0</text></inputEntry><inputEntry><text>-</text></inputEntry><outputEntry><text>"refused"</text></outputEntry></rule>
  <rule><inputEntry><text>-</text></inputEntry><inputEntry><text>true</text></inputEntry><outputEntry><text>"refused"</text></outputEntry></rule>
  <rule><inputEntry><text><![CDATA[> 0]]></text></inputEntry><inputEntry><text>false</text></inputEntry><outputEntry><text>"approved"</text></outputEntry></rule>
</decisionTable>
```

If overlapping rules produce different outputs at runtime, the engine raises an incident.

### FIRST

Top-to-bottom evaluation, first match wins. Use for hard-then-soft semantics:

```xml
<decisionTable hitPolicy="FIRST">
  <input label="Customer"><inputExpression typeRef="string"><text>customer.id</text></inputExpression></input>
  <input label="Credit score"><inputExpression typeRef="number"><text>creditScore</text></inputExpression></input>
  <output name="decision" typeRef="string"/>
  <rule><inputEntry><text>blocklist[item = customer.id] != null</text></inputEntry><inputEntry><text>-</text></inputEntry><outputEntry><text>"refused"</text></outputEntry></rule>
  <rule><inputEntry><text>-</text></inputEntry><inputEntry><text><![CDATA[>= 700]]></text></inputEntry><outputEntry><text>"approved"</text></outputEntry></rule>
  <rule><inputEntry><text>-</text></inputEntry><inputEntry><text>-</text></inputEntry><outputEntry><text>"refused"</text></outputEntry></rule>
</decisionTable>
```

A catch-all final row makes the no-match path explicit. Without it, `FIRST` returns `null` when nothing matches.

### RULE ORDER

Returns all matching rules' outputs as a list, in rule order:

```xml
<decisionTable hitPolicy="RULE ORDER">
  <input label="Age"><inputExpression typeRef="number"><text>age</text></inputExpression></input>
  <output name="ad" typeRef="string"/>
  <rule><inputEntry><text><![CDATA[>= 18]]></text></inputEntry><outputEntry><text>"Cars"</text></outputEntry></rule>
  <rule><inputEntry><text><![CDATA[< 25]]></text></inputEntry><outputEntry><text>"Music"</text></outputEntry></rule>
  <rule><inputEntry><text><![CDATA[> 12]]></text></inputEntry><outputEntry><text>"Gaming"</text></outputEntry></rule>
</decisionTable>
```

For age 19, the BPMN result is `["Cars", "Music", "Gaming"]`.

### COLLECT

Returns all matching rules' outputs in **arbitrary order** as a list. Functionally similar to `RULE ORDER` when order does not matter — `COLLECT` is the right choice for permissions / groups / tags:

```xml
<decisionTable hitPolicy="COLLECT">
  <input label="Order amount"><inputExpression typeRef="number"><text>amount</text></inputExpression></input>
  <output name="reviewer" typeRef="string"/>
  <rule><inputEntry><text><![CDATA[>= 1000]]></text></inputEntry><outputEntry><text>"sales"</text></outputEntry></rule>
  <rule><inputEntry><text><![CDATA[>= 10000]]></text></inputEntry><outputEntry><text>"management"</text></outputEntry></rule>
</decisionTable>
```

For amount 15000, both rules match; result is a list `["sales", "management"]` (order not guaranteed).

### COLLECT with aggregators

Add `aggregation="SUM" | "MIN" | "MAX" | "COUNT"` to collapse the list into a single value:

```xml
<decisionTable hitPolicy="COLLECT" aggregation="SUM">
  <input label="Years at company"><inputExpression typeRef="number"><text>years</text></inputExpression></input>
  <output name="bonus" typeRef="number"/>
  <rule><inputEntry><text><![CDATA[>= 1]]></text></inputEntry><outputEntry><text>100</text></outputEntry></rule>
  <rule><inputEntry><text><![CDATA[>= 3]]></text></inputEntry><outputEntry><text>200</text></outputEntry></rule>
  <rule><inputEntry><text><![CDATA[>= 5]]></text></inputEntry><outputEntry><text>300</text></outputEntry></rule>
</decisionTable>
```

For 4 years, rules 1 and 2 match; `SUM` aggregator returns `300`.

`COLLECT` with aggregator requires the output to be a numeric type for `SUM`/`MIN`/`MAX`; `COUNT` works for any type and returns the number of matches.

### Hit policies Camunda does NOT support

The DMN spec defines `PRIORITY` and `OUTPUT ORDER`. **Camunda 8 does not support these.** If you need priority-based selection, use `COLLECT` and post-process the list in the calling BPMN — e.g. with a FEEL script task that selects by a priority field.

## DMN data types

`typeRef` accepts:

| Type | FEEL literal | Notes |
|---|---|---|
| `string` | `"text"` | |
| `number` | `42`, `3.14` | |
| `boolean` | `true`, `false` | |
| `date` | `date("2026-01-01")` | ISO 8601 |
| `time` | `time("14:30:00")` | |
| `dateTime` | `date and time("2026-01-01T14:30:00")` | |
| `dayTimeDuration` | `duration("P30D")` | days/hours/minutes/seconds |
| `yearMonthDuration` | `duration("P1Y6M")` | years/months |

Type-checking is best-effort — DMN converts where it can and raises a runtime error where it cannot. Declare `typeRef` to catch shape mismatches early.

## Common pitfalls

- **Unquoted string output**: `HIGH` instead of `"HIGH"` parses as a variable reference and evaluates to `null` at runtime. `dmnlint` does not catch this; behaviour validation does.
- **`null` result from BPMN**: the `resultVariable` name and decision ID/output name don't match (case-sensitive), or the ID/output name contains a forbidden character (`-`, whitespace) so the engine can't resolve it.
- **`resultVariable` clobbering**: pick a name distinct from any input variable — DMN overwrites silently.
- **Input wildcard inconsistency**: `-` and an empty `<text/>` both mean "any value" but mixing them in a file is noisy. Pick one — `-` is the conventional form in Modeler-generated DMN.
- **CDATA wrapping**: input entries containing `<`, `>`, `&` should be wrapped in `<![CDATA[...]]>` to avoid XML escaping confusion. `<= 8` becomes `<![CDATA[<= 8]]>`.
- **Hit policy violations at runtime, not deploy**: `UNIQUE` / `ANY` violations only surface when input data matches multiple rules. Test the table with the values that exercise overlap, not just the happy path.
