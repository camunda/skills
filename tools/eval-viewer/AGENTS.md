# Eval Viewer — Maintenance Notes

This file is for contributors changing the viewer. The user-facing readme lives
in `README.md`.

## Architecture

Two files, no build step:

- `serve.js` — Vite dev server hosting `index.html`, plus three Express-style
  middlewares mounted on `/api/*` for the eval data API.
- `index.html` — single-page UI that fetches from `/api/*` and renders BPMN
  via `bpmn-js`, fed by ES-module imports the Vite server resolves out of
  `node_modules/`.

There is intentionally no bundler config and no client framework. Everything
runs through Vite's dev server in the user's browser.

## API contract

`serve.js` exposes:

| Path | Returns | Code ref |
|---|---|---|
| `GET /api/skills` | `{ skills: [{name, iterations[]}], initial?: {skill, iteration} }` | `serve.js:164-170` |
| `GET /api/iteration/:skill/:iteration` | `{ skill, iteration, directory, evals[] }` | `serve.js:172-190` |
| `GET /api/file?path=<abs>` | raw file content; rejects paths outside `evalsRoot` | `serve.js:192-209` |

`/api/file` enforces a path-prefix check (`serve.js:195`) so the browser cannot
exfiltrate arbitrary host files. **Do not loosen this check** — when the runner
relativizes paths in `grading.json`, the viewer compensates by joining them
back against `evalsRoot`; absolute paths in the request must still live under
`evalsRoot` to be served.

## JSON shapes the viewer reads

These are consumed by `scanIteration()` in `serve.js:89-153` and rendered in
`index.html`. Field-by-field citations:

### `eval_metadata.json` (per case)

```jsonc
{
  "eval_name": "basic-expression",
  "prompt": "Write a FEEL expression to ...",
  "assertions": [ /* free-form prose, currently unused by index.html */ ]
}
```

Read at `serve.js:99-103`. The runner writes this when the case is dispatched.

### `grading.json` (per config)

Required for the assertions panel:

```jsonc
{
  "summary": { "passed": 4, "total": 5 },
  "expectations": [
    { "text": "Use if-then-else with an else branch", "passed": true,
      "evidence": "expression contains `if ... then ... else`" }
  ]
}
```

Field cites in `index.html`: `index.html:330-342` reads
`grading.expectations[].text`, `.passed`, `.evidence`, plus
`grading.summary.passed` and `grading.summary.total`.

### `timing.json` (per config, optional)

```jsonc
{ "total_tokens": 12345, "total_duration_seconds": 18.4 }
```

Read at `index.html:300-302`.

### `outputs/` (per config)

Any files the agent emitted. Renderer dispatch (`serve.js:115`):

| Extension | `type` | Renderer |
|---|---|---|
| `.bpmn` | `bpmn` | `bpmn-js` viewer (`index.html:362-375`) |
| `.dmn`  | `dmn`  | `bpmn-js` viewer (TODO: dedicated dmn-js, see parity audit) |
| `.form` | `form` | TODO; currently routed to text fallback |
| anything else | `text` | `<div class="text-output">` (`index.html:323`) |

`.bpmnlintrc` and `.gitkeep` are explicitly skipped at `serve.js:116`.

## Renderer registry interface

`index.html` does not have a pluggable registry today; the dispatch table is
inline at `index.html:309-325, 391-404` (file-tab logic) and `index.html:362-378`
(per-type render). When extending to support a new renderable type:

1. Add the extension to the `RENDERABLE` set in `serve.js:115`.
2. Map it to a `type` string in `serve.js:124`.
3. Add a `Content-Type` for `/api/file` in `serve.js:204-206`.
4. In `index.html:317-325`, branch on the new `type` and emit the right
   container element.
5. In `loadOutputs()` (`index.html:352-381`), branch on `f.type` and call
   the renderer.

The form-render verifier (Issue #14) will land its renderer here, at which
point we should refactor steps 4–5 into a small dispatch object indexed by
`type`. Until then keep the if/else; premature abstraction has bitten us
on the upstream fork.

## Parity audit vs. upstream

Forked from `anthropics/skills/skills/skill-creator/eval-viewer/`. Audit
performed 2026-05-04. Items below describe upstream features and our
position on each.

| Upstream feature | Our position |
|---|---|
| Auto-discovery of `evals/<skill>/iteration-N/` directories | **Done** (`serve.js:65-87`) |
| Skill + iteration dropdowns, switchable without restart | **Done** (`serve.js:164-170`, `/api/skills` + `?initial`) |
| Side-by-side panels per config | **Done** |
| BPMN rendering via `bpmn-js` with element-template icons | **Done** (`index.html:364-368`) |
| Multi-file output support with tab strip | **Done** (`index.html:309-325, 391-404`) — local addition past upstream |
| Pass/fail assertion list with evidence | **Done** (`index.html:330-342`) |
| Per-config tokens + duration meta strip | **Done** (`index.html:300-302`) |
| Form rendering (forms-js) | **Declined for now** — Issue #14 will add the verifier and renderer together. Currently falls back to text. |
| DMN rendering (dmn-js) | **Declined for now** — out of scope until a DMN skill exists; `.dmn` files currently route through `bpmn-js`, which fails to render but does not crash. |
| Diff highlighting between configs | **Declined** — visual side-by-side is sufficient for current scale. |
| Per-iteration cost roll-up | **Declined** — cost lives in summary.json (Issue #11 surfaces it in the PR comment, not the viewer). |
| Run-without-install guard via Makefile | **Done** (`Makefile` `viewer` target) |

When porting future upstream changes, update this table and cite the upstream
commit SHA.

## Local additions worth preserving

- Multi-file `.file-tabs` (BPMN-output skills like `camunda-bpmn` may emit a
  process file alongside a `.bpmnlintrc` or example artifact).
- The `RENDERABLE` set sorts renderable files first so the panel opens on the
  diagram, not the lint config (`serve.js:128-132`).
- `eval_metadata.json` parsing tolerates malformed JSON (try/catch silently
  falls back to a default — `serve.js:101-103`). This is intentional: a broken
  metadata file should not block viewing the outputs.

## Things NOT to change without coordinating with the runner

- The `outputs/` directory name (`serve.js:113`). The runner writes here; if
  we rename, we break iterations across the repo.
- The `grading.json` / `timing.json` filenames (`serve.js:136, 142`).
- The path-prefix check on `/api/file` (`serve.js:195`).

## Pinned dependency posture

`package.json` pins `bpmn-js` and the element-template icon renderer.
`package-lock.json` IS committed alongside it for reproducible installs in
CI and on contributor machines. When bumping a dep, regenerate the lockfile
with `npm install` and commit both files together.
