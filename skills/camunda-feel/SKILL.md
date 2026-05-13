---
name: camunda-feel
description: |
  Use this skill to write, debug, and evaluate FEEL (Friendly Enough Expression Language) expressions for Camunda 8 — the expression language Zeebe uses in BPMN, DMN, and Camunda Forms.

  Use for: gateway conditions and conditional sequence flows; service-task input/output mappings; timer durations and cycles (ISO 8601 PT.../R...); DMN input/output entries; Camunda Form validation rules and conditional visibility; connector result and error expressions; list filters, projections, and quantifiers; date and duration arithmetic; type coercion (number-to-string); null-safe access; debugging FEEL_RESOLUTION_ERROR or "Can't add 'N' to ..." warnings.

  Do not use for: writing the BPMN XML around expressions (use camunda-bpmn) or designing form structure (use camunda-forms).

  **Utility skill** — FEEL is reused inside BPMN, DMN, forms, and connector configuration. Covers c8ctl feel evaluate for validating expressions.
---

# Camunda FEEL Expressions

Write, debug, and evaluate FEEL expressions used in Camunda 8 BPMN processes, DMN decisions, and forms.

## Prerequisites

- c8ctl CLI installed and configured (`c8ctl add profile`) — provides `c8ctl feel evaluate`
- Camunda 8.9+ cluster for default cluster-engine evaluation (uses `POST /v2/expression/evaluation`)

## Cross-References

- **camunda-bpmn**: Use when FEEL expressions are part of BPMN conditions or I/O mappings
- **camunda-forms**: Use when FEEL expressions control form validation or conditional visibility
- **camunda-ai-agent**: Use when FEEL expressions are prompts, `fromAi()` parameter declarations, or `toolCallResult` shaping in an AI Agent process

## Instructions

### FEEL in Camunda

FEEL is used for:
- **Gateway conditions**: Route process flow based on variable values
- **Input/output mappings**: Transform variables between process scopes
- **Timer definitions**: Define durations, dates, and cycles
- **DMN decision tables**: Define input/output rules
- **Form validation**: Validate user input

All FEEL expressions in BPMN XML must be prefixed with `=`:
```xml
<bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">=amount &gt; 1000</bpmn:conditionExpression>
```

### Expression Evaluation

To validate and debug FEEL expressions, use `c8ctl feel evaluate`. By default this runs against the configured cluster's Scala FEEL engine — the same engine that Zeebe uses at runtime, so results match production behavior exactly.

```bash
# Simple expression
c8ctl feel evaluate '1 + 2'

# Expression with individual variables (leading = optional)
c8ctl feel evaluate '=amount * 1.15' --var amount=100

# Multiple variables
c8ctl feel evaluate 'a + b' --var a=1 --var b=2

# JSON values for complex types
c8ctl feel evaluate 'sum(items)' --var 'items=[1,2,3]'

# Bulk variables as a single JSON object
c8ctl feel evaluate 'orderTotal > 1000 and customer.tier = "premium"' \
  --vars '{"orderTotal": 1500, "customer": {"tier": "premium"}}'

# Dot-path nesting on the CLI
c8ctl feel evaluate 'customer.name' --var customer.name=Alice
```

**Debugging workflow:**
1. Write the expression
2. Identify the expected variable context
3. Evaluate via `c8ctl feel evaluate` to validate against the cluster engine
4. If evaluation fails, fix based on error message and retry

#### Offline evaluation (`--engine local`)

`c8ctl feel evaluate --engine local` evaluates expressions locally using the `feelin` JavaScript engine — useful when no cluster is available. **Use only when explicitly requested or when no cluster is reachable AND the user has confirmed the fallback.** Never silently fall back.

`feelin` behaves DIFFERENTLY from the Scala FEEL engine that Zeebe runs in production. Subtle differences in type coercion, function support, and date/time handling can cause an expression that passes locally to fail in the cluster (and vice versa). Always re-validate against the cluster before relying on a result obtained with `--engine local`.

```bash
c8ctl feel evaluate '=amount * 1.15' --var amount=100 --engine local
```

**Concrete divergence: `today()` returns a different type.** On the cluster engine, `today()` returns a `date` (e.g. `2026-05-12`). On `--engine local` (feelin), it returns a date-time at midnight in the local timezone (e.g. `2026-05-12T00:00:00.000+02:00`). This breaks downstream comparisons:

```bash
# cluster engine — passes
c8ctl feel evaluate 'today() = date("2026-05-12")'           # → true

# local engine — fails silently
c8ctl feel evaluate 'today() = date("2026-05-12")' --engine local   # → false
```

If a date-typed argument is required by a downstream function, the local result may also raise a type error that the cluster never sees.

### Core Syntax

**Data Types**: Numbers (`1`, `1.5`), Strings (`"hello"`), Booleans (`true`/`false`), `null`, Dates (`date("2024-01-15")`), Times (`time("14:30:00")`), Date-times (`date and time("2024-01-15T14:30:00")`), Durations (`duration("P1D")`), Lists (`[1, 2, 3]`), Contexts (`{name: "Alice"}`), Ranges (`[1..10]`)

**Operators**: `+`, `-`, `*`, `/`, `**`, `=`, `!=`, `<`, `>`, `<=`, `>=`, `and`, `or`, `not()`, `between x and y`, `in`

**If-Then-Else** (every `if` requires `else`):
```feel
if score >= 80 then "A" else if score >= 60 then "B" else "C"
```

**For Loops**:
```feel
for x in [1, 2, 3] return x * 2
```

**Quantifiers**:
```feel
every x in items satisfies x.price > 0
some x in items satisfies x.status = "urgent"
```

**List Operations**:
- 1-based indexing: `list[1]`, negative: `list[-1]`
- Filter: `items[price > 100]`
- Projection: `items.name` extracts name from each item

**Context Operations**:
- Property access: `customer.name`
- `get value(ctx, "key")`, `get entries(ctx)`
- `context put(ctx, "key", value)`, `context merge(ctx1, ctx2)`

### Common Patterns in Camunda

**Gateway condition**:
```feel
=orderTotal > 1000 and customer.tier = "premium"
```

**Input mapping with transformation**:
```feel
="https://api.example.com/users/" + string(userId)
```

The `string()` wrapper is required, not stylistic. FEEL does not auto-coerce types in arithmetic — `"prefix-" + userId` (where `userId` is a number) silently evaluates to `null` with a `Can't add 'N' to '"prefix-"'` warning, not an error. See `references/common-patterns.md` § Type Coercion Pitfalls for the full rule and debugging tip.

**Result expression (extract from API response)**:
```feel
={user: response.body, status: response.statusCode}
```

**Error expression (throw BPMN error on failure)**:
```feel
=if response.statusCode >= 400 then bpmnError("HTTP_ERROR", string(response.statusCode)) else null
```

**Timer duration (FEEL required)**:
```feel
="PT" + string(delayHours) + "H"
```

**Null-safe access**:
```feel
=if customer != null then customer.name else "Unknown"
```

## References

For detailed reference material, read from `references/`:
- [function-reference.md](references/function-reference.md) — complete list of built-in FEEL functions (string, numeric, list, context, date/time, boolean)
- [common-patterns.md](references/common-patterns.md) — date arithmetic, list filtering, multi-entry context patterns, fromAi() for agentic AI
