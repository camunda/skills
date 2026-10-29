"""List the Copilot models the current token can use, and check requested ids.

Preflight for ``eval-models.yml``: Copilot CLI rejects an unavailable model
only when a session starts (``Model "…" from --model flag is not available``),
so a bad id would otherwise fan out into dozens of jobs that each fail in
seconds. The model catalogue depends on the token — a user's own sign-in and
the Actions job token (billed to the org, governed by org policy) can differ.

Reads ``COPILOT_GITHUB_TOKEN`` and queries ``api.githubcopilot.com/models``.
Writes a Markdown table of the chat models and their policy state to stdout.

    evals-copilot-models [--check m1,m2,...]

Exit codes: 0 all requested models available (or no ``--check``); 1 some
requested models unavailable; 3 the catalogue couldn't be read (the caller may
proceed unverified).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from scripts.build_matrix import parse_models

MODELS_URL = "https://api.githubcopilot.com/models"
TOKEN_ENV = "COPILOT_GITHUB_TOKEN"
# The catalogue differs by integration (without this, Gemini models are
# omitted); send Copilot CLI's so the list matches what `copilot --model` sees.
INTEGRATION_ID = "copilot-developer-cli"


def fetch_models(token: str, timeout: float = 20) -> list[dict]:
    req = urllib.request.Request(
        MODELS_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Copilot-Integration-Id": INTEGRATION_ID,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp).get("data") or []


def selectable(models: list[dict]) -> dict[str, dict]:
    """Chat models a session can pick: listed in the picker and not disabled
    by policy (a missing policy block means no restriction)."""
    out: dict[str, dict] = {}
    for m in models:
        if (m.get("capabilities") or {}).get("type") != "chat":
            continue
        if not m.get("model_picker_enabled"):
            continue
        if ((m.get("policy") or {}).get("state") or "enabled") != "enabled":
            continue
        out[m["id"]] = m
    return out


def check(requested: list[str], available: dict[str, dict]) -> list[str]:
    """Requested ids that aren't available (``auto`` is always accepted)."""
    return [m for m in requested if m != "auto" and m not in available]


def render(models: list[dict], requested: list[str]) -> str:
    rows = []
    for m in sorted(models, key=lambda m: m.get("id", "")):
        if (m.get("capabilities") or {}).get("type") != "chat":
            continue
        if not m.get("model_picker_enabled"):
            continue
        state = (m.get("policy") or {}).get("state") or "—"
        mark = "✅" if m["id"] in requested else ""
        rows.append(f"| `{m['id']}` | {m.get('vendor', '')} | {state} | {mark} |")
    return "\n".join(
        [
            "### Copilot models available to this token",
            "",
            "| model | vendor | policy | requested |",
            "| --- | --- | --- | :---: |",
            *rows,
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", default="", help="comma-separated model ids")
    args = parser.parse_args()
    requested = parse_models(args.check)

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"{TOKEN_ENV} is not set", file=sys.stderr)
        sys.exit(3)
    try:
        models = fetch_models(token)
    # OSError covers URLError, timeouts, and connection resets while reading
    # the response; ValueError covers malformed JSON. All mean "unverified".
    except (OSError, ValueError) as e:
        print(f"could not read the Copilot model catalogue: {e}", file=sys.stderr)
        sys.exit(3)

    print(render(models, requested))
    missing = check(requested, selectable(models))
    if missing:
        print(
            f"Unavailable to this token: {', '.join(missing)}. "
            f"Available: {', '.join(sorted(selectable(models)))}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
