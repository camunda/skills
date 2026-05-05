"""Thin async adapter around `claude_agent_sdk.query()`.

Two entry points:

  ``run_arm``    — runs the agent for one (case × arm × trial). Captures all
                   ToolUseBlock events and the final ResultMessage; returns a
                   structured ArmResult the orchestrator persists.

  ``run_grader`` — runs the SHA-pinned ``agents/grader.md`` prompt against a
                   trial's transcript + outputs and parses the resulting
                   grading.json.

The SDK is used here because both flows benefit from typed tool-use events
(skill-load detection in the arm; Read/Write access for the grader). Plain
``anthropic.messages.create`` is insufficient for the grader because the
grader prompt is designed as a tool-using agent (it reads transcript files
and writes grading.json). Both flows ultimately shell out to the same
``claude -p`` headless CLI under the hood, just with different option sets.

Environment override: when the harness is running as root (CI containers
typically are), the underlying ``claude -p`` refuses ``--dangerously-skip-
permissions`` unless ``IS_SANDBOX=1`` is in the env. We always set it for
both arm and grader runs since the harness is, by construction, sandboxed.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

_HARNESS_ENV: dict[str, str] = {"IS_SANDBOX": "1"}


# --- Result shapes ----------------------------------------------------------


@dataclass
class ArmResult:
    arm: str  # "with_skill" | "without_skill"
    case_id: str
    trial: int
    duration_ms: int
    cost_usd: float | None
    total_tokens: int | None
    num_turns: int | None
    is_error: bool
    stop_reason: str | None
    tool_uses: list[dict[str, Any]] = field(default_factory=list)
    skill_loads_via_tool: list[str] = field(default_factory=list)
    skill_loads_via_read: list[str] = field(default_factory=list)
    transcript_path: Path | None = None  # JSONL of all messages
    outputs_dir: Path | None = None
    raw_text: str = ""  # concatenated assistant text blocks (for grader convenience)

    def to_timing_json(self) -> dict[str, Any]:
        return {
            "duration_ms": self.duration_ms,
            "total_duration_seconds": round(self.duration_ms / 1000.0, 2),
            "total_tokens": self.total_tokens or 0,
            "num_turns": self.num_turns,
            "cost_usd": self.cost_usd,
        }


# --- Skill-load detection ---------------------------------------------------


def _skill_name_from_read_path(path: str) -> str | None:
    """Best-effort: extract the skill directory name from a SKILL.md read.

    Matches both our repo layout (``skills/<name>/SKILL.md``) and the canonical
    Claude Code layout (``.claude/skills/<name>/SKILL.md``). Returns None for
    paths that don't look like a skill.
    """
    if "SKILL.md" not in path:
        return None
    parts = Path(path).parts
    try:
        idx = parts.index("SKILL.md")
    except ValueError:
        return None
    if idx == 0:
        return None
    return parts[idx - 1]


def _record_tool_use(blocks_acc: list[dict[str, Any]], block: ToolUseBlock) -> None:
    blocks_acc.append({"name": block.name, "input": block.input, "id": block.id})


# --- Skills bridging --------------------------------------------------------


def ensure_skills_bridged(repo_root: Path) -> None:
    """Symlink ``<repo>/.claude/skills/<name>`` → ``../../skills/<name>`` once.

    Idempotent. Required because Claude Code's skill discovery looks under
    ``.claude/skills/`` while this repo's source-of-truth is ``skills/``. The
    symlinks bridge the two without changing the on-disk layout.

    For arm filtering (``without_skill`` case), pass a ``skills=[...]`` list to
    ``ClaudeAgentOptions`` rather than removing the symlink — the symlink is a
    discovery affordance, not a sandbox.
    """
    skills_src = repo_root / "skills"
    bridge_root = repo_root / ".claude" / "skills"
    if not skills_src.is_dir():
        raise FileNotFoundError(f"no skills source dir at {skills_src}")
    bridge_root.mkdir(parents=True, exist_ok=True)
    for skill_dir in sorted(p for p in skills_src.iterdir() if p.is_dir()):
        link = bridge_root / skill_dir.name
        target = Path("../..") / "skills" / skill_dir.name
        if link.is_symlink() or link.exists():
            try:
                if link.resolve() == skill_dir.resolve():
                    continue
            except OSError:
                pass
            link.unlink()
        link.symlink_to(target)


def all_skill_names(repo_root: Path) -> list[str]:
    return sorted(
        p.name for p in (repo_root / "skills").iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    )


# --- Arm execution ----------------------------------------------------------


async def run_arm(
    *,
    repo_root: Path,
    prompt: str,
    target_skill: str,
    arm: str,
    case_id: str,
    trial: int,
    outputs_dir: Path,
    transcript_path: Path,
    model: str | None = None,
    max_turns: int = 30,
    max_budget_usd: float | None = 1.0,
) -> ArmResult:
    """Run one (case × arm × trial) and persist the transcript.

    ``arm`` is "with_skill" (target available) or "without_skill" (target
    suppressed; siblings still available). Outputs the agent writes go under
    ``outputs_dir``; the JSONL transcript is appended to ``transcript_path``.
    """
    if arm not in ("with_skill", "without_skill"):
        raise ValueError(f"arm must be 'with_skill' or 'without_skill', got {arm!r}")

    ensure_skills_bridged(repo_root)
    available = all_skill_names(repo_root)
    if arm == "without_skill":
        available = [s for s in available if s != target_skill]

    outputs_dir.mkdir(parents=True, exist_ok=True)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    options = ClaudeAgentOptions(
        cwd=str(repo_root),
        add_dirs=[str(outputs_dir)],
        skills=available,
        setting_sources=["project"],
        permission_mode="bypassPermissions",
        env=_HARNESS_ENV,
        model=model,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
    )

    blocks: list[dict[str, Any]] = []
    via_skill: list[str] = []
    via_read: list[str] = []
    raw_text_parts: list[str] = []
    result_msg: ResultMessage | None = None

    started = time.monotonic()
    with transcript_path.open("w", encoding="utf-8") as transcript_fh:
        async for msg in query(prompt=prompt, options=options):
            transcript_fh.write(_serialize_message(msg) + "\n")
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, ToolUseBlock):
                        _record_tool_use(blocks, b)
                        if b.name == "Skill":
                            s = b.input.get("skill") if isinstance(b.input, dict) else None
                            if s:
                                via_skill.append(s)
                        elif b.name == "Read":
                            fp = (
                                b.input.get("file_path", "")
                                if isinstance(b.input, dict) else ""
                            )
                            name = _skill_name_from_read_path(fp)
                            if name:
                                via_read.append(name)
                    elif isinstance(b, TextBlock):
                        raw_text_parts.append(b.text)
            elif isinstance(msg, ResultMessage):
                result_msg = msg
    elapsed_ms = int((time.monotonic() - started) * 1000)

    return ArmResult(
        arm=arm,
        case_id=case_id,
        trial=trial,
        duration_ms=result_msg.duration_ms if result_msg else elapsed_ms,
        cost_usd=result_msg.total_cost_usd if result_msg else None,
        total_tokens=_total_tokens(result_msg),
        num_turns=result_msg.num_turns if result_msg else None,
        is_error=bool(result_msg and result_msg.is_error),
        stop_reason=result_msg.stop_reason if result_msg else None,
        tool_uses=blocks,
        skill_loads_via_tool=via_skill,
        skill_loads_via_read=via_read,
        transcript_path=transcript_path,
        outputs_dir=outputs_dir,
        raw_text="\n".join(raw_text_parts),
    )


def _total_tokens(rm: ResultMessage | None) -> int | None:
    if rm is None or rm.usage is None:
        return None
    u = rm.usage
    if not isinstance(u, dict):
        return None
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
            "cache_read_input_tokens")
    total = 0
    found = False
    for k in keys:
        v = u.get(k)
        if isinstance(v, int):
            total += v
            found = True
    return total if found else None


# --- Grader -----------------------------------------------------------------


def _grader_md_path(repo_root: Path) -> Path:
    return (
        repo_root / "tools" / "external" / "anthropics-skills"
        / "skills" / "skill-creator" / "agents" / "grader.md"
    )


def load_grader_prompt(repo_root: Path) -> str:
    p = _grader_md_path(repo_root)
    if not p.is_file():
        raise FileNotFoundError(
            f"grader.md not found at {p}. Run `make setup-skill-creator`."
        )
    return p.read_text(encoding="utf-8")


async def run_grader(
    *,
    repo_root: Path,
    expectations: list[str],
    transcript_path: Path,
    outputs_dir: Path,
    case_dir: Path,
    judge_model: str = "claude-sonnet-4-6",
    max_turns: int = 12,
    max_budget_usd: float | None = 0.5,
) -> dict[str, Any]:
    """Run the SHA-pinned grader prompt and return the parsed grading.json.

    Side effect: the grader writes ``case_dir/grading.json`` per its own
    prompt instructions. We re-read and parse it to return.
    """
    grader_prompt = load_grader_prompt(repo_root)
    user_msg = json.dumps(
        {
            "expectations": expectations,
            "transcript_path": str(transcript_path),
            "outputs_dir": str(outputs_dir),
        },
        indent=2,
    )

    options = ClaudeAgentOptions(
        cwd=str(repo_root),
        add_dirs=[str(case_dir)],
        system_prompt=grader_prompt,
        # Grader needs Read (to inspect transcript + outputs) and Write
        # (to emit grading.json). No Bash, no Skill, no other tools.
        tools=["Read", "Write"],
        allowed_tools=["Read", "Write"],
        setting_sources=[],  # isolation: grader gets ONLY the prompt above
        permission_mode="bypassPermissions",
        env=_HARNESS_ENV,
        model=judge_model,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
    )

    async for msg in query(prompt=user_msg, options=options):
        # We don't need to inspect events here; the grader writes the file
        # itself. But we still iterate to drain the stream.
        if isinstance(msg, ResultMessage) and msg.is_error:
            raise RuntimeError(
                f"grader run errored: stop_reason={msg.stop_reason} "
                f"errors={msg.errors}"
            )

    grading_path = case_dir / "grading.json"
    if not grading_path.is_file():
        raise RuntimeError(
            f"grader did not produce {grading_path}. Inspect the case dir."
        )
    return json.loads(grading_path.read_text(encoding="utf-8"))


# --- Helpers ----------------------------------------------------------------


def _serialize_message(msg: Any) -> str:
    """Serialize an SDK message to a single-line JSON record for the transcript."""
    if isinstance(msg, AssistantMessage):
        return json.dumps({
            "type": "assistant",
            "content": [_block_to_dict(b) for b in msg.content],
        })
    if isinstance(msg, UserMessage):
        return json.dumps({
            "type": "user",
            "content": (
                [_block_to_dict(b) for b in msg.content]
                if isinstance(msg.content, list) else msg.content
            ),
        })
    if isinstance(msg, SystemMessage):
        return json.dumps({"type": "system", "subtype": getattr(msg, "subtype", None)})
    if isinstance(msg, ResultMessage):
        return json.dumps({
            "type": "result",
            "subtype": msg.subtype,
            "is_error": msg.is_error,
            "duration_ms": msg.duration_ms,
            "num_turns": msg.num_turns,
            "stop_reason": msg.stop_reason,
            "total_cost_usd": msg.total_cost_usd,
            "usage": msg.usage,
        })
    return json.dumps({"type": "unknown", "repr": repr(msg)})


def _block_to_dict(b: Any) -> dict[str, Any]:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if isinstance(b, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": b.tool_use_id,
            "content": b.content,
            "is_error": getattr(b, "is_error", False),
        }
    return {"type": "unknown", "repr": repr(b)}
