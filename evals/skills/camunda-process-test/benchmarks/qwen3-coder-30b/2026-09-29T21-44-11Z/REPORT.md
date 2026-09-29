# Benchmark report

- Model: `ollama/qwen3-coder:30b`
- Duration: 1m 53s
- Tokens: 110,146 (7,657 input; 99,370 cache read; 3,119 output)
- Skill loaded: pass
- Final `test_spec_complete` rubric: fail (`0.0`)
- Failure: artifact section has fewer than two Markdown links
- Inspect log: `2026-09-29T21-44-11-00-00_camunda-process-test_Jkc9jc6Up2XjsGYXgm29JV.eval`

This output prompted the requirement that every artifact use explicit
`[label](target)` Markdown syntax.
