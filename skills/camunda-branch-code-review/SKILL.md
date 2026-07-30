---
name: camunda-branch-code-review
description: Reviews the code introduced/changed on the current git branch of the camunda/camunda monorepo against SOLID, DRY, KISS, clean-code principles and the refactoring.guru code-smell & design-pattern catalogs, combined with a SpotBugs static-analysis pass. Use when asked to review a branch/PR, do a code review, check a diff for design or correctness issues, or before opening a pull request in the camunda/camunda monorepo.
---

# Branch Code Review

Review the code **introduced or changed on the current branch** of the
camunda/camunda monorepo. Combines an automated SpotBugs pass (high-signal
review profile) with a manual SOLID / DRY / KISS / clean-code analysis backed by
the refactoring.guru code-smell & design-pattern catalogs
(`references/refactoring-guru-checks.md`). The review **fans out to one parallel
agent per topic/tool** — led by an adversarial **logic-correctness** pass — then
merges everything into one consolidated findings list with `file:line`
references and severity tags.

## When to use

- "Review this branch / PR / my changes"
- "Code review before I open the PR"
- "Check this diff for design / correctness issues"

## Tooling prerequisite

The SpotBugs runner ships with this skill under `scripts/`:

- `scripts/camunda-static-analysis.sh` — the runner
- `scripts/spotbugs-review-include.xml` — curated high-signal filter (`-p review`)
- `scripts/spotbugs-all-include.xml` — every category (`-p all`)

The runner resolves the two include filters relative to itself, so the whole
`scripts/` directory is self-contained. It must run against a **camunda/camunda
checkout** and needs the repo's Maven wrapper (`./mvnw`) plus `python3` (used to
parse the SpotBugs XML report). If `python3` or a usable checkout is
unavailable, **do not launch the `spotbugs` agent** (Phase 2); say so in the
output and run only the manual review agents.

## Severity tags

Use exactly these tags. Every finding carries one; order the final report
**correctness > SOLID > DRY > KISS > clean > hygiene**.

- **correctness** — bugs / provably-wrong logic (most SpotBugs HIGH/MED; leaked
  secrets; a dead path that hides real intent; an untested branch where a bug
  would most likely hide).
- **SOLID** — single-responsibility / OO-design violations (god classes,
  switch-on-type, leaky abstractions, concrete deps that should be injected).
- **DRY** — duplicated logic/constants/branches that should share a helper.
- **KISS** — unnecessary complexity, over-abstraction, speculative generality,
  misapplied/over-engineered patterns.
- **clean** — naming, function length, nesting, magic values, comments that
  explain *what* not *why*, harmless unused code, weak assertions.
- **hygiene** — build/format/test/doc gaps, stray files, missing `@Nullable`,
  leftover TODOs/scaffolding, scope creep.

## Procedure

The review runs in three phases: **(1) Setup** — the orchestrator establishes
shared context once; **(2) Fan-out** — one parallel agent per topic/tool, each
returning findings in the standard format; **(3) Consolidate** — the orchestrator
merges them into a single report.

### Phase 1 — Setup (orchestrator, run once)

Determine the branch base and the exact changed files. Prefer the merge-base so
only this branch's commits are reviewed (not changes already on main), and
capture the **stated goal** from commit messages / PR title:

```bash
cd <repo-root>
git fetch origin --quiet 2>/dev/null || true
BASE=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)
echo "base=$BASE"
git --no-pager diff --stat "$BASE"...HEAD
git --no-pager diff --name-only "$BASE"...HEAD
git --no-pager log --oneline "$BASE"..HEAD
```

Map the changed files to the distinct top-level Maven module(s) touched (e.g.
`zeebe/engine`, `optimize/backend`, `service`) — these scope the SpotBugs pass
and the scope judgement.

**New module check:** if the branch adds a brand-new Maven module (a new
`pom.xml`) that ships with no public/protected classes yet (e.g. only
`package-info.java`), it needs the `maven.javadoc.skip=true` + empty-javadoc-jar
placeholder or the release javadoc build fails; flag `[hygiene]` if missing, and
also flag `[hygiene]` if the placeholder lingers after real classes land. See
`references/review-heuristics.md` → "New-module javadoc placeholder".

Assemble a **shared review context block** to paste verbatim into every fan-out
agent (each agent is stateless — this is its only context):

```
REPO_ROOT: <abs path>
BASE: <short-sha>            (diff range: BASE...HEAD)
GOAL: <one-line stated goal from commit/PR>
JAVA MODULES: <list>
SKILL_DIR: <abs path to this skill dir; reference files live under references/
            (refactoring-guru-checks.md, review-heuristics.md), the SpotBugs
            runner under scripts/>
CHANGED FILES:
<paste `git --no-pager diff --name-only BASE...HEAD`>

Read the diff you need with: git --no-pager diff <BASE>...HEAD -- <file>
Never review from the file list alone.
Conventions: obey AGENTS.md / module docs over generic ideals (e.g. Optimize C7
Id/Key naming per optimize/docs/adr/001-c7-naming-conventions.md — do NOT flag a
`...Key` holding a String or `...Id` holding a Long; JSpecify migration lands in
separate commits).
Severity tags (use exactly these, one per finding): correctness, SOLID, DRY,
KISS, clean, hygiene — as defined in the skill's Severity tags section.
OUTPUT: only finding lines, one per line, no preamble:
  `path/File.java:NN [tag] message`
Cite file:line for every finding; suffix SpotBugs hits with "(SpotBugs)".
High signal only — do not invent issues. If you have nothing to report, output
the single literal line `No findings` (exactly that, no file:line, nothing else).
```

### Phase 2 — Fan out to parallel review agents

**When to fan out vs run inline.** Parallel agents pay off on larger diffs; for
a tiny change the orchestration overhead outweighs it. Decide from the Phase-1
diff:

- **Small diff** — ≲ 3 changed files **and** ≲ ~150 changed lines **and** a
  single module: skip the fan-out. The orchestrator runs every topic itself
  inline (still run the `spotbugs` pass if the runner is usable), applying the
  same per-agent task specs below as a checklist — but still give the
  `logic-correctness` adversarial trace its full treatment (it's the pass most
  likely to catch a serious bug), not a skim.
- **Otherwise** — fan out. Launch **all applicable agents in a single message**
  so they run in parallel.

Paste the shared review context block into each agent, followed by its task spec.
The **correctness-critical** agents — `logic-correctness` and `sensitive-data` —
run on a **high-capability reasoning model at high effort** (use the
`general-purpose` agent type, not the lightweight `explore`): logic-bug recall is
model-bound, so under-powering these is the main reason serious bugs slip
through. The remaining design/hygiene agents use `explore`; the `spotbugs` agent
uses `task` (heavier — it builds). All are read-only reviewers: none modify code.

| Agent | Type | Owns | Reads |
|-------|------|------|-------|
| `logic-correctness` | general-purpose | **Adversarial semantic trace of every changed function** — wrong conditions, off-by-one, null, error handling — **plus sibling-path invariant completeness** | `references/review-heuristics.md` |
| `spotbugs` | task | SpotBugs pass across **all** touched Java modules | — |
| `principles` | explore | SOLID / DRY / KISS / clean-code + refactoring.guru smells & patterns | `references/refactoring-guru-checks.md` |
| `goal-scope` | explore | Goal completeness; scope correctness; agnostic/extensible/reusable | — |
| `docs-accuracy` | explore | Javadoc/comment claims vs implementation | `references/review-heuristics.md` |
| `sensitive-data` | general-purpose | Secret/PII leaks via exceptions & logs | `references/review-heuristics.md` |
| `test-quality` | explore | Branch coverage, assertion strength, boundaries, per-unit | `references/review-heuristics.md` |
| `dead-code` | explore | Unused members, unreachable/vacuous code, dead API, scaffolding | `references/review-heuristics.md` |
| `third-party` | explore | Deprecated SDK calls; unnormalized external values | `references/review-heuristics.md` |

Per-agent task specs (append to the shared context block):

- **`logic-correctness`** — the **highest-priority** pass and the one most likely
  to catch a serious bug. Do **not** scan for smells: for every changed function
  and branch, read it in full context, state its contract, then **simulate it
  against edge/hostile inputs** (null, empty, 0, negative, boundary ± 1, max,
  duplicates, wrong-case) and verify each branch's result. Flag every input that
  yields wrong behaviour as `[correctness]`, citing `file:line` **and the
  triggering input**. Then, for any changed side effect tied to a lifecycle/state
  transition, run the **sibling-path completeness** check — enumerate *every*
  path that reaches the same state (grep the underlying state mutation and all
  sibling intents/appliers, not just the ones in the diff) and confirm each
  performs the equivalent step or provably cannot reach that state. Never dismiss
  a sibling path by asserting an invariant — verify it in code. Run on a
  high-capability model at high reasoning effort.
  See `references/review-heuristics.md` → "Logic correctness — adversarial trace"
  and "Sibling-path / invariant completeness".
- **`spotbugs`** — run the curated review profile scoped to the branch diff, once
  per touched Java module. This catches logic smells the repo/CI filter omits
  (vacuous `instanceof`, useless/dead code, `==` on Strings, redundant
  null-checks, swallowed exceptions, security):
  ```bash
  scripts/camunda-static-analysis.sh -a spotbugs -p review \
    --changed-base "$BASE" <module>
  ```
  - Pass **only Java modules**. Skip `*/client` (frontend) and pure-resource changes.
  - If an upstream module changed (e.g. `optimize-commons` feeding
    `optimize/backend`), add `-i` so its JAR is reinstalled, else compilation
    resolves against a stale dependency.
  - Optimize modules are auto-handled (`include-optimize`). For a deep pass on a
    small change use `-p all`.
  - **This single agent handles every module sequentially** — do not split
    SpotBugs across parallel agents, because `-i` runs `mvn install` and
    concurrent installs corrupt the local repo.
  - Map priority to severity: HIGH/MED correctness-class → `correctness`;
    STYLE/dead-code → `clean`. Record type, category, `file:line`, message.
- **`principles`** — read `references/refactoring-guru-checks.md`; scan each
  changed hunk against the smell catalog (Bloaters, OO Abusers, Change
  Preventers, Dispensables, Couplers) and assess SOLID / DRY / KISS / clean-code.
  For every real hit, name the matching refactoring technique and/or design
  pattern as the remedy; flag misapplied/over-engineered patterns as speculative
  generality `[KISS]`. Honor KISS/YAGNI — do not demand patterns.
- **`goal-scope`** — Does the change **fully** address GOAL? Is it scoped to the
  right module(s) with no drive-by edits, unrelated refactors, or formatting
  churn? Are the changes agnostic/extensible/reusable where reasonable (flag
  hard-coded assumptions / one-off logic that should be shared — respect
  YAGNI/KISS)? If GOAL is to maintain an invariant on a state transition (add
  cleanup / a step when an entity reaches some state), confirm the change covers
  **all** paths to that state, not only the ones named in the commit — apply the
  "Sibling-path / invariant completeness" check in `references/review-heuristics.md`
  and flag any uncovered sibling path (`[correctness]` if it leaks the invariant,
  `[hygiene]` if the fix is deliberately scoped but the boundary is left implicit).
- **`docs-accuracy`** — see `references/review-heuristics.md` → "Documentation accuracy".
- **`sensitive-data`** — see `references/review-heuristics.md` → "Sensitive-data hygiene".
- **`test-quality`** — see `references/review-heuristics.md` → "Test quality, not just presence".
- **`dead-code`** — see `references/review-heuristics.md` → "Dead / unused code".
- **`third-party`** — see `references/review-heuristics.md` → "Third-party API usage".

### Phase 3 — Consolidate (orchestrator)

Collect every agent's finding lines and merge into one report:

- **Dedupe overlaps** — the same `file:line` issue can surface from multiple
  agents (e.g. `spotbugs` and `dead-code` both flag an unused private). Keep one
  line, preferring the SpotBugs-attributed wording when they coincide.
- Normalise tags and order by severity per the Severity tags section.
- If an agent returned nothing (the literal `No findings`), that's fine. If one
  failed, note it and re-run just that topic yourself — don't block the report.
- Emit the single report below.

## Output format

Produce a single consolidated report:

```
## Branch Code Review

**Goal:** <one line>  | **Base:** <short-sha>  | **Modules:** <list>

### Goal & scope
- Fully addresses goal: yes/partial/no — <why>
- Scoped correctly: yes/no — <unrelated files, if any>
- Agnostic/extensible/reusable: <assessment>

### Findings
- `path/File.java:120` [correctness] BC_VACUOUS_INSTANCEOF — instanceof always
  true; the guarded early-return branch is dead code. (SpotBugs)
- `path/File.java:88` [DRY] Two variants duplicate the same aggregation logic;
  extract a shared helper.
- `path/Other.java:42` [clean] Magic string literal — replace with the existing
  named constant.
- `path/Helper.java:67` [clean] Unused private method added on this branch but no
  caller; remove or wire it up.
...

### Summary
<counts by severity; top 1-3 things to fix before merge; note any agent that was
skipped (e.g. spotbugs runner unavailable) or failed>
```

Tag and order findings per the **Severity tags** section above
(correctness > SOLID > DRY > KISS > clean > hygiene).

## Rules

- Every finding **must** cite `file:line`. No vague or whole-file findings.
- High signal-to-noise: report real issues only. Do not invent problems to fill
  the list; "no findings in category X" is a valid result.
- Each fan-out agent owns exactly its topic/tool and returns only finding lines;
  the orchestrator does setup and consolidation. On larger diffs launch the
  agents in parallel (one message, multiple task calls) — they are read-only and
  independent; on a small diff (Phase 2 threshold) run the same checks inline.
- Do **not** modify code being reviewed — review only. Offer fixes only if asked.
- Attribute SpotBugs findings with "(SpotBugs)"; everything else is manual.
- Respect repo conventions in `AGENTS.md` and module docs over generic ideals
  (e.g. Optimize C7 naming, JSpecify nullness migration done in separate commits).
