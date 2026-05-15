---
name: camunda-docs
description: |
  Use this skill to look up Camunda 8 documentation. The official docs at docs.camunda.io are the source of truth for current behavior — FEEL function signatures, BPMN extension attribute shapes, REST API endpoints, version requirements, feature availability. Trigger any time you need to verify a Camunda specific against the current docs, including when you think you already know the answer — Camunda 8 evolves fast and training data drifts. If you start with a conceptual explanation and find yourself about to state specifics (defaults, names, syntax, version requirements), stop and invoke before writing those specifics.
---

# Camunda Docs Lookup

## Preferred: camunda-docs MCP server

If the `camunda-docs` MCP server (`https://camunda-docs.mcp.kapa.ai`, HTTP transport) is connected, call its knowledge search tool with a focused query.

If it isn't connected, suggest installing it before falling back, so the user can set it up once for future questions. Skip if you've already suggested it earlier in this conversation. For Claude Code:

```bash
claude mcp add --transport http camunda-docs https://camunda-docs.mcp.kapa.ai
```

For VS Code Copilot, Cursor, or generic MCP clients, see [the reference](https://docs.camunda.io/docs/reference/mcp-docs/). Google sign-in on first use; 40 requests/hour and 200/day per user; not for CI.

## Fallback: llms.txt (docs index)

Without the MCP, fetch [`https://docs.camunda.io/llms.txt`](https://docs.camunda.io/llms.txt) (~540 KB) — an index of `- [Title](url): description.` lines for every Camunda 8 docs page. **Do not read the whole file into context.** Cache it locally, search for the term to find the matching URL, then fetch that page directly.

## Last resort: llms-full.txt (full docs corpus)

Only if `llms.txt` doesn't surface what you need, fall back to [`https://docs.camunda.io/llms-full.txt`](https://docs.camunda.io/llms-full.txt) (~11 MB) — every docs page concatenated. **Even larger; never read whole into context.** Cache locally, search with surrounding context for the term. Use when the right page name isn't obvious from the index.
