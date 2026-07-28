# Runtime compatibility checklist

Use this before deploy/test runs against a real Camunda 8 runtime.

## When to run

- After BPMN edits are structurally clean.
- Before `c8ctl deploy`, smoke runs, or handing off for release.
- On all changed `.bpmn` files, not just one representative file.

## Targeting mode

- **Single file**: run lint on the file directly.
- **Directory**: discover `.bpmn` files recursively, skipping `.git`, `node_modules`, `target`, `build`, `.gradle`, `.mvn`, `.idea`, `.settings`, `.snapshots`.

```bash
find <target-dir> -type d \( -name .git -o -name node_modules -o -name target -o -name build -o -name .gradle -o -name .mvn -o -name .idea -o -name .settings -o -name .snapshots \) -prune -o -type f -name '*.bpmn' -print
```

Then run:

```bash
c8ctl bpmn lint <file.bpmn>
```

for each discovered file.

## Fix loop

1. Lint target files.
2. Apply targeted BPMN XML fixes for each reported issue.
3. Re-lint the same target set.
4. Repeat until all files are clean.

## Common compatibility categories

| Category | What it usually means | Typical fix |
|---|---|---|
| Implementation extensions | Required Zeebe extension missing for the BPMN element type | Add missing `<zeebe:taskDefinition>`, `<zeebe:calledDecision>`, `<zeebe:userTask />`, etc. |
| FEEL / expression parsing | Legacy or invalid expression syntax | Rewrite to Camunda 8 FEEL and validate with **camunda-feel**. |
| I/O mapping | Mapping syntax not valid for runtime evaluation | Use valid FEEL in `source`/`target` mappings. |
| Unsupported structure | BPMN construct is incompatible with runtime constraints | Remodel using supported gateways/events/tasks. |
| Timer/event config | Event definition present but invalid at runtime | Correct timer/event definition shape and expression. |

If a rule is unclear, inspect the exact lint message and map it back to the BPMN element first, then fix the smallest possible section.
