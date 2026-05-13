#!/usr/bin/env bash
# Deterministic verifier: extracts the last fenced code block from the
# agent's response (on stdin), evaluates it with `c8ctl feel evaluate`,
# and compares the result against the expected output.
#
# Usage (from a task's `program` grader):
#   args:
#     - evals/camunda-feel/graders/feel-evaluate.sh
#     - '{"events":[…]}'                   # variable context as JSON
#     - "100"                              # expected output
#
# Exit 0 on match, 1 otherwise.
set -euo pipefail

context_json="$1"
expected="$2"

# Pull the last fenced code block from the agent's response. Allows
# any language hint (```feel, ```xml, plain ```), keeps multi-line
# expressions intact.
expr=$(awk '
  /^[[:space:]]*```/ {
    if (in_block) { last = current; current = ""; in_block = 0 }
    else { in_block = 1 }
    next
  }
  in_block { current = current $0 "\n" }
  END {
    if (in_block && current) last = current
    printf "%s", last
  }
')

# Strip trailing newlines.
expr="${expr%$'\n'}"

if [ -z "$expr" ]; then
  echo "FAIL: no fenced code block found in agent response"
  exit 1
fi

# Strip a leading `=` (FEEL-in-BPMN syntax). c8ctl feel evaluate
# accepts both forms, but normalising avoids ambiguous error messages.
expr="${expr#=}"

actual=$(c8ctl feel evaluate "$expr" --vars "$context_json")

if [ "$actual" = "$expected" ]; then
  echo "PASS: $expr -> $actual"
  exit 0
fi

echo "FAIL: $expr -> $actual (expected $expected)"
exit 1
