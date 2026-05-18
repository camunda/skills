# dmnlint reference

`dmnlint` is the [bpmn-io] DMN linter that Camunda's CI/CD documentation recommends alongside `bpmnlint` ([docs.camunda.io › modeler › web-modeler › integrate-web-modeler-in-ci-cd › Test stage](https://docs.camunda.io/docs/components/modeler/web-modeler/integrate-web-modeler-in-ci-cd/#test-stage)). It is the same rule library Web Modeler uses to flag issues in the editor.

Install-free invocation:

```bash
npx --yes dmnlint path/to/decision.dmn
```

Exit codes: `0` clean, `1` lint issues found, `>1` tool failure.

## Configuration — `.dmnlintrc`

Drop a `.dmnlintrc` at the project root. The minimum useful contents:

```json
{ "extends": "dmnlint:recommended" }
```

`dmnlint` picks the file up automatically from the working directory. The skill creates it on the fly if missing:

```bash
[ -f .dmnlintrc ] || echo '{ "extends": "dmnlint:recommended" }' > .dmnlintrc
```

If your project already has a `.dmnlintrc` with a different `extends`, do not overwrite it — respect the project's choice and surface any rule disagreements in your final message.

## Recommended rule set

`dmnlint:recommended` enables these rules (both are errors by default):

| Rule | Catches | Fix |
|---|---|---|
| `label-required` | Any Decision, InputData, BusinessKnowledgeModel, KnowledgeSource, or DecisionService missing a human-readable `name` attribute. The `id` is internal; `name` is what shows in Modeler and in error messages. | Add a descriptive `name=` to the flagged element. Pick something a domain reader can interpret without the diagram. |
| `no-duplicate-requirements` | A decision that references the same upstream decision (or BKM / authority source) twice via `informationRequirement`, `knowledgeRequirement`, or `authorityRequirement`. | Remove the duplicate edge. The DRG must reference each upstream artifact at most once per decision. |

`dmnlint` operates on the DMN XML — it catches the structural defects above but does not understand FEEL semantics, hit-policy correctness, or runtime variable resolution. Those are stage-2 concerns covered by execution (CPT or deploy-and-run) in the main SKILL.md.

## Output format

```
decision.dmn
  Decision_12    error  Element is missing label/name       label-required
  Decision_15    error  Element is missing label/name       label-required

✖ 2 problems (2 errors, 0 warnings)
```

Each report line is `<elementId>  <severity>  <message>  <ruleId>` — columns separated by two or more spaces. Lines starting with `✖` are summary only.

## Targeting files

**Single file:**

```bash
npx --yes dmnlint path/to/decision.dmn
```

**Directory:** pass discovered files explicitly so build / cache directories are skipped:

```bash
find src -name '*.dmn' -not -path '*/target/*' -not -path '*/node_modules/*' \
  | xargs npx --yes dmnlint
```

Skip these directories during discovery: `.git`, `node_modules`, `target`, `build`, `.gradle`, `.mvn`, `.idea`.

**Stdin** is supported by some bpmn-io linters; for `dmnlint`, stick to file arguments.

## CI integration

Camunda's CI/CD guide recommends running `dmnlint` (and `bpmnlint`) as a pipeline step before deploy. Minimal GitHub Actions example:

```yaml
- name: Lint DMN
  run: |
    [ -f .dmnlintrc ] || echo '{ "extends": "dmnlint:recommended" }' > .dmnlintrc
    find src -name '*.dmn' -print0 | xargs -0 npx --yes dmnlint
```

The same shape works in any CI that gives you Node + a shell.

## Limitations and what to layer on top

`dmnlint` is structural-only and its rule set is small. The rules it does NOT have:

- It does not flag unquoted string output entries (`HIGH` instead of `"HIGH"`) — those evaluate to `null` at runtime and are caught only by behaviour validation.
- It does not check hit-policy correctness — `UNIQUE` tables with overlapping rules pass lint cleanly and fail at evaluation time.
- It does not validate `typeRef` matches between input expression and input entries.
- It does not check that BPMN `<zeebe:calledDecision decisionId>` references resolve to a deployed decision — cross-file references are out of scope.

Treat `dmnlint` as the structural floor. Layer the by-execution validation (CPT or deploy) on top — see the main SKILL.md § Validation — two-stage loop.
