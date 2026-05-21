# Skill Testing & Eval Frameworks — Research Summary

**Date:** May 2026
**Context:** Deciding how `camunda/skills` should test its Claude Agent Skills.
**Current state:** Self-made framework in `tools/eval-runner/` (Python, three-tier
model, asymmetric-regression baselines). Considering replacing or stripping it down.

---

## TL;DR

1. **The field is wide open.** Of ~22 substantial community skill repos audited,
   only ~18% have any skill-eval infrastructure. No third-party framework
   (Promptfoo, Waza, Skillgrade, UPskill) shows up in a single leaf skill repo.
2. **Two emerging conventions:** Anthropic's `evals/evals.json` + `agents/grader.md`
   (prescribed by `skill-creator`, adopted by a handful of external repos), and
   PluginEval (heavier, lives inside `wshobson/agents`, no external adopters yet).
3. **For Camunda-skills specifically:** stay close to the Anthropic convention,
   strip the eval-runner down to ~40 lines of bash, **keep the deterministic
   verifier idea** (e.g. `c8ctl feel evaluate` against expected output) — that's
   the genuinely valuable piece, and no public framework does it well.
4. **Waza, even bug-free, is a no.** Copilot-SDK executor lock-in and no obvious
   path for deterministic verifiers.
5. **Promptfoo is community-misaligned.** Strong tool, but zero leaf-repo
   adoption. Revisit only if that changes.

---

## 1. Framework landscape

| Tool | Type | Trigger evals | Quality evals | Local models | Verdict |
|---|---|---|---|---|---|
| [Anthropic `skill-creator`](https://github.com/anthropics/skills/tree/main/skills/skill-creator) | Meta-skill + Python scripts | ✓ 60/40 split, F1, 5-iter loop | ✓ paired with/without + LLM judge | Anthropic API only | **Reference implementation** — vendor pieces |
| [Promptfoo](https://www.promptfoo.dev/docs/providers/claude-agent-sdk/) | YAML CLI, huge OSS community | ⚠ via assertions, no opt loop | ✓ `skill-used`, `llm-rubric`, `trajectory:tool-used` | ✓ any OpenAI-compatible | **Strong tool, no community adoption in skill repos** |
| [Microsoft Waza](https://github.com/microsoft/waza) | Go CLI, YAML | ✓ dedicated trigger grader | ✓ separate `waza quality` | ✗ Copilot-SDK lock-in | **Avoid** — architectural mismatch |
| [Skillgrade](https://github.com/mgechev/skillgrade) | TS/npm CLI, YAML | ⚠ author-it-yourself | ✓ deterministic + llm_rubric | ✗ cloud keys only | Decent 3rd choice |
| [HF UPskill](https://github.com/huggingface/upskill) | Teacher→student distillation | ✗ | ✓ success + token delta | ✓ best in class | **Wrong axis** — generates skills |
| [PluginEval](https://github.com/wshobson/agents/tree/main/plugins/plugin-eval) | 3-layer scoring | ✓ static + scoring | ⚠ partial | n/a | Most rigorous public framework |
| Inspect AI / DeepEval / Langfuse / Braintrust | General LLM eval | ✗ no skill awareness | ✓ generic | mixed | Overkill, no skill awareness |

### Key takeaways
- `skill-creator`'s `evals.json` + `grader.md` shape is the **only thing approaching a community convention**.
- **No tool combines** Claude execution + deterministic verifiers + baseline-aware regression gates. Camunda's home-grown harness is in that gap by accident.
- The "Codex and Gemini CLI read SKILL.md" claim came up but is unverified — would need a focused check before planning multi-runtime support.

---

## 2. What community skill repos actually do

Audited the top 22 repos across four awesome lists
([hesreallyhim](https://github.com/hesreallyhim/awesome-claude-code),
[ComposioHQ](https://github.com/ComposioHQ/awesome-claude-skills),
[travisvn](https://github.com/travisvn/awesome-claude-skills),
[VoltAgent](https://github.com/VoltAgent/awesome-agent-skills)).

| Repo | Stars | Skill evals? | What it uses |
|---|---|---|---|
| [anthropics/skills](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) | 133k | Partial (only `skill-creator`) | `evals/evals.json` + `grader.md` + `eval-viewer` |
| [obra/superpowers](https://github.com/obra/superpowers/tree/main/tests/skill-triggering) | 189k | ✓ trigger-rate only | 50-line bash + `claude -p --output-format stream-json` + grep |
| [wshobson/agents](https://github.com/wshobson/agents/tree/main/plugins/plugin-eval) | 35k | ✓ full 3-layer | PluginEval |
| [conorluddy/ios-simulator-skill](https://github.com/conorluddy/ios-simulator-skill) | 985 | ✓ adopts Anthropic pattern | `evals/evals.json`, reports "100% with skill, 46% without" |
| [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) | small | Partial | Layout mirrors skill-creator |
| trailofbits, expo, angular, veniceai, Pimzino, disler, lackeyjb, Skill_Seekers, … | varies | ✗ none | — |

**Pattern:** ~80% of public skill repos have zero automated quality testing.
The remaining 20% are nearly all in the Anthropic `evals.json` + `grader.md`
shape, by gravity from `skill-creator` being the recommended scaffold.

---

## 3. Waza-specific findings

The current "I'm trying it and it feels buggy" instinct checks out:

- [#227 (Apr 28 2026)](https://github.com/microsoft/waza/issues/227): canonical
  sample eval (`code-explainer`) fails on CI with 0% pass rate on `main`.
- [#223](https://github.com/microsoft/waza/issues/223): `HeuristicScorer` only
  checks frontmatter description for triggers — ignores SKILL.md body.
- Python implementation deprecated mid-stream (`v0.3.2` → Go-only `v0.4.0-alpha.1`).
- **Architectural blocker:** plugin ecosystem is Copilot-SDK-centric; no
  first-class Anthropic/Bedrock executor as of May 2026.

Net: bugginess looks temporary (active commits, structured triage), but the
Anthropic-execution gap is structural and wrong-direction for a Claude-on-Camunda
repo. **Even bug-free, Waza would still be a no** — Copilot lock-in plus no
obvious deterministic-verifier path means it can't replicate the FEEL
"evaluate-the-expression" pattern that gives the current harness most of its value.

---

## 4. Recommendation

**Strip `tools/eval-runner/` down to a 40-line bash runner. Keep the deterministic
verifiers. Stay close to Anthropic's `evals.json` convention.**

### What to keep vs. delete

```
tools/eval-runner/
├── verifiers/feel_evaluate.py    KEEP — irreplaceable, ~30 lines
├── verifiers/bpmn_lint.py        KEEP — same
├── cli.py                        REPLACE with bash + jq
├── sdk_runner.py                 REPLACE with `claude -p`
├── quality_eval.py               DELETE — LLM judge optional
├── trigger_eval.py               REPLACE with obra/superpowers-style bash
├── baseline.py / report.py       DELETE — overkill for 7 skills
└── tests/                        DELETE
```

### The runner becomes a script

```bash
# scripts/run-eval.sh <skill>
set -e
skill=$1
evals="skills/$skill/evals/evals.json"

jq -c '.evals[]' "$evals" | while read eval; do
  id=$(echo "$eval" | jq -r .id)
  prompt=$(echo "$eval" | jq -r .prompt)
  outdir=$(mktemp -d)
  prompt=${prompt//\{\{OUTPUTS_DIR\}\}/$outdir}

  claude -p "$prompt" --output-format text \
    --append-system-prompt "Load the $skill skill." > /dev/null

  echo "$eval" | jq -c '.verifiers[]' | while read v; do
    case $(echo "$v" | jq -r .type) in
      feel-evaluate)
        ctx=$(echo "$v" | jq -c .context)
        expected=$(echo "$v" | jq -c .expected)
        actual=$(c8ctl feel evaluate "$(cat $outdir/answer.feel)" \
                   --vars "$ctx" --output json | jq -c .result)
        [ "$actual" = "$expected" ] || { echo "FAIL $id"; exit 1; } ;;
      bpmn-lint)
        c8ctl bpmn lint "$outdir/process.bpmn" || exit 1 ;;
    esac
  done
done
```

### CI integration

```yaml
# .github/workflows/skill-evals.yml
name: skill-evals
on:
  pull_request:
    paths: ['skills/**', 'scripts/run-eval.sh']
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm install -g @camunda8/cli
      - run: make lint
  eval:
    needs: lint
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        skill: [camunda-feel, camunda-bpmn, camunda-forms]
    steps:
      - uses: actions/checkout@v4
      - run: npm install -g @camunda8/cli @anthropic-ai/claude-code
      - run: c8ctl cluster start &
      - run: ./scripts/run-eval.sh ${{ matrix.skill }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

**Cost control:** `paths:` filter, per-skill matrix with `dorny/paths-filter`,
Haiku via `ANTHROPIC_MODEL=claude-haiku-4-5`, `--max-turns 5`, skip drafts.
A 7-eval FEEL run on Haiku is ~$0.05; on Sonnet ~$0.30. Per-PR + nightly stays
well under $5/month.

### "Hard facts" for FEEL — the mechanism

Already in `evals.json` today:

1. Prompt instructs Claude to write the expression to `{{OUTPUTS_DIR}}/answer.feel`
2. Verifier shells out to `c8ctl feel evaluate` with a JSON context
3. Asserts the result equals an expected literal
4. Multiple verifier entries per eval = parameterized tests

This is strictly better than an LLM judge for FEEL — the FEEL engine is ground
truth; an LLM judge can be confused into approving `first(events).timestamp`
(doesn't exist).

### What's lost vs. saved

| Lose | Save |
|---|---|
| Asymmetric-regression baselines | ~1500 lines of Python |
| HTML iteration reports | SHA-pinned `skill-creator` clone |
| Trigger F1 with train/test split | Custom verifier abstraction |
| `make compare` / `make promote` UX | Tests for the test harness |

The baseline gate can be added back as ~30 lines of bash diff against a
checked-in `baseline.json` if it's ever actually missed.

---

## 5. Distribution / marketplaces

Lower-confidence — earlier research didn't survey this dimension deeply.

| Channel | SKILL.md compatible? | Worth supporting? |
|---|---|---|
| Claude Code (first-party) | ✓ native | Yes — primary |
| [officialskills.sh](https://officialskills.sh) | ✓ aggregates SKILL.md repos | **Yes** — list the repo, effort near zero, biggest cross-vendor catalog |
| OpenAI Codex CLI | Claimed ✓ — unverified | Defer until a user asks |
| Gemini CLI | Claimed ✓ — unverified | Defer until a user asks |
| GitHub Copilot | Different format under the hood | No — same reasoning as Waza |
| Cursor / Continue.dev / Cline | No clear skill format | Unclear |
| ChatGPT Apps / Custom GPTs | ✗ different ecosystem | No |

Shortlist worth committing to: **Claude Code + officialskills.sh listing**.
Multi-runtime support should wait until the SKILL.md compatibility claim is
verified for Codex / Gemini CLI.

---

## 6. Open questions

1. **Verify SKILL.md compatibility** with Codex and Gemini CLI before planning
   multi-runtime evals.
2. **Has the asymmetric-regression gate ever caught a real regression**? If not,
   the case for deleting it strengthens.
3. **Is the cluster requirement for FEEL evals acceptable in CI?** `c8ctl
   cluster start` adds ~30s of warm-up and disk for c8run. Alternative:
   `--engine local` (feelin JS engine) for tests, with the cluster engine reserved
   for production validation.
4. **List the repo on officialskills.sh** — cheap distribution win, no migration
   risk.

---

## Sources

Frameworks:
[Anthropic skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator),
[Promptfoo Claude Agent SDK provider](https://www.promptfoo.dev/docs/providers/claude-agent-sdk/),
[Microsoft Waza](https://github.com/microsoft/waza),
[Skillgrade](https://github.com/mgechev/skillgrade),
[HF UPskill](https://github.com/huggingface/upskill),
[PluginEval](https://github.com/wshobson/agents/tree/main/plugins/plugin-eval).

Awesome lists:
[hesreallyhim](https://github.com/hesreallyhim/awesome-claude-code),
[ComposioHQ](https://github.com/ComposioHQ/awesome-claude-skills),
[travisvn](https://github.com/travisvn/awesome-claude-skills),
[VoltAgent](https://github.com/VoltAgent/awesome-agent-skills),
[officialskills.sh](https://officialskills.sh).

Practitioner posts:
[Mager: Validating and Evaluating Claude Skills (2026-02-23)](https://www.mager.co/blog/2026-02-23-skills-validate-eval/),
[Mager: A Claude Code Eval Loop (2026-03-08)](https://www.mager.co/blog/2026-03-08-claude-code-eval-loop/).

Methodology docs:
[agentskills.io — optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions),
[agentskills.io — evaluating skills](https://agentskills.io/skill-creation/evaluating-skills).
