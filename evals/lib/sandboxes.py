"""Resolve a scenario's Docker sandbox from its typed metadata.

The single hook between ``metadata.image`` / ``metadata.verifier`` and
the actual compose file Inspect AI brings up. Each ``task.py`` calls
``sandbox_for(METADATA)`` and passes the result to ``Task(sandbox=...)``.

Resolution order:

1. If ``scenarios/<id>/compose.yaml`` exists, use it. This is the
   per-scenario override hook — used when a scenario needs custom
   infra (e.g., WireMock with specific mappings for invoice-approval).
2. Otherwise, pick an archetype from ``sandboxes/`` keyed on
   ``(metadata.image, needs_verifier?)``:

   | image       | verifier kind                  | archetype                  |
   |-------------|--------------------------------|----------------------------|
   | base        | any                            | compose-base.yaml          |
   | with-c8ctl  | cpt, composite                 | compose-cpt-verifier.yaml  |
   | with-c8ctl  | exit-code, transcript, judge   | compose-with-c8ctl.yaml    |

   The ``composite`` verifier conservatively spins up the verifier
   service because composite scorers may include CPT — extra container
   is cheap when unused.

Per-scenario compose files (option 1) should ``include:`` from one of
the archetypes rather than duplicating the base config:

    # scenarios/02-invoice-approval/compose.yaml
    include:
      - ../../sandboxes/compose-cpt-verifier.yaml
    services:
      wiremock:
        image: wiremock/wiremock:latest
        ...
"""

from __future__ import annotations

from pathlib import Path

from evals.lib.metadata import ScenarioMetadata

EVALS_DIR = Path(__file__).resolve().parent.parent
SANDBOXES_DIR = EVALS_DIR / "sandboxes"
SCENARIOS_DIR = EVALS_DIR / "scenarios"

_VERIFIERS_NEEDING_CPT_CONTAINER = {"cpt", "composite"}


def sandbox_for(metadata: ScenarioMetadata) -> tuple[str, str]:
    """Return ``(provider, compose_path)`` for the scenario's metadata.

    Uses ``metadata.id`` to look up a per-scenario ``compose.yaml``
    override first; falls back to the archetype keyed on
    ``(image, verifier)``.
    """
    override = SCENARIOS_DIR / metadata.id / "compose.yaml"
    if override.exists():
        return ("docker", str(override))

    archetype = _archetype_for(metadata)
    return ("docker", str(SANDBOXES_DIR / archetype))


def _archetype_for(metadata: ScenarioMetadata) -> str:
    if metadata.image == "base":
        return "compose-base.yaml"
    if metadata.image == "with-c8ctl":
        if metadata.verifier in _VERIFIERS_NEEDING_CPT_CONTAINER:
            return "compose-cpt-verifier.yaml"
        return "compose-with-c8ctl.yaml"
    raise ValueError(f"unsupported image: {metadata.image}")
