# Evaluate coverage gaps in an existing suite

Use this before adding more scenarios to avoid random test growth.

## Inputs

- Target BPMN file(s)
- Existing `.test.json` scenarios and/or Java CPT tests

## Evaluation steps

1. Parse BPMN decisions: gateways, boundary events, end events, called DMN decisions.
2. Map each existing scenario to the path it covers.
3. Explain current coverage in plain business language (what situations are tested, what are not).
4. Classify gaps:
   - Missing gateway branches
   - Missing boundary-event/error paths
   - Missing alternate end states
   - Missing DMN rule paths that affect routing
5. Recommend the **smallest additional scenario set** that closes the biggest gaps first.

## Recommendation format

For each proposed scenario:

- **Name** (`<who/what> — <outcome>`)
- **Business description**
- **Type** (JSON process test or Java fallback)
- **Gap covered** (specific branch/boundary/rule)

Then suggest a coverage level target:

- **Quick**: happy path + one critical exception path
- **Standard**: all gateway branches and key boundaries
- **Thorough**: full branch/boundary/rule coverage + stability-focused integration checks
