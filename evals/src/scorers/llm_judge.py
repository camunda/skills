"""Scorer: lightweight LLM quality judge for BPMN artifacts.

CPT is the main quality signal — this is a cheap addon that catches
"deploys and runs but looks awful" cases (bad naming, wrong primitives,
sloppy Camunda 8 syntax). One judge call, one number, one rationale.

Reads BPMN from ``state.store["artifacts"]`` (populated by the
``collect_artifacts`` solver).
"""

from __future__ import annotations

import re

from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState

# Sonnet is plenty for a coarse 0-10 rating; override per-scenario if needed.
_DEFAULT_JUDGE = "anthropic/claude-sonnet-4-6"

PROMPT = """\
Rate this Camunda 8 BPMN from 0 to 10 on overall quality.

Look for:
- Sentence-case names ("Review invoice", not "Task1"); tasks as
  verb+object; gateways labelled as questions.
- Idiomatic primitives — timer events for delays, gateways with
  real conditions, no script-task abuse.
- Deployable Camunda 8 syntax: isExecutable, modeler:executionPlatform
  "Camunda Cloud" with an 8.x version, zeebe:* extensions where needed.
- Sound flow — single start, every path reaches an end, no dead-ends.

ORIGINAL REQUEST
{user_request}

BPMN
{bpmn}

Reply with one short paragraph of justification, then end with exactly
one line:

SCORE: <integer 0-10>
"""

_SCORE_RE = re.compile(r"SCORE:\s*(\d+)", re.IGNORECASE)


@scorer(metrics=[])
def judge_bpmn_quality(
    judge_model: str = _DEFAULT_JUDGE,
    max_tokens: int = 400,
) -> Scorer:
    """Single 0-10 BPMN quality rating, returned as a 0-1 float."""

    async def score(state: TaskState, target: Target) -> Score:
        artifacts = state.store.get("artifacts", {}) or {}
        bpmn_paths = sorted(p for p in artifacts if p.lower().endswith(".bpmn"))
        if not bpmn_paths:
            return Score(value=0.0, explanation="no BPMN artifact")

        path = bpmn_paths[0]
        bpmn = artifacts[path]
        if not isinstance(bpmn, str) or not bpmn.strip():
            return Score(value=0.0, explanation=f"empty BPMN at {path}")

        request = (state.input_text or "").strip() or "(not available)"
        prompt = PROMPT.format(user_request=request, bpmn=bpmn)

        response = await get_model(judge_model).generate(
            prompt,
            config=GenerateConfig(temperature=0.0, max_tokens=max_tokens),
        )
        text = (response.completion or "").strip()

        match = _SCORE_RE.search(text)
        if not match:
            return Score(
                value=0.0,
                explanation=f"judge did not emit SCORE: line; raw: {text[:300]}",
                metadata={"judge_raw": text, "bpmn_path": path},
            )

        raw = max(0, min(10, int(match.group(1))))
        return Score(
            value=raw / 10,
            explanation=f"{raw}/10\n{text[:600]}",
            metadata={
                "judge_model": judge_model,
                "bpmn_path": path,
                "judge_raw": text,
                "raw_score": raw,
            },
        )

    return score
