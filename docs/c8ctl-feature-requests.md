# c8ctl Feature Requests

Missing c8ctl features identified during skills development. These would improve the AI-assisted development experience.

Status legend: ✅ DONE — implemented and in use; 📋 OPEN — not yet implemented.

---

## 1. ✅ Element Templates: List/Search — DONE

**Implemented as**: `c8 element-template search [<query>]`

Lists OOTB element templates by name. Empty query returns all entries. Each result shows the template name, ID, and version. The local catalog is populated/refreshed by `c8 element-template sync`.

The skills now use this in the `camunda-connectors` workflow as the first step — discover the template ID via search rather than guessing or hardcoding it.

---

## 2. ✅ Element Templates: Get/Inspect — DONE

**Implemented as**: `c8 element-template list-properties <template-id>` (alias: `props`)

Shows the settable properties of a template (skipping `Hidden` ones), including type, FEEL support, conditions, and constraints. This is the more useful form for AI agents than dumping raw JSON, because the icon field (large base64 blob) is filtered out.

If raw JSON is needed, the OOTB cache populated by `c8 element-template sync` contains the full template files locally.

---

## 3. ✅ Element Templates: Apply — DONE

**Implemented as**: `c8 element-template apply <template> <element-id> <bpmn-file>`

Where `<template>` is a local path, https:// URL, or OOTB template ID (with optional `@<version>`).

Key flags:
- `--in-place` — modify the BPMN file directly (otherwise prints to stdout)
- `--set key=value` (repeatable) — set property values inline at apply time

This eliminates the need for the `element-templates-cli` npm package and avoids npm cache permission issues that previously blocked the sandbox.

---

## 4. ✅ FEEL Expression Evaluation — DONE

**Implemented as**: `c8 feel eval '<expression>'`

Key flags:
- `--var key=value` (repeatable; supports JSON values and dot-path nesting like `customer.name=Alice`)
- `--vars '{"a":1,"b":2}'` — bulk variables as a single JSON object
- `--engine local` — offline evaluation via the `feelin` JS engine

**Engine semantics**: Default is cluster evaluation against the Scala FEEL engine — the same engine Zeebe runs in production. `--engine local` uses `feelin`, which behaves DIFFERENTLY from the Scala engine in subtle ways (type coercion, function support, date/time). Skills must default to cluster mode and only fall back to `--engine local` when the user explicitly asks for offline evaluation, or when no cluster is available AND the user has confirmed the fallback. Never silently fall back.

---

## 5. ✅ BPMN Validation — DONE

**Implemented as**: `c8 bpmn lint <file>` (also accepts BPMN via stdin)

Auto-detects the Camunda execution platform version from the BPMN file. Uses `.bpmnlintrc` if present in the project; otherwise applies sensible Camunda defaults. No npm cache dependency — the original sandbox blocker for `npx bpmnlint` is gone.

---

## 6. 📋 Dry Run for Deployment — OPEN

**Command**: `c8 deploy <file> --dry-run`

**Description**: Validate a deployment without actually deploying. Returns what would be deployed and any validation errors.

**Why**: Allows AI agents to preview deployment effects safely. Supports the plan-validate-execute pattern recommended for AI agent tooling.

---

## 7. 📋 Per-invocation Output Mode — OPEN

**Command**: `c8 <any> --json` (or `--output json`) and/or env var `C8CTL_OUTPUT_MODE=json`

**Description**: Allow setting the output mode (json/text) for a single invocation, without persisting it to `session.json`. Today, switching mode requires `c8 output json && c8 <cmd> && c8 output text`, which (a) is awkward for scripting, (b) mutates persistent session state, and (c) fails entirely under sandboxed agents that can't write to `~/Library/Application Support/c8ctl/session.json` (`C8CTL_DATA_DIR` works around this but adds setup overhead).

**Why**: Aligns with common CLI conventions (`gh --json`, `kubectl -o json`, `aws --output json` / `AWS_OUTPUT_FORMAT`). Makes c8ctl scriptable from CI pipelines and AI agents without state side effects.
