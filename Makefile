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

SKILL_CREATOR_DIR = tools/external/anthropics-skills
SKILL_CREATOR_SHA_FILE = tools/eval-runner/.skill-creator-sha
SKILL_CREATOR_REPO = https://github.com/anthropics/skills.git

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
	@echo "  try             Launch an interactive Claude Code session with this repo's skills loaded (no install)."
	@echo "  lint            Tier-0 structural + schema checks."
	@echo "  eval            Trigger + quality evals (writes evals/<skill>/iteration-N/)."
	@echo "  eval-triggers   Tier-1 trigger eval only."
	@echo "  eval-quality    Tier-2 quality eval only."
	@echo "  eval-dry        Scaffold an iteration without calling any model."
	@echo "  compare         Diff latest iteration against committed baseline."
	@echo "  promote         Snapshot iteration into skills/<skill>/evals/baseline.json."
	@echo "  test            Unit tests for tools/."
	@echo "  setup-skill-creator   Clone anthropics/skills@<pinned SHA> for run_eval.py + grader.md."
	@echo "  verify-skill-creator  Confirm the pinned upstream is checked out and reachable."
	@echo ""
	@echo "Reports are emitted as self-contained HTML next to each iteration:"
	@echo "  evals/<skill>/iteration-N/report.html  (open with file://)"
	@echo "  evals/<skill>/index.html               (cross-iteration index)"
	@echo ""
	@echo "Variables:"
	@echo "  SKILL      Skill name (e.g. camunda-feel). Empty = all where applicable."
	@echo "  RUNS       Trials per case (default 3)."
	@echo "  ITERATION  Iteration dir name (default: latest)."

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
	$(UV) --with pytest --with pytest-asyncio --project tools/eval-runner pytest tools/eval-runner/tests -q

# Clone or refresh the anthropics/skills repo at the SHA pinned in
# tools/eval-runner/.skill-creator-sha. Idempotent: re-running checks out the
# current pin in an existing clone instead of recloning.
.PHONY: setup-skill-creator
setup-skill-creator:
	@SHA=$$(cat $(SKILL_CREATOR_SHA_FILE) | tr -d '[:space:]'); \
	if [ -z "$$SHA" ]; then \
		echo "error: $(SKILL_CREATOR_SHA_FILE) is empty"; exit 2; \
	fi; \
	if [ ! -d $(SKILL_CREATOR_DIR)/.git ]; then \
		mkdir -p $(SKILL_CREATOR_DIR); \
		git clone --filter=blob:none $(SKILL_CREATOR_REPO) $(SKILL_CREATOR_DIR); \
	else \
		git -C $(SKILL_CREATOR_DIR) fetch origin --quiet; \
	fi; \
	git -C $(SKILL_CREATOR_DIR) checkout --quiet $$SHA; \
	echo "anthropics/skills checked out at $$SHA"

.PHONY: verify-skill-creator
verify-skill-creator:
	@PINNED=$$(cat $(SKILL_CREATOR_SHA_FILE) | tr -d '[:space:]'); \
	if [ ! -d $(SKILL_CREATOR_DIR)/.git ]; then \
		echo "error: $(SKILL_CREATOR_DIR) not present. Run: make setup-skill-creator"; exit 2; \
	fi; \
	HEAD=$$(git -C $(SKILL_CREATOR_DIR) rev-parse HEAD); \
	if [ "$$HEAD" != "$$PINNED" ]; then \
		echo "error: $(SKILL_CREATOR_DIR) is at $$HEAD, pinned to $$PINNED. Run: make setup-skill-creator"; exit 2; \
	fi; \
	test -f $(SKILL_CREATOR_DIR)/skills/skill-creator/scripts/run_eval.py || \
		(echo "error: run_eval.py missing from upstream clone"; exit 2); \
	test -f $(SKILL_CREATOR_DIR)/skills/skill-creator/agents/grader.md || \
		(echo "error: agents/grader.md missing from upstream clone"; exit 2); \
	echo "ok: $(SKILL_CREATOR_DIR) at pinned $$PINNED"
