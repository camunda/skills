# Element-template migration

Before finalizing a new version of an existing template or a replacement, produce a review-ready migration in one pass from the exact source and target templates and representative BPMN. Optimize for **minimal risk and user action**: preserve configured behavior and user decisions, adopt safe target defaults, automate deterministic conversions, and ask users to act only when their specific configuration requires it.

## 1. Inventory source evidence

Pin source/target template IDs and versions. Diff their bindings, values, defaults (including stored source defaults), dropdown choices, visibility conditions, and target constraints. Trace every meaningful setting through the connector contract and runtime, including inputs, headers, outputs, authentication, endpoints, and removed or newly supported options. Enumerate source-valid branches; do not plan for impossible dropdown values.

Account for each source binding with a target mapping: automatic copy/remap, intentional target default or drop, or a specific loss requiring action. Distinguish configured overrides from stored defaults where the BPMN supports it. Same-name bindings do not prove equivalent behavior. Show coverage by source branch and identify genuine losses; never infer complete coverage from same-name bindings.

Keep migration paths separate. The manual Modeler upgrade guide describes user work when no migration recipe runs: treat its mappings as candidates to automate, not as instructions to repeat after migration. Inspect any c8ctl migration recipe and its separately labeled notes independently; trace the actual recipe, overrides, and target runtime behavior. Infer deterministic intent from evidence, but do not evaluate FEEL or secrets. For example, when a public endpoint selects a backend that supplies its own URL, use that target default; preserve custom endpoints and proxy prefixes, normalizing only documented terminal suffixes.

## 2. Present the plan

Write shared `changes` for the majority of users on that migration step (>50%). Draft it in one pass from the source/target diff, migration instructions, and runtime/deployment requirements. In a few bullets, summarize new capabilities, major configuration reorganizations, what migrates automatically, and the broadly required next step (for example, deploy a new version while retaining workers needed by existing instances). End with a simple fallback to run the migrated connector and consult an agent or linked guide if it does not work. Do not expose every user to rare provider/backend/auth combinations; document those edge cases separately and link the guide from the fallback.

Call out conscious deprecations in `changes` when they affect the majority. For a minority-only deprecation, describe the affected configuration and its resolution in detailed documentation instead of making every user read irrelevant guidance. Then give a human-readable migration table grouped by user effort:

| Resolution | Source configuration / exact predicate | Migration result or remaining gap / action |
|---|---|---|
| Automatic / no action | Exact source binding, value/branch, or default case | Target binding/value or evidence normal update/default is sufficient |
| Target constraints | Exact invalid or missing value | Constraint and expected validation error |
| Manual review/action | Technically valid source configuration that the target may not support (for example, a custom URL accepted by v1 but unsupported by v2) | Exact compatibility gap and the required alternative or edit |

Use element-template **constraints** for invalid values; do not duplicate constraint-covered work, restate available dropdown choices, or list unsupported source configurations as migration failures. Automate deterministic changes even if the manual guide describes them.

Manual review/action is for technically valid source configurations that may not be supported by the target—not values already invalid under the source template. For each row, give an exact predicate identifying the affected configuration, the target compatibility gap the recipe or constraints cannot close, and the precise alternative or edit. Never say only “review if affected.” If applicability cannot be detected from stored values, document what to inspect and how to resolve it, but keep rare-case detail out of shared `changes`; link it from the generic fallback. `changes` applies to the whole migration step, not individual elements.

Example of concise, broadly relevant `changes` guidance for a significant change:

```json
"changes": "- New capabilities include reasoning controls, prompt caching, more model backends and authentication options, and custom chat model providers (Self-Managed/Hybrid).\n- Providers and backends are reorganized: Azure OpenAI and OpenAI-compatible move under OpenAI; Vertex AI moves under Google Gemini.\n- Authentication, supported endpoints, models, prompts, and other shared settings migrate automatically.\n- Make the v2 worker available and deploy a new process version; keep the v1 worker for deployed v1 processes.\n- Run the agent. If it does not work as expected, see the [upgrade guide](https://docs.camunda.io/docs/components/connectors/out-of-the-box-connectors/agentic-ai-aiagent-upgrade/)."
```

Present the proposed plan for review before implementation. Ask only about real unresolved decisions—never facts available from the templates, recipe, notes, or runtime contract. Incorporate feedback, then implement evidence-backed choices.

## 3. Implement and validate

Declare `migratesFrom` steps on the target template. Each step has positive `toVersion`, optional `sourceTemplateId` (defaults to the target ID), inclusive `minSourceVersion` / `maxSourceVersion`, `availabilityMessage`, `changes`, and ordered `instructions`. Unversioned means version `0`. Same-ID updates run eligible target steps above the source and through the target version in ascending order. Different-ID changes run the earliest eligible direct step, then target-ID update steps—not source update steps. Steps read the previous step's result; intermediate defaults are not applied, and versions without steps are no-ops.

- Use full binding descriptors in `from`, `to`, and `when.binding`. `from` skips missing/empty values; `set` writes a literal, and `set: ""` clears a value. `values` remaps matching strings; `replace: { pattern, replacement }` applies a JavaScript regex after remapping.
- `when` accepts `equals`, `isEmpty`, or `matches` with optional `not`; arrays require every condition to match. Group `instructions` under a shared `when`. Some getters return empty for missing values, so missing and empty may be indistinguishable.
- Conditions read pre-step values. Writes apply in order after the target is applied, so set a controlling value before its conditional destinations. Missing/inactive destinations are skipped; hidden destinations take target defaults. Other unwritten properties use normal update/default behavior.
- Instructions transform stored text, not resolved FEEL or secrets. Do not infer dynamic values or rewrite them as known endpoints. Constraints can flag invalid fields but do not validate cross-field behavior.

Lint templates/BPMN and run migration tests. Run a sample migration in the actual Modeler and assert resulting BPMN bindings and values for every valid source branch, version boundary, default/override, missing value, and conditional destination. Check target constraints and that only applicable cases need manual action; exercise undo/redo and reload. Test connector behavior on a cluster when credentials are already configured and the operation is safe. Otherwise run the strongest fixture/mock-based checks available and report exactly what remains unverified. Never request or print secret values.

Migration does not prove completeness or runtime equivalence, resolve FEEL/secrets, validate across fields, or generate a loss report.

See the [migration contract](https://github.com/bpmn-io/bpmn-js-element-templates/blob/6f93b0dc1a4a34ce9a0139683314fc024500b6d6/docs/TEMPLATE_MIGRATION.md), its [REST](https://github.com/bpmn-io/bpmn-js-element-templates/blob/6f93b0dc1a4a34ce9a0139683314fc024500b6d6/docs/examples/rest-connector-migrates-from.json), [AI Agent Sub-process](https://github.com/bpmn-io/bpmn-js-element-templates/blob/6f93b0dc1a4a34ce9a0139683314fc024500b6d6/docs/examples/ai-agent-migrates-from.json), and [AI Agent Task](https://github.com/bpmn-io/bpmn-js-element-templates/blob/6f93b0dc1a4a34ce9a0139683314fc024500b6d6/docs/examples/ai-agent-task-migrates-from.json) examples. Use them as evidence, not as a substitute for accounting for the actual source/target pair.
