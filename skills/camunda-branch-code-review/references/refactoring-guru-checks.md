# Refactoring.guru checks reference

Catalog used by the **camunda-branch-code-review** skill as an additional source of
review checks, derived from:

- Code smells & refactoring techniques — <https://refactoring.guru/refactoring>
- Design patterns — <https://refactoring.guru/design-patterns>

Use these as a **checklist to detect problems and recommend remedies** — not as
a mandate to introduce patterns. Respect KISS/YAGNI: only suggest a refactoring
or pattern when it removes a concrete smell in the changed code. Every finding
must still cite `file:line`.

Map findings to the skill's severity tags as noted per group (most smells →
`DRY`/`KISS`/`clean`/`SOLID`; provably-dead/broken → `correctness`).

---

## 1. Code smells (detect these)

### Bloaters — code/methods/classes grown too large
- **Long Method** — method > ~10 lines doing too much. → *Extract Method*. `[KISS/clean]`
- **Large Class** — too many fields/methods/responsibilities. → *Extract Class/Subclass*, *Extract Interface*. `[SOLID]`
- **Primitive Obsession** — primitives/constants/strings instead of small types; constants encoding info (e.g. `ROLE=1`); string keys for pseudo-fields. → *Replace Data Value with Object*, *Replace Type Code with Class/Enum*. `[clean]`
- **Long Parameter List** — > ~3-4 params. → *Introduce Parameter Object*, *Preserve Whole Object*. `[clean]`
- **Data Clumps** — same group of fields/params recurring together. → *Extract Class*, *Introduce Parameter Object*. `[DRY]`

### Object-Orientation Abusers — incomplete/incorrect use of OO
- **Switch Statements / type-dispatch** — `switch`/`if-else` on a type code, repeated. → *Replace Conditional with Polymorphism*, *Strategy/State*. `[SOLID]`
- **Temporary Field** — field set only in some circumstances; empty otherwise. → *Extract Class*, *Introduce Null Object*. `[clean]`
- **Refused Bequest** — subclass uses little of its inherited API, or overrides to no-op/throw. → *Replace Inheritance with Delegation*, *Extract Superclass*. `[SOLID]`
- **Alternative Classes with Different Interfaces** — two classes do the same job with different method names. → *Rename/Move Method*, unify interface. `[DRY/SOLID]`

### Change Preventers — one change forces many edits
- **Divergent Change** — one class changed for many unrelated reasons. → *Extract Class* (SRP). `[SOLID]`
- **Shotgun Surgery** — one logical change requires edits scattered across many classes. → *Move Method/Field*, *Inline Class*. `[SOLID]`
- **Parallel Inheritance Hierarchies** — every subclass of A forces a subclass of B (a special Shotgun Surgery). → collapse/merge hierarchies. `[SOLID]`

### Dispensables — pointless things to remove
- **Duplicate Code** — identical/near-identical fragments (incl. copy-pasted ES/OS or per-DB variants beyond the established dual-stack split). → *Extract Method*, *Pull Up Method*, *Form Template Method*. `[DRY]`
  - **Verify against existing code, not just within the diff.** New duplication is often a copy of a block that *already exists elsewhere in the codebase* — so it won't show up by eyeballing the hunk alone. When a hunk adds a non-trivial loop/helper (e.g. a "collect entries into a list, then act on each" visit pattern, or a specific query-and-filter sequence), grep the touched package/module for the same shape (the same state API call, the same visitor lambda) before accepting it. A small shared state helper often removes both copies. `[DRY]`
- **Dead Code** — unreachable branch, unused var/param/field/method, vacuous condition. → delete. `[correctness]` if provably unreachable, else `[clean]`
- **Lazy Class** — class doing too little to justify its existence. → *Inline Class*, *Collapse Hierarchy*. `[clean]`
- **Speculative Generality** — unused abstraction/hook/param "for the future" (YAGNI). → *Collapse Hierarchy*, *Inline Class*, *Remove Parameter*. `[KISS]`
- **Data Class** — class with only fields + getters/setters and no behavior, while logic lives elsewhere. → *Move Method* behavior in. `[SOLID]` (note: DTOs/records are legitimate; only flag when behavior is misplaced).
- **Comments (as deodorant)** — comments explaining *what* obscure code does instead of *why*. → *Extract Method* with intention-revealing name, *Rename*. `[clean]`
- **Misleading / imprecise name** — a method/field/variable name that implies something the code doesn't do (wrong cardinality, wrong subject, wrong action). Check every new public API name against what it *actually* operates on. → *Rename Method/Field*. `[clean]`.

### Couplers — excessive coupling
- **Feature Envy** — method more interested in another class's data than its own. → *Move Method*, *Extract Method*. `[SOLID]`
- **Inappropriate Intimacy** — classes reach into each other's internals / mutable shared state / hidden side-channels (temporal coupling). → *Move Method/Field*, *Hide Delegate*, pass data explicitly. `[SOLID]`
- **Message Chains** — `a.getB().getC().getD()`. → *Hide Delegate*. `[clean]`
- **Middle Man** — class that only delegates to another. → *Remove Middle Man*. `[clean]` (note: Facade/delegation can be intentional — don't over-flag).
- **Incomplete Library Class** — library missing needed methods. → *Introduce Foreign Method / Local Extension*. `[clean]`

---

## 2. Refactoring techniques (recommend these as remedies)

Cite the technique by name when proposing a fix.

- **Composing Methods:** Extract Method, Inline Method, Extract Variable, Inline Temp, Replace Temp with Query, Split Temporary Variable, Remove Assignments to Parameters, Replace Method with Method Object, Substitute Algorithm.
- **Moving Features between Objects:** Move Method, Move Field, Extract Class, Inline Class, Hide Delegate, Remove Middle Man, Introduce Foreign Method, Introduce Local Extension.
- **Organizing Data:** Encapsulate Field/Collection, Replace Data Value with Object, Replace Type Code with Class/Subclasses/State-Strategy, Replace Array with Object, Replace Magic Number with Symbolic Constant.
- **Simplifying Conditionals:** Decompose Conditional, Consolidate Conditional Expression, Consolidate Duplicate Conditional Fragments, Remove Control Flag, Replace Nested Conditional with Guard Clauses, Replace Conditional with Polymorphism, Introduce Null Object, Introduce Assertion.
- **Simplifying Method Calls:** Rename Method, Add/Remove Parameter, Introduce Parameter Object, Preserve Whole Object, Separate Query from Modifier, Replace Parameter with Explicit Methods, Replace Error Code with Exception.
- **Dealing with Generalization:** Pull Up / Push Down Field & Method, Extract Subclass/Superclass/Interface, Collapse Hierarchy, Form Template Method, Replace Inheritance with Delegation (and vice versa).

---

## 3. Design patterns (recognize fit & misuse)

Use to (a) suggest a pattern when it cleanly removes a smell, and (b) flag a
**misapplied/over-engineered** pattern (itself a Speculative Generality smell).
Tag pattern-fit findings `[SOLID]` (or `[KISS]` when the pattern is overkill).

- **Creational:** Factory Method, Abstract Factory, Builder, Prototype, Singleton.
  - Cues: sprawling `new`/switch-on-type construction → Factory; telescoping constructors / Long Parameter List on build → Builder; global mutable singletons → review for testability.
- **Structural:** Adapter, Bridge, Composite, Decorator, Facade, Flyweight, Proxy.
  - Cues: Alternative Classes w/ Different Interfaces → Adapter; tree of part/whole → Composite; wrapping to add behavior → Decorator; subsystem entry point → Facade (legitimate Middle Man).
- **Behavioral:** Chain of Responsibility, Command, Iterator, Mediator, Memento, Observer, State, Strategy, Template Method, Visitor.
  - Cues: Switch/type-dispatch → Strategy/State/Polymorphism; duplicated algorithm skeleton across ES/OS or sub-types → Template Method; many-to-many object refs → Mediator; behavior varying by lifecycle status flag → State.

### Pattern anti-checks (flag as `[KISS]`)
- Pattern introduced with a single implementation and no second caller (Speculative Generality).
- Indirection that adds layers without removing duplication or coupling.
- A "manager/util" Facade that only forwards calls (Middle Man) with no cohesion gain.

---

## How to apply during review (Step 5 of SKILL.md)
1. For each changed hunk, scan the smell list above; record concrete hits with `file:line`.
2. Name the matching **refactoring technique** and/or **pattern** as the suggested remedy.
3. Keep high signal: report a smell only if it's real in the changed code, not theoretical. "No smells in category X" is fine.
4. Honor repo conventions (e.g. Optimize's intentional ES/OS dual stack, C7 `Id`/`Key` naming, JSpecify migration in separate commits) over generic catalog advice.
