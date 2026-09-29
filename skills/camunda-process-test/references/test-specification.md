# Test-spec-first workflow

Create a Markdown test specification before implementing a suite. Its job is to make the intended guarantees reviewable by a process owner who should not need the BPMN open to understand them.

Use `TESTING.md` unless the repository already has a testing/acceptance document. Link it from the project README when practical.

## Required structure

```markdown
# Testing and acceptance criteria

Status: DRAFT

## Assertion philosophy
State what the tests prove, what they deliberately do not assert, and which
outputs need semantic or contract assertions rather than exact values.

## High-level testing strategy
| Layer | Purpose | External systems | Acceptance signal | Run/cadence |
| ... |

## Requirements traceability
| ID | Requirement | Layer | Verified by | Evidence/assertions | Dependency/status | Comment |
| PR-1 | ... |

## Coverage thresholds
| Layer | Target | Machine gate | Report source | Rationale |
| ... |

Thresholds are user-tunable and require approval before implementation.

## End-to-end scenario catalogue
| # | Scenario in plain language | Inputs/context | Expected outcome | Terminal element | Expected tool set | Requirement | Retry/determinism policy |
| ... |

## How to run each layer
Commands, prerequisites, credentials/local stubs, profiles, and report paths.

## Artifacts and links
| Artifact | Location |
| Source BPMN | [process.bpmn](...) |
| This specification | [TESTING.md](...) |
| Planned/implemented tests | [...] |
| CPT documentation | [...] |

## Assumptions, open questions, and approval
List decisions still needed. State: "Do not implement tests until the user
approves the requirements, scenarios, dependencies, and thresholds."
```

## Requirement IDs and evidence

Use stable IDs:

- `PR-n`: deterministic process/routing requirement;
- `SIR-n`: segment/point integration contract;
- `PIR-n`: whole-process integration or E2E business outcome.

Every row names the test layer and planned scenario/test. Evidence describes concrete assertions: route elements, terminal state, routing variable, stable response shape, expected tool **set**, error boundary, or quality output. Process completion alone is not sufficient evidence.

Mark unavailable dependencies and planned/disabled tests visibly. Never present an unimplemented or disabled requirement as passing.

## Coverage thresholds

Record two values per layer:

- **Target**: the desired completeness level.
- **Machine gate**: the current enforced minimum.

Default a new deterministic process suite to 100% of reachable BPMN elements and sequence flows. Integration gates depend on available fixtures, credentials, cost, and environment stability. The user may tune every threshold; capture the rationale and approval. Report unreachable elements as BPMN defects rather than silently excluding them.

## Realistic E2E scenarios

Write scenarios in domain language with representative inputs and an outcome a human expects. Include:

- expected terminal element/end state;
- requirement ID;
- expected tools as a set (do not require incidental order);
- human steps and feedback/retry behavior;
- deterministic fixture or live-model policy;
- retry/quality-signal handling for non-deterministic outcomes.

For agentic processes, distinguish deterministic mocked evidence from optional live-model quality evidence. Never assert exact generated prose.

## Approval loop

In interactive mode:

1. Draft the specification from the BPMN and project evidence.
2. Show the user the requirements, E2Es, dependencies, and threshold decisions.
3. Ask for one focused decision at a time when values or business outcomes are unknown.
4. Revise the Markdown and keep `Status: DRAFT`.
5. Implement only after explicit approval; record `Status: APPROVED`, approver/date if available, and the agreed gates.

If the request is only to plan or clarify tests, the approved Markdown is the final deliverable.

## Maintenance

Update the specification when the BPMN, prompts/models, connectors, fixtures, thresholds, or test status changes. Keep links repository-relative where possible. After implementation, replace planned links with actual source/report links and ensure each requirement row reflects pass, fail, skipped, blocked, or not implemented honestly.
