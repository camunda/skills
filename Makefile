# Camunda skills — local + CI command surface.
#
# Constraints: POSIX-compatible (BSD make on macOS, GNU make on Linux/CI).
# - tabs for recipe indentation
# - no `:=`, no `$(shell ...)`, no GNU-only `.PHONY` grouping
# - SKILL ?= is empty by default; `make <target> SKILL=<name>` filters to one skill

SKILL ?=
TARGET ?=
# Comparison arm. Always passed as `-T arm=$(ARM)` so the value shows up
# in Inspect's TASK ARGS column for every run (not just non-default ones).
# Override on the command line for the baseline arm:
#   make run-outcome-evals TARGET=scenarios/rocket-launch ARM=without_skill
ARM ?= with_skill
# Model + agent loop, passed to every `inspect eval`. The suite is
# model-agnostic; MODEL is just the default and runs on the Anthropic API
# (set ANTHROPIC_API_KEY in the environment). EVAL_MODEL (env/CI) wins when set;
# override per run for another provider or AGENT=claude_code. CI uses the same
# default via the EVAL_MODEL repo variable — see .github/workflows/eval.yml.
MODEL ?= $(if $(EVAL_MODEL),$(EVAL_MODEL),anthropic/claude-sonnet-4-6)
AGENT ?= react
# Arbitrary extra flags forwarded to `inspect eval`.
# Example: make run-outcome-evals TARGET=scenarios/rocket-launch ARGS="--epochs 3"
ARGS ?=
# Temperature for all eval runs. Default 0 for deterministic, reproducible runs
# that compare cleanly against baselines. Override with TEMPERATURE=1 for
# stochastic exploration.
TEMPERATURE ?= 0
# Trigger evals are sandbox-free model calls, so their samples run fully in
# parallel. Caps concurrent samples per skill; raise it if a skill grows.
TRIGGER_SAMPLES ?= 20

REPO_ROOT = $(CURDIR)
EVALS_DIR = $(REPO_ROOT)/evals

.PHONY: help
help:
	@echo "Usage: make <target> [SKILL=<name>] [TARGET=<dir>]"
	@echo ""
	@echo "General:"
	@echo "  help                 Show this help."
	@echo "  try                  Launch an interactive Claude Code session with this repo's skills loaded (no install)."
	@echo "  lint                 Run waza check across all skills (or one if SKILL=<name> is set)."
	@echo ""
	@echo "Run:"
	@echo "  run-trigger-evals    Run trigger evals: every skill, or one with SKILL=<name>."
	@echo "  run-outcome-evals    Run outcome evals: one with TARGET=<dir> (e.g. skills/camunda-feel), or the whole Docker suite without TARGET."
	@echo "  build-docker-images  Build the sandbox Docker images (base, with-c8ctl, verifier)."
	@echo ""
	@echo "Analyze:"
	@echo "  summarize            Render a Markdown summary of the eval logs in evals/logs."
	@echo "  pass-fail            Check the most recent eval log against the outcome thresholds + token baseline."
	@echo "  view-eval-logs       Open the Inspect trajectory viewer over evals/logs (web UI)."
	@echo "  extract-artifacts    Extract agent artifacts from the most recent eval log to logs/artifacts/."
	@echo "  regenerate-baseline  Regenerate outcomes_baseline.json for one target (TARGET=<dir> required)."
	@echo ""
	@echo "Variables:"
	@echo "  SKILL     Skill name (e.g. camunda-feel). For run-trigger-evals."
	@echo "  TARGET    Outcome eval dir path (skills/<name> or scenarios/<name>), for run-outcome-evals / regenerate-baseline."
	@echo "  ARM       Comparison arm: with_skill (default) or without_skill."
	@echo "  MODEL     Inspect model id (default anthropic/claude-sonnet-4-6; needs ANTHROPIC_API_KEY)."
	@echo "  AGENT       Agent loop: react (default) or claude_code."
	@echo "  TEMPERATURE Temperature for inspect eval (default 0 — deterministic). Override with TEMPERATURE=1 for stochastic runs."
	@echo "  ARGS        Extra flags forwarded to 'inspect eval' (run-trigger-evals / run-outcome-evals)."
	@echo "              Example: ARGS=\"--epochs 3\""
	@echo ""
	@echo "Notes:"
	@echo "  run-outcome-evals runs at each eval's METADATA.max_sandboxes (default 1, sequential)."
	@echo "  Cluster-backed evals stay at 1 — a sandbox is a whole cluster and concurrent"
	@echo "  Camunda JVMs starve each other; override per run via ARGS=\"--max-sandboxes N\"."

.PHONY: try
try:
	@command -v claude >/dev/null 2>&1 || { \
		echo "claude CLI not found on PATH. Install Claude Code first: https://docs.claude.com/en/docs/agents-and-tools/claude-code"; \
		exit 2; \
	}
	@TRYDIR=$$(mktemp -d -t camunda-skills-try-XXXXXX); \
	echo "Launching Claude Code in a fresh dir: $$TRYDIR"; \
	echo "Skills loaded from: $(REPO_ROOT)"; \
	cd "$$TRYDIR" && claude --plugin-dir $(REPO_ROOT)

.PHONY: lint
lint:
	@command -v waza >/dev/null 2>&1 || { \
		echo "waza CLI not found on PATH. Install it from https://github.com/microsoft/waza"; \
		exit 2; \
	}
	@if [ -n "$(SKILL)" ]; then \
		waza check $(SKILL); \
	else \
		waza check; \
	fi

.PHONY: build-docker-images
build-docker-images:
	@command -v docker >/dev/null 2>&1 || { echo "docker not found on PATH."; exit 2; }
	@# All three images build from one definition (sandboxes/docker-bake.hcl);
	@# the with-c8ctl/verifier `FROM base` dependency is wired via bake contexts.
	@# CI reuses the same file and adds layer caching with --set (see eval.yml).
	@cd $(EVALS_DIR) && docker buildx bake -f sandboxes/docker-bake.hcl --load

# Triggers are sandbox-free routing calls. With SKILL=<name> runs that skill's
# trigger; without, runs every skill's (glob expands after cd into evals/).
.PHONY: run-trigger-evals
run-trigger-evals:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@cd $(EVALS_DIR) && \
	if [ -n "$(SKILL)" ]; then \
		t="skills/$(SKILL)/triggers.py"; \
		[ -f "$$t" ] || { echo "no triggers.py for SKILL=$(SKILL)"; exit 2; }; \
	else \
		t="skills/*/triggers.py"; \
	fi; \
	uv run inspect eval $$t --log-dir logs/ --max-samples $(TRIGGER_SAMPLES) --model $(MODEL) --temperature $(TEMPERATURE) $(ARGS)

# Outcome evals run in a Docker sandbox. With TARGET=<dir> runs that one;
# without, runs the whole suite (slow + costly). TARGET is the eval dir path,
# e.g. skills/camunda-feel or scenarios/rocket-launch (a trailing slash from
# shell autocompletion is stripped). Paths are relative to evals/ (Inspect
# rejects absolute globs; uv walks up to the root pyproject).
.PHONY: run-outcome-evals
run-outcome-evals:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@cd $(EVALS_DIR) && \
	if [ -n "$(TARGET)" ]; then \
		d="$(TARGET)"; d="$${d%/}"; \
		[ -f "$$d/outcomes.py" ] || { echo "no outcomes.py at $$d"; exit 2; }; \
		set -- "$$d/outcomes.py"; \
	else \
		set -- scenarios/*/outcomes.py skills/*/outcomes.py; \
	fi; \
	targets=$$(uv run evals-list --json) || exit $$?; \
	for s in "$$@"; do \
		ms=$$(printf '%s' "$$targets" | uv run python -c "import sys,json; print(next((t['max_sandboxes'] for t in json.load(sys.stdin) if t['path']==sys.argv[1]), 1))" "$$s"); \
		echo "=== $$s (max-sandboxes $$ms) ==="; \
		uv run inspect eval "$$s" --log-dir logs/ --max-sandboxes $$ms --model $(MODEL) --temperature $(TEMPERATURE) -T arm=$(ARM) -T agent=$(AGENT) $(ARGS) || exit $$?; \
		uv run evals-extract-artifacts || exit $$?; \
	done

.PHONY: summarize
summarize:
	@cd $(EVALS_DIR) && uv run evals-summarize --log-dir logs/

.PHONY: pass-fail
pass-fail:
	@cd $(EVALS_DIR) && uv run evals-pass-fail

.PHONY: extract-artifacts
extract-artifacts:
	@uv run evals-extract-artifacts

.PHONY: view-eval-logs
view-eval-logs:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@uv run inspect view --log-dir $(EVALS_DIR)/logs

.PHONY: regenerate-baseline
regenerate-baseline:
	@if [ -z "$(TARGET)" ]; then echo "TARGET=<dir> required (e.g. skills/camunda-feel)"; exit 2; fi
	@uv run evals-regenerate-baseline --target $(TARGET)
