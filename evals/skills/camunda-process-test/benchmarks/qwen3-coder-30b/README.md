# Qwen test-spec benchmarks

These snapshots retain the generated `TESTING.md` and run report for each
prompt/rubric iteration. They make output regressions visible without checking
transient Inspect `.eval` logs into Git.

| Run | Result with final rubric | Purpose |
| --- | --- | --- |
| `2026-09-29T21-34-03Z` | Pass | Passing reference output |
| `2026-09-29T21-44-11Z` | Fail | Missing Markdown artifact links |
| `2026-09-29T21-46-33Z` | Fail | Placeholder artifact links |

Refresh by running the outcome eval with local Qwen, copying the extracted
`TESTING.md` into a new timestamped directory, and recording the model, token
counts, scorer result, and Inspect log identifier in `REPORT.md`. Do not copy
the `.eval` log because it is a transient runtime artifact.
