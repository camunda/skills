# Camunda skills — local + CI command surface.
#
# Constraints: POSIX-compatible (BSD make on macOS, GNU make on Linux/CI).
# - tabs for recipe indentation
# - no `:=`, no `$(shell ...)`, no GNU-only `.PHONY` grouping
# - SKILL ?= is empty by default; `make <target> SKILL=<name>` filters to one skill

SKILL ?=

REPO_ROOT = $(CURDIR)

.PHONY: help
help:
	@echo "Usage: make <target> [SKILL=<name>]"
	@echo ""
	@echo "Targets:"
	@echo "  help    Show this help."
	@echo "  try     Launch an interactive Claude Code session with this repo's skills loaded (no install)."
	@echo "  lint    Run waza check across all skills (or one if SKILL=<name> is set)."
	@echo ""
	@echo "Variables:"
	@echo "  SKILL   Skill name (e.g. camunda-feel). Empty = all where applicable."

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
		for d in skills/*/; do \
			name=$$(basename $$d); \
			echo ""; echo "=== $$name ==="; \
			waza check $$name || exit $$?; \
		done; \
	fi
