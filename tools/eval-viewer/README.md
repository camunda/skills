# Eval Viewer

A local web UI for inspecting eval iterations produced by the `tools/eval-runner`
harness. Renders BPMN, DMN, and Camunda Form outputs side by side with
LLM-judge gradings and per-config timing/token accounting.

## Run

From the repo root:

```sh
make viewer
```

This auto-installs `node_modules/` on first run (via the `[ -d node_modules ] || npm install` guard in the Makefile) and serves at <http://localhost:3334>.

To run directly without the Makefile:

```sh
cd tools/eval-viewer
npm install         # first time only
node serve.js                              # browse all skills
node serve.js ../../evals/camunda-feel     # jump to one skill
node serve.js ../../evals/camunda-feel/iteration-3   # jump to one iteration
```

The viewer auto-discovers everything under `evals/` (the gitignored top-level
workspace dir). Pick a skill and iteration with the dropdowns at the top —
no restart needed when switching.

## What it shows

- **Side-by-side panels** — one per config (typically `with_skill` and
  `without_skill`) for the same case, so you can eyeball deltas.
- **Renderers**:
  - `.bpmn`, `.dmn` — interactive `bpmn-js` canvas with element-template icons.
  - `.form` — Camunda Forms preview (TODO: see parity audit in `AGENTS.md`).
  - Anything else (e.g. `.feel`, `.json`, `.txt`) — plain-text panel.
- **Multi-file outputs** — when a config produces several files, a tab strip
  appears above the panel; the renderable file (BPMN/DMN/Form) is selected
  first and others fall back to text.
- **Assertions** — pass/fail indicators with the LLM judge's evidence text.
- **Meta strip** — total tokens and duration per config, sourced from
  `timing.json`.

## Iteration directory contract

The viewer expects, per case, the following layout:

```
evals/<skill>/iteration-N/
  <case-id>/
    eval_metadata.json       (optional: prompt + assertions text)
    with_skill/
      outputs/
        answer.feel | process.bpmn | form.form | ...
      grading.json           (LLM-judge result; see schema below)
      timing.json            (optional)
    without_skill/
      outputs/
      grading.json
      timing.json
```

The runner produces this shape; documenting it here so the viewer and runner
stay in lockstep.

## Troubleshooting

- **Blank page / "Cannot GET /node_modules/..."** — `node_modules/` missing.
  Run `npm install` in `tools/eval-viewer/`.
- **404 on `/api/iteration/.../iteration-N`** — that iteration directory
  doesn't exist. Check the dropdown; iterations not on disk are not listed.
- **Port already in use** — `PORT=3335 node serve.js`.
- **Different evals root** — pass it as the first arg, or set `evalsRoot` via
  the path argument: `node serve.js /absolute/path/to/evals`.

## Maintenance

Architecture notes, the JSON contract this viewer reads (with file:line
citations), the renderer-registry interface, and the parity-audit log against
the upstream `anthropics/skills/skills/skill-creator/eval-viewer/` fork live in
[`AGENTS.md`](AGENTS.md). Read that before changing `serve.js` or `index.html`.
