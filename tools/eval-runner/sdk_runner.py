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

import contextlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
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
    leaks: dict[str, Any] = field(default_factory=dict)

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


@contextlib.contextmanager
def isolated_workdir(repo_root: Path, allowed_skills: list[str]) -> Iterator[Path]:
    """Yield a temp dir that the agent runs in.

    Bridges:
      - ``<temp>/.claude/skills/<name>`` -> ``<repo>/skills/<name>`` for
        every name in ``allowed_skills`` so Claude Code's project setting
        source discovers them.
      - ``<temp>/examples`` -> ``<repo>/examples`` (read-only — symlink
        target is the repo's source-of-truth) so eval prompts that
        reference relative paths like ``examples/invoice-approval.bpmn``
        resolve correctly. Agents are expected to copy files INTO
        ``outputs/`` before editing; if an agent overwrites a symlinked
        file in place it would be writing into the symlink target — but
        the harness ``isolated_workdir`` runs as the same uid as the
        repo, so this is bounded by what the calling user can already
        change. Live runs we've observed always copy first.

    Writes the agent makes (even with absolute paths under
    ``bypassPermissions``) land in /tmp rather than the repo tree. The
    caller copies anything interesting from ``<temp>/outputs/`` back
    into the per-trial directory before the temp dir is cleaned up.

    Why this is needed: with ``permission_mode="bypassPermissions"`` the
    agent can ignore add_dirs and write absolute paths anywhere on the
    filesystem. Setting cwd to a temp dir under /tmp confines the blast
    radius for stray writes; an over-eager agent that does ``Write
    /home/user/skills/outputs/answer.feel`` cannot reach committed source.
    """
    with tempfile.TemporaryDirectory(prefix="eval-trial-") as tmp:
        tmp_path = Path(tmp)
        bridge = tmp_path / ".claude" / "skills"
        bridge.mkdir(parents=True)
        for name in allowed_skills:
            src = repo_root / "skills" / name
            if src.is_dir():
                (bridge / name).symlink_to(src.resolve())
        examples = repo_root / "examples"
        if examples.is_dir():
            (tmp_path / "examples").symlink_to(examples.resolve())
        (tmp_path / "outputs").mkdir()
        yield tmp_path


def _copy_outputs(src: Path, dst: Path) -> None:
    """Copy any files the agent wrote into the temp workdir back to the trial dir."""
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.is_dir():
            shutil.copytree(entry, dst / entry.name, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, dst / entry.name)


# --- Leak detection --------------------------------------------------------
#
# With ``permission_mode="bypassPermissions"`` the agent can ignore add_dirs
# and write to absolute paths anywhere on the filesystem. ``isolated_workdir``
# bounds the *intended* sandbox to /tmp, but an over-eager agent can still
# do ``Write /root/outputs/answer.feel`` or similar. We've observed this in
# practice on a single rehearsal trial.
#
# The runner can't prevent that without a heavier sandbox (bubblewrap,
# user namespaces, container per trial). It CAN scan a small set of
# common leak destinations after each run and report what it finds, so
# the leak doesn't escape attention.

_LEAK_SCAN_PATHS: tuple[Path, ...] = ()


def _default_leak_scan_paths() -> tuple[Path, ...]:
    """Common $HOME-ish places an agent might mistake for cwd."""
    candidates: list[Path] = []
    home = os.environ.get("HOME")
    if home:
        candidates.append(Path(home) / "outputs")
    # Common alternates that show up if the agent reads /etc/passwd or
    # similar to "find" a working dir.
    for p in ("/root/outputs", "/home/user/outputs", "/tmp/outputs"):
        candidates.append(Path(p))
    # De-dupe while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in candidates:
        rc = c.resolve(strict=False)
        if rc not in seen:
            seen.add(rc)
            unique.append(c)
    return tuple(unique)


@dataclass
class LeakReport:
    """Files an agent wrote outside the intended /tmp sandbox.

    ``paths`` lists the directories that were already populated when the
    runner snapshotted state (typically because some prior trial — or
    this trial via absolute path — wrote there).

    ``new_paths`` lists the directories that the just-finished trial
    created or added files to (i.e. populated AFTER the snapshot was
    taken). Those are the ones to investigate first.
    """

    paths: list[Path] = field(default_factory=list)
    new_paths: list[Path] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.paths and not self.new_paths

    def to_dict(self) -> dict[str, Any]:
        return {
            "paths": [str(p) for p in self.paths],
            "new_paths": [str(p) for p in self.new_paths],
        }


def snapshot_leak_state(
    paths: tuple[Path, ...] | None = None,
) -> dict[Path, set[str]]:
    """Record which leak-scan dirs already exist and what they contain.

    Call once before a trial; pass the result to ``check_leaks`` after.
    Returns a mapping from each scanned path to the set of names it
    contained at snapshot time (empty set if the path doesn't exist).
    """
    targets = paths if paths is not None else _default_leak_scan_paths()
    state: dict[Path, set[str]] = {}
    for p in targets:
        try:
            state[p] = {e.name for e in p.iterdir()} if p.is_dir() else set()
        except OSError:
            state[p] = set()
    return state


def check_leaks(
    snapshot: dict[Path, set[str]],
    paths: tuple[Path, ...] | None = None,
) -> LeakReport:
    """Report leak-scan dirs populated since the snapshot.

    A directory is reported as ``new`` if it didn't exist at snapshot
    time but does now, or if its contents grew. Otherwise an existing
    populated directory is just flagged in ``paths`` (likely cruft from
    earlier runs; still worth surfacing).
    """
    targets = paths if paths is not None else tuple(snapshot.keys())
    report = LeakReport()
    for p in targets:
        before = snapshot.get(p, set())
        try:
            current = {e.name for e in p.iterdir()} if p.is_dir() else set()
        except OSError:
            continue
        if not current:
            continue
        new_entries = current - before
        if new_entries:
            report.new_paths.append(p)
        elif current:
            report.paths.append(p)
    return report


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

    available = all_skill_names(repo_root)
    if arm == "without_skill":
        available = [s for s in available if s != target_skill]

    outputs_dir.mkdir(parents=True, exist_ok=True)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    blocks: list[dict[str, Any]] = []
    via_skill: list[str] = []
    via_read: list[str] = []
    raw_text_parts: list[str] = []
    result_msg: ResultMessage | None = None

    started = time.monotonic()
    leak_snapshot = snapshot_leak_state()
    # Run the agent inside a fresh /tmp dir with skills symlinked in. This
    # confines stray writes (the agent may use absolute paths under
    # bypassPermissions) and prevents leaks into the committed repo tree.
    with isolated_workdir(repo_root, available) as workdir:
        options = ClaudeAgentOptions(
            cwd=str(workdir),
            add_dirs=[str(workdir)],
            skills=available,
            setting_sources=["project"],
            permission_mode="bypassPermissions",
            env=_HARNESS_ENV,
            model=model,
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
        )

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

        # Copy any files the agent wrote under workdir/outputs/ back into the
        # trial's persistent outputs/ dir before the temp dir is removed.
        _copy_outputs(workdir / "outputs", outputs_dir)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    # Did the agent leak writes outside the intended /tmp sandbox?
    leak_report = check_leaks(leak_snapshot)

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
        leaks=leak_report.to_dict(),
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
