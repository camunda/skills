# Benchmark report

- Model: `ollama/qwen3-coder:30b`
- Duration: 8m 17s
- Tokens: 257,453 (43,074 input; 202,512 cache read; 11,867 output)
- Skill loaded: pass
- Final `test_spec_complete` rubric: pass (`1.0`)
- Requirements found: 10
- E2E scenarios found: 3
- Inspect log: `2026-09-29T21-34-03-00-00_camunda-process-test_T5dKj3fVn8jHEUiiY4PJdk.eval`

The original run exposed heading-selection defects in the deterministic
scorer. Re-scoring the unchanged generated artifact after fixing the rubric
passes. This is the reference benchmark.
