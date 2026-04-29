---
name: camunda-feel
description: Writes and debugs FEEL (Friendly Enough Expression Language) expressions for Camunda 8. This skill should be used when creating FEEL expressions for gateway conditions, input/output mappings, timer definitions, form validation, or DMN decision logic.
---

# Camunda FEEL Expressions

Write, debug, and evaluate FEEL expressions used in Camunda 8 BPMN processes, DMN decisions, and forms.

## Prerequisites

- Camunda 8.8+ cluster for expression evaluation via REST API

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

To validate and debug FEEL expressions, use the Camunda REST API via c8ctl:

```bash
c8 evaluate expression '=amount * 1.15' --variables '{"amount": 100}'
```

If c8ctl does not support expression evaluation directly, use the REST API:

```bash
curl -X POST http://localhost:8080/v2/expressions/evaluation \
  -H 'Content-Type: application/json' \
  -d '{"expression": "=amount * 1.15", "variables": {"amount": 100}}'
```

**Debugging workflow:**
1. Write the expression
2. Identify the expected variable context
3. Evaluate via API to validate
4. If evaluation fails, fix based on error message and retry

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
