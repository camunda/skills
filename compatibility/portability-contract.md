# Skills portability contract

This directory is the contract surface for running the skills in this repository
with Claude Code, GitHub Copilot, and other Agent Skills-compatible runtimes.
The contract is intentionally separate from the user documentation, skill
instructions, behavioural evaluations, and CI implementation. Those consumers
must use the names, paths, and semantics defined here instead of defining
parallel compatibility metadata.

## Contract authority and scope

The external format authority is the [Agent Skills specification](https://agentskills.io/specification).
The canonical URL is repeated in the inventory, audit, and portability declarations as
`https://agentskills.io/specification`. The current audit baseline is
`2026-09-11`; it is represented by `specRevisionOrAuditDate` until a named
specification revision is available.

The specification defines the portable skill package and its `SKILL.md`
metadata. This repository policy defines the following additional compatibility
surface:

| Field or behavior | Authority |
| --- | --- |
| `skills/<name>/SKILL.md` package layout, `name`, `description`, and supported frontmatter | Agent Skills specification |
| `skillDirectory`, `skillName`, `status`, `agentSkillsSpec`, `harnesses`, `limitations`, and `differences` in `portability.json` | Repository policy |
| `skills-index.json`, `audit.json`, and their cross-file consistency rules | Repository policy |
| Discovery, activation fixture, result assertions, adapter modes, and live-integration reporting | Repository policy |

Do not add portability fields to `SKILL.md` frontmatter. Portability belongs in
the sidecar described below.

## Ownership boundaries

This wave defines the contract and seed inventories. Later changes must keep
these ownership boundaries:

- `compatibility/portability-contract.md` is the normative human-readable
  contract.
- `compatibility/portability.schema.json` validates each
  `skills/<skill>/portability.json` sidecar.
- `compatibility/skills-index.json` is the complete inventory of skills,
  entrypoints, sidecars, and repository-level statuses.
- `compatibility/audit.json` records the dated audit and the same complete skill
  set.
- `compatibility/harness-smoke-contract.json` defines the adapter boundary and
  assertions.
- `compatibility/fixtures/camunda-bpmn-smoke.json` is the fixed checked-in
  smoke fixture consumed by both deterministic adapters.
- `compatibility/check.py` is the conformance checker and is responsible for
  filesystem and cross-file checks:
  missing skills, duplicate names, stale paths, and mismatched sidecar,
  inventory, and audit values are failures.

The contract does not prescribe where a harness installs a skill or how its
adapter is implemented. It does prescribe the repository-relative discovery
path and the observable smoke result.

## Per-skill portability declaration

Every skill directory must contain `portability.json` at
`skills/<skillName>/portability.json`. It must validate against
`compatibility/portability.schema.json` and contain exactly these top-level
fields:

```json
{
  "$schema": "https://raw.githubusercontent.com/camunda/skills/main/compatibility/portability.schema.json",
  "skillDirectory": "skills/camunda-bpmn",
  "skillName": "camunda-bpmn",
  "status": "portable-with-adapter",
  "agentSkillsSpec": {
    "specUrl": "https://agentskills.io/specification",
    "specRevisionOrAuditDate": "2026-09-11"
  },
  "harnesses": {
    "claude": {
      "status": "native",
      "differences": ["Uses the Claude Code skill discovery path."]
    },
    "copilot": {
      "status": "adapter-required",
      "differences": ["Maps the c8ctl command to the Copilot tool surface."]
    },
    "generic": {
      "status": "adapter-required",
      "differences": ["The host supplies discovery and tool invocation adapters."]
    }
  },
  "limitations": ["A Camunda 8 cluster is required for live c8ctl operations."],
  "differences": ["Tool names and credential setup can vary by harness."]
}
```
### Repository status enum

`status` describes the skill as a repository artifact, not the result of one
smoke run:

- `portable`: the package and behavior use the common Agent Skills contract
  without a harness-specific adapter.
- `portable-with-adapter`: the skill package is portable, but a documented
  adapter is required for one or more harness tool, credential, or invocation
  differences.
- `harness-specific`: a documented behavior cannot currently be represented by
  the common contract. The sidecar must identify the exception and the usable
  portable path, if one exists.

### Harness status enum

Each of `harnesses.claude`, `harnesses.copilot`, and
`harnesses.generic` is required and has a `status` plus at least one concrete
`differences` entry. The allowed statuses are:

- `native`: the harness can discover and invoke the skill without a
  compatibility adapter.
- `adapter-required`: the skill is usable after the repository or host maps a
  documented harness difference.
- `unsupported`: the skill is not usable in that harness under the current
  contract; `differences` must explain the blocking behavior.
- `not-tested`: no compatibility claim is made yet; `differences` must state
  what remains unverified. This status is not a successful smoke result.

`limitations` and the top-level `differences` list are mandatory, even when a
skill is `portable`. They must contain concrete behavior, setup, or support
constraints rather than generic text.

## Repository inventory and audit

`compatibility/skills-index.json` is the machine-readable inventory. It lists
each current skill exactly once and records:

- `name`: the skill name and `SKILL.md` frontmatter name;
- `skillDirectory`: the repository-relative skill directory;
- `skillMarkdown`: the repository-relative entrypoint;
- `sidecar`: the repository-relative portability declaration;
- `status`: the same repository status as the sidecar.

`compatibility/audit.json` is the dated audit record. It repeats the canonical
specification URL, `specRevisionOrAuditDate`, `auditDate`, and the complete
skill list with the same name, paths, and status values. The index and audit
must agree with every sidecar. A checker must reject omitted skills, duplicate
names, paths that do not resolve to the expected files, and status or
specification-date mismatches. The checked-in sidecars are part of this
contract, so the checker also rejects a skill directory without a sidecar or a
sidecar that is not represented in both inventories.

## Harness smoke boundary

The contract in `harness-smoke-contract.json` and the checked-in fixture at
`compatibility/fixtures/camunda-bpmn-smoke.json` define one deterministic
interaction boundary:

1. Discover `skills/camunda-bpmn/SKILL.md` from the repository root.
2. Activate `camunda-bpmn` with the fixture's fixed prompt.
3. Report `discovered: true` and `activated: true`.
4. Emit an artifact named exactly `process.bpmn`, and require that it exists
   and is valid BPMN.
5. Execute the exact tool command `c8ctl bpmn lint process.bpmn` and require a
   successful result.

The Claude and GitHub Copilot deterministic mock adapters are separate entry
points at `compatibility/adapters/mock-claude` and
`compatibility/adapters/mock-copilot`. Both produce the same assertion shape
without credentials, network calls, or model output. They materialize the
checked-in `compatibility/fixtures/process.bpmn`, validate the emitted copy,
and execute the contract command through the local deterministic
`compatibility/adapters/c8ctl` shim. A deterministic mock pass is required PR
evidence and is enforced by `make compatibility-check` and
`.github/workflows/compatibility.yml`. Live GitHub Copilot execution is a
separate, opt-in integration. Its result must be explicitly `passed`, `failed`,
`skipped`, or `unavailable`; `skipped` and `unavailable` are reported outcomes
and never count as a mock pass. An unavailable live integration must not be
converted into success by a catch-all fallback.
Before activation, each adapter reads the required `SKILL.md`, validates its
frontmatter name and description, and confirms that it declares the required
BPMN lint command. This prevents path-only discovery from being reported as
activation.

## Conformance and smoke commands

Run the complete local gate from the repository root:

```bash
make compatibility-check
```

The conformance checker validates the inventory, audit, sidecar, schema-shape,
and filesystem relationships. It emits one `Compatibility skill <name>:
passed` or `failed` record for every discovered skill before the aggregate
result. The two deterministic adapters then validate the artifact and execute
the required command independently; each smoke result retains its `adapter`
harness name.

## Examples

### Portable skill with an adapter

`camunda-bpmn` can be `portable-with-adapter` when all three harness entries
can load the same package, but Copilot and generic hosts need a mapping from
the skill's c8ctl command to their tool surface. The sidecar keeps that
difference in `harnesses.copilot.differences` and
`harnesses.generic.differences`; it does not change `SKILL.md` frontmatter.

### Harness-specific exception

A skill with `"status": "harness-specific"` must identify the unsupported
operation, for example a Claude-only interactive feature that has no
deterministic generic equivalent:

```json
{
  "$schema": "https://raw.githubusercontent.com/camunda/skills/main/compatibility/portability.schema.json",
  "skillDirectory": "skills/example",
  "skillName": "example",
  "status": "harness-specific",
  "agentSkillsSpec": {
    "specUrl": "https://agentskills.io/specification",
    "specRevisionOrAuditDate": "2026-09-11"
  },
  "harnesses": {
    "claude": {
      "status": "native",
      "differences": ["Supports the interactive operation."]
    },
    "copilot": {
      "status": "unsupported",
      "differences": ["The operation has no Copilot adapter."]
    },
    "generic": {
      "status": "unsupported",
      "differences": ["The operation requires a host capability not in this contract."]
    }
  },
  "limitations": ["Use the documented non-interactive path when available."],
  "differences": ["Interactive operation support differs by harness."]
}
```
