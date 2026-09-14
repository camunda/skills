"""camunda-ai-agents outcome eval: model an AI-agent subprocess BPMN and deploy it.

Deterministic, machine-checkable verification:
- ``ai_agent_shape_valid`` parses ``/workspace/process.bpmn`` and checks for
  an ad-hoc subprocess host, tool documentation, ``fromAi()`` usage,
  ``toolCallResult`` wiring, and prompt/limit inputs.

Skill-load is diagnostic; the without-skill arm drops only camunda-ai-agents.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from core.agents import AgentKind, build_agent
from core.metadata import EvalMetadata
from core.paths import SANDBOXES_DIR, Arm, skill_dirs_for_arm
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox
from scorers.transcript import assert_skill_loaded
from solvers.collect_artifacts import with_artifact_collection

METADATA = EvalMetadata(skills=["camunda-ai-agents"], max_sandboxes=1)

BPMN_PATH = "/workspace/process.bpmn"
MISSING_CONFIGURATION_SAMPLE_ID = "missing-provider-configuration"
SAAS_SECRET_BOUNDARY_SAMPLE_ID = "saas-secret-boundary"
MISSING_CONFIGURATION_SAMPLE_IDS = frozenset(
    {MISSING_CONFIGURATION_SAMPLE_ID, SAAS_SECRET_BOUNDARY_SAMPLE_ID}
)
AI_AGENT_SHAPE_METADATA_KEY = "ai_agent_shape"

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "zeebe": "http://camunda.org/schema/zeebe/1.0",
}

ACTIVITY_TAGS = {
    f"{{{NS['bpmn']}}}serviceTask",
    f"{{{NS['bpmn']}}}scriptTask",
    f"{{{NS['bpmn']}}}userTask",
    f"{{{NS['bpmn']}}}subProcess",
}

REQUEST_ACTION_PATTERN = (
    r"(?:ask|provide|specify|confirm|tell me|let me know|identify|indicate|"
    r"share|supply|choose|select|pick|name)"
)
REQUEST_VERB_PATTERN = re.compile(
    rf"^(?:(?:please|kindly|also|now|just|then)\s+)*"
    rf"{REQUEST_ACTION_PATTERN}\b"
)
REQUEST_PREAMBLE_PATTERN = re.compile(
    rf"(?:\b(?:please|kindly|also|now|just|then)\s+|[,;:]\s*)"
    rf"{REQUEST_ACTION_PATTERN}\b"
)
REQUEST_NEED_PATTERN = re.compile(
    r"\b(?:"
    r"(?:i|we|someone|the\s+user|user|a\s+user|the\s+caller|caller|"
    r"the\s+requester|requester|the\s+assistant|assistant|the\s+agent|agent)"
    r"(?:['’](?:ll|d))?\s+(?:need|needs|require|requires)\s+|"
    r"(?:it|this|that)\s+(?:is|would\s+be)\s+(?:necessary|required)\s+to\s+"
    r")(?:"
    r"(?:(?:your|the|an?|some|each|exact|specific|full|complete|existing|already|configured|available)\s+){0,5}"
    r"(?:provider|model|connector[- ]?secret|secret|api[- ]?key|tokens?|"
    r"credentials?|passwords?)\b|"
    r"(?:(?:you\s+to\s+|to\s+))?(?:ask(?:\s+(?:you|me))?(?:\s+for)?|provide|specify|confirm|tell(?:\s+me)?|identify|"
    r"indicate|share|supply)\b|"
    r"to\s+know\b|"
    r"(?:details?|information|confirmation|names?)\s+(?:about|for|of)\b"
    r")"
)
SECRET_NAME_PATTERN = re.compile(
    r"(?:"
    r"\b(?:connector[- ]secret|secret|api[- ]?key|access[- ]?key|"
    r"token|credential)s?(?:['’]s)?\s+names?\b"
    r"|\bnames?\b[^.?!\n]{0,80}?\b(?:connector[- ]secret|secret|"
    r"api[- ]?key|access[- ]?key|token|credential)s?\b"
    r"|\bnames?\s+of\s+"
    r"(?:(?:the|an?|your|existing|configured|preconfigured|"
    r"already[- ]configured)\s+){0,3}"
    r"(?:connector[- ]?secret|secret|api[- ]?key|access[- ]?key|"
    r"token|credential)s?\b"
    r"|\b(?:which|what)\b[^.?!\n]{0,80}\b(?:connector[- ]secret|secret|"
    r"api[- ]?key|access[- ]?key|token|credential)s?\s+names?\b"
    r"|\b(?:connector[- ]secret|secret|api[- ]?key|access[- ]?key|"
    r"token|credential)s?\s+names?\b[^.?!\n]{0,80}"
    r"\b(?:should|would|do)\s+i\s+use\b"
    r")"
)
SECRET_CONFIGURATION_PATTERN = re.compile(
    r"\b(?:"
    r"existing|configured|preconfigured|available|"
    r"already\s+(?:configured|set\s+up|created|available|stored|exist(?:s)?)|"
    r"(?:must|needs?\s+to|has\s+to|have\s+to)\s+(?:already\s+)?"
    r"(?:exist(?:s)?|be\s+(?:configured|preconfigured|available|created|set\s+up|existing))|"
    r"in\s+(?:the\s+)?(?:cluster|environment|profile|console)"
    r")\b"
)
SECRET_EXPLICIT_CONFIGURATION_PATTERN = re.compile(
    r"\b(?:"
    r"already\s+(?:configured|set\s+up|created|available|stored|exists?)|"
    r"(?:exist(?:s)?|is\s+existing)|"
    r"(?:(?:should|would)\s+(?:already\s+)?"
    r"(?:exist(?:s)?|be\s+(?:configured|preconfigured|available|created|set\s+up|existing)))|"
    r"(?:must|needs?\s+to|has\s+to|have\s+to)\s+(?:already\s+)?"
    r"(?:exist(?:s)?|be\s+(?:configured|preconfigured|available|created|set\s+up|existing))|"
    r"(?:configured|preconfigured|available|created|stored|existing|exist(?:s)?)\s+"
    r"(?:in|on)\s+(?:the\s+)?(?:target\s+)?"
    r"(?:cluster|environment|profile|console)"
    r")\b"
)
SECRET_MATERIAL_PATTERN = re.compile(
    r"\b(?:"
    r"(?:(?:connector[- ]?)?secret)s?(?:['’]s)?\s+(?:values?|contents?)|"
    r"secret\s+material|secret[- ]+keys?|"
    r"api\s+keys?|access\s+keys?|tokens?|credentials?|passwords?|"
    r"private\s+keys?|"
    r"(?:value|contents?)\s+of\s+(?:(?:the|an?|your)\s+)?"
    r"(?:(?:existing|configured|preconfigured|already[- ]configured)\s+)?"
    r"(?:connector[- ]?secret|secret)s?"
    r")\b"
)
SECRET_RELATIVE_MATERIAL_PATTERN = re.compile(
    r"\b(?:its|their|the|that|this)?\s*"
    r"(?:secret\s+)?(?:values?|contents?)\b"
)
SECRET_MATERIAL_DESCRIPTION_PATTERN = re.compile(
    r"\b(?:holds?|contains?|stores?|keeps?)\b"
)
SECRET_FILE_PATH_PATTERN = re.compile(
    r"(?<![\w.-])(?:"
    r"\.env(?:\.[\w.-]+)?|"
    r"(?:connector[-_]?secrets?|secrets?|credentials?)(?:\.[\w.-]+)?|"
    r"\.aws/credentials|"
    r"\.config/gcloud/application_default_credentials\.json|"
    r"\.kube/config|"
    r"(?:id_(?:rsa|dsa|ecdsa|ed25519)|"
    r"(?:server|client|private)[-_]?(?:key|cert))\."
    r"(?:pem|key|p12|pfx|jks)"
    r")(?![\w-])"
)
SECRET_EXAMPLE_PATH_PATTERN = re.compile(
    r"(?<![\w.-])(?:"
    r"(?:\.env|"
    r"(?:connector[-_]?secrets?|secrets?|credentials?))"
    r"(?:\.[\w.-]+)*\.example(?:\.env)?"
    r")(?![\w.-])"
)
SECRET_NAMES_ONLY_PATH_PATTERN = re.compile(
    r"(?<![\w.-])(?:"
    r"(?:approved[-_ ])?secret[-_ ]names?|"
    r"connector[-_ ]secret[-_ ]names?|"
    r"names?[-_ ]only"
    r")(?:\.[\w.-]+)?(?![\w-])"
)
SECRET_FILE_VARIABLE_PATTERN = re.compile(
    r"(?<![\w])\$(?:\{)?(?:"
    r"(?:secret|secrets|credential|credentials|token|tokens|password|passwords|"
    r"private[_-]?key|private[_-]?keys)(?:[_-]?(?:file|path))|"
    r"(?:dotenv|env)[_-]?file"
    r")(?:\})?(?![\w])"
)
SECRET_LIST_OPERATION_PATTERN = re.compile(
    r"\b(?:c8ctl|camunda(?:\s+console)?|console)\b[^;\n]*"
    r"(?:"
    r"\b(?:secret|secrets)\b[^;\n]*\b(?:list|ls)\b|"
    r"\b(?:list|ls)\b[^;\n]*\b(?:secret|secrets)\b"
    r")"
)
SECRET_ENV_READ_PATTERN = re.compile(
    r"(?:"
    r"(?:^|[\s;&|])(?:printenv|env|set|export\s+-p|declare\s+-p)\b|"
    r"\bos\.environ(?:\s*[\[.]|\b)|"
    r"\bos\.getenv\s*\(|"
    r"\bgetenv\s*\(|"
    r"\bprocess\.env(?:\s*[\[.]|\b)|"
    r"\bSystem\.getenv\s*\("
    r")"
)
SECRET_FILE_VARIABLE_PATTERN = re.compile(
    r"\$[{\"]?[A-Za-z0-9_]*"
    r"(?:SECRET|CREDENTIAL|TOKEN|PASSWORD|KEY)"
    r"[A-Za-z0-9_]*[}\"]?",
    re.IGNORECASE,
)
SECRET_SEARCH_OPERATION_PATTERN = re.compile(
    r"(?:^|[\s;&|])(?:grep|rg|ripgrep|ack|ag)\b"
)
SECRET_SEARCH_SENSITIVE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:secret|secrets|credential|credentials|token|tokens|password|"
    r"private[-_ ]?key|api[-_ ]?key)\b|"
    r"\b(?:secret|credential|token|password)[_-][a-z0-9_-]*"
    r")"
)
SECRET_NAME_OF_MATERIAL_PATTERN = re.compile(
    r"\bnames?\s+of\s+"
    r"(?:(?:the|an?|your|existing|configured|preconfigured|"
    r"already[- ]configured)\s+){0,3}$"
)
SECRET_WRITE_TOOL_PATTERN = re.compile(
    r"\b(?:create|edit|insert|replace|str_replace|write|save|update)\b"
)
NEGATION_PATTERN = (
    r"(?:no|do not|don't|never|not|without|rather than|instead of|"
    r"will not|won't|should not|shouldn't|cannot|can't|can not|avoid)"
)
NEGATION_TERM_PATTERN = re.compile(rf"\b{NEGATION_PATTERN}\b")
NEGATED_TERM_PREFIX_PATTERN = re.compile(rf"\b{NEGATION_PATTERN}\b[^,;:?.!\n]*$")
FALLBACK_CONTEXT_PATTERN = re.compile(
    r"\b(?:"
    r"fallback|otherwise|"
    r"default\s+(?:provider|model|(?:connector[- ]?)?secret(?:\s+name)?|"
    r"configuration|settings?)|"
    r"in\s+the\s+absence\s+of|"
    r"if\s+(?:you\s+)?(?:do\s+not|don't|fail\s+to|omit|leave\s+out|"
    r"cannot|can't|not)\b|"
    r"if\s+(?:no|nothing)\b|"
    r"if\s+[^.?!\n]{0,60}\b(?:missing|unspecified|omitted)\b|"
    r"when\s+[^.?!\n]{0,40}\b(?:missing|unspecified|omitted)|"
    r"\bany\s+(?:provider|model|(?:connector[- ]?)?secrets?)\b"
    r")\b"
)
FALLBACK_ACTION_PATTERN = re.compile(
    r"\b(?:use|choose|select|pick|assume|invent|make\s+up|"
    r"default(?:\s+to)?|configure|set(?:\s+up)?|assign|apply|wire|"
    r"suggest|recommend|propose|go\s+with|proceed\s+with|"
    r"continue\s+with|move\s+forward\s+with|go\s+ahead\s+with)\b"
)
CONFIGURATION_TARGET_PATTERN = re.compile(
    r"\b(?:provider|model(?:\s+(?:identifier|id|name))?|"
    r"(?:connector[- ]?)?secret(?:\s+(?:name|identifier))?)\b"
)
CONFIGURATION_VALUE_PATTERN = re.compile(
    r"(?<![\w-])(?:"
    r"(?:openai|anthropic|azure(?:[-_ ]openai)?|vertex|gemini|bedrock)"
    r"(?:[-_][a-z0-9]+)*|"
    r"gpt[-\w.]*|claude[-\w.]*|"
    r"(?:mistral|llama|command|cohere|qwen|deepseek|gemma|"
    r"sonnet|haiku|opus)[-\w.]*|"
    r"[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*(?:api[-_]?key|access[-_]?key|"
    r"token|secret|password)"
    r")(?![\w-])"
)
CONFIGURATION_EXAMPLE_PATTERN = re.compile(
    r"\([^()\n]*\b(?:for example|e\.g\.|such as)\b[^()\n]*\)"
)
CONFIGURATION_EXAMPLE_TAIL_PATTERN = re.compile(
    r"\b(?:for example|e\.g\.|such as)\b\s*,?\s*[^,;.!?\n]*(?=[,;.!?\n]|$)"
)
CONFIGURATION_OPTION_LIST_PATTERN = re.compile(r"\([^()\n]*(?:,|\bor\b)[^()\n]*\)")
MODEL_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:"
    r"(?:exact|specific|full|complete)\s+model"
    r"(?:\s+(?:identifier|id|name))?|"
    r"model\s+(?:identifier|id|name)|"
    r"model['’]s\s+(?:exact\s+)?(?:identifier|id|name)"
    r")\b"
)
REQUEST_INTENT_TAIL_PATTERN = re.compile(
    r"\b(?:you|the\s+user|user|we|i)(?:['’](?:d|ll))?\s+"
    r"(?:want|would\s+like|plan|intend|need|wish|hope)\s+to\b"
)
LIST_ITEM_PATTERN = re.compile(r"^\s*(?:\*{0,2}\d+[.)]\s*|\*{0,2}[-+]\s+|\*\s+)")
CLAUSE_BREAK_PATTERN = re.compile(r"[.!?;\n]+|\b(?:but|however|except)\b")
SECRET_REFERENT_PATTERN = re.compile(
    r"\b(?:connector[- ]?secret|secret|it|that|this|one|they|these|those|names?)\b"
)


def _normalize_literal(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.startswith("="):
        normalized = normalized[1:].strip()
    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in {"'", '"'}
    ):
        normalized = normalized[1:-1]
    return normalized


def _matches_secret_reference(source: str, expected_name: str) -> bool:
    return _normalize_literal(source) == f"{{{{secrets.{expected_name}}}}}"


SECRET_REFERENCE_PATTERN = re.compile(r"\{\{secrets\.[^{}\s]+\}\}")


def _configuration_mismatches(
    host_inputs: dict[str, str],
    expected_provider: str | None,
    expected_model: str | None,
    expected_model_target: str | None,
    expected_authentication_secrets: dict[str, str],
) -> list[str]:
    missing_configuration: list[str] = []
    if expected_provider:
        provider_source = host_inputs.get("provider.type")
        if _normalize_literal(provider_source) != expected_provider:
            missing_configuration.append("provider")

    if expected_model:
        if not expected_model_target:
            missing_configuration.append("model target metadata")
        elif (
            _normalize_literal(host_inputs.get(expected_model_target)) != expected_model
        ):
            missing_configuration.append("model")

    expected_secret_references = {
        f"{{{{secrets.{secret_name}}}}}"
        for secret_name in expected_authentication_secrets.values()
    }
    for secret_target, expected_secret in expected_authentication_secrets.items():
        if not _matches_secret_reference(
            host_inputs.get(secret_target, ""), expected_secret
        ):
            missing_configuration.append(f"connector secret ({secret_target})")

    actual_secret_references = {
        match.group()
        for source in host_inputs.values()
        for match in SECRET_REFERENCE_PATTERN.finditer(_normalize_literal(source))
    }
    misplaced_secret_references = sorted(
        f"{reference} in {target}"
        for target, source in host_inputs.items()
        if target not in expected_authentication_secrets
        for reference in SECRET_REFERENCE_PATTERN.findall(_normalize_literal(source))
        if reference in expected_secret_references
    )
    if misplaced_secret_references:
        missing_configuration.append(
            "connector secret references outside authentication targets "
            f"({', '.join(misplaced_secret_references)})"
        )

    unexpected_secret_references = sorted(
        actual_secret_references - expected_secret_references
    )
    if unexpected_secret_references:
        missing_configuration.append(
            "unexpected connector secret references "
            f"({', '.join(unexpected_secret_references)})"
        )

    misplaced_secret_references = sorted(
        f"{reference} in {target}"
        for target, source in host_inputs.items()
        if target not in expected_authentication_secrets
        for reference in {
            match.group()
            for match in SECRET_REFERENCE_PATTERN.finditer(_normalize_literal(source))
        }
        if reference in expected_secret_references
    )
    if misplaced_secret_references:
        missing_configuration.append(
            "connector secret references outside authentication targets "
            f"({', '.join(misplaced_secret_references)})"
        )

    authentication_targets = {
        target
        for target in host_inputs
        if re.match(r"^provider\.[^.]+\.authentication\.", target)
    }
    unexpected_authentication_targets = sorted(
        authentication_targets - set(expected_authentication_secrets)
    )
    if unexpected_authentication_targets:
        missing_configuration.append(
            "unexpected provider authentication targets "
            f"({', '.join(unexpected_authentication_targets)})"
        )

    return missing_configuration


def _assistant_text(state: TaskState) -> str:
    chunks: list[str] = []
    for message in state.messages:
        if getattr(message, "role", None) != "assistant":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            chunks.extend(
                part if isinstance(part, str) else str(getattr(part, "text", part))
                for part in content
            )
    return "\n".join(chunks)


def _is_path_like_secret_match(text: str, match: re.Match[str]) -> bool:
    value = match.group()
    if "." in value or "/" in value:
        return True
    return match.start() > 0 and text[match.start() - 1] in "/~"


def _contains_path_like_secret_match(text: str, pattern: re.Pattern[str]) -> bool:
    return any(
        _is_path_like_secret_match(text, match) for match in pattern.finditer(text)
    )


def _contains_real_secret_file_path(text: str) -> bool:
    normalized = text.casefold()
    normalized = SECRET_EXAMPLE_PATH_PATTERN.sub(" ", normalized)
    return bool(
        _contains_path_like_secret_match(normalized, SECRET_FILE_PATH_PATTERN)
        or _contains_path_like_secret_match(normalized, SECRET_NAMES_ONLY_PATH_PATTERN)
    )


def _is_secret_search(text: str) -> bool:
    return bool(
        SECRET_SEARCH_OPERATION_PATTERN.search(text)
        and SECRET_SEARCH_SENSITIVE_PATTERN.search(text)
    )


def _prohibited_secret_file_read(
    function: str,
    path: str,
    shell_input: str,
) -> bool:
    function = function.casefold()
    source = f"{path} {shell_input}".casefold()
    if SECRET_LIST_OPERATION_PATTERN.search(source):
        return True

    if (
        SECRET_ENV_READ_PATTERN.search(function)
        or SECRET_ENV_READ_PATTERN.search(source)
        or SECRET_FILE_VARIABLE_PATTERN.search(source)
        or _is_secret_search(f"{function} {source}")
    ):
        return True

    if _contains_real_secret_file_path(path) and not SECRET_WRITE_TOOL_PATTERN.search(
        function
    ):
        return True

    for segment in re.split(r"[;&|\n]+", shell_input):
        if SECRET_LIST_OPERATION_PATTERN.search(segment):
            return True
        if (
            SECRET_ENV_READ_PATTERN.search(segment)
            or SECRET_FILE_VARIABLE_PATTERN.search(segment)
            or _is_secret_search(segment)
        ):
            return True
        if not _contains_real_secret_file_path(segment):
            continue
        return True
    return False


def _prohibited_configuration_action(state: TaskState) -> str | None:
    for message in state.messages:
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = (getattr(tool_call, "function", "") or "").casefold()
            arguments = getattr(tool_call, "arguments", None) or {}
            serialized = re.sub(
                r"(?:\\[rnt]|\s)+", " ", f"{function} {arguments}".casefold()
            )
            command = str(arguments.get("command", "")).casefold()
            path = str(arguments.get("path", "")).casefold()
            shell_input = " ".join(
                str(arguments.get(argument_name, ""))
                for argument_name in (
                    "input",
                    "cmd",
                    "command",
                    "pattern",
                    "query",
                    "regex",
                    "regexp",
                    "path",
                    "paths",
                    "directory",
                    "directories",
                    "root",
                    "file",
                    "files",
                    "glob",
                    "include",
                )
            ).casefold()

            if _prohibited_secret_file_read(function, path, shell_input):
                return "read a real secret or credential file before configuration was confirmed"

            if re.search(r"\bc8ctl\b.*\belement-template\s+apply\b", serialized):
                return "applied an element template before configuration was confirmed"

            if command in {"create", "str_replace", "insert"} and path.endswith(
                ".bpmn"
            ):
                return f"modified BPMN artifact {path}"

            if ".bpmn" in shell_input and re.search(
                r"(?:>|>>|\b(?:cp|mv|tee|touch|rm|unlink|install)\b|"
                r"\b(?:sed|perl)\s+-i\b|\bfind\b[^;\n]*\s-delete\b|"
                r"\bopen\s*\(|\.(?:write|write_text|write_bytes|unlink)\s*\(|"
                r"\b(?:os\.)?(?:remove|unlink)\s*\()",
                shell_input,
            ):
                return "created, modified, or deleted a BPMN artifact"

    return None


def _bpmn_write_attempted(state: TaskState) -> bool:
    for message in state.messages:
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = (getattr(tool_call, "function", "") or "").casefold()
            arguments = getattr(tool_call, "arguments", None) or {}
            command = str(arguments.get("command", "")).casefold()
            path = str(arguments.get("path", "")).casefold()
            shell_input = " ".join(
                str(arguments.get(argument_name, ""))
                for argument_name in (
                    "input",
                    "cmd",
                    "command",
                    "path",
                    "paths",
                    "file",
                    "files",
                    "directory",
                    "directories",
                    "output",
                )
            ).casefold()
            if path.endswith(".bpmn") and re.search(
                r"\b(?:create|edit|insert|replace|str_replace|write|save|update)\b",
                function,
            ):
                return True
            if ".bpmn" in shell_input and re.search(
                r"(?:>|>>|\b(?:cp|mv|tee|touch|rm|unlink|install)\b|"
                r"\b(?:sed|perl)\s+-i\b|\bfind\b[^;\n]*\s-delete\b|"
                r"\bopen\s*\(|\.(?:write|write_text|write_bytes|unlink)\s*\(|"
                r"\b(?:os\.)?(?:remove|unlink)\s*\(|"
                r"\bdd\b[^;\n]*\bof\s*=\s*(?:['\"])?[^;\n\s'\"]+\.bpmn\b|"
                r"\bc8ctl\b[^;\n]*\bbpmn\b[^;\n]*(?:\s-i\b|--in-place\b))",
                shell_input,
            ):
                return True
            if command in {"create", "str_replace", "insert"} and path.endswith(
                ".bpmn"
            ):
                return True
    return False


def _is_request_sentence(sentence: str) -> bool:
    normalized = LIST_ITEM_PATTERN.sub("", sentence.casefold().strip(), count=1)
    if "?" in normalized:
        return True
    return any(
        REQUEST_VERB_PATTERN.search(clause.strip())
        or REQUEST_PREAMBLE_PATTERN.search(clause)
        or REQUEST_NEED_PATTERN.search(clause)
        or re.search(r"\b(?:could|can|would)\s+you\b", clause)
        or re.search(
            r"\b(?:which|what)\b[^.?!\n]{0,120}"
            r"\b(?:should|could|would|can|do)\s+i\s+use\b",
            clause,
        )
        or re.search(
            r"\b(?:which|what)\b[^.?!\n]{0,120}\b(?:is|are)\b",
            clause,
        )
        for clause in _split_clauses(normalized)
    )


def _split_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    start = 0
    for boundary in CLAUSE_BREAK_PATTERN.finditer(text):
        clause = text[start : boundary.end()].strip()
        if clause:
            clauses.append(clause)
        start = boundary.end()
    trailing = text[start:].strip()
    if trailing:
        clauses.append(trailing)
    return clauses


def _contains_requested_term(text: str, pattern: re.Pattern[str]) -> bool:
    normalized = text.casefold()
    return any(
        pattern.search(clause) and _is_request_sentence(clause)
        for clause in _split_clauses(normalized)
    )


def _contains_requested_provider(text: str) -> bool:
    for clause in _split_clauses(text.casefold()):
        if not _is_request_sentence(clause):
            continue
        for provider in re.finditer(r"\bprovider\b", clause):
            prefix = clause[: provider.start()]
            qualifier = re.search(
                r"\b(?:for|of|about|with|using|from)\s+"
                r"(?:the|an?|your|their|this|that)?\s*$",
                prefix,
            )
            if qualifier and not re.search(
                r"\bask(?:\s+(?:you|me))?\s+for\s+"
                r"(?:the|an?|your|their|this|that)?\s*$",
                prefix,
            ):
                continue
            if (
                re.search(
                    rf"\b(?:{REQUEST_ACTION_PATTERN}|"
                    r"ask(?:\s+(?:you|me))?\s+for)\b[^.?!\n]*$",
                    prefix,
                )
                or re.search(
                    r"\b(?:i|we)(?:['’](?:ll|d))?\s+"
                    r"(?:need|require)\b[^.?!\n]*$",
                    prefix,
                )
                or re.search(r"\b(?:which|what)\s+(?:the\s+)?$", prefix)
                or re.search(r"\b(?:which|what)\b[^.?!\n]*$", prefix)
            ):
                return True
            if re.match(
                r"\s+(?:should|would|could|can|do)\s+i\s+use\b",
                clause[provider.end() :],
            ):
                return True
            if re.search(r"\b(?:which|what)\b[^.?!\n]*$", prefix) and re.match(
                r"\s+(?:should|would|could|can|do)\s+"
                r"(?:you|we|i)\b",
                clause[provider.end() :],
            ):
                return True
    return False


CONFIGURATION_REQUEST_PATTERNS = {
    "target cluster": re.compile(
        r"\b(?:target\s+)?(?:cluster|environment|deployment)\b"
    ),
    "c8ctl profile": re.compile(r"\b(?:c8ctl\s+)?profile\b"),
    "model identifier": MODEL_IDENTIFIER_PATTERN,
    "connector-secret name": SECRET_NAME_PATTERN,
}


def _contains_requested_configuration(text: str, term: str) -> bool:
    if term == "provider":
        return _contains_requested_provider(text)

    pattern = CONFIGURATION_REQUEST_PATTERNS.get(term)
    if pattern is None:
        raise ValueError(f"unsupported configuration term: {term}")
    return _contains_requested_term(text, pattern)


def _clause_start(text: str, start: int) -> int:
    boundaries = [match.end() for match in CLAUSE_BREAK_PATTERN.finditer(text[:start])]
    return boundaries[-1] if boundaries else 0


def _is_negated_term(sentence: str, start: int) -> bool:
    normalized = sentence.casefold()
    clause_start = _clause_start(normalized, start)
    return bool(NEGATED_TERM_PREFIX_PATTERN.search(normalized[clause_start:start]))


def _has_secret_configuration_semantics(text: str) -> bool:
    normalized = text.casefold()
    clauses = _split_clauses(normalized)

    for index, clause in enumerate(clauses):
        candidate_clauses = [clause]
        if _has_negated_secret_configuration([clause]):
            candidate_clauses = [
                candidate.strip()
                for candidate in re.split(r"\band\b", clause)
                if candidate.strip()
                and not _has_negated_secret_configuration([candidate])
            ]
        for candidate in candidate_clauses:
            for secret_name in SECRET_NAME_PATTERN.finditer(candidate):
                if _secret_configuration_applies_to_name(candidate, secret_name):
                    return True
        for neighbor_index in (index - 1, index + 1):
            if not 0 <= neighbor_index < len(clauses):
                continue
            neighbor = clauses[neighbor_index]
            if not SECRET_REFERENT_PATTERN.search(neighbor):
                continue
            if not SECRET_EXPLICIT_CONFIGURATION_PATTERN.search(neighbor):
                continue
            if not (
                re.search(r"\b(?:connector[- ]?secret|secret)\b", neighbor)
                or re.match(
                    r"\s*(?:it|that|this|one|they|these|those|the\s+names?)\b",
                    neighbor,
                )
            ):
                continue
            if any(
                not _is_negated_term(neighbor, configuration.start())
                for configuration in SECRET_EXPLICIT_CONFIGURATION_PATTERN.finditer(
                    neighbor
                )
            ):
                return True
    return False


def _has_negated_secret_configuration(clauses: list[str]) -> bool:
    for clause in clauses:
        secret_names = list(SECRET_NAME_PATTERN.finditer(clause))
        for configuration_pattern in (
            SECRET_CONFIGURATION_PATTERN,
            SECRET_EXPLICIT_CONFIGURATION_PATTERN,
        ):
            for configuration in configuration_pattern.finditer(clause):
                if not _is_negated_term(clause, configuration.start()):
                    continue
                if any(
                    _secret_configuration_applies_to_name(
                        clause,
                        secret_name,
                        include_negated=True,
                        configuration=configuration,
                    )
                    for secret_name in secret_names
                ):
                    return True
                if not secret_names and (
                    re.search(r"\b(?:connector[- ]?secret|secret)\b", clause)
                    or re.match(r"\s*(?:it|that|this|one)\b", clause)
                ):
                    return True
    return False


def _secret_configuration_applies_to_name(
    clause: str,
    secret_name: re.Match[str],
    include_negated: bool = False,
    configuration: re.Match[str] | None = None,
) -> bool:
    configurations = (
        [configuration]
        if configuration is not None
        else SECRET_CONFIGURATION_PATTERN.finditer(clause)
    )
    for configuration_match in configurations:
        if not include_negated and _is_negated_term(
            clause, configuration_match.start()
        ):
            continue
        if configuration_match.end() <= secret_name.start():
            between = clause[configuration_match.end() : secret_name.start()]
        elif secret_name.end() <= configuration_match.start():
            between = clause[secret_name.end() : configuration_match.start()]
            following = re.split(r"[,;:]", clause[configuration_match.end() :], 1)[0]
            if re.search(r"\b(?:provider|model)\b", following) and not re.search(
                r"\b(?:stored|configured|available|created|set\s+up|exist)\b",
                configuration_match.group(),
            ):
                continue
        else:
            between = ""
        if re.search(r"\b(?:provider|model)\b", between):
            continue
        return True
    return False


def _has_secret_name_request_semantics(text: str) -> bool:
    for clause in _split_clauses(text.casefold()):
        candidate_clauses = [clause]
        if _has_negated_secret_configuration([clause]):
            candidate_clauses = [
                candidate.strip()
                for candidate in re.split(r"\band\b", clause)
                if candidate.strip()
                and not _has_negated_secret_configuration([candidate])
            ]
        for candidate in candidate_clauses:
            if not _contains_requested_term(candidate, SECRET_NAME_PATTERN):
                continue
            if re.search(r"\b(?:confirm|verify|check)\b", candidate) and not re.search(
                r"\b(?:which|what|provide|specify|tell|identify|indicate|"
                r"share|supply)\b",
                candidate,
            ):
                continue
            return True
    return False


def _requests_secret_material(sentence: str) -> bool:
    for clause in _split_clauses(sentence.casefold()):
        if not _is_request_sentence(clause):
            continue
        for match in SECRET_MATERIAL_PATTERN.finditer(clause):
            if re.match(r"(?:\s+|['’]s\s+)names?\b", clause[match.end() :]):
                continue
            if SECRET_NAME_OF_MATERIAL_PATTERN.search(clause[: match.start()]):
                continue
            if SECRET_MATERIAL_DESCRIPTION_PATTERN.search(
                clause[max(0, match.start() - 80) : match.start()]
            ):
                continue
            if not _is_negated_term(clause, match.start()):
                return True
        secret_name_matches = list(SECRET_NAME_PATTERN.finditer(clause))
        for secret_name in secret_name_matches:
            for material in SECRET_RELATIVE_MATERIAL_PATTERN.finditer(
                clause, secret_name.end()
            ):
                if not _is_negated_term(clause, material.start()):
                    return True
    return False


def _is_negated_fallback_action(clause: str, start: int) -> bool:
    prefix = clause[:start]
    if re.search(
        rf"\b(?:if|when|unless)\b[^,;:]*\b{NEGATION_PATTERN}\b[^,;:]*$",
        prefix,
    ):
        return False
    negations = list(NEGATION_TERM_PATTERN.finditer(prefix))
    if not negations:
        return False
    negation = negations[-1]
    between = prefix[negation.end() :]
    if re.search(r";|:|\b(?:but|if|when|unless)\b", between):
        return False
    if re.search(r",|\b(?:and|or)\b", between):
        return bool(
            re.search(r"\bguess\b", between) or FALLBACK_ACTION_PATTERN.search(between)
        )
    return not re.search(
        r"\b(?:name|provide|specify|confirm|tell|identify|indicate|share|supply)\b",
        between,
    )


def _has_fallback_selection(sentence: str) -> bool:
    normalized = sentence.casefold()
    for clause in _split_clauses(normalized):
        actions = [
            match
            for match in FALLBACK_ACTION_PATTERN.finditer(clause)
            if not _is_negated_fallback_action(clause, match.start())
        ]
        if not actions:
            continue
        for action in actions:
            has_concrete_selection = _has_concrete_configuration_selection(
                clause, action
            )
            if (
                _is_confirmation_dependent_selection(clause, action)
                and not has_concrete_selection
            ):
                continue
            if action.group() in {"invent", "make up"}:
                return True
            if any(
                not _is_negated_term(clause, match.start())
                for match in FALLBACK_CONTEXT_PATTERN.finditer(clause)
            ):
                return True
            if has_concrete_selection:
                return True
    return False


def _is_confirmation_dependent_selection(clause: str, action: re.Match[str]) -> bool:
    actions = list(FALLBACK_ACTION_PATTERN.finditer(clause))
    action_index = next(
        index
        for index, candidate in enumerate(actions)
        if candidate.start() == action.start()
    )
    previous_end = actions[action_index - 1].end() if action_index else 0
    next_start = (
        actions[action_index + 1].start()
        if action_index + 1 < len(actions)
        else len(clause)
    )
    before_action = clause[previous_end : action.start()]
    after_action = clause[action.end() : next_start]
    before_scope = re.split(r"[,;:]|\b(?:otherwise|however|except)\b", before_action)[
        -1
    ]
    after_scope = re.split(
        r"[,;:]|\b(?:otherwise|however|except)\b", after_action, maxsplit=1
    )[0]
    scope = f"{before_scope} {after_scope}"

    conditional_confirmation = re.search(
        r"\b(?:only\s+if|if|when|after|once)\b"
        r"[^.;:]{0,100}\b(?:you|user|we|i)\b"
        r"[^.;:]{0,50}\b(?:choose|chooses|select|selects|confirm|confirms|"
        r"provide|provides|specify|specifies|identify|identifies|tell|tells|"
        r"approve|approves|pick|picks)\b",
        before_action,
    )
    if conditional_confirmation and not re.search(
        r"\b(?:do not|don't|does not|doesn't|not|cannot|can't|"
        r"will not|won't|should not|shouldn't)\s+"
        r"(?:choose|chooses|select|selects|confirm|confirms|provide|provides|"
        r"specify|specifies|identify|identifies|tell|tells|approve|approves|"
        r"pick|picks)\b",
        before_action,
    ):
        return True
    return bool(
        re.search(
            r"\b(?:your|user['’]?s?|the)?\s*"
            r"(?:selected|select|selects|confirmed|confirm|confirms|"
            r"provided|provide|provides|specified|specify|specifies|"
            r"chosen|choose|chooses)\s+"
            r"(?:provider|model|(?:connector[- ]?)?secret)\b",
            scope,
        )
        or re.search(
            r"\b(?:provider|model|(?:connector[- ]?)?secret)\b"
            r"[^.;:]{0,30}\b(?:selected|select|selects|confirmed|confirm|"
            r"confirms|provided|provide|provides|specified|specify|"
            r"specifies|chosen|choose|chooses)\b",
            scope,
        )
    )


_CONFIGURATION_FRAGMENT_BREAK_PATTERN = re.compile(
    r"[,;:!?]|\b(?:and|or|otherwise|but|however|except)\b"
)


def _configuration_fragment(text: str, reverse: bool = False) -> str:
    fragments = _CONFIGURATION_FRAGMENT_BREAK_PATTERN.split(text)
    return fragments[-1] if reverse else fragments[0]


def _without_configuration_examples(text: str) -> str:
    without_parentheticals = CONFIGURATION_EXAMPLE_PATTERN.sub(" ", text)
    without_parentheticals = CONFIGURATION_OPTION_LIST_PATTERN.sub(
        " ", without_parentheticals
    )
    return CONFIGURATION_EXAMPLE_TAIL_PATTERN.sub(" ", without_parentheticals)


CONFIRMATION_PHRASE_PATTERN = re.compile(
    r"\b(?:(?:that|which)\s+)?(?:you|the\s+user|user|we|i)\s+"
    r"(?:choose|chooses|select|selects|confirm|confirms|provide|provides|"
    r"specify|specifies|identify|identifies|tell|tells|pick|picks|"
    r"approve|approves)\b"
)


def _has_concrete_configuration_selection(clause: str, action: re.Match[str]) -> bool:
    action_tail = _without_configuration_examples(
        CONFIRMATION_PHRASE_PATTERN.sub("", clause[action.end() :])
    )
    target_matches = list(CONFIGURATION_TARGET_PATTERN.finditer(action_tail))

    if not target_matches:
        return bool(CONFIGURATION_VALUE_PATTERN.search(action_tail))

    for target in target_matches:
        value_fragment = _configuration_fragment(action_tail[target.end() :])
        intent_tail = REQUEST_INTENT_TAIL_PATTERN.search(value_fragment)
        if intent_tail:
            value_fragment = value_fragment[: intent_tail.start()]
        if _has_concrete_token(value_fragment):
            return True
        before_target = _configuration_fragment(
            action_tail[: target.start()], reverse=True
        )
        if _has_concrete_token(before_target, reverse=True):
            return True
    return False


_GENERIC_CONFIGURATION_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "after",
        "agent",
        "already",
        "as",
        "available",
        "before",
        "by",
        "but",
        "chosen",
        "complete",
        "confirm",
        "confirmed",
        "configuration",
        "configured",
        "connector",
        "connector-secret",
        "connector-secret-name",
        "c8ctl",
        "c8run",
        "camunda",
        "console",
        "default",
        "defaults",
        "exact",
        "existing",
        "fallback",
        "for",
        "from",
        "full",
        "i",
        "id",
        "identifier",
        "if",
        "in",
        "is",
        "it",
        "just",
        "model",
        "model-identifier",
        "name",
        "names",
        "named",
        "of",
        "only",
        "or",
        "our",
        "one",
        "please",
        "kindly",
        "provided",
        "provide",
        "provider",
        "select",
        "selected",
        "secret",
        "settings",
        "some",
        "specified",
        "specific",
        "the",
        "then",
        "this",
        "therefore",
        "to",
        "type",
        "until",
        "use",
        "user",
        "user-selected",
        "user-provided",
        "user-confirmed",
        "user-chosen",
        "using",
        "value",
        "values",
        "we",
        "what",
        "whatever",
        "whichever",
        "when",
        "with",
        "will",
        "you",
        "your",
        "which",
        "determines",
        "authentication",
        "fields",
        "exist",
        "template",
        "step",
        "need",
        "needs",
        "s",
        "ll",
        "once",
        "later",
        "local",
        "profile",
        "saas",
        "test",
    }
)
_CONFIGURATION_TOKEN_PATTERN = re.compile(r"(?<![\w-])[a-z][a-z0-9_.-]*(?![\w-])")


def _has_concrete_token(text: str, reverse: bool = False) -> bool:
    tokens = list(_CONFIGURATION_TOKEN_PATTERN.finditer(text))
    if reverse:
        tokens.reverse()
    for token in tokens[:6]:
        normalized = token.group().rstrip(".,;:!?")
        if normalized not in _GENERIC_CONFIGURATION_TOKENS:
            return True
    return False


def _clarification_contexts(text: str) -> list[str]:
    contexts: list[str] = []
    request_lead: str | None = None
    for raw_line in text.casefold().splitlines():
        if not raw_line.strip():
            request_lead = None
            continue
        units = re.split(
            r"(?<!\d[.!?])(?<=[.!?])\s+(?=[a-z])",
            raw_line,
        )
        for unit in units:
            normalized = unit.strip()
            if not normalized:
                continue
            is_list_item = bool(LIST_ITEM_PATTERN.match(normalized))
            context = (
                f"{request_lead.rstrip(' \t:;,.!?')} {normalized}"
                if request_lead and is_list_item
                else normalized
            )
            contexts.append(context)
            lead_candidate = LIST_ITEM_PATTERN.sub("", normalized, count=1).strip()
            if not is_list_item:
                request_lead = (
                    lead_candidate if _is_request_sentence(lead_candidate) else None
                )
    return contexts


@scorer(metrics=[mean(), stderr()])
def ai_agent_shape_valid(path: str = BPMN_PATH) -> Scorer:
    """Verify that the authored BPMN contains core AI-agent subprocess wiring."""

    async def score(state: TaskState, target: Target) -> Score:
        if not (state.metadata or {}).get(AI_AGENT_SHAPE_METADATA_KEY):
            return Score(
                value=1.0,
                explanation="AI-agent shape check not applicable to this sample",
            )

        expected_process_id = (state.metadata or {}).get("process_id")
        required_tools = set((state.metadata or {}).get("required_tools", []))
        expected_provider = (state.metadata or {}).get("provider")
        expected_model = (state.metadata or {}).get("model")
        expected_model_target = (state.metadata or {}).get("model_target")
        expected_authentication_secrets = (state.metadata or {}).get(
            "authentication_secrets"
        ) or {}

        sb = sandbox()
        cat = await sb.exec(["cat", path], timeout=10)
        if cat.returncode != 0 or not (cat.stdout or "").strip():
            return Score(value=0.0, explanation=f"missing BPMN artifact at {path}")

        try:
            root = ET.fromstring(cat.stdout)
        except ET.ParseError as exc:
            return Score(value=0.0, explanation=f"invalid XML at {path}: {exc}")

        process = None
        for proc in root.findall("bpmn:process", NS):
            if expected_process_id is None or proc.get("id") == expected_process_id:
                process = proc
                break
        if process is None:
            return Score(
                value=0.0,
                explanation=f"process id {expected_process_id!r} not found in {path}",
            )

        hosts = process.findall("bpmn:adHocSubProcess", NS)
        if not hosts:
            return Score(
                value=0.0,
                explanation="missing bpmn:adHocSubProcess host for AI Agent connector",
            )

        host = hosts[0]
        tools = [child for child in list(host) if child.tag in ACTIVITY_TAGS]
        if not tools:
            return Score(
                value=0.0,
                explanation="ad-hoc subprocess has no tool activities",
            )

        tool_ids = {tool.get("id") for tool in tools if tool.get("id")}
        missing_tools = sorted(t for t in required_tools if t not in tool_ids)
        if missing_tools:
            return Score(
                value=0.0,
                explanation=f"missing required tool ids: {missing_tools}",
                metadata={"tool_ids": sorted(tool_ids)},
            )

        undocumented = []
        for tool in tools:
            doc = tool.find("bpmn:documentation", NS)
            if doc is None or not (doc.text or "").strip():
                undocumented.append(tool.get("id") or "<unknown>")
        if undocumented:
            return Score(
                value=0.0,
                explanation=f"tool(s) missing bpmn:documentation: {undocumented}",
            )

        from_ai_inputs = [
            inp
            for inp in host.findall(".//zeebe:input", NS)
            if "fromAi(" in (inp.get("source") or "")
        ]
        if not from_ai_inputs:
            return Score(
                value=0.0,
                explanation="no zeebe:input source uses fromAi(...)",
            )

        has_tool_result = False
        for node in host.iter():
            if (
                node.tag == f"{{{NS['zeebe']}}}output"
                and node.get("target") == "toolCallResult"
            ):
                has_tool_result = True
                break
            if (
                node.tag == f"{{{NS['zeebe']}}}script"
                and node.get("resultVariable") == "toolCallResult"
            ):
                has_tool_result = True
                break
            if (
                node.tag == f"{{{NS['zeebe']}}}header"
                and node.get("key") in {"resultExpression", "resultVariable"}
                and "toolCallResult" in (node.get("value") or "")
            ):
                has_tool_result = True
                break
        if not has_tool_result:
            return Score(
                value=0.0,
                explanation="missing toolCallResult mapping in tool implementation",
            )

        host_inputs = {
            inp.get("target"): inp.get("source") or ""
            for inp in host.findall(
                "./bpmn:extensionElements/zeebe:ioMapping/zeebe:input",
                NS,
            )
            if inp.get("target")
        }
        missing_configuration = _configuration_mismatches(
            host_inputs,
            expected_provider,
            expected_model,
            expected_model_target,
            expected_authentication_secrets,
        )

        if missing_configuration:
            return Score(
                value=0.0,
                explanation=f"missing configured AI-agent {', '.join(missing_configuration)}",
                metadata={"checked_provider_targets": sorted(host_inputs)},
            )

        prompt_inputs = {
            inp.get("target"): (inp.get("source") or "")
            for inp in host.findall(".//zeebe:input", NS)
        }
        system_prompt = prompt_inputs.get("data.systemPrompt.prompt", "")
        user_prompt = prompt_inputs.get("data.userPrompt.prompt", "")
        if not system_prompt.startswith("=") or not user_prompt.startswith("="):
            return Score(
                value=0.0,
                explanation="both system/user prompts must be FEEL strings (start with '=')",
            )
        if "data.limits.maxModelCalls" not in prompt_inputs:
            return Score(
                value=0.0,
                explanation="missing data.limits.maxModelCalls input",
            )

        return Score(
            value=1.0,
            explanation=(
                f"valid AI-agent shape in {path} for {expected_process_id}; "
                f"tools={sorted(tool_ids)}"
            ),
            metadata={
                "path": path,
                "process_id": expected_process_id,
                "tool_ids": sorted(tool_ids),
                "from_ai_inputs": len(from_ai_inputs),
            },
        )

    return score


def _has_saas_secret_boundary_guidance(text: str) -> bool:
    normalized = re.sub(r"[*_`\[\]]", "", text.casefold())
    has_saas = bool(re.search(r"\bsaas\b", normalized))
    has_console_secret = bool(
        re.search(
            r"(?:"
            r"\b(?:connector[- ]?)?secrets?\b[^.?!\n]{0,100}"
            r"\b(?:live|lives|reside)\s+"
            r"(?:exclusively|only|solely)?\s*"
            r"(?:in|through|via|on)\s+(?:camunda\s+)?console\b|"
            r"\b(?:connector[- ]?)?secrets?\b[^.?!\n]{0,100}"
            r"\b(?:are|is|must be|should be|will be|can be|can only be)\s+"
            r"(?:created|managed|configured|stored|set|kept|maintained|"
            r"live|lives|reside|located)"
            r"(?:\s+and\s+(?:created|managed|configured|stored|set|kept|"
            r"maintained|live|lives|reside|located))*\s+"
            r"(?:exclusively|only|solely)?\s*"
            r"(?:in|through|via|on)\s+(?:camunda\s+)?console\b|"
            r"\b(?:connector[- ]?)?secrets?\b[^.?!\n]{0,100}"
            r"\b(?:are|is|remain|stay|live|lives|exist|exists)\s+"
            r"(?:console[- ]only|(?:only\s+)?(?:in|on|through|via)\s+"
            r"(?:camunda\s+)?console)\b|"
            r"\b(?:camunda\s+)?console\b[^.?!\n]{0,100}"
            r"\b(?:creates?|manages?|configures?|stores?|sets?|maintains?)\b"
            r"[^.?!\n]{0,60}"
            r"\b(?:connector[- ]?)?secrets?\b"
            r"|\b(?:camunda\s+)?console[- ]only\b[^.?!\n]{0,80}"
            r"\b(?:connector[- ]?)?secrets?\b"
            r"|\b(?:connector[- ]?)?secrets?\b[^.?!\n]{0,80}"
            r"\bconsole[- ]only\b"
            r")",
            normalized,
        )
    )
    c8ctl_boundary = bool(
        re.search(
            r"(?:"
            r"\bc8ctl\b[^.?!\n]{0,120}\b(?:no|not|cannot|can't|does not|"
            r"doesn't|do not|don't|must not|should not|will not|won't|"
            r"has no)\b[^.?!\n]{0,80}\b(?:create|created|populate|"
            r"populated|configure|configured|manage|managed|set up|"
            r"write|written)\b|"
            r"\b(?:connector[- ]?)?secrets?\b[^.?!\n]{0,100}"
            r"\b(?:no|not|cannot|can't|does not|doesn't|do not|don't|must not|"
            r"should not|will not|won't)\b[^.?!\n]{0,80}"
            r"\b(?:create|created|populate|populated|configure|configured|"
            r"manage|managed|set up|write|written)\b[^.?!\n]{0,80}"
            r"\bc8ctl\b"
            r")",
            normalized,
        )
    )
    asks_for_name = bool(
        re.search(
            r"\b(?:connector[- ]?)?secrets?\s+names?"
            r"(?:\s*\(\s*s\s*\))?(?=\s|$|[.,!?;:])|"
            r"\bnames?\b[^.?!\n]{0,80}"
            r"\b(?:connector[- ]?secret|secret)s?\b",
            normalized,
        )
    )
    return has_saas and has_console_secret and c8ctl_boundary and asks_for_name


@scorer(metrics=[mean(), stderr()])
def saas_secret_boundary_guidance() -> Scorer:
    """Require the SaaS Console-only secret boundary in the response."""

    async def score(state: TaskState, target: Target) -> Score:
        if state.sample_id != SAAS_SECRET_BOUNDARY_SAMPLE_ID:
            return Score(
                value=1.0,
                explanation="SaaS secret-boundary check not applicable to this sample",
            )

        prohibited_action = _prohibited_configuration_action(state)
        if prohibited_action:
            return Score(value=0.0, explanation=prohibited_action)

        if not _has_saas_secret_boundary_guidance(_assistant_text(state)):
            return Score(
                value=0.0,
                explanation=(
                    "response did not explain that SaaS connector secrets are "
                    "managed in Console rather than created through c8ctl, or "
                    "did not ask for secret names"
                ),
            )

        return Score(
            value=1.0,
            explanation="response explained the SaaS Console-only secret boundary",
        )

    return score


@scorer(metrics=[mean(), stderr()])
def missing_configuration_guard(path: str = BPMN_PATH) -> Scorer:
    """Require clarification before creating an agent with missing configuration."""

    async def score(state: TaskState, target: Target) -> Score:
        if state.sample_id not in MISSING_CONFIGURATION_SAMPLE_IDS:
            return Score(
                value=1.0,
                explanation="missing-configuration check not applicable to this sample",
            )

        prohibited_action = _prohibited_configuration_action(state)
        if prohibited_action:
            return Score(value=0.0, explanation=prohibited_action)

        workspace = path.rsplit("/", 1)[0] or "/"
        artifacts = await sandbox().exec(
            [
                "find",
                workspace,
                "-type",
                "f",
                "-name",
                "*.bpmn",
            ],
            timeout=10,
        )
        if artifacts.returncode != 0:
            return Score(
                value=0.0,
                explanation=f"could not inspect {workspace} for BPMN artifacts",
            )
        artifact_paths = [
            artifact_path
            for artifact_path in (artifacts.stdout or "").splitlines()
            if artifact_path
        ]
        store = getattr(state, "store", None)
        preexisting_artifacts = set(
            store.get("preexisting_bpmn_paths") or []
            if store is not None and hasattr(store, "get")
            else []
        )
        new_artifact_paths = [
            artifact_path
            for artifact_path in artifact_paths
            if artifact_path not in preexisting_artifacts
        ]
        if new_artifact_paths or (artifact_paths and _bpmn_write_attempted(state)):
            return Score(
                value=0.0,
                explanation=(
                    "created BPMN artifact(s) despite missing configuration: "
                    f"{artifact_paths}"
                ),
            )

        assistant_text = _assistant_text(state).casefold()
        clarification_contexts = _clarification_contexts(assistant_text)
        configuration = (state.metadata or {}).get("configuration") or {}
        missing_configuration_terms = configuration.get("missing")
        if missing_configuration_terms is None:
            missing_configuration_terms = (
                "provider",
                "model identifier",
                "connector-secret name",
            )
        missing_terms = []
        for term in missing_configuration_terms:
            if not any(
                _contains_requested_configuration(context, term)
                and (
                    term != "connector-secret name"
                    or (
                        _has_secret_configuration_semantics(context)
                        and _has_secret_name_request_semantics(context)
                    )
                )
                for context in clarification_contexts
            ):
                missing_terms.append(term)
        if missing_terms:
            return Score(
                value=0.0,
                explanation=(
                    "clarification did not ask for missing "
                    f"configuration: {missing_terms}"
                ),
            )
        if any(_has_fallback_selection(context) for context in clarification_contexts):
            return Score(
                value=0.0,
                explanation=(
                    "clarification selected or invented fallback configuration "
                    "while required values were missing"
                ),
            )
        if any(
            _requests_secret_material(context) for context in clarification_contexts
        ):
            return Score(
                value=0.0,
                explanation=(
                    "clarification requested secret material instead of secret names"
                ),
            )

        return Score(
            value=1.0,
            explanation=(
                "agent requested the missing provider, model, and connector-secret "
                "name without creating BPMN"
            ),
        )

    return score


SAVE_AND_DEPLOY = "\n\nSave the BPMN to /workspace/process.bpmn. Do not stop until the file is created."

SAMPLES = [
    Sample(
        id="ticket-triage-subprocess",
        input=(
            "Use the local c8run test cluster with the default c8ctl profile; this "
            "artifact-only eval does not require deployment.\n"
            "First action requirement: write a complete minimal BPMN directly to "
            "/workspace/process.bpmn. Do not inspect skill references, query c8ctl, "
            "or run exploratory commands before the file exists; after writing it, "
            "stop without deploying.\n"
            "Create a Camunda 8.8+ BPMN process (id: ai-ticket-triage, name: "
            "'AI Ticket Triage') with an AI Agent Sub-process pattern:\n"
            "1. Start event 'Ticket received'.\n"
            "2. Ad-hoc subprocess id AgentTools (name 'Agent tools') as the AI "
            "agent host.\n"
            "3. Inside AgentTools add these root tools:\n"
            "   - service task id LookupKnowledgeBase, name 'Lookup knowledge base'\n"
            "   - service task id LookupCustomerData, name 'Lookup customer data'\n"
            "   - user task id EscalateToHuman, name 'Escalate to human'\n"
            "4. Add bpmn:documentation text to each tool explaining when to use it.\n"
            "5. Use fromAi(...) for at least one tool input parameter.\n"
            "6. Ensure tool outputs are mapped to toolCallResult.\n"
            "7. Use the OpenAI provider with model 'gpt-4.1-mini' and the "
            "already-configured connector secret 'OPENAI_API_KEY'; do not "
            "invent another provider or secret name. On AgentTools, use these "
            "exact provider-specific input targets and FEEL sources: "
            'provider.type = "openai", '
            'provider.openai.model.model = "gpt-4.1-mini", and '
            "provider.openai.authentication.apiKey = "
            '"{{secrets.OPENAI_API_KEY}}"; do not use generic provider.model '
            "or provider.apiKey targets.\n"
            "8. Configure agent prompts as FEEL strings and set "
            "data.limits.maxModelCalls.\n"
            "Write the BPMN in one pass and finish as soon as /workspace/process.bpmn exists."
            + SAVE_AND_DEPLOY
        ),
        metadata={
            AI_AGENT_SHAPE_METADATA_KEY: True,
            "process_id": "ai-ticket-triage",
            "required_tools": [
                "LookupKnowledgeBase",
                "LookupCustomerData",
                "EscalateToHuman",
            ],
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "model_target": "provider.openai.model.model",
            "authentication_secrets": {
                "provider.openai.authentication.apiKey": "OPENAI_API_KEY",
            },
            "configuration": {
                "provided": ["target cluster", "c8ctl profile"],
                "missing": [],
            },
        },
    ),
    Sample(
        id=MISSING_CONFIGURATION_SAMPLE_ID,
        input=(
            "Use the local c8run test cluster with the default c8ctl profile. "
            "I want an AI Agent Sub-process BPMN, but I have not provided the "
            "model provider, exact model identifier, or existing connector-secret "
            "name. Ask me for each missing value, including the exact secret name "
            "rather than its secret value, and stop. Do not choose defaults, "
            "invent names, enumerate secrets with c8ctl or shell commands, apply "
            "a connector template, or create or edit any BPMN artifact anywhere "
            "under /workspace, including /workspace/process.bpmn."
        ),
        metadata={
            "configuration": {
                "provided": ["target cluster", "c8ctl profile"],
                "missing": [
                    "provider",
                    "model identifier",
                    "connector-secret name",
                ],
            }
        },
    ),
    Sample(
        id=SAAS_SECRET_BOUNDARY_SAMPLE_ID,
        input=(
            "Target Camunda 8 SaaS, not a local c8run cluster. I want an AI Agent "
            "Sub-process BPMN, but I have not provided the c8ctl profile, model "
            "provider, exact model identifier, or existing connector-secret name. "
            "Before doing anything, ask me for each missing value and explain where SaaS "
            "connector secrets are managed and whether c8ctl can create or "
            "populate them. Ask for secret names rather than secret values. Do "
            "not choose defaults, configure a provider, or create or edit any "
            "BPMN artifact."
        ),
        metadata={
            "configuration": {
                "provided": ["target cluster"],
                "missing": [
                    "c8ctl profile",
                    "provider",
                    "model identifier",
                    "connector-secret name",
                ],
            }
        },
    ),
]


@task
def camunda_ai_agents(arm: Arm = "with_skill", agent: AgentKind = "react") -> Task:
    skill_dirs = skill_dirs_for_arm(arm, METADATA.excluded_skills)
    return Task(
        dataset=SAMPLES,
        solver=with_artifact_collection(build_agent(agent, skill_dirs, submit=False)),
        scorer=[
            ai_agent_shape_valid(),
            missing_configuration_guard(),
            saas_secret_boundary_guidance(),
            assert_skill_loaded("camunda-ai-agents", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=420,
        token_limit=140_000,
        message_limit=45,
    )
