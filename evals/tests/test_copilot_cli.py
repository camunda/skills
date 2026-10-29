"""Unit tests for the Copilot CLI agent's event/usage parsing.

Fixtures mirror real ``copilot -p --output-format json`` and
``--usage-output-file`` output (trimmed)."""

from __future__ import annotations

import json

from core.copilot_cli import _copilot_command, parse_events, parse_usage
from core.lint_attempts import lint_attempts
from scorers.transcript import skills_loaded

EVENTS = [
    {"type": "session.mcp_servers_loaded", "data": {}},
    {"type": "user.message", "data": {"content": "go"}},
    {
        "type": "assistant.message",
        "data": {
            "model": "claude-haiku-5.5",
            "content": "",
            "toolRequests": [
                {
                    "toolCallId": "t1",
                    "name": "skill",
                    "arguments": {"skill": "camunda-bpmn"},
                }
            ],
        },
    },
    {
        "type": "tool.execution_complete",
        "data": {
            "toolCallId": "t1",
            "success": True,
            "result": {"content": 'Skill "camunda-bpmn" loaded successfully.'},
        },
    },
    {
        "type": "assistant.message",
        "data": {
            "model": "claude-haiku-5.5",
            "content": "Linting now.",
            "toolRequests": [
                {
                    "toolCallId": "t2",
                    "name": "bash",
                    "arguments": {
                        "command": "c8ctl bpmn lint --json p.bpmn",
                        "description": "lint",
                    },
                }
            ],
        },
    },
    {
        "type": "tool.execution_complete",
        "data": {
            "toolCallId": "t2",
            "success": True,
            "result": {
                "content": '{"errorCount": 0, "warningCount": 0}\n<shellId: 0 completed with exit code 0>'
            },
        },
    },
    {
        "type": "assistant.message",
        "data": {"model": "claude-haiku-5.5", "content": "DONE", "toolRequests": []},
    },
    {
        "type": "result",
        "exitCode": 0,
        "usage": {"premiumRequests": 1, "sessionDurationMs": 6279},
    },
]

USAGE = {
    "totalPremiumRequestCost": 1,
    "totalNanoAiu": 178985700,
    "tokenDetails": {
        "input": {"tokenCount": 6},
        "cache_read": {"tokenCount": 14488},
        "cache_write": {"tokenCount": 14566},
        "output": {"tokenCount": 45},
    },
    "totalApiDurationMs": 3574,
    "modelMetrics": {"claude-haiku-5.5": {}},
    "currentModel": "claude-haiku-5.5",
}


def _lines():
    return [json.dumps(e) for e in EVENTS] + ["not json", ""]


def test_events_become_inspect_messages():
    messages, final, result = parse_events(_lines())
    assert [m.role for m in messages] == [
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert messages[0].tool_calls[0].function == "skill"
    assert messages[1].tool_call_id == "t1" and messages[1].function == "skill"
    assert final == "DONE"
    assert result["exitCode"] == 0


def test_existing_transcript_signals_work_on_copilot_messages():
    messages, _, _ = parse_events(_lines())
    state = type("S", (), {"messages": messages})()
    assert skills_loaded(state, ["camunda-bpmn", "camunda-dmn"]) == {"camunda-bpmn"}
    lint = lint_attempts(messages)
    assert lint.attempts_to_clean == 1 and lint.reached_clean


def test_usage_normalised():
    _, _, result = parse_events(_lines())
    u = parse_usage(USAGE, result, "claude-haiku-5.5")
    assert u["ai_credits"] == 178985700 / 1e9
    assert u["premium_requests"] == 1
    assert u["tokens"] == {
        "input": 6,
        "cache_write": 14566,
        "cache_read": 14488,
        "output": 45,
    }
    assert u["models_used"] == ["claude-haiku-5.5"]
    assert u["session_duration_s"] == 6.279


def test_usage_missing_is_tolerated():
    u = parse_usage({}, {}, "gpt-6.1-sol")
    assert u["model"] == "gpt-6.1-sol" and u["ai_credits"] is None


def test_command_keeps_token_out_of_shell_and_quotes_model():
    cmd = _copilot_command("claude-sonnet-5.5; rm -rf /")
    assert "--secret-env-vars=COPILOT_GITHUB_TOKEN" in cmd
    assert "'claude-sonnet-5.5; rm -rf /'" in cmd
    assert "--no-ask-user" in cmd and "--output-format json" in cmd


def test_interrupted_session_keeps_partial_telemetry(monkeypatch):
    """A timeout mid-run still replays events and records checkpoint credits."""
    import anyio
    import pytest
    from inspect_ai.agent import AgentState
    from inspect_ai.model import ChatMessageUser
    from inspect_ai.util import ExecResult

    import core.copilot_cli as cc

    partial_events = "\n".join(
        [json.dumps(EVENTS[4]), json.dumps(EVENTS[5])]
        + [
            json.dumps(
                {
                    "type": "session.usage_checkpoint",
                    "data": {"totalNanoAiu": 2_500_000_000, "totalPremiumRequests": 1},
                }
            ),
            '{"type": "assistant.mess',  # truncated mid-write
        ]
    )

    class FakeSandbox:
        def as_type(self, _cls):
            return self

        async def exec(self, cmd, **kwargs):
            if "--version" in cmd[-1]:
                return ExecResult(True, 0, "GitHub Copilot CLI 9.9.9.", "")
            raise TimeoutError("sample time limit")

        async def write_file(self, path, data):
            pass

        async def read_file(self, path, text=True):
            if path == cc.EVENTS_FILE:
                return partial_events
            raise FileNotFoundError(path)

    class FakeStore(dict):
        def set(self, key, value):
            self[key] = value

    fake_store = FakeStore()
    monkeypatch.setattr(cc, "sandbox", lambda: FakeSandbox())
    monkeypatch.setattr(cc, "store", lambda: fake_store)
    monkeypatch.setenv(cc.MODEL_ENV, "gpt-6.1-sol")
    monkeypatch.setenv(cc.TOKEN_ENV, "test-token")

    agent = cc.copilot_cli(skill_dirs=[], system_prompt="rules")
    state = AgentState(messages=[ChatMessageUser(content="go")])

    async def run():
        with pytest.raises(TimeoutError):
            await agent(state)

    anyio.run(run)

    record = fake_store["copilot"]
    assert record["status"] == "interrupted" and record["partial"] is True
    assert record["ai_credits"] == 2.5 and record["premium_requests"] == 1
    assert record["agent_duration_s"] >= 0
    # The checkpoint carries no token split: unknown, not zero.
    assert set(record["tokens"].values()) == {None}
    # The lint run before the interruption is in the transcript.
    assert lint_attempts(state.messages).attempts_to_clean == 1


def test_usage_survives_a_failing_transcript_replay(monkeypatch):
    """Seen in CI: replaying a long Gemini session tripped the task's message
    limit mid-collection and lost the usage. Usage is now stored first."""
    import anyio
    import pytest
    from inspect_ai.model import ChatMessageUser
    from inspect_ai.util import ExecResult

    import core.copilot_cli as cc

    class FakeSandbox:
        def as_type(self, _cls):
            return self

        async def exec(self, cmd, **kwargs):
            out = "GitHub Copilot CLI 9.9.9." if "--version" in cmd[-1] else ""
            return ExecResult(True, 0, out, "")

        async def write_file(self, path, data):
            pass

        async def read_file(self, path, text=True):
            if path == cc.EVENTS_FILE:
                return "\n".join(json.dumps(e) for e in EVENTS)
            if path == cc.USAGE_FILE:
                return json.dumps(USAGE)
            raise FileNotFoundError(path)

    class FakeStore(dict):
        def set(self, key, value):
            self[key] = value

    class LimitedMessages(list):
        def extend(self, _items):
            raise RuntimeError("message limit exceeded")

    class State:
        messages = LimitedMessages([ChatMessageUser(content="go")])
        output = None

    fake_store = FakeStore()
    monkeypatch.setattr(cc, "sandbox", lambda: FakeSandbox())
    monkeypatch.setattr(cc, "store", lambda: fake_store)
    monkeypatch.setenv(cc.MODEL_ENV, "gemini-3.8-flash")
    monkeypatch.setenv(cc.TOKEN_ENV, "test-token")
    state = State()

    async def run():
        with pytest.raises(RuntimeError, match="message limit"):
            await cc.copilot_cli(skill_dirs=[], system_prompt="r")(state)

    anyio.run(run)
    record = fake_store["copilot"]
    assert record["ai_credits"] == USAGE["totalNanoAiu"] / 1e9
    assert record["transcript_messages"] == 5
    assert state.output.completion == "DONE"
