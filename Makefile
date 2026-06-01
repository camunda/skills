# Camunda skills — local + CI command surface.
#
# Constraints: POSIX-compatible (BSD make on macOS, GNU make on Linux/CI).
# - tabs for recipe indentation
# - no `:=`, no `$(shell ...)`, no GNU-only `.PHONY` grouping
# - SKILL ?= is empty by default; `make <target> SKILL=<name>` filters to one skill

SKILL ?=
SCENARIO ?=
# Comparison arm. Always passed as `-T arm=$(ARM)` so the value shows up
# in Inspect's TASK ARGS column for every run (not just non-default ones).
# Override on the command line for the baseline arm:
#   make eval SCENARIO=rocket-launch ARM=without_skill
ARM ?= with_skill
# Model + agent loop, passed to every `inspect eval`. The suite is
# model-agnostic; MODEL is just the default and uses the Anthropic API
# (export ANTHROPIC_API_KEY). Override per run for another provider,
# e.g. MODEL=anthropic/bedrock/<profile> (then supply that provider's creds), or
# AGENT=claude_code. CI defaults to its own model via the EVAL_MODEL
# repo variable — see .github/workflows/eval.yml.
MODEL ?= anthropic/claude-sonnet-4-6
AGENT ?= react
# Arbitrary extra flags forwarded to `inspect eval`.
# Example: make eval SCENARIO=c8ctl-bootstrap ARGS="--epochs 3"
ARGS ?=

REPO_ROOT = $(CURDIR)
EVALS_DIR = $(REPO_ROOT)/evals

.PHONY: help
help:
	@echo "Usage: make <target> [SKILL=<name>]"
	@echo ""
	@echo "Targets:"
	@echo "  help            Show this help."
	@echo "  try             Launch an interactive Claude Code session with this repo's skills loaded (no install)."
	@echo "  lint            Run waza check across all skills (or one if SKILL=<name> is set)."
	@echo "  eval-trigger    Run one skill's trigger eval (SKILL=<name> required)."
	@echo "  eval-triggers   Run every skill's trigger eval."
	@echo "  eval-result     Run one skill's result eval (SKILL=<name> required, skills/<name>/task.py)."
	@echo "  eval            Run one scenario eval (SCENARIO=<id> required, e.g. rocket-launch)."
	@echo "  eval-all        Run all scenario + per-skill result evals."
	@echo "  eval-baseline   Regenerate baseline.json for one target (TARGET=<skill-or-scenario> required)."
	@echo "  eval-extract    Extract agent artifacts from the most recent eval log to logs/artifacts/."
	@echo "  eval-viewer     Open the Inspect trajectory viewer over evals/logs (web UI)."
	@echo "  eval-images     Build the sandbox Docker images (base, with-c8ctl, verifier)."
	@echo ""
	@echo "Variables:"
	@echo "  SKILL     Skill name (e.g. camunda-feel). For eval-trigger / eval-result."
	@echo "  SCENARIO  Eval scenario id (e.g. rocket-launch)."
	@echo "  TARGET    Skill or scenario dir name, for eval-baseline."
	@echo "  ARM       Comparison arm: with_skill (default) or without_skill."
	@echo "  MODEL     Inspect model id (default anthropic/claude-sonnet-4-6; needs ANTHROPIC_API_KEY)."
	@echo "  AGENT     Agent loop: react (default) or claude_code."
	@echo "  ARGS      Extra flags forwarded to 'inspect eval' (eval / eval-all targets)."
	@echo "            Example: ARGS=\"--epochs 3\""
	@echo ""
	@echo "Notes:"
	@echo "  eval / eval-all default to --max-samples 1 (sequential)."
	@echo "  Concurrent Camunda 8.9 JVMs starve each other on a laptop;"
	@echo "  override via ARGS=\"--max-samples 3\" if you've got the headroom."

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

.PHONY: eval-images
eval-images:
	@command -v docker >/dev/null 2>&1 || { echo "docker not found on PATH."; exit 2; }
	@cd $(EVALS_DIR)/sandboxes && \
		docker build -t camunda-skills-evals-base:latest -f base.Dockerfile . && \
		docker build -t camunda-skills-evals-with-c8ctl:latest -f with-c8ctl.Dockerfile .
	@# Verifier image builds from the evals/ root so its Dockerfile can
	@# bind-mount scenarios/*/cpt-verifier/pom.xml during build to
	@# pre-warm Maven (see verifier.Dockerfile).
	@cd $(EVALS_DIR) && \
		docker build -t camunda-skills-evals-verifier:latest -f sandboxes/verifier.Dockerfile .

.PHONY: eval-trigger
eval-trigger:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@if [ -z "$(SKILL)" ]; then echo "SKILL=<name> required (e.g. SKILL=camunda-feel)"; exit 2; fi
	@cd $(EVALS_DIR) && uv run inspect eval skills/_triggers.py@trigger --log-dir logs/ --max-samples 1 --model $(MODEL) -T skill=$(SKILL) -T agent=$(AGENT) $(ARGS)

.PHONY: eval-triggers
eval-triggers:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@cd $(EVALS_DIR) && for d in skills/*/triggers.yaml; do \
		s=$$(basename $$(dirname $$d)); \
		echo "=== trigger: $$s ==="; \
		uv run inspect eval skills/_triggers.py@trigger --log-dir logs/ --max-samples 1 --model $(MODEL) -T skill=$$s -T agent=$(AGENT) $(ARGS) || exit $$?; \
	done

.PHONY: eval-result
eval-result:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@if [ -z "$(SKILL)" ]; then echo "SKILL=<name> required (e.g. SKILL=camunda-feel)"; exit 2; fi
	@if [ ! -f "$(EVALS_DIR)/skills/$(SKILL)/task.py" ]; then echo "no result eval: skills/$(SKILL)/task.py"; exit 2; fi
	@cd $(EVALS_DIR) && uv run inspect eval skills/$(SKILL)/task.py --log-dir logs/ --max-samples 1 --model $(MODEL) -T arm=$(ARM) -T agent=$(AGENT) $(ARGS) \
		&& uv run evals-extract-artifacts

.PHONY: eval
eval:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@if [ -z "$(SCENARIO)" ]; then echo "SCENARIO=<id> required (e.g. SCENARIO=rocket-launch)"; exit 2; fi
	@if [ ! -d "$(EVALS_DIR)/scenarios/$(SCENARIO)" ]; then echo "scenario not found: $(SCENARIO)"; exit 2; fi
	@# cd into evals/ and pass a path relative to it — Inspect's task
	@# loader rejects absolute glob patterns. uv walks up to the root
	@# pyproject; logs/ resolves to evals/logs (where the scripts read).
	@cd $(EVALS_DIR) && uv run inspect eval scenarios/$(SCENARIO)/task.py --log-dir logs/ --max-samples 1 --model $(MODEL) -T arm=$(ARM) -T agent=$(AGENT) $(ARGS) \
		&& uv run evals-extract-artifacts

.PHONY: eval-all
eval-all:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@cd $(EVALS_DIR) && for s in scenarios/*/task.py skills/*/task.py; do \
		echo "=== $$s ==="; \
		uv run inspect eval "$$s" --log-dir logs/ --max-samples 1 --model $(MODEL) -T arm=$(ARM) -T agent=$(AGENT) $(ARGS) || exit $$?; \
		uv run evals-extract-artifacts || exit $$?; \
	done

.PHONY: eval-extract
eval-extract:
	@uv run evals-extract-artifacts

.PHONY: eval-viewer
eval-viewer:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@uv run inspect view --log-dir $(EVALS_DIR)/logs

.PHONY: eval-baseline
eval-baseline:
	@if [ -z "$(TARGET)" ]; then echo "TARGET=<skill-or-scenario> required (e.g. TARGET=camunda-feel)"; exit 2; fi
	@uv run evals-regen-baseline --target $(TARGET)
