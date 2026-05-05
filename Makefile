# Camunda skills — local + CI command surface.
#
# Constraints: POSIX-compatible (BSD make on macOS, GNU make on Linux/CI).
# - tabs for recipe indentation
# - no `:=`, no `$(shell ...)`, no GNU-only `.PHONY` grouping
# - SKILL ?= is empty by default; `make <target> SKILL=foo` filters to one skill

SKILL ?=
RUNS ?= 3
ITERATION ?=

REPO_ROOT = $(CURDIR)

UV = uv run
LINT = $(UV) --project tools/skill-lint tools/skill-lint/check.py
RUNNER = $(UV) --project tools/eval-runner tools/eval-runner/cli.py

SKILL_FLAG_LINT =
ifneq ($(strip $(SKILL)),)
SKILL_FLAG_LINT = --skill $(SKILL)
endif

.PHONY: help
help:
	@echo "Usage: make <target> [SKILL=<name>] [RUNS=<n>] [ITERATION=<dir>]"
	@echo ""
	@echo "Targets:"
	@echo "  help            Show this help."
	@echo "  lint            Tier-0 structural + schema checks."
	@echo "  eval            Trigger + quality evals (writes evals/<skill>/iteration-N/)."
	@echo "  eval-triggers   Tier-1 trigger eval only."
	@echo "  eval-quality    Tier-2 quality eval only."
	@echo "  eval-dry        Scaffold an iteration without calling any model."
	@echo "  compare         Diff latest iteration against committed baseline."
	@echo "  promote         Snapshot iteration into skills/<skill>/evals/baseline.json."
	@echo "  test            Unit tests for tools/."
	@echo ""
	@echo "Reports are emitted as self-contained HTML next to each iteration:"
	@echo "  evals/<skill>/iteration-N/report.html  (open with file://)"
	@echo "  evals/<skill>/index.html               (cross-iteration index)"
	@echo ""
	@echo "Variables:"
	@echo "  SKILL      Skill name (e.g. camunda-feel). Empty = all where applicable."
	@echo "  RUNS       Trials per case (default 3)."
	@echo "  ITERATION  Iteration dir name (default: latest)."

.PHONY: lint
lint:
	$(LINT) $(SKILL_FLAG_LINT)

.PHONY: eval
eval:
	@if [ -z "$(SKILL)" ]; then echo "SKILL=<name> is required for eval"; exit 2; fi
	$(RUNNER) run --skill $(SKILL) --runs $(RUNS)

.PHONY: eval-triggers
eval-triggers:
	@if [ -z "$(SKILL)" ]; then echo "SKILL=<name> is required for eval-triggers"; exit 2; fi
	$(RUNNER) triggers --skill $(SKILL) --runs $(RUNS)

.PHONY: eval-quality
eval-quality:
	@if [ -z "$(SKILL)" ]; then echo "SKILL=<name> is required for eval-quality"; exit 2; fi
	$(RUNNER) quality --skill $(SKILL) --runs $(RUNS)

.PHONY: eval-dry
eval-dry:
	@if [ -z "$(SKILL)" ]; then echo "SKILL=<name> is required for eval-dry"; exit 2; fi
	$(RUNNER) run --skill $(SKILL) --runs $(RUNS) --dry-run

.PHONY: compare
compare:
	@if [ -z "$(SKILL)" ]; then echo "SKILL=<name> is required for compare"; exit 2; fi
	@if [ -z "$(ITERATION)" ]; then \
		$(RUNNER) compare --skill $(SKILL); \
	else \
		$(RUNNER) compare --skill $(SKILL) --iteration $(ITERATION); \
	fi

.PHONY: promote
promote:
	@if [ -z "$(SKILL)" ]; then echo "SKILL=<name> is required for promote"; exit 2; fi
	@if [ -z "$(ITERATION)" ]; then \
		$(RUNNER) promote --skill $(SKILL); \
	else \
		$(RUNNER) promote --skill $(SKILL) --iteration $(ITERATION); \
	fi

.PHONY: test
test:
	$(UV) --with pytest --project tools/eval-runner pytest tools/eval-runner/tests -q
