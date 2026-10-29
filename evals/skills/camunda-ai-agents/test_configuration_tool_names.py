"""The configuration tool is recognised under every harness's name."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_path = Path(__file__).with_name("outcomes.py")
_spec = importlib.util.spec_from_file_location(
    "camunda_ai_agents_outcomes_names", _path
)
_outcomes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_outcomes)


def test_configuration_request_names_per_harness():
    for name in (
        "request_configuration",  # react
        "mcp__configuration__request_configuration",  # Claude Code
        "configuration-request_configuration",  # Copilot CLI
    ):
        assert _outcomes._is_configuration_request(name), name
    assert not _outcomes._is_configuration_request("bash")
    assert not _outcomes._is_configuration_request("request_configuration_x")
