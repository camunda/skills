---
name: camunda-feel
description: Writes and debugs FEEL (Friendly Enough Expression Language) expressions for Camunda 8. This skill should be used when creating FEEL expressions for gateway conditions, input/output mappings, timer definitions, form validation, or DMN decision logic.
---

# Camunda FEEL Expressions

Write, debug, and evaluate FEEL expressions used in Camunda 8 BPMN processes, DMN decisions, and forms.

## Prerequisites

- c8ctl CLI installed and configured (`c8 add profile`) — provides `c8 feel evaluate`
- Camunda 8.9+ cluster for default cluster-engine evaluation (uses `POST /v2/expression/evaluation`)

## Cross-References

- **camunda-bpmn**: Use when FEEL expressions are part of BPMN conditions or I/O mappings
- **camunda-forms**: Use when FEEL expressions control form validation or conditional visibility

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

To validate and debug FEEL expressions, use `c8 feel evaluate`. By default this runs against the configured cluster's Scala FEEL engine — the same engine that Zeebe uses at runtime, so results match production behavior exactly.

```bash
# Simple expression
c8 feel evaluate '1 + 2'

# Expression with individual variables (leading = optional)
c8 feel evaluate '=amount * 1.15' --var amount=100

# Multiple variables
c8 feel evaluate 'a + b' --var a=1 --var b=2

# JSON values for complex types
c8 feel evaluate 'sum(items)' --var 'items=[1,2,3]'

# Bulk variables as a single JSON object
c8 feel evaluate 'orderTotal > 1000 and customer.tier = "premium"' \
  --vars '{"orderTotal": 1500, "customer": {"tier": "premium"}}'

# Dot-path nesting on the CLI
c8 feel evaluate 'customer.name' --var customer.name=Alice
```

**Debugging workflow:**
1. Write the expression
2. Identify the expected variable context
3. Evaluate via `c8 feel evaluate` to validate against the cluster engine
4. If evaluation fails, fix based on error message and retry

#### Offline evaluation (`--engine local`)

`c8 feel evaluate --engine local` evaluates expressions locally using the `feelin` JavaScript engine — useful when no cluster is available. **Use only when explicitly requested or when no cluster is reachable AND the user has confirmed the fallback.** Never silently fall back.

`feelin` behaves DIFFERENTLY from the Scala FEEL engine that Zeebe runs in production. Subtle differences in type coercion, function support, and date/time handling can cause an expression that passes locally to fail in the cluster (and vice versa). Always re-validate against the cluster before relying on a result obtained with `--engine local`.

```bash
c8 feel evaluate '=amount * 1.15' --var amount=100 --engine local
```

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
- `references/function-reference.md` — complete list of built-in FEEL functions (string, numeric, list, context, date/time, boolean)
- `references/common-patterns.md` — date arithmetic, list filtering, multi-entry context patterns, fromAi() for agentic AI
