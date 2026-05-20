#!/usr/bin/env bash
# Search docs.camunda.io via the public Algolia DocSearch index.
# Usage: docs-search.sh <query> [--version stable|next|<major>.<minor>|all] [--limit N]
#
# Version mapping (Algolia 'version' facet → URL prefix):
#   current → /docs/next/        (unreleased dev branch)
#   <highest numeric> → /docs/   (no prefix; latest stable)
#   8.8     → /docs/8.8/
#   8.7     → /docs/8.7/         (etc., for any released <major>.<minor>)
#
# This script accepts user-friendly version names:
#   stable          → highest numeric version present in the index (auto-resolved each call)
#   next            → mapped to Algolia 'current'
#   <major>.<minor> → passed through (e.g. 8.7, 9.0)
#   all             → no filter; results deduped by URL path stripped of version segment
set -euo pipefail

# ---------------------------------------------------------------------------
# PUBLIC credentials — safe to commit.
#
# These are Algolia DocSearch search-only credentials. They are public by
# design: Algolia ships them in the browser JS bundle of docs.camunda.io
# (extracted from /assets/js/main.*.js), so every visitor to the docs site
# already has them. Search-only keys are read-only and scoped to one index;
# they cannot write, delete, list other indexes, or read account data.
# If Camunda ever rotates the key on the docs site, re-extract from the JS
# bundle.
# ---------------------------------------------------------------------------
APP_ID="6KYF3VMCXZ"
API_KEY="68db7725a8410eace68419c29385ad1e"
INDEX="camunda-v2"
URL="https://${APP_ID}-dsn.algolia.net/1/indexes/${INDEX}/query"

usage() {
  echo "Usage: $0 <query> [--version stable|next|<major>.<minor>|all] [--limit N]" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' is required but not installed." >&2
    exit 1
  fi
}

if [ $# -lt 1 ]; then
  usage
fi

QUERY="$1"; shift
VERSION="stable"
LIMIT=10

while [ $# -gt 0 ]; do
  case "$1" in
    --version)
      [ $# -ge 2 ] || { echo "Error: --version requires a value" >&2; usage; }
      VERSION="$2"; shift 2 ;;
    --limit)
      [ $# -ge 2 ] || { echo "Error: --limit requires a value" >&2; usage; }
      [[ "$2" =~ ^[1-9][0-9]*$ ]] || { echo "Error: --limit must be a positive integer (got: $2)" >&2; usage; }
      LIMIT="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
done

require_cmd curl
require_cmd jq

# Resolve "stable" to the highest numeric version reported by the index.
# This keeps the script working when 9.0 ships without a code change.
# Max-version selection runs entirely in jq so the script's runtime deps
# stay limited to curl + jq (no coreutils sort/tail needed).
resolve_stable() {
  curl -sf -X POST "$URL" \
    -H "X-Algolia-API-Key: $API_KEY" \
    -H "X-Algolia-Application-Id: $APP_ID" \
    -H "Content-Type: application/json" \
    -d '{"query":"","hitsPerPage":0,"facets":["version"]}' \
    | jq -r '
        .facets.version
        | keys
        | map(select(test("^[0-9]+\\.[0-9]+$")))
        | sort_by(split(".") | map(tonumber))
        | last // empty
      '
}

if [ "$VERSION" = "stable" ]; then
  ALGOLIA_VERSION="$(resolve_stable)"
  if [ -z "$ALGOLIA_VERSION" ]; then
    echo "Error: could not resolve 'stable' version from index" >&2
    exit 1
  fi
elif [ "$VERSION" = "next" ]; then
  ALGOLIA_VERSION="current"
elif [ "$VERSION" = "all" ]; then
  ALGOLIA_VERSION=""
elif [[ "$VERSION" =~ ^[0-9]+\.[0-9]+$ ]]; then
  ALGOLIA_VERSION="$VERSION"
else
  echo "Invalid --version: $VERSION (use stable|next|<major>.<minor>|all)" >&2
  exit 1
fi

# In `all` mode, over-fetch from Algolia: the same content is indexed across
# 3-4 versions, so dedupe by URL stem typically collapses N raw hits down to
# ~N/3. Request 4× the requested limit (capped at 100) to land close to LIMIT
# unique results after dedupe.
if [ "$VERSION" = "all" ]; then
  REQUEST_LIMIT=$(( LIMIT * 4 ))
  [ "$REQUEST_LIMIT" -gt 100 ] && REQUEST_LIMIT=100
else
  REQUEST_LIMIT="$LIMIT"
fi

if [ -n "$ALGOLIA_VERSION" ]; then
  BODY=$(jq -n \
    --arg q "$QUERY" \
    --argjson n "$REQUEST_LIMIT" \
    --arg v "$ALGOLIA_VERSION" \
    '{query: $q, hitsPerPage: $n, facetFilters: [["version:" + $v]]}')
else
  BODY=$(jq -n \
    --arg q "$QUERY" \
    --argjson n "$REQUEST_LIMIT" \
    '{query: $q, hitsPerPage: $n}')
fi

RAW=$(curl -sf -X POST "$URL" \
  -H "X-Algolia-API-Key: $API_KEY" \
  -H "X-Algolia-Application-Id: $APP_ID" \
  -H "Content-Type: application/json" \
  -d "$BODY")

# Project to a stable shape; in 'all' mode dedupe by URL with version segment
# stripped, preserving Algolia's relevance order, then trim to LIMIT.
#   total           = number of hits in this response (== hits | length)
#   total_matching  = raw Algolia nbHits (total pages matching the query in
#                     the index, before pagination/dedupe)
#   algolia_version = the Algolia 'version' facet value sent to the index;
#                     null in `all` mode (no facet filter applied)
# Order-preserving dedupe: jq's `unique_by` sorts by the key and would lose
# Algolia's relevance ranking. The reduce-based form below keeps the first
# occurrence of each stem in the original order.
if [ "$VERSION" = "all" ]; then
  echo "$RAW" | jq --arg q "$QUERY" --argjson lim "$LIMIT" '
    . as $raw
    | [ .hits[] | {
          url,
          stem: (.url | sub("/docs/(next|[0-9]+\\.[0-9]+)/"; "/docs/")),
          hierarchy: (.hierarchy.lvl0 // ""),
          title: ((.hierarchy.lvl1 // .hierarchy.lvl0) // ""),
          snippet: (.content // (.hierarchy.lvl5 // .hierarchy.lvl4 // .hierarchy.lvl3 // .hierarchy.lvl2 // ""))
        }
      ]
    | reduce .[] as $h ([]; if any(.[]; .stem == $h.stem) then . else . + [$h] end)
    | .[0:$lim]
    | map(del(.stem))
    | {
        query: $q,
        version: "all",
        algolia_version: null,
        total: length,
        total_matching: $raw.nbHits,
        hits: .
      }'
else
  echo "$RAW" | jq --arg q "$QUERY" --arg v "$VERSION" --arg av "$ALGOLIA_VERSION" '
    {
      query: $q,
      version: $v,
      algolia_version: $av,
      total: (.hits | length),
      total_matching: .nbHits,
      hits: [ .hits[] | {
        url,
        hierarchy: (.hierarchy.lvl0 // ""),
        title: ((.hierarchy.lvl1 // .hierarchy.lvl0) // ""),
        snippet: (.content // (.hierarchy.lvl5 // .hierarchy.lvl4 // .hierarchy.lvl3 // .hierarchy.lvl2 // ""))
      } ]
    }'
fi
