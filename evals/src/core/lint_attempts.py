"""Count how many validator runs an agent needed before reaching a clean result.

Post-hoc, transcript-only: reads ``sample.messages`` from an Inspect eval log,
so it works on any existing ``.eval`` without a scorer in the task. Consumed by
``scripts.model_matrix`` (the skill × model comparison).

A *validator run* is one agent tool call whose command invokes a structural
validator the skills prescribe as their closing gate:

- ``bpmn`` — ``c8ctl bpmn lint`` (``--dry-run`` ruleset checks are excluded:
  they report config, not issues)
- ``dmn``  — ``dmnlint``
- ``form`` — ``node validate-form.cjs``, or an inline ``node -e`` script
  validating against ``@bpmn-io/form-json-schema``

Only *executed* invocations count: heredoc bodies and quoted strings (e.g. the
helper's own ``Usage: node validate-form.cjs`` line, an ``echo`` of a command)
are stripped before matching, and each shell segment is matched on the tool it
*executes* (after ``npx``/``npm exec``/env-var wrappers) — so ``npm install
dmnlint`` isn't a run, and a ``--dry-run`` check doesn't hide a real lint in the
same tool call.

Each run is classified ``clean`` / ``dirty`` / ``unknown`` from its output and,
where the harness reports it, the exit code. Failure evidence is checked before
success markers, and a missing result or unrecognised output is ``unknown`` —
never silently clean.
``attempts_to_clean`` counts runs up to and including the first clean one; if
no run is ever clean it's the total run count and ``reached_clean`` is False.
One tool call is one attempt, even if its command validates several files or
runs several validators; it's clean only if every validator in it is clean.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

Validator = Literal["bpmn", "dmn", "form"]
Verdict = Literal["clean", "dirty", "unknown"]

# Inline validation: the schema reference lives inside the quoted script, so
# this is matched before quotes are stripped (heredocs are still removed); the
# segment must also *execute* `node -e` (see `_validators_in_segment`).
_INLINE_FORM = re.compile(
    r"\bnode\s+(?:-e|--eval)\s+(['\"])[\s\S]*?@bpmn-io/form-json-schema[\s\S]*?\1"
)
_DRY_RUN = re.compile(r"--dry-run\b")
_HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.DOTALL
)
_QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")
_SEPARATORS = re.compile(r"&&|\|\||[;&|\n]")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
# Leading words that run the next word as the command.
_PREFIXES = {
    "time",
    "sudo",
    "exec",
    "command",
    "env",
    "nohup",
    "do",
    "then",
    "else",
    "!",
}
# Package runners: `<runner> [flags] <tool> ...`; flags that take a value.
_RUNNERS = {"npx", "pnpx", "bunx"}
_RUNNER_VALUE_FLAGS = {"-p", "--package", "-c", "--call"}

_COMMAND_KEYS = ("input", "command", "cmd")


@dataclass
class ValidatorRun:
    """One tool call: every validator it executed, and their combined verdict."""

    validators: tuple[Validator, ...]
    verdict: Verdict
    command: str


@dataclass
class LintAttempts:
    runs: list[ValidatorRun] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        """Whether the agent ran any validator at all."""
        return bool(self.runs)

    @property
    def reached_clean(self) -> bool:
        return any(r.verdict == "clean" for r in self.runs)

    @property
    def attempts_to_clean(self) -> int | None:
        """Runs up to and including the first clean one (all runs if never
        clean); ``None`` when no validator ran."""
        if not self.runs:
            return None
        for i, run in enumerate(self.runs, start=1):
            if run.verdict == "clean":
                return i
        return len(self.runs)

    def by_validator(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.runs:
            for v in r.validators:
                counts[v] = counts.get(v, 0) + 1
        return counts


def _command_of(arguments: dict) -> str | None:
    for key in _COMMAND_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _argv(segment: str) -> list[str]:
    """The executed command's argv: leading `(`/`{`, env assignments, prefix
    words, and package-runner wrappers (`npx`, `npm exec`, `pnpm dlx`, ...)
    removed, so `argv[0]` is the tool actually run."""
    tokens = segment.replace("(", " ").replace("{", " ").split()
    i = 0
    while i < len(tokens) and (tokens[i] in _PREFIXES or _ENV_ASSIGN.match(tokens[i])):
        i += 1
    tokens = tokens[i:]
    if not tokens:
        return []
    head = tokens[0].rsplit("/", 1)[-1]
    rest = tokens[1:]
    if head in ("npm", "pnpm", "yarn", "bun") and rest[:1] in (
        ["exec"],
        ["x"],
        ["dlx"],
    ):
        head, rest = "npx", rest[1:]
    if head in _RUNNERS:
        j = 0
        while j < len(rest) and rest[j].startswith("-"):
            if rest[j] == "--":
                j += 1
                break
            j += 2 if rest[j] in _RUNNER_VALUE_FLAGS else 1
        return rest[j:]
    return tokens


def _validators_in_segment(segment: str, inline_form: bool) -> list[Validator]:
    argv = _argv(segment)
    if not argv:
        return []
    exe = argv[0].rsplit("/", 1)[-1]
    if exe == "c8ctl" or argv[0].startswith("@camunda8/cli"):
        words = argv[1:]
        is_lint = any(words[k : k + 2] == ["bpmn", "lint"] for k in range(len(words)))
        return ["bpmn"] if is_lint and not _DRY_RUN.search(segment) else []
    if exe == "dmnlint":
        return ["dmn"]
    if exe == "node":
        args = argv[1:]
        if inline_form and any(a in ("-e", "--eval") for a in args):
            return ["form"]
        script = next((a for a in args if not a.startswith("-")), "")
        if script.rsplit("/", 1)[-1] == "validate-form.cjs":
            return ["form"]
    return []


def _match_validators(command: str) -> tuple[Validator, ...]:
    """Every validator the command executes, in order, de-duplicated."""
    text = _HEREDOC.sub("<<HEREDOC", command)
    inline_form = bool(_INLINE_FORM.search(text))
    found: list[Validator] = []
    for segment in _SEPARATORS.split(_QUOTED.sub("''", text)):
        for v in _validators_in_segment(segment, inline_form):
            if v not in found:
                found.append(v)
    return tuple(found)


def _combine(verdicts: list[Verdict]) -> Verdict:
    """One attempt is clean only if every validator in it is clean."""
    if "dirty" in verdicts:
        return "dirty"
    if verdicts and all(v == "clean" for v in verdicts):
        return "clean"
    return "unknown"


def _message_text(msg) -> str:
    text = getattr(msg, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        t = getattr(c, "text", None)
        if isinstance(t, str):
            parts.append(t)
    return "\n".join(parts)


_ERROR_COUNT = re.compile(r'"errorCount"\s*:\s*(\d+)')
_WARNING_COUNT = re.compile(r'"warningCount"\s*:\s*(\d+)')
_PROBLEM_SUMMARY = re.compile(r"(\d+)\s+problems?\b", re.IGNORECASE)
_ESLINT_ROW = re.compile(r"\s{2,}(error|warning)\s{2,}", re.IGNORECASE)
_TOOL_FAILURE = re.compile(
    r"command not found|No such file or directory|Cannot find module|"
    r"npm ERR!|Usage: node validate-form",
    re.IGNORECASE,
)


# Copilot CLI's bash tool appends the exit status to every result.
_EXIT_TRAILER = re.compile(r"<shellId:[^>]*?exit code (\d+)\s*>")
_SHELL_TRAILER = re.compile(r"<shellId:[^>]*>")
_GENERIC_FAILURE = re.compile(
    r"permission denied|EACCES|ENOENT|^\s*error:|Traceback \(most recent call",
    re.IGNORECASE | re.MULTILINE,
)


def _exit_code(output: str) -> int | None:
    codes = _EXIT_TRAILER.findall(output)
    return int(codes[-1]) if codes else None


def _body(output: str) -> str:
    return _SHELL_TRAILER.sub("", output).strip()


def _classify_bpmn(output: str) -> Verdict:
    errors = [int(m) for m in _ERROR_COUNT.findall(output)]
    warnings = [int(m) for m in _WARNING_COUNT.findall(output)]
    if errors or warnings:
        return "clean" if sum(errors) + sum(warnings) == 0 else "dirty"
    problems = _PROBLEM_SUMMARY.findall(output)
    if problems:
        return "clean" if all(int(p) == 0 for p in problems) else "dirty"
    if _ESLINT_ROW.search(output):
        return "dirty"
    return "unknown"


def _classify_dmn(output: str) -> Verdict:
    # Diagnostics first: they establish a dirty result whatever else happened.
    if "✖" in output or _ESLINT_ROW.search(output):
        return "dirty"
    problems = _PROBLEM_SUMMARY.findall(output)
    if problems:
        return "clean" if all(int(p) == 0 for p in problems) else "dirty"
    if _TOOL_FAILURE.search(output) or _GENERIC_FAILURE.search(output):
        return "unknown"
    code = _exit_code(output)
    if code is not None:
        # dmnlint: 0 clean, 1 lint issues, >1 tool failure.
        return {0: "clean", 1: "dirty"}.get(code, "unknown")
    # dmnlint is silent on success; with no exit status, only an empty result
    # counts as clean.
    return "clean" if not _body(output) else "unknown"


def _classify_form(output: str) -> Verdict:
    # Failure signals before the success marker: a multi-file call can print
    # `Valid ✓` for one file and Ajv errors for the next.
    if "FAILED" in output or '"instancePath"' in output or '"keyword"' in output:
        return "dirty"
    if _TOOL_FAILURE.search(output) or _GENERIC_FAILURE.search(output):
        return "unknown"
    code = _exit_code(output)
    if code not in (None, 0):
        return "dirty" if code == 1 else "unknown"
    if "Valid ✓" in output:
        return "clean"
    # Inline `ajv.validate(...)` scripts commonly print the bare boolean.
    lines = [ln.strip().lower() for ln in _body(output).splitlines() if ln.strip()]
    if lines and any(ln.startswith(("false", "invalid")) for ln in lines):
        return "dirty"
    if lines and all(ln in ("true", "valid") for ln in lines):
        return "clean"
    return "unknown"


_CLASSIFIERS = {"bpmn": _classify_bpmn, "dmn": _classify_dmn, "form": _classify_form}


def lint_attempts(messages) -> LintAttempts:
    """Extract validator runs from a sample's message history.

    ``bash_session`` (the react agent's shell) may return a command's output
    across follow-up ``read`` calls, so their results are folded into the
    preceding validator run before it's classified.
    """
    results: dict[str, str] = {}
    for msg in messages or []:
        if getattr(msg, "role", None) == "tool":
            call_id = getattr(msg, "tool_call_id", None)
            if call_id:
                results[call_id] = _message_text(msg)

    pending: list[tuple[tuple[Validator, ...], str, list[str | None]]] = []
    window_open = False  # whether `read` output still belongs to the last run
    for msg in messages or []:
        for tc in getattr(msg, "tool_calls", None) or []:
            arguments = tc.arguments or {}
            output = results.get(tc.id)  # None: the call never returned
            if arguments.get("action") == "read":
                if window_open and output is not None:
                    pending[-1][2].append(output)
                continue
            command = _command_of(arguments)
            validators = _match_validators(command) if command else ()
            if not validators:
                if command is not None:
                    window_open = False
                continue
            pending.append((validators, command, [output]))
            window_open = True

    runs = []
    for validators, cmd, outs in pending:
        if outs[0] is None:
            verdict: Verdict = "unknown"
        else:
            output = "\n".join(o for o in outs if o is not None)
            verdict = _combine([_CLASSIFIERS[v](output) for v in validators])
        runs.append(ValidatorRun(validators, verdict, cmd))
    return LintAttempts(runs=runs)


def to_json(attempts: LintAttempts) -> dict:
    return {
        "applicable": attempts.applicable,
        "attempts_to_clean": attempts.attempts_to_clean,
        "reached_clean": attempts.reached_clean,
        "total_runs": len(attempts.runs),
        "by_validator": attempts.by_validator(),
    }


if __name__ == "__main__":  # pragma: no cover - debugging aid
    import sys

    from inspect_ai.log import read_eval_log

    log = read_eval_log(sys.argv[1])
    for s in log.samples or []:
        print(s.id, s.epoch, json.dumps(to_json(lint_attempts(s.messages))))
