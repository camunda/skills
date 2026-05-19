# FEEL in DMN

DMN uses FEEL (Friendly Enough Expression Language) for every expression-bearing element. The full FEEL reference lives in **camunda-feel** — this file covers only the DMN-specific contexts and the unary-tests subset.

## Where FEEL appears in DMN

| Location | FEEL flavour | Implicit subject | Example |
|---|---|---|---|
| `inputExpression` / `text` | full FEEL | none | `customer.totalAmount * 1.19` |
| `inputEntry` / `text` (decision-table cell, condition side) | **unary tests** | the input value | `>= 1000`, `"gold", "silver"`, `not(null)` |
| `outputEntry` / `text` (decision-table cell, result side) | full FEEL | none | `{ status: "approved", limit: amount * 2 }` |
| `literalExpression` / `text` | full FEEL | none | `if size(orders) > 0 then orders[1].id else null` |
| `variable` declaration in literal expression decisions | n/a (name + typeRef) | n/a | `<variable name="result" typeRef="string"/>` |

The expression context differs in two important ways from FEEL in BPMN:

1. **No `=` prefix.** Unlike BPMN, where every FEEL expression starts with `=`, DMN FEEL is implicit — every `text` element is parsed as FEEL. Adding `=` is a syntax error.
2. **The cell is the unit.** Each input entry / output entry is evaluated as a separate FEEL expression. You cannot share state across rules.

## Unary tests — the narrower grammar

`inputEntry` cells use **unary tests**, a subset of FEEL designed for "does this value match this condition?". Differences from full FEEL:

- The input value is implicit. `< 5` is shorthand for `? < 5` where `?` is the input.
- A bare literal means equality: `"Winter"` matches when the input equals `"Winter"`.
- Comma-separated lists mean OR: `"Winter", "Spring"` matches either value.
- Comma-separated comparisons mean AND across the same input: `> 0, < 100` matches values in `(0, 100)`.
- Ranges: `[1..10]` (closed), `(1..10)` (open), `[1..10)` (half-open).
- Negation: `not("Winter", "Spring")` matches anything other than those.
- Wildcard: `-` matches anything.
- Function calls are still legal: `starts with("PREFIX-")`, `contains(?, "smith")`, `even(?)`.
- Variable references are legal: `< threshold` where `threshold` is in scope.

### What you cannot do in a unary test

- Arithmetic on the implicit input alone is not valid as a *condition* — write the comparison explicitly. `* 2 > 100` is wrong; `? * 2 > 100` works.
- Local variable binding (`let ... in ...`) is not part of unary tests.
- Multi-statement expressions are not supported — one expression per cell.

If you need expressive logic beyond unary tests, move it to the upstream `inputExpression` (which is full FEEL) and keep the unary test simple.

## Variable scope across linked decisions

When `decision B` requires `decision A` via `informationRequirement`, the result of A is in scope for B under A's decision ID:

- A has **one output** (no `name`): use `decisionAId` as the variable.
- A has **multiple outputs** (each with `name`): use `decisionAId.outputName`.

Example — `seasonalMenu` depends on `season`:

```xml
<decision id="season">
  <variable name="season" typeRef="string"/>
  <literalExpression><text>if today().month in [12, 1, 2] then "Winter" else "Other"</text></literalExpression>
</decision>

<decision id="seasonalMenu">
  <informationRequirement><requiredDecision href="#season"/></informationRequirement>
  <decisionTable>
    <input>
      <inputExpression typeRef="string"><text>season</text></inputExpression>
    </input>
    <!-- ... -->
  </decisionTable>
</decision>
```

Here the input expression `season` references the result of the `season` decision (which is a literal expression with a `<variable name="season"/>` declaration). For a decision table with `id="season"` and a single output, the reference would still be `season`. For a multi-output table with `id="seasons"` and outputs `name="hemisphere"` and `name="solstice"`, references would be `seasons.hemisphere` and `seasons.solstice`.

Only the root decision is invoked from BPMN; required decisions are evaluated transparently and exist only within DMN scope.

## FEEL features especially useful in DMN

- **`list contains`**: `list contains(blocklist, customer.id)` — boolean check.
- **`item in collection` filtering**: `customer.orders[totalAmount > 1000]` — returns the matching items as a list. Useful in `inputExpression`.
- **Context literals**: `{ status: "ok", details: { code: 200 } }` — produce a structured output entry without a separate decision.
- **`get value(context, "key")`** / **`get entries(context)`**: navigate context maps without dot notation; handy when keys are dynamic.
- **Date arithmetic**: `today() - person.birthDate` produces a `dayTimeDuration` you can compare in unary tests.
- **Date components are properties, not functions.** `someDate.month`, `someDate.year`, `someDate.day`, `someDate.weekday`. There is no `month(date)` function — `month(today())` raises `NO_FUNCTION_FOUND` at runtime and the decision returns `null`.

For full FEEL reference and gotchas (number/string coercion, `null` handling), see **camunda-feel**.
