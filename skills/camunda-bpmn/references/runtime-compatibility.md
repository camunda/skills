# Runtime compatibility checklist

Use this before deploy/test runs against a real Camunda 8 runtime.

## When to run

- After BPMN edits are structurally clean.
- Before `c8ctl deploy`, smoke runs, or handing off for release.
- On the full `.bpmn` target set for the intended deploy/test run (single file or directory set), not just one representative file.

## Targeting mode

- **Single file**: run lint on the file directly.
- **Directory**: use the discovery workflow in [bpmn-lint.md](bpmn-lint.md) to recursively find target `.bpmn` files (including the shared skip-directory list), then lint each discovered file.

Then, for each discovered file, confirm the Camunda ruleset applies and lint it:

```bash
c8ctl --dry-run bpmn lint --json <file.bpmn>   # config.extends must include plugin:camunda-compat/camunda-cloud-*
c8ctl bpmn lint --json <file.bpmn>
```

Without the `camunda-compat` entry (no `modeler:executionPlatformVersion`), none of the compatibility categories below are checked.

## Fix loop

1. Confirm the Camunda ruleset applies to every target file; set `modeler:executionPlatformVersion` where it doesn't.
2. Lint target files.
3. Apply targeted BPMN XML fixes for each reported issue.
4. Re-lint the same target set.
5. Repeat until every file reports zero errors and zero warnings.

## Common compatibility categories

| Category | What it usually means | Typical fix |
|---|---|---|
| Implementation extensions | Required Zeebe extension missing for the BPMN element type | Add missing `<zeebe:taskDefinition>`, `<zeebe:calledDecision>`, `<zeebe:userTask />`, etc. |
| FEEL / expression parsing | Legacy or invalid expression syntax | Rewrite to Camunda 8 FEEL and validate with **camunda-feel**. |
| I/O mapping | Mapping syntax not valid for runtime evaluation | Use valid FEEL in `source`/`target` mappings. |
| Unsupported structure | BPMN construct is incompatible with runtime constraints | Remodel using supported gateways/events/tasks. |
| Timer/event config | Event definition present but invalid at runtime | Correct timer/event definition shape and expression. |

If a rule is unclear, inspect the exact lint message and map it back to the BPMN element first, then fix the smallest possible section.
