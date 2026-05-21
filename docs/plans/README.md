# Plans

Multi-PR execution plans for cross-cutting work in this repo. Numbered in
order — `NN-<slug>.md`. Each plan ships as its own PR before the work it
describes lands, so subsequent PRs have a stable artifact to reference and
update.

A plan is a living document while its PRs are landing: each PR ticks the
Execution checklist at the bottom of the plan and notes any deviations from
the original design. Once all PRs land, the plan graduates to a historical
record and operational guidance moves into the relevant `docs/<area>/`
folder.

`docs/plans/` is the right home (not `docs/rfcs/` / `docs/adr/`) because
these are coordination artifacts for work-in-flight, not one-shot decisions
or proposals for debate.

## Current plans

- [`01-eval-suite.md`](01-eval-suite.md) — Qualitative evaluation suite for
  camunda/skills. Status: approved, PR #1 (the plan itself) landing.
