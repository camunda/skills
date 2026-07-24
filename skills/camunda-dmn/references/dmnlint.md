# dmnlint reference

`dmnlint` is the bpmn-io DMN linter — the same rule library Web Modeler uses to flag issues in the editor. Run it as a structural gate on every DMN edit.

```bash
npx --yes dmnlint path/to/decision.dmn
```

Exit codes: `0` clean, `1` lint issues found, `>1` tool failure.

## Configuration — `.dmnlintrc`

Drop a `.dmnlintrc` at the project root:

```json
{ "extends": "dmnlint:recommended" }
```

`dmnlint` picks the file up automatically from the working directory. The skill creates it on the fly if missing:

```bash
[ -f .dmnlintrc ] || echo '{ "extends": "dmnlint:recommended" }' > .dmnlintrc
```

If the project already has a `.dmnlintrc` with a different `extends`, do not overwrite it — respect the project's choice and surface any rule disagreements in your final message.

## Recommended rule set

`dmnlint:recommended` enables these rules (both errors by default):

| Rule | Catches | Fix |
|---|---|---|
| `label-required` | A Decision, InputData, BusinessKnowledgeModel, KnowledgeSource, or DecisionService missing a `name` attribute. The `id` is internal; `name` is what shows in Modeler and error messages. | Add a descriptive `name=` to the flagged element. |
| `no-duplicate-requirements` | A decision that references the same upstream decision (or BKM / authority source) twice via `informationRequirement`, `knowledgeRequirement`, or `authorityRequirement`. | Remove the duplicate edge. |

## Output format

```
decision.dmn
  Decision_12    error  Element is missing label/name       label-required

✖ 1 problem (1 error, 0 warnings)
```

Each report line is `<elementId>  <severity>  <message>  <ruleId>` — columns separated by two or more spaces. Lines starting with `✖` are summary only.

## Common pitfalls beyond lint coverage

`dmnlint` operates on the DMN XML — it catches the structural defects above but does not understand FEEL semantics or runtime resolution. Cover these by execution (CPT or deploy-and-run) instead:

- **Unquoted string output entries** (`HIGH` instead of `"HIGH"`) — evaluate to `null` at runtime; no parse error, no lint warning.
- **Hit-policy violations** — `UNIQUE` tables with overlapping rules pass lint cleanly and raise an incident only when input data hits the overlap.
- **`typeRef` mismatches** between input expression and input entries — surface at evaluation time.
- **Broken BPMN ↔ DMN references** — `<zeebe:calledDecision decisionId="…">` that no deployed decision satisfies; cross-file references are out of `dmnlint`'s scope.
