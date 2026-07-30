# Review heuristics — detailed guidance

Depth reference for the **camunda-branch-code-review** skill. `SKILL.md` keeps
the checklist scannable; this file holds the rationale and edge cases behind each
check. Consult the relevant section when a checklist item fires and you need the
full reasoning.

---

## Logic correctness — adversarial trace (`logic-correctness` agent)

The highest-recall correctness check, and the one a checklist alone misses. Do
**not** skim the hunk for smells — **simulate the changed code against hostile
inputs** and confirm each branch produces the right result. Run this on a
high-capability reasoning model, not a lightweight one.

Method — for every changed or added function/method (and every changed branch):

1. **Read it in full context**, not just the diff hunk — open the file so you
   see the surrounding method, the fields it touches, and what its callers
   expect back.
2. **State its intended contract** in one line (what it must return / do for
   which inputs). If the diff changed that contract, note who relies on the old one.
3. **Enumerate every branch** (`if`/`else`, `switch` arm, ternary, `catch`, loop
   entry/exit, early return) and pick **concrete edge inputs** for each: `null`,
   empty, `0`, negative, `1`, the exact boundary and boundary ± 1, max,
   duplicates, unsorted, wrong-case, and the "impossible" value.
4. **Mentally execute** each input and check the actual output / side effect /
   thrown exception is correct. Any input that yields wrong behaviour is a
   `[correctness]` finding — cite `file:line` **and the triggering input**.

Scan specifically for these bug classes — this is where real logic bugs hide:

- **Conditions & booleans** — wrong comparison (`<` vs `<=`, `>` vs `>=`),
  inverted/negated logic, `&&` vs `||`, De Morgan mistakes, operator precedence,
  a guard that is always true / always false, a condition testing the wrong
  variable (copy-paste).
- **Off-by-one & ranges** — loop bounds, index arithmetic, `substring`/slice
  ranges, inclusive-vs-exclusive limits, `size` vs `size - 1`, `<= limit` vs
  `< limit` on a max-size check.
- **Null / empty / Optional** — unchecked dereference of a value that can be null
  (map `get`, first element, injected field, method return), `Optional.get`
  without `isPresent`, empty-collection access, autoboxing NPE (`int` from a
  nullable `Integer`), a new branch that skips the null-handling done elsewhere.
- **Error / exception handling** — swallowed or too-broadly-caught exception,
  wrong exception type, control flow that depends on an exception that won't
  fire, missing rollback/cleanup/resource-close on the error path, returning
  `null`/empty/partial (or a success code) on failure, not restoring state after
  a caught error, ignoring a return/status code that signals failure.
- **Arithmetic** — integer overflow/underflow, `int` division truncation,
  division/modulo by zero, sign errors, rounding, `int` where a `long` is needed.
- **Equality & identity** — `==` on objects/boxed types instead of `equals`, an
  enum compared by its value string, broken `equals`/`hashCode`, case/whitespace
  sensitivity on external strings.
- **State & ordering** — a value read before it is set, mutation of a shared or
  argument object, an operation whose correctness depends on order, a field
  updated without its parallel field, a stale cached value.
- **Collections & streams** — concurrent modification during iteration, wrong
  default from `getOrDefault`, a filter/`distinct` that drops or keeps the wrong
  elements, `findFirst` on an unordered stream.
- **Data flow** — a value computed but never used or returned, the wrong
  variable used (copy-paste), swapped arguments, a unit/type mismatch.

Do not stop at the first bug in a method — trace the whole thing. "No
correctness issues after tracing X inputs" is a valid, useful result.

---

## Sibling-path / invariant completeness (`logic-correctness` + `goal-scope` agents)

The highest-value *whole-diff* check, and the one this skill has actually missed
in practice. When a change adds a step to **one** code path that maintains an
invariant, verify **every sibling path that reaches the same state also performs
that step** — a maintained invariant must hold on *all* paths, not just the one
or two named in the commit message. Partial coverage of a set of equivalent
paths is a real `[correctness]` defect (a leaked/inconsistent invariant), not a
nitpick.

**Do not reason your way out of this by asserting an invariant — verify it in
code.** If you find yourself thinking "path X can't happen because Y", that "Y"
is a claim you must confirm by *reading the code for path X*, not a licence to
skip it. Abstract reasoning ("a parked job can't be completed, so I don't need
to check completion") is exactly how a leaked invariant on an unenumerated
sibling path slips through.

Method — when the diff adds/removes a side effect tied to a lifecycle or state
transition (cleanup, index update, metric, counter, notification, resource
release, cache invalidation, parallel-field update):

1. **Name the invariant** the new step maintains (e.g. "no waiting-secret-index
   rows survive once a job leaves `JobState`").
2. **Enumerate every path that reaches the same terminal state / does the same
   trigger action** — don't trust the commit message's list. Grep for the
   underlying operation, not just the intent named in the diff. Concretely:
   - the state mutation the new step pairs with — e.g. grep every caller of
     `jobState.delete` / `.remove` / `.cancel` / `.complete`, every writer of the
     sibling intents (`grep "JobIntent.<X>"` for **all** terminal intents, not
     just the changed one), every applier/processor for the same value type.
   - **versioned appliers**: if the change adds behaviour to
     `FooCompletedV4Applier`, list *all* `Foo*Applier` classes that delete/finish
     the same entity (`FooCanceledV*`, `FooErrorThrownV*`, `FooTimedOutV*`, …) and
     confirm each either performs the step or provably cannot reach the state.
3. **For each sibling path, confirm** it either (a) performs the equivalent step,
   or (b) provably cannot reach the state that needs it — and back (b) with the
   specific code line that makes it impossible, not intuition.
4. Flag every sibling path that drops the invariant as `[correctness]`, citing
   its `file:line` and naming the leaked/inconsistent state. If the author
   intends to scope the fix to a subset, that scoping must be stated as an
   explicit invariant in the code/PR — flag `[hygiene]` if it is merely implicit.

---

## New-module javadoc placeholder (Phase 1 setup)

When a branch adds a brand-new Maven module (a new `pom.xml` under a module
directory), flag it if it ships with **no public/protected classes yet** (e.g.
only `package-info.java`).

Why: the release process attaches a javadoc jar to every Java module, and
`javadoc` treats *"No public or protected classes found to document"* as a
**hard build failure**, which breaks the scheduled release dry-run.

- If the module is intentionally scaffolded ahead of its content, it must carry
  the `maven.javadoc.skip=true` + empty-javadoc-jar placeholder — the existing
  convention in `zeebe/protocol-asserts`, `zeebe/expression-language`,
  `optimize`, `operate`, `tasklist`, `webapp`. Flag `[hygiene]` if it's missing.
- Once real classes land (often in a later branch/PR building on the scaffold),
  flag `[hygiene]` if the placeholder is still present but no longer needed —
  leaving it in permanently just hides future javadoc regressions instead of
  catching them.

---

## Documentation accuracy (`docs-accuracy` agent)

For every Javadoc/comment claim about behavior (auth/permission model, which
error/status a branch returns, mutual-exclusivity rules, thread-safety, ordering
guarantees), grep the actual implementation and confirm it matches. Don't take a
docstring's claim at face value — treat it as a **testable assertion about the
code**, not background prose. Flag `[hygiene]` if stale/wrong.

---

## Sensitive-data hygiene (`sensitive-data` agent)

In any code that handles secrets, credentials, tokens, personal data, or other
data that must not be exposed: do thrown exceptions, wrapped causes, or log/error
messages ever carry raw content derived from that value?

Parser exceptions in particular (JSON/YAML/regex/XML) commonly embed a snippet
of their input in `getMessage()` — if that input is (or contains) the sensitive
value, it leaks into logs, error responses, or stack traces. Flag `[correctness]`
(a real bug, not style) any exception path that propagates `e.getMessage()` or
the exception itself from parsing/processing a value that must stay confidential.

---

## Test quality, not just presence (`test-quality` agent)

Target: every changed/added line of production code in the diff is exercised by
at least one test — every new method, every new/changed branch (`if`/`else`,
`switch` arm, `catch` block, ternary), not just "the class has some tests." No
automated diff-coverage tool is wired into this skill, so do this manually: for
each changed/added non-test file, walk each new or modified conditional arm and
confirm a test in the diff (or already in the suite) actually drives execution
down that arm — don't infer coverage from a method merely being *called* by a
test, confirm the specific branch is reached. Flag every uncovered branch/arm
individually with `[hygiene]` (or `[correctness]` if the untested path is where a
bug would most likely hide) — list each one by `file:line`, don't just note
"coverage could be better." A green full suite proves nothing here: a whole new
class, or one branch of an `if`/`switch` in an otherwise-tested method, can sit
completely uncovered while every existing test keeps passing.

- **Assertion strength** — a loose assertion (`contains`, `anyMatch`,
  `isNotEmpty`) where a stronger one (`containsExactly`,
  `containsExactlyInAnyOrder`, an exact equality check) would catch a missing or
  unexpected-extra item that the loose form silently lets through. `[clean]` or
  `[correctness]` if the looseness could actually mask a bug.
- **Boundary/edge cases** — for any logic with a size limit, page/batch
  boundary, min/max range, or empty/single/many cardinality, is there a test at
  the boundary (exactly at the limit, one over it, empty), not just the
  happy-path middle case? Flag `[hygiene]` if only the happy path is exercised.
- **Per-unit coverage** — does every new class/function with non-trivial logic
  have its own direct test, or is it only exercised incidentally as a side effect
  of testing something else? Incidental-only coverage is fragile — flag
  `[hygiene]`.

---

## Dead / unused code (`dead-code` agent)

Scan every changed hunk for code that is added or left behind but never actually
reached or used. Flag each occurrence individually by `file:line`:

- **Unused members** — new `private` methods, fields, constants, parameters, or
  local variables that nothing references (SpotBugs `UPM_*`/`URF_*`/`DLS_*` catch
  some, but not all — confirm by grepping for each new private symbol's usages
  within its scope).
- **Unreachable / vacuous code** — statements after an unconditional
  `return`/`throw`, branches whose condition is always true/false, `catch` blocks
  for exceptions that can't be thrown, `default` arms that can't be hit, or
  guards made redundant by an earlier check.
- **Dead public API surface** — a new public/protected method or overload the
  branch introduces but neither wires up nor tests, and that no caller exists for
  (speculative generality — YAGNI). Distinguish from an intentionally-public
  SPI/extension point.
- **Leftover scaffolding** — commented-out code, `System.out`/debug prints,
  unused imports, orphaned helper classes, or a feature flag/branch that is never
  enabled.

Tag `[clean]` for harmless-but-unused code, `[hygiene]` for leftover
scaffolding/commented-out code, and `[correctness]` when the dead path hides a
real intent (e.g. an always-false guard that was *meant* to protect something).
Never silently accept "it'll be used in a later PR" — if there is no caller and
no test on this branch, flag it and let the author confirm.

---

## Third-party API usage (`third-party` agent)

When the diff calls into an external library/SDK: check for deprecated
methods/fields (per that library's currently-pinned version) that have a
documented non-deprecated replacement, and check whether the code trusts an
external string/code/enum-like value verbatim in a `switch`/`equals`/comparison
without normalizing case/whitespace first — external systems don't always
guarantee exact formatting across versions.
