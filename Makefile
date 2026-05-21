# Camunda skills — local + CI command surface.
#
# Constraints: POSIX-compatible (BSD make on macOS, GNU make on Linux/CI).
# - tabs for recipe indentation
# - no `:=`, no `$(shell ...)`, no GNU-only `.PHONY` grouping
# - SKILL ?= is empty by default; `make <target> SKILL=<name>` filters to one skill

SKILL ?=
SCENARIO ?=

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
	@echo "  eval            Run one eval scenario (SCENARIO=<id> required, e.g. 01-rocket-launch)."
	@echo "  eval-all        Run all eval scenarios."
	@echo "  eval-baseline   Regenerate baseline.json for one scenario (SCENARIO=<id> required)."
	@echo "  eval-images     Build the sandbox Docker images (base, with-c8ctl, verifier)."
	@echo ""
	@echo "Variables:"
	@echo "  SKILL     Skill name (e.g. camunda-feel). Empty = all where applicable."
	@echo "  SCENARIO  Eval scenario id (e.g. 01-rocket-launch)."

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
		docker build -t camunda-skills-evals-with-c8ctl:latest -f with-c8ctl.Dockerfile . && \
		docker build -t camunda-skills-evals-verifier:latest -f verifier.Dockerfile .

.PHONY: eval
eval:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@if [ -z "$(SCENARIO)" ]; then echo "SCENARIO=<id> required (e.g. SCENARIO=01-rocket-launch)"; exit 2; fi
	@if [ ! -d "$(EVALS_DIR)/scenarios/$(SCENARIO)" ]; then echo "scenario not found: $(SCENARIO)"; exit 2; fi
	@cd $(EVALS_DIR) && uv run inspect eval scenarios/$(SCENARIO)/task.py --log-dir logs/

.PHONY: eval-all
eval-all:
	@command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH. Install: https://docs.astral.sh/uv/"; exit 2; }
	@cd $(EVALS_DIR) && \
		for s in scenarios/*/task.py; do \
			echo "=== $$s ==="; \
			uv run inspect eval "$$s" --log-dir logs/ || exit $$?; \
		done

.PHONY: eval-baseline
eval-baseline:
	@if [ -z "$(SCENARIO)" ]; then echo "SCENARIO=<id> required"; exit 2; fi
	@cd $(EVALS_DIR) && uv run python -m evals.scripts.regen_baseline --scenario $(SCENARIO)
