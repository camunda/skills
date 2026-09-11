---
name: camunda-docs
description: |
  Use this skill to retrieve current Camunda 8 documentation from docs.camunda.io. Use it for version-specific FEEL functions, BPMN extension attributes, REST endpoints, release requirements, and feature availability. It chooses MCP, Algolia, or llms.txt retrieval and cites source URLs. Do not use it to author BPMN, DMN, forms, connectors, or process operations.
---

# Camunda Docs Lookup

**UTILITY SKILL**: retrieve source-backed Camunda documentation, then route implementation work to the focused skill.

## DO NOT USE FOR:

Do not use this skill to author BPMN, DMN, forms, or connectors, or to deploy and operate process instances. Route those tasks to the corresponding Camunda skill after verifying any version-sensitive fact here.

Two retrieval paths into `docs.camunda.io`, each with a different strength. Pick by question shape; fall back to `llms.txt` only if both are unavailable.

| Path | Mechanism | Best for | Returns |
|---|---|---|---|
| **camunda-docs MCP** | Semantic retrieval (vector search) over docs + other Camunda knowledge sources | Conceptual or fuzzy questions; you don't know the exact term; want chunks ready to read | Top-k markdown chunks with source URLs |
| **Algolia DocSearch** | Classical lexical search (the same index docs.camunda.io's own search box uses) | You know the term; want **version-scoped** results (8.7 vs 8.9 vs next); want to triage a ranked page list | Ranked pages with title, hierarchy, snippet — fetch the page for full content |
| **llms.txt / llms-full.txt** | Static text index/corpus | Offline fallback when neither service is reachable | Plain text; grep locally |

Use both primary paths in parallel when in doubt — they're cheap and frequently surface different relevant pages.

## camunda-docs MCP server

If the `camunda-docs` MCP server (`https://camunda-docs.mcp.kapa.ai`, HTTP transport) is connected, call its knowledge search tool with a single, well-formed natural-language sentence (the tool requires a complete sentence, not keywords).

If it isn't connected, suggest configuring the server once so the user has it set up for future questions. Skip the suggestion if you've already made it earlier in this conversation. Add the HTTP server at `https://camunda-docs.mcp.kapa.ai` using the harness's documented MCP configuration flow. For VS Code Copilot, Cursor, or other generic MCP clients, see [the reference](https://docs.camunda.io/docs/reference/mcp-docs/). Google sign-in on first use; 40 requests/hour and 200/day per user; not for CI.

## Algolia DocSearch

A bash wrapper around the public Algolia DocSearch endpoint lives at `scripts/docs-search.sh`. Run it as:

```bash
scripts/docs-search.sh "<query>" [--version stable|next|<major>.<minor>|all] [--limit N]
```

Default `--version stable` resolves to the highest numeric version in the index (so it keeps working when 9.0 ships). Default `--limit 10`. Returns JSON:

```json
{
  "query": "...",
  "version": "stable",
  "algolia_version": "8.9",
  "total": 5,
  "total_matching": 25,
  "hits": [
    { "url": "...", "hierarchy": "...", "title": "...", "snippet": "..." }
  ]
}
```

- `total` — hits in this response.
- `total_matching` — raw count of pages matching the query in the index, before pagination/dedupe. Useful for "how broadly does my term appear?"
- `algolia_version` — the `version` facet value sent to the index (e.g. `"8.9"`, `"current"`). `null` in `--version all` mode (no facet filter applied).

### Search flow

1. **Pick a version** (see table below). Default `stable`.
2. Run the script.
3. Inspect the hits — each has `url`, `hierarchy`, `title`, `snippet`.
4. **Fetch the most relevant page(s)** directly by URL to read full context. Snippets are short; don't answer from them alone if the question needs detail.
5. **Refine if insufficient** — see refinement strategy below.

### Version handling

The Camunda docs are versioned in the URL path. The Algolia `version` facet exposes those versions — without filtering, the same page returns 3-4 times across versions, which is noisy.

| Flag value | Algolia facet | URL prefix | Use when |
|---|---|---|---|
| `stable` (default) | highest numeric (e.g. `8.9`) | `/docs/` | General questions, no version context |
| `next` | `current` | `/docs/next/` | Upcoming/unreleased behavior, alpha features |
| `8.8` / `8.7` / etc. | matching numeric | `/docs/8.8/` etc. | Customer/cluster on a specific generation |
| `all` | (none) | any | Comparing versions; results deduped by URL stem so best-relevance version per page wins |

**Pick explicitly when:**

- Question is about a specific customer/cluster on a known generation → use that version.
- Question is about an upcoming feature, an alpha, or "will this change in 8.10?" → run `stable` and `next` in parallel and compare.
- Question is version-neutral (concepts, BPMN semantics, generic API shape) → `stable` is fine.

In `--version all` mode the script over-fetches (4× `--limit`, capped at 100) so that after dedupe by URL stem the response contains close to `--limit` unique pages. Dedupe preserves Algolia's relevance order — first hit per unique URL stem wins, then trimmed to `--limit`.

### Examples

```bash
# Default — latest stable
scripts/docs-search.sh "zeebe gateway long polling timeout"

# Specific version (customer on 8.7)
scripts/docs-search.sh "task assignment" --version 8.7

# Upcoming behavior
scripts/docs-search.sh "agentic connectors" --version next

# Compare across versions (deduped by URL stem)
scripts/docs-search.sh "decision evaluation API" --version all --limit 15
```

### Refinement strategy

If the first query is unhelpful:

- **Too broad → too many off-topic hits**: add specifics (component, error code, config key).
- **Too narrow → no hits**: drop adjectives, try the canonical product term (e.g. `"Tasklist"` not `"task UI"`, `"Zeebe"` not `"workflow engine"`).
- **Wrong version**: try `--version all` to see if the term exists elsewhere, then narrow to the right release.
- **Synonyms**: try alternative names — e.g. `"Operate"` ↔ `"process monitoring"`, `"Optimize"` ↔ `"analytics"`.

Don't loop more than 2-3 refinements. If still nothing, switch to the MCP path (or note the gap to the user).

### No credentials needed

The Algolia search-only API key is public — Algolia ships it in the browser JS bundle of docs.camunda.io, so every visitor already has it. It's hardcoded at the top of `scripts/docs-search.sh` with a comment explaining why it's safe to commit. No env vars, no auth, safe in CI.

### Without the wrapper script

If you can't or don't want to run `scripts/docs-search.sh` (e.g. `jq` missing, restricted sandbox, or you just need the raw API), call the Algolia endpoint directly:

```bash
curl -sS -f -X POST \
  "https://6KYF3VMCXZ-dsn.algolia.net/1/indexes/camunda-v2/query" \
  -H "X-Algolia-API-Key: 68db7725a8410eace68419c29385ad1e" \
  -H "X-Algolia-Application-Id: 6KYF3VMCXZ" \
  -H "Content-Type: application/json" \
  -d '{"query":"YOUR QUERY","hitsPerPage":10,"facetFilters":[["version:8.9"]]}'
```

Substitute the `version:` facet for the version you want (`current` for `next`, omit `facetFilters` entirely for `all`). The response shape is Algolia's raw hits — useful fields per hit are `url`, `hierarchy.lvl0..lvl5`, and `content`. If `curl` itself isn't available either, use any HTTP client that can POST JSON (Python `urllib`, Node `fetch`, PowerShell `Invoke-RestMethod`); the endpoint, headers, and body are the same. The credentials in the snippet are public by design (see "No credentials needed" above).

## Fallback: llms.txt (docs index)

If neither MCP nor Algolia is usable, fetch [`https://docs.camunda.io/llms.txt`](https://docs.camunda.io/llms.txt) (~540 KB) — an index of `- [Title](url): description.` lines for every Camunda 8 docs page. **Do not read the whole file into context.** Cache it locally, search for the term to find the matching URL, then fetch that page directly.

## Last resort: llms-full.txt (full docs corpus)

Only if `llms.txt` doesn't surface what you need, fall back to [`https://docs.camunda.io/llms-full.txt`](https://docs.camunda.io/llms-full.txt) (~11 MB) — every docs page concatenated. **Even larger; never read whole into context.** Cache locally, search with surrounding context for the term. Use when the right page name isn't obvious from the index.

## Troubleshooting

- If MCP is unavailable, use `scripts/docs-search.sh` when `curl` and `jq` are installed.
- If Algolia search fails, use the `llms.txt` index to locate a page, then fetch that page directly.
- If no source is reachable, state that the lookup is unverified instead of presenting remembered behavior as current.
