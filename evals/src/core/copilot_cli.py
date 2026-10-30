"""GitHub Copilot CLI as an eval agent (``-T agent=copilot_cli``).

Runs ``copilot -p`` inside the sample's sandbox, then replays its JSONL event
stream into the Inspect transcript as assistant / tool messages, so the existing
scorers (artifacts in ``/workspace``, ``assert_skill_loaded``) and the
post-hoc ``core.lint_attempts`` work unchanged. Model calls go to GitHub, not
through Inspect: the Copilot model comes from ``COPILOT_MODEL`` and usage
(AI credits, premium requests, tokens) is read from ``--usage-output-file``
into ``state.store["copilot"]``.

Auth is the Actions job token (``permissions: copilot-requests: write``),
read from ``COPILOT_GITHUB_TOKEN`` on the host. It must never reach the eval
log: Inspect's sandbox proxy records ``exec`` env vars and ``write_file``
contents as transcript events, so the Copilot run goes through the unwrapped
sandbox (``as_type``), and ``--secret-env-vars`` strips the token from the
agent's own shell and redacts it from output.
"""

from __future__ import annotations

import json
import os
import shlex
import time
from contextlib import AsyncExitStack
from collections.abc import Iterable, Sequence
from pathlib import Path

import anyio
from inspect_ai.agent import (
    Agent,
    AgentState,
    BridgedToolsSpec,
    agent,
    sandbox_agent_bridge,
)
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ModelOutput
from inspect_ai.tool import ToolCall
from inspect_ai.util import SandboxEnvironment, sandbox, store

TOKEN_ENV = "COPILOT_GITHUB_TOKEN"
MODEL_ENV = "COPILOT_MODEL"
VERSION_ENV = "COPILOT_CLI_VERSION"

SKILLS_ROOT = "/home/agent/.copilot-eval/skills"
EVENTS_FILE = "/tmp/copilot-events.jsonl"
USAGE_FILE = "/tmp/copilot-usage.json"
PROMPT_FILE = "/tmp/copilot-prompt.md"
STDERR_FILE = "/tmp/copilot-stderr.txt"
MCP_CONFIG_FILE = "/tmp/copilot-mcp.json"

# Wall-clock cap for one Copilot run; the task's own time_limit still applies.
RUN_TIMEOUT_S = 3600
# Upper bound on post-run telemetry recovery (runs shielded from cancellation).
COLLECT_TIMEOUT_S = 60


def _skill_files(skill_dirs: Sequence[Path]) -> Iterable[tuple[str, bytes]]:
    for d in skill_dirs:
        for f in sorted(d.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                yield (
                    f"{SKILLS_ROOT}/{d.name}/{f.relative_to(d).as_posix()}",
                    f.read_bytes(),
                )


def _prompt_text(state: AgentState, system_prompt: str) -> str:
    user = "\n\n".join(m.text for m in state.messages if m.role == "user" and m.text)
    return f"{system_prompt.strip()}\n\n{user}".strip() + "\n"


def parse_events(lines: Iterable[str]) -> tuple[list, str, dict]:
    """Copilot ``--output-format json`` lines → (messages, final text, result).

    ``assistant.message`` becomes a ChatMessageAssistant carrying its
    ``toolRequests`` as ToolCalls; ``tool.execution_complete`` becomes the
    matching ChatMessageTool (content = what the model saw). Sub-agent turns
    are included — their tool calls are work the session did. Unparseable
    lines are skipped.
    """
    messages: list = []
    functions: dict[str, str] = {}
    final = ""
    result: dict = {}
    checkpoint: dict = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "assistant.message":
            calls = []
            for req in data.get("toolRequests") or []:
                call_id = req.get("toolCallId") or ""
                name = req.get("name") or ""
                functions[call_id] = name
                args = req.get("arguments")
                calls.append(
                    ToolCall(
                        id=call_id,
                        function=name,
                        arguments=args if isinstance(args, dict) else {"input": args},
                    )
                )
            content = data.get("content") or ""
            messages.append(
                ChatMessageAssistant(
                    content=content,
                    tool_calls=calls or None,
                    model=data.get("model"),
                )
            )
            if content.strip():
                final = content
        elif kind == "tool.execution_complete":
            call_id = data.get("toolCallId") or ""
            res = data.get("result") or {}
            text = res.get("content") or res.get("detailedContent") or ""
            error = data.get("error")
            if not text and isinstance(error, dict):
                text = error.get("message") or ""
            elif not text and error:
                text = str(error)
            messages.append(
                ChatMessageTool(
                    content=text,
                    tool_call_id=call_id,
                    function=functions.get(call_id),
                )
            )
        elif kind == "session.usage_checkpoint":
            checkpoint = data
        elif kind == "result":
            result = dict(event)
    if checkpoint and not result.get("usage_checkpoint"):
        result = {**result, "usage_checkpoint": checkpoint}
    return messages, final, result


def parse_usage(usage: dict, result: dict, requested_model: str) -> dict:
    """Normalise ``--usage-output-file`` JSON (+ the ``result`` event).

    The usage file is written only when the session ends. If it's missing (an
    interrupted run), fall back to the last ``session.usage_checkpoint`` event
    for credits/premium requests and flag the record ``partial``.
    """
    partial = not usage
    if partial:
        cp = result.get("usage_checkpoint") or {}
        usage = {
            "totalNanoAiu": cp.get("totalNanoAiu"),
            "totalPremiumRequestCost": cp.get("totalPremiumRequests"),
        }
    details = usage.get("tokenDetails") or {}

    def tokens(key: str) -> int | None:
        # No tokenDetails (an interrupted run's checkpoint has none): unknown,
        # not zero — a zero would drag the matrix's token medians down.
        if not details:
            return None
        return int((details.get(key) or {}).get("tokenCount") or 0)

    nano = usage.get("totalNanoAiu")
    return {
        "model": usage.get("currentModel") or requested_model,
        "requested_model": requested_model,
        "models_used": sorted((usage.get("modelMetrics") or {}).keys()),
        "ai_credits": None if nano is None else float(nano) / 1e9,
        "premium_requests": usage.get("totalPremiumRequestCost"),
        "tokens": {
            "input": tokens("input"),
            "cache_write": tokens("cache_write"),
            "cache_read": tokens("cache_read"),
            "output": tokens("output"),
        },
        "api_duration_s": (usage.get("totalApiDurationMs") or 0) / 1000,
        "session_duration_s": (
            (result.get("usage") or {}).get("sessionDurationMs") or 0
        )
        / 1000,
        "exit_code": result.get("exitCode"),
        "partial": partial,
    }


def mcp_config(servers) -> dict:
    """Copilot ``--additional-mcp-config`` JSON for Inspect's bridged-tool MCP
    servers (``MCPServerConfigHTTP``: name, type, url, headers)."""
    return {
        "mcpServers": {
            s.name: {
                "type": s.type,
                "url": s.url,
                **({"headers": s.headers} if s.headers else {}),
                "tools": ["*"],
            }
            for s in servers
        }
    }


def _copilot_command(model: str, mcp_config_file: str | None = None) -> str:
    flags = [
        "--model", model,
        "--allow-all",
        "--no-ask-user",
        "--no-custom-instructions",
        "--disable-builtin-mcps",
        "--output-format", "json",
        "--usage-output-file", USAGE_FILE,
        f"--secret-env-vars={TOKEN_ENV}",
        "--log-level", "none",
        *(["--additional-mcp-config", f"@{mcp_config_file}"] if mcp_config_file else []),
    ]  # fmt: skip
    return (
        f'copilot -p "$(cat {PROMPT_FILE})" {shlex.join(flags)} '
        f"> {EVENTS_FILE} 2> {STDERR_FILE}"
    )


async def _ensure_cli(sb: SandboxEnvironment) -> str:
    """Use the image's Copilot CLI (with-c8ctl bakes it in), else install it.

    Installs as the sandbox's default user into its npm prefix (see
    base.Dockerfile) — not as root, which would leave root-owned directories
    in that prefix and break the agent's own ``npm install -g``.
    """
    probe = await sb.exec(["bash", "-lc", "copilot --version"], timeout=60)
    if probe.returncode != 0:
        version = os.environ.get(VERSION_ENV) or "latest"
        install = await sb.exec(
            [
                "npm",
                "install",
                "-g",
                "--no-fund",
                "--no-audit",
                f"@github/copilot@{version}",
            ],
            timeout=600,
        )
        if install.returncode != 0:
            raise RuntimeError(
                f"installing Copilot CLI failed: {install.stderr[-500:]}"
            )
        probe = await sb.exec(["bash", "-lc", "copilot --version"], timeout=60)
    return (probe.stdout or "").strip().splitlines()[0] if probe.stdout else "unknown"


@agent
def copilot_cli(
    skill_dirs: Sequence[Path] = (),
    system_prompt: str = "",
    bridged_tools: Sequence[BridgedToolsSpec] | None = None,
) -> Agent:
    """Run the sample through GitHub Copilot CLI in the default sandbox.

    ``bridged_tools`` exposes host-side Inspect tools to Copilot as MCP
    servers inside the sandbox (Inspect's sandbox agent bridge — the same
    mechanism ``inspect_swe``'s Claude Code agent uses). Copilot's own model
    calls still go to GitHub; the bridge only serves the tools.
    """

    skill_dirs = list(skill_dirs)
    bridged_tools = list(bridged_tools or [])

    async def execute(state: AgentState) -> AgentState:
        model = os.environ.get(MODEL_ENV)
        if not model:
            raise RuntimeError(f"{MODEL_ENV} must name the Copilot model to run")
        token = os.environ.get(TOKEN_ENV)
        if not token:
            raise RuntimeError(f"{TOKEN_ENV} is not set (Actions: github.token)")

        record: dict = {"requested_model": model, "model": model}
        store().set("copilot", record)

        sb = sandbox()
        # Unwrapped sandbox: no transcript events. Keeps the token in `env`
        # out of the eval log, and the skill files out of every sample's log.
        raw = sb.as_type(SandboxEnvironment)
        record["cli_version"] = await _ensure_cli(sb)
        for path, data in _skill_files(skill_dirs):
            await raw.write_file(path, data)
        await sb.write_file(PROMPT_FILE, _prompt_text(state, system_prompt))

        async with AsyncExitStack() as stack:
            mcp_file = None
            if bridged_tools:
                bridge = await stack.enter_async_context(
                    sandbox_agent_bridge(state, bridged_tools=bridged_tools)
                )
                mcp_file = MCP_CONFIG_FILE
                await sb.write_file(
                    mcp_file, json.dumps(mcp_config(bridge.mcp_server_configs))
                )
            run = await _run(raw, state, record, model, token, skill_dirs, mcp_file)

        if run.returncode != 0:
            stderr = (await _read_or_empty(raw, STDERR_FILE))[-500:]
            raise RuntimeError(f"copilot exited {run.returncode}: {stderr}")
        return state

    return execute


async def _run(
    raw: SandboxEnvironment,
    state: AgentState,
    record: dict,
    model: str,
    token: str,
    skill_dirs: list[Path],
    mcp_file: str | None,
):
    started = time.monotonic()
    run = None
    try:
        run = await raw.exec(
            ["bash", "-lc", _copilot_command(model, mcp_file)],
            cwd="/workspace",
            env={
                TOKEN_ENV: token,
                "COPILOT_SKILLS_DIRS": SKILLS_ROOT if skill_dirs else "",
            },
            timeout=RUN_TIMEOUT_S,
        )
    finally:
        # Recover whatever the session left — even when the exec raised or
        # the sample's time limit cancelled it — so credits already spent
        # still reach the matrix. Shielded (bounded) so cancellation can't
        # abort the cleanup; the original exception then propagates.
        record["agent_duration_s"] = time.monotonic() - started
        record["status"] = "completed" if run is not None else "interrupted"
        with anyio.move_on_after(COLLECT_TIMEOUT_S, shield=True):
            await _collect(raw, state, record, model)
    return run


async def _collect(
    raw: SandboxEnvironment, state: AgentState, record: dict, model: str
) -> None:
    """Record usage, then replay events into the transcript, tolerating missing
    or truncated files (an interrupted session writes no usage file).

    Usage and the final output are stored *before* the replay: appending
    messages can raise (e.g. an Inspect message limit), and the credits a
    session spent must survive that.
    """
    messages, final, result = parse_events(
        (await _read_or_empty(raw, EVENTS_FILE)).splitlines()
    )
    try:
        usage = json.loads(await _read_or_empty(raw, USAGE_FILE) or "{}")
    except json.JSONDecodeError:
        usage = {}
    record.update(parse_usage(usage, result, model))
    record["transcript_messages"] = len(messages)
    store().set("copilot", record)
    state.output = ModelOutput.from_content(model=f"copilot/{model}", content=final)
    state.messages.extend(messages)


async def _read_or_empty(sb: SandboxEnvironment, path: str) -> str:
    try:
        return str(await sb.read_file(path))
    except Exception:
        return ""
