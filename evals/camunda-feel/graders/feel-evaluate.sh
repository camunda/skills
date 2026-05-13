#!/usr/bin/env bash
# Deterministic verifier: shell to `c8ctl feel evaluate` and compare the
# result against the expected value. Reads the agent's FEEL expression
# from a file written into the per-trial workspace, defaults to
# outputs/answer.feel.
#
# Usage (from a task's `program` grader):
#   args:
#     - evals/camunda-feel/graders/feel-evaluate.sh
#     - outputs/answer.feel                # answer file (relative to workspace)
#     - '{"events":[…]}'                   # context as JSON
#     - "100"                              # expected output (stdout match)
#
# Exit 0 on match, 1 otherwise. The agent's text response is on stdin.

set -euo pipefail

answer_path="${WAZA_WORKSPACE_DIR:?WAZA_WORKSPACE_DIR not set}/$1"
context_json="$2"
expected="$3"

if [ ! -f "$answer_path" ]; then
  echo "FAIL: $1 not found in workspace ($answer_path)"
  exit 1
fi

expr=$(< "$answer_path")
actual=$(c8ctl feel evaluate "$expr" --vars "$context_json")

if [ "$actual" = "$expected" ]; then
  echo "PASS: $expr -> $actual"
  exit 0
fi

echo "FAIL: $expr -> $actual (expected $expected)"
exit 1
