# Common FEEL Patterns

Frequently used FEEL patterns in Camunda processes.

## Date Arithmetic

Add or subtract durations from dates:

```feel
date("2024-01-01") + duration("P6M")
// date("2024-07-01")

date("2024-12-31") - date("2024-01-01")
// duration("P365D")

now() + duration("PT4H")
// 4 hours from now

today() + duration("P30D")
// 30 days from today
```

Construct dynamic durations from variables:

```feel
="PT" + string(delayHours) + "H"
```

Calculate age or elapsed time:

```feel
years and months duration(date("1990-05-15"), today())
```

## List Filtering and Projection

Filter list elements by condition (1-based indexing):

```feel
employees[department = "Engineering"]
```

Project a single property from a list of contexts:

```feel
employees.name
// ["Alice", "Bob", "Carol"]
```

Combine filter and projection:

```feel
employees[salary > 80000].name
```

Use `item` keyword when filtering primitive lists:

```feel
[1, 2, 3, 4, 5][item > 3]
// [4, 5]
```

Use quantifiers to check list conditions:

```feel
every x in items satisfies x.price > 0
some x in items satisfies x.status = "urgent"
```

Use `for` loop to transform list elements:

```feel
for emp in employees return {name: emp.name, bonus: emp.salary * 0.1}
```

## Multi-Entry Context Pattern

Break complex expressions into named intermediate steps. Each entry can reference previous entries. Extract the final value with dot notation:

```feel
{
  "fibonaccis": [1, 1, 2, 3, 5, 8, 13, 21],
  "squaredValues": for fibonacci in fibonaccis return fibonacci ** 2,
  "meanValue": mean(squaredValues),
  "flooredValue": floor(meanValue),
  "isOdd": odd(flooredValue)
}.isOdd
```

Use for order total calculations:

```feel
{
  "orderTotal": sum(orders.amount),
  "discountRate": if orderTotal > 1000 then 0.15 else 0.05,
  "discountAmount": orderTotal * discountRate,
  "finalAmount": orderTotal - discountAmount
}.finalAmount
```

Use for date format conversion (non-ISO to ISO):

```feel
{
  "day": number(substring before("31.12.2020", ".")),
  "month": number(substring before(substring after("31.12.2020", "."), ".")),
  "year": number(substring after(substring after("31.12.2020", "."), ".")),
  "converted": date(year, month, day)
}.converted
```

## Null-Safe Access

FEEL returns `null` for missing variables, missing context keys, and failed operations. Guard against nulls:

```feel
if customer != null then customer.name else "Unknown"
```

Provide default values with `get or else`:

```feel
get or else(customer.email, "no-email@example.com")
```

Assert non-null with error message:

```feel
assert(orderId, orderId != null, "orderId must not be null")
```

Chain null-safe checks:

```feel
if customer != null and customer.address != null then customer.address.city else "N/A"
```

## Type Coercion Pitfalls

FEEL does **not** auto-coerce between types in arithmetic. Operating on mismatched types produces `null` plus a warning — not an error. The expression "succeeds" silently with a null result, which deploys cleanly but breaks downstream when a worker or condition sees null where it expected a value.

```feel
"hello " + 42                 // → null   (warning: Can't add '42' to '"hello "')
"user-" + userId              // → null   when userId is a number
1 + true                      // → null   (warning: Can't add 'true' to '1')
[1, 2] + 3                    // → null   (warning: Can't add '3' to '[1, 2]')
```

**Fix: wrap with the explicit converter.**

```feel
"hello " + string(42)         // → "hello 42"
"user-" + string(userId)      // → "user-42"
"PT" + string(delayHours) + "H"   // → "PT12H"  (timer duration pattern)
```

| Coerce to | Function |
|---|---|
| String | `string(value)` |
| Number | `number(text)` |
| Boolean | `boolean(value)` |
| Date / time / duration | `date(...)`, `time(...)`, `duration(...)` |

**Debugging tip.** When a process variable comes out null unexpectedly, run the suspect expression through `c8ctl feel evaluate` and read the warnings:

```bash
c8ctl feel evaluate '"user-" + userId' --var userId=42
# null
#
# ⚠ 1 warning:
#   Can't add '42' to '"user-"'
```

`Can't add 'X' to 'Y'` is the smoking gun: the operand quoting style hints at the type (unquoted = number, double-quoted = string), and the fix is `string()` (or `number()` etc.) on whichever side is the wrong type.

`--engine local` adds an explicit diagnostic type in parentheses — `(INVALID_TYPE)` for coercion failures, `(NO_VARIABLE_FOUND)` for missing vars, etc. The cluster engine omits the type tag (the `message` is the only diagnostic). In JSON mode, local-engine warnings additionally carry `type` and `position` fields; cluster-engine warnings carry only `message`. Treat those extra fields as engine-conditional when scripting.

## fromAi() Function

The `fromAi()` function is a Camunda extension for AI Agent connector tool definitions. Tag parameters as AI-generated so the LLM knows to fill them in.

### Signatures

```feel
fromAi(value: Any): Any
fromAi(value: Any, description: string): Any
fromAi(value: Any, description: string, type: string): Any
fromAi(value: Any, description: string, type: string, schema: context): Any
fromAi(value: Any, description: string, type: string, schema: context, options: context): Any
```

### Rules

- First argument must reference `toolCall` context (e.g., `toolCall.myParameter`)
- Parameter name derives from the final segment of the variable reference
- `description`, `type`, `schema`, and `options` must be null or constants

### Examples

Basic usage:

```feel
fromAi(toolCall.url)
```

With description and type:

```feel
fromAi(toolCall.firstNumber, "The first number", "number")
```

With enum schema constraint:

```feel
fromAi(toolCall.documentType, "The document type", "string", {enum: ["invoice", "receipt", "contract"]})
```

Optional parameter:

```feel
fromAi(toolCall.optionalParam, "An optional parameter", "string", null, {required: false})
```

Complex object with nested properties:

```feel
fromAi(toolCall.address, "User's address", "object", {
  properties: {
    street: {type: "string"},
    city: {type: "string"},
    zipCode: {type: "string"}
  }
})
```

Tool parameter definition combining multiple fromAi calls:

```feel
{
  searchQuery: fromAi(toolCall.searchQuery, "The search query", "string"),
  maxResults: fromAi(toolCall.maxResults, "Maximum results to return", "number", null, {required: false})
}
```
