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
