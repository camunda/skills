# Run and diagnose CPT suites

Use this when tests already exist and the user asks to run/fix them.

## Execution loop

1. Ensure Docker runtime is available (see [setup.md](setup.md)).
2. Run:

```bash
mvn test
```

3. If tests fail, classify each failure:
   - **Infrastructure** (Docker down, deployment parse failure, missing resources)
   - **Test defect** (wrong IDs, missing instruction, stale variable names)
   - **Process defect** (gateway logic, DMN rule behavior, BPMN error code mismatch)
4. Apply fixes in batches by class (not one-by-one churn), then re-run `mvn test`.
5. Stop after 3 no-progress cycles — defined as a re-run producing no reduction in failing tests and no new diagnostic signal — and surface blockers explicitly.

## Failure-class defaults

- Prefer fixing **test defects** in the suite directly.
- For ambiguous routing mismatches, verify BPMN/FEEL intent first, then decide whether test data or model logic is wrong.
- Do not mask process defects by weakening assertions.

Use [troubleshooting.md](troubleshooting.md) for detailed failure signatures and exact repair actions.
