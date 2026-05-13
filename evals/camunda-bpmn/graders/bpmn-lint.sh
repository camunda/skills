#!/usr/bin/env bash
# Deterministic verifier: lint the agent's BPMN output via
# `c8ctl bpmn lint --quiet`. Exits 0 if the file parses and passes the
# bundled bpmnlint ruleset; non-zero otherwise.
#
# Usage (from a task's `program` grader):
#   args:
#     - evals/camunda-bpmn/graders/bpmn-lint.sh
#     - outputs/process.bpmn               # BPMN file (relative to workspace)

set -euo pipefail

answer_path="${WAZA_WORKSPACE_DIR:?WAZA_WORKSPACE_DIR not set}/$1"

if [ ! -f "$answer_path" ]; then
  echo "FAIL: $1 not found in workspace ($answer_path)"
  exit 1
fi

c8ctl bpmn lint "$answer_path" --quiet
