# FEEL Built-in Function Reference

Complete list of built-in functions available in Camunda FEEL expressions, organized by category.

## String Functions

- `substring(string, start, length?)` - Extract substring (1-based index). `substring("hello", 2, 3)` -> `"ell"`
- `string length(string)` - Return length of string. `string length("hello")` -> `5`
- `upper case(string)` - Convert to uppercase. `upper case("hello")` -> `"HELLO"`
- `lower case(string)` - Convert to lowercase. `lower case("HELLO")` -> `"hello"`
- `contains(string, match)` - Check if string contains match. `contains("hello world", "world")` -> `true`
- `starts with(string, match)` - Check if string starts with match. `starts with("hello", "hel")` -> `true`
- `ends with(string, match)` - Check if string ends with match. `ends with("hello", "lo")` -> `true`
- `substring before(string, match)` - Extract substring before first occurrence. `substring before("hello world", " ")` -> `"hello"`
- `substring after(string, match)` - Extract substring after first occurrence. `substring after("hello world", " ")` -> `"world"`
- `replace(input, pattern, replacement)` - Replace all occurrences (supports regex). `replace("hello", "l", "r")` -> `"herro"`
- `split(string, delimiter)` - Split string into list. `split("a,b,c", ",")` -> `["a", "b", "c"]`
- `string join(list, delimiter?)` - Join list elements into string. `string join(["a", "b", "c"], ",")` -> `"a,b,c"`
- `matches(input, pattern)` - Test string against regex pattern. `matches("foobar", "^foo")` -> `true`
- `trim(string)` - Remove leading and trailing whitespace
- `extract(string, pattern)` - Extract all regex matches as a list

## Numeric Functions

- `decimal(number, scale)` - Round to specified decimal places. `decimal(1.335, 2)` -> `1.34`
- `floor(number)` - Round down to nearest integer. `floor(1.9)` -> `1`
- `ceiling(number)` - Round up to nearest integer. `ceiling(1.1)` -> `2`
- `round up(number, scale)` - Round away from zero. `round up(5.25, 1)` -> `5.3`
- `round down(number, scale)` - Round toward zero. `round down(5.25, 1)` -> `5.2`
- `round half up(number, scale)` - Round half values up. `round half up(5.25, 1)` -> `5.3`
- `round half down(number, scale)` - Round half values down. `round half down(5.25, 1)` -> `5.2`
- `abs(number)` - Return absolute value. `abs(-5)` -> `5`
- `modulo(dividend, divisor)` - Return remainder. `modulo(10, 3)` -> `1`
- `sqrt(number)` - Return square root. `sqrt(16)` -> `4`
- `log(number)` - Return natural logarithm
- `exp(number)` - Return e raised to the power
- `odd(number)` - Check if integer is odd. `odd(3)` -> `true`
- `even(number)` - Check if integer is even. `even(4)` -> `true`
- `random number()` - Return random number between 0 and 1

## Boolean Functions

- `not(value)` - Negate boolean value. `not(true)` -> `false`
- `is defined(value)` - Check if value is not null. `is defined(null)` -> `false`
- `get or else(value, default)` - Return value if non-null, otherwise default. `get or else(null, "fallback")` -> `"fallback"`
- `assert(value, condition, message?)` - Return value if condition is true, otherwise error. `assert(x, x != null, "x required")`

## List Functions

- `count(list)` - Return number of elements. `count([1, 2, 3])` -> `3`
- `sum(list)` - Return sum of numeric elements. `sum([1, 2, 3])` -> `6`
- `mean(list)` - Return average. `mean([2, 4, 6, 8])` -> `5`
- `min(list)` - Return minimum value. `min([5, 3, 9])` -> `3`
- `max(list)` - Return maximum value. `max([5, 3, 9])` -> `9`
- `median(list)` - Return median value
- `stddev(list)` - Return standard deviation
- `mode(list)` - Return most frequent values
- `append(list, item)` - Add item to end of list. `append([1, 2], 3)` -> `[1, 2, 3]`
- `concatenate(list1, list2, ...)` - Merge multiple lists. `concatenate([1, 2], [3, 4])` -> `[1, 2, 3, 4]`
- `flatten(list)` - Flatten nested lists. `flatten([[1, 2], [3, 4]])` -> `[1, 2, 3, 4]`
- `distinct values(list)` - Remove duplicates. `distinct values([1, 2, 2, 3])` -> `[1, 2, 3]`
- `reverse(list)` - Reverse list order. `reverse([1, 2, 3])` -> `[3, 2, 1]`
- `sublist(list, start, length?)` - Extract sublist (1-based). `sublist([1, 2, 3, 4], 2, 2)` -> `[2, 3]`
- `sort(list, precedes)` - Sort list with comparator. `sort(list, function(x, y) x < y)`
- `list contains(list, element)` - Check if list contains element. `list contains([1, 2, 3], 2)` -> `true`
- `index of(list, match)` - Return indices of matching elements. `index of([1, 2, 3, 2], 2)` -> `[2, 4]`
- `union(list1, list2, ...)` - Merge lists and remove duplicates
- `intersection(list1, list2, ...)` - Return elements common to all lists
- `product(list)` - Return product of numeric elements. `product([2, 3, 4])` -> `24`
- `all(list)` - Check if all elements are true. `all([true, true, false])` -> `false`
- `any(list)` - Check if any element is true. `any([true, false, false])` -> `true`

## Context Functions

- `get value(context, key)` - Get value by key name. `get value({a: 1}, "a")` -> `1`
- `get entries(context)` - Get list of key-value pairs. `get entries({a: 1, b: 2})` -> `[{key: "a", value: 1}, {key: "b", value: 2}]`
- `context put(context, key, value)` - Add or update a key. `context put({a: 1}, "b", 2)` -> `{a: 1, b: 2}`
- `context merge(contexts)` - Merge list of contexts. `context merge([{a: 1}, {b: 2}])` -> `{a: 1, b: 2}`

## Date and Time Functions

- `now()` - Return current date-time
- `today()` - Return current date
- `date(string)` - Parse date from ISO string. `date("2024-01-15")`
- `date(year, month, day)` - Construct date from components. `date(2024, 1, 15)`
- `time(string)` - Parse time from string. `time("14:30:00")`
- `time(hour, minute, second)` - Construct time from components
- `date and time(string)` - Parse date-time from ISO string. `date and time("2024-01-15T14:30:00")`
- `date and time(date, time)` - Combine date and time values
- `duration(string)` - Parse duration from ISO 8601 string. `duration("P1D")`, `duration("PT2H30M")`
- `year(date)` - Extract year. `year(date("2024-01-15"))` -> `2024`
- `month(date)` - Extract month (1-12)
- `day(date)` - Extract day of month
- `hour(time)` - Extract hour (0-23)
- `minute(time)` - Extract minute
- `second(time)` - Extract second
- `day of week(date)` - Return day name. `day of week(date("2024-01-15"))` -> `"Monday"`
- `day of year(date)` - Return day number (1-366)
- `week of year(date)` - Return ISO week number
- `years and months duration(from, to)` - Calculate duration between dates. `years and months duration(date("2020-01-01"), date("2021-06-01"))` -> `duration("P1Y5M")`
- `abs(duration)` - Return absolute duration value

## Range Functions

- `before(a, b)` - Check if a is before b
- `after(a, b)` - Check if a is after b
- `meets(a, b)` - Check if end of a meets start of b
- `met by(a, b)` - Check if start of a is met by end of b
- `overlaps(a, b)` - Check if ranges overlap
- `includes(range, value)` - Check if range includes value
- `during(value, range)` - Check if value is during range
- `started by(a, b)` - Check if a starts with b
- `finished by(a, b)` - Check if a finishes with b

## Conversion Functions

- `string(value)` - Convert any value to string. `string(123)` -> `"123"`
- `number(string)` - Parse string to number. `number("123.45")` -> `123.45`
- `date(string)` - Parse string to date
- `time(string)` - Parse string to time
- `duration(string)` - Parse string to duration

These are **required, not optional**, when combining values across types — FEEL does not auto-coerce in arithmetic. `"user-" + userId` (number) silently evaluates to `null` with a `Can't add 'N' to 'Y'` warning. See `common-patterns.md` § Type Coercion Pitfalls.
