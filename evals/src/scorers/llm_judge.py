"""Scorer: LLM rubric judge for BPMN quality.

Hands the agent's BPMN to a judge model along with the user's
original prompt and a four-criterion rubric. Returns the average
score / 5 as a 0–1 float; per-criterion scores plus rationale live
in metadata so the Inspect viewer surfaces the *why* of each grade.

The rubric is grounded in concrete Camunda 8 conventions (sentence
case naming, verb+object tasks, idiomatic primitives, `zeebe:`
extensions, etc.) so the judge effectively measures "did the agent
absorb the skill's idioms?" — the hypothesis this eval suite tests.

Reads BPMN content from ``state.store["artifacts"]`` (populated by
the ``collect_artifacts`` solver). No sandbox round-trip needed.
"""

from __future__ import annotations

import json
import re

from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState

# Rubric — keep close to the canonical-style.md guidance from the
# camunda-bpmn skill so the judge grades against the same rules the
# skill teaches.
RUBRIC_PROMPT = """\
You are an expert Camunda 8 BPMN reviewer. Score the BPMN below on \
FOUR criteria, each on a 0–5 scale.

ORIGINAL USER REQUEST
---------------------
{user_request}

CRITERIA
--------
1. **Naming clarity** (0–5)
   - 5: Tasks named verb+object in sentence case ("Review invoice");
     gateways are questions ("Amount exceeds limit?"); events are
     descriptive ("Order received"); IDs are PascalCase and meaningful.
   - 3: Names exist but are generic ("Task 1", "Step 2") or break case
     conventions.
   - 0: Default IDs only, missing names, or random tokens.

2. **Idiomatic BPMN construct choice** (0–5)
   - 5: Right primitive for the job — timer intermediate events for
     delays, exclusive/parallel gateways used correctly, message/signal
     events for external triggers, script tasks only for FEEL
     expressions, service tasks with `zeebe:taskDefinition` where work
     is delegated.
   - 3: Mostly idiomatic but one or two awkward choices (e.g. a script
     task that should be a service task, or a deeply nested gateway
     where a multi-branch one would do).
   - 0: Abuses constructs (a single script task simulating an entire
     flow, gateways with no conditions, etc.).

3. **Structural soundness** (0–5)
   - 5: Single start event, every path reaches an end event, gateways
     converge properly, no dead-ends, no disconnected nodes, sensible
     flow direction (left-to-right or top-down).
   - 3: Minor issues (e.g. duplicate end events with no semantic
     reason).
   - 0: Missing start/end, dead-ends, disconnected fragments.

4. **Camunda 8 specifics** (0–5)
   - 5: `isExecutable="true"`, `modeler:executionPlatform="Camunda Cloud"`
     with a valid 8.x version, `zeebe:` extensions where required
     (taskDefinition, calledDecision, formDefinition, etc.), no
     Camunda-7-only constructs.
   - 3: Has the basics but missing some attributes (no executionPlatform
     declared, or wrong version tag).
   - 0: Not deployable to Zeebe — Camunda-7 syntax, missing isExecutable,
     malformed namespaces.

OUTPUT FORMAT
-------------
Return ONLY a JSON object (no prose before or after, no markdown
fences). The object must have exactly these keys:

{{
  "naming_clarity": <integer 0-5>,
  "idiomaticity": <integer 0-5>,
  "structure": <integer 0-5>,
  "camunda8_specifics": <integer 0-5>,
  "rationale": "<2-4 sentences naming specific element IDs from the BPMN to justify the scores>"
}}

BPMN
----
{bpmn}
"""

_DEFAULT_JUDGE = "anthropic/claude-opus-4-7"

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction — handles bare JSON or fenced blocks."""
    text = text.strip()
    # Try direct parse first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try fenced block.
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try first `{...}` span (greedy match on outermost braces).
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


_CRITERIA = (
    "naming_clarity",
    "idiomaticity",
    "structure",
    "camunda8_specifics",
)


@scorer(metrics=[])
def judge_bpmn_quality(
    judge_model: str = _DEFAULT_JUDGE,
    max_tokens: int = 800,
) -> Scorer:
    """Score the agent's BPMN against a 4-criterion rubric.

    Returns the per-criterion average / 5 as a 0–1 float so the
    score composes with the binary scorers. Per-criterion scores
    and the judge's rationale are stored in metadata.
    """

    async def score(state: TaskState, target: Target) -> Score:
        artifacts = state.store.get("artifacts", {}) or {}
        bpmn_paths = sorted(p for p in artifacts if p.lower().endswith(".bpmn"))
        if not bpmn_paths:
            return Score(
                value=0.0,
                explanation="no BPMN artifact in state.store",
            )

        # Judge the first BPMN — scenarios typically produce one main
        # file. If a scenario produces multiple, extend this to loop
        # and average.
        path = bpmn_paths[0]
        bpmn = artifacts[path]
        if not isinstance(bpmn, str) or not bpmn.strip():
            return Score(
                value=0.0,
                explanation=f"BPMN at {path} is empty or non-text",
            )

        user_request = (state.input_text or "").strip() or "(not available)"
        prompt = RUBRIC_PROMPT.format(user_request=user_request, bpmn=bpmn)

        model = get_model(judge_model)
        response = await model.generate(
            prompt,
            config=GenerateConfig(temperature=0.0, max_tokens=max_tokens),
        )
        text = (response.completion or "").strip()

        parsed = _extract_json(text)
        if parsed is None:
            return Score(
                value=0.0,
                explanation=f"judge returned non-JSON; raw: {text[:400]}",
                metadata={"judge_raw": text},
            )

        per_criterion: dict[str, int] = {}
        for key in _CRITERIA:
            raw = parsed.get(key)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return Score(
                    value=0.0,
                    explanation=f"judge missing or non-int {key!r}: {raw!r}",
                    metadata={"judge_parsed": parsed, "judge_raw": text},
                )
            per_criterion[key] = max(0, min(5, value))

        avg = sum(per_criterion.values()) / (5 * len(_CRITERIA))
        rationale = (parsed.get("rationale") or "").strip()

        return Score(
            value=avg,
            explanation=(
                f"avg {avg:.2f}  "
                + "  ".join(f"{k}={v}/5" for k, v in per_criterion.items())
                + (f"\n{rationale}" if rationale else "")
            ),
            metadata={
                "judge_model": judge_model,
                "bpmn_path": path,
                "per_criterion": per_criterion,
                "rationale": rationale,
            },
        )

    return score
