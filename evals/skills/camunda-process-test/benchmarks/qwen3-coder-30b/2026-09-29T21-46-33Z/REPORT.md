# Benchmark report

- Model: `ollama/qwen3-coder:30b`
- Duration: 1m 46s
- Tokens: 101,882 (6,304 input; 92,507 cache read; 3,071 output)
- Skill loaded: pass
- Final `test_spec_complete` rubric: fail (`0.0`)
- Failure: artifact section contains placeholder links
- Inspect log: `2026-09-29T21-46-33-00-00_camunda-process-test_J3T4VhetGvnajUxHxXFeNn.eval`

This output used `#` targets despite the link requirement, motivating the
explicit placeholder-link rejection in the prompt and scorer.
