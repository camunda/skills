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
