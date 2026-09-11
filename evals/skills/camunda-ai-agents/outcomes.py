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
    r"(?:provide|specify|confirm|tell me|let me know|identify|indicate|share|supply)"
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
    r"\b(?:i|we)(?:['’](?:ll|d))?\s+(?:need|require)\s+(?:"
    r"(?:(?:your|the|an?|some|each|exact|specific|full|complete|existing|already|configured|available)\s+){0,5}"
    r"(?:provider|model|connector[- ]?secret|secret|api[- ]?key|tokens?|"
    r"credentials?|passwords?)\b|"
    r"(?:you\s+to\s+)?(?:provide|specify|confirm|tell(?:\s+me)?|identify|"
    r"indicate|share|supply)\b|"
    r"to\s+know\b|"
    r"(?:details?|information|confirmation|names?)\s+(?:about|for|of)\b"
    r")"
)
SECRET_NAME_PATTERN = re.compile(
    r"(?:"
    r"\b(?:connector[- ]secret|secret)s?\s+names?\b"
    r"|\bnames?\b[^.?!\n]{0,80}\b(?:connector[- ]secret|secret)s?\b"
    r"|\b(?:which|what)\b[^.?!\n]{0,80}\b(?:connector[- ]secret|secret)s?\b"
    r"|\b(?:connector[- ]secret|secret)s?\b[^.?!\n]{0,80}"
    r"\b(?:should|would|do)\s+i\s+use\b"
    r")"
)
SECRET_CONFIGURATION_PATTERN = re.compile(
    r"\b(?:"
    r"existing|configured|preconfigured|available|"
    r"already\s+(?:configured|set\s+up|created|available|exist(?:s)?)|"
    r"(?:must|needs?\s+to|has\s+to|have\s+to)\s+(?:already\s+)?"
    r"(?:exist(?:s)?|be\s+(?:configured|preconfigured|available|created|set\s+up|existing))|"
    r"in\s+(?:the\s+)?(?:cluster|environment|profile|console)"
    r")\b"
)
SECRET_EXPLICIT_CONFIGURATION_PATTERN = re.compile(
    r"\b(?:"
    r"already\s+(?:configured|set\s+up|created|available|exists?)|"
    r"(?:is|are|was|were)\s+(?:already\s+)?"
    r"(?:configured|preconfigured|available|created|set\s+up|existing)|"
    r"(?:(?:should|would)\s+(?:already\s+)?"
    r"(?:exist(?:s)?|be\s+(?:configured|preconfigured|available|created|set\s+up|existing)))|"
    r"(?:must|needs?\s+to|has\s+to|have\s+to)\s+(?:already\s+)?"
    r"(?:exist(?:s)?|be\s+(?:configured|preconfigured|available|created|set\s+up|existing))|"
    r"(?:configured|preconfigured|available)\s+"
    r"(?:in|on)\s+(?:the\s+)?(?:cluster|environment|profile|console)"
    r")\b"
)
SECRET_MATERIAL_PATTERN = re.compile(
    r"\b(?:"
    r"secret\s+values?|secret\s+material|secret[- ]+keys?|"
    r"api\s+keys?|access\s+keys?|tokens?|credentials?|passwords?|"
    r"private\s+keys?|"
    r"(?:value|contents?)\s+of\s+(?:(?:the|an?|your)\s+)?"
    r"(?:(?:existing|configured|preconfigured|already[- ]configured)\s+)?"
    r"(?:connector[- ]?secret|secret)s?"
    r")\b"
)
SECRET_RELATIVE_MATERIAL_PATTERN = re.compile(
    r"\b(?:its|their|the|that|this)?\s*"
    r"(?:secret\s+)?(?:value|contents?)\b"
)
NEGATION_PATTERN = (
    r"(?:do not|don't|never|not|without|rather than|instead of|"
    r"will not|won't|should not|shouldn't|cannot|can't|can not)"
)
NEGATION_TERM_PATTERN = re.compile(rf"\b{NEGATION_PATTERN}\b")
NEGATED_TERM_PREFIX_PATTERN = re.compile(
    rf"\b{NEGATION_PATTERN}\b[^,;:?.!\n]*$"
)
FALLBACK_CONTEXT_PATTERN = re.compile(
    r"\b(?:"
    r"fallback|otherwise|"
    r"defaults?|"
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
    r"suggest|recommend|propose|go\s+with)\b"
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
    r"[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*(?:api[-_]?key|access[-_]?key|"
    r"token|secret|password)"
    r")(?![\w-])"
)
MODEL_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:"
    r"(?:exact|specific|full|complete)\s+model"
    r"(?:\s+(?:identifier|id|name))?|"
    r"model\s+(?:identifier|id|name)|"
    r"model['’]s\s+(?:exact\s+)?(?:identifier|id|name)"
    r")\b"
)
LIST_ITEM_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
CLAUSE_BREAK_PATTERN = re.compile(
    r"[.!?;\n]+|\b(?:but|however|except)\b"
)
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


def _prohibited_configuration_action(state: TaskState) -> str | None:
    for message in state.messages:
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = (getattr(tool_call, "function", "") or "").casefold()
            arguments = getattr(tool_call, "arguments", None) or {}
            serialized = f"{function} {arguments}".casefold()
            command = str(arguments.get("command", "")).casefold()
            path = str(arguments.get("path", "")).casefold()
            shell_input = " ".join(
                str(arguments.get(argument_name, ""))
                for argument_name in ("input", "cmd", "command")
            ).casefold()

            if re.search(r"\bc8ctl\b.*\belement-template\s+apply\b", serialized):
                return "applied an element template before configuration was confirmed"

            if command in {"create", "str_replace", "insert"} and path.endswith(".bpmn"):
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
    return any(
        pattern.search(clause) and _is_request_sentence(clause)
        for clause in _split_clauses(text.casefold())
    )


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
    if _has_negated_secret_configuration(clauses):
        return False

    for index, clause in enumerate(clauses):
        for secret_name in SECRET_NAME_PATTERN.finditer(clause):
            if _secret_configuration_applies_to_name(clause, secret_name):
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
                if (
                    not secret_names
                    and (
                        re.search(
                            r"\b(?:connector[- ]?secret|secret)\b", clause
                        )
                        or re.match(r"\s*(?:it|that|this|one)\b", clause)
                    )
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
            following = re.split(
                r"[,;:]", clause[configuration_match.end() :], 1
            )[0]
            if re.search(r"\b(?:provider|model)\b", following):
                continue
        else:
            between = ""
        if re.search(r"\b(?:provider|model)\b", between):
            continue
        return True
    return False


def _has_secret_name_request_semantics(text: str) -> bool:
    return _contains_requested_term(text, SECRET_NAME_PATTERN)


def _requests_secret_material(sentence: str) -> bool:
    for clause in _split_clauses(sentence.casefold()):
        if not _is_request_sentence(clause):
            continue
        for match in SECRET_MATERIAL_PATTERN.finditer(clause):
            if re.match(r"\s+names?\b", clause[match.end() :]):
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
    if re.search(r"[,;:]|\b(?:and|but|if|when|unless)\b", between):
        return False
    return not re.search(
        r"\b(?:provide|specify|confirm|tell|identify|indicate|share|supply)\b",
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
            if _is_confirmation_dependent_selection(clause, action):
                continue
            if action.group() in {"invent", "make up"}:
                return True
            if any(
                not _is_negated_term(clause, match.start())
                for match in FALLBACK_CONTEXT_PATTERN.finditer(clause)
            ):
                return True
            if _has_concrete_configuration_selection(clause, action):
                return True
    return False


def _is_confirmation_dependent_selection(
    clause: str, action: re.Match[str]
) -> bool:
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
    before_scope = re.split(
        r"[,;:]|\b(?:otherwise|however|except)\b", before_action
    )[-1]
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
            r"(?:selected|confirmed|provided|specified|chosen)\s+"
            r"(?:provider|model|(?:connector[- ]?)?secret)\b",
            scope,
        )
        or re.search(
            r"\b(?:provider|model|(?:connector[- ]?)?secret)\b"
            r"[^.;:]{0,30}\b(?:selected|confirmed|provided|specified|chosen)\b",
            scope,
        )
    )


_CONFIGURATION_FRAGMENT_BREAK_PATTERN = re.compile(
    r"[,;:!?]|\b(?:and|or|otherwise|but|however|except)\b"
)


def _configuration_fragment(text: str, reverse: bool = False) -> str:
    fragments = _CONFIGURATION_FRAGMENT_BREAK_PATTERN.split(text)
    return fragments[-1] if reverse else fragments[0]


def _has_concrete_configuration_selection(
    clause: str, action: re.Match[str]
) -> bool:
    action_tail = clause[action.end() :]
    target_matches = list(CONFIGURATION_TARGET_PATTERN.finditer(action_tail))

    if CONFIGURATION_VALUE_PATTERN.search(action_tail):
        return True

    for target in target_matches:
        if _has_concrete_token(_configuration_fragment(action_tail[target.end() :])):
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
        "default",
        "defaults",
        "exact",
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
        "name",
        "names",
        "named",
        "of",
        "only",
        "or",
        "our",
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
        "to",
        "type",
        "until",
        "use",
        "user",
        "using",
        "value",
        "values",
        "we",
        "when",
        "with",
        "you",
        "your",
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
    previous_context: str | None = None
    for raw_line in text.casefold().splitlines():
        if not raw_line.strip():
            previous_context = None
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
                f"{request_lead} {normalized}"
                if request_lead and is_list_item
                else normalized
            )
            contexts.append(context)
            if previous_context and not is_list_item:
                contexts.append(f"{previous_context} {context}")
            lead_candidate = LIST_ITEM_PATTERN.sub("", normalized, count=1).strip()
            if normalized.endswith(":") and _is_request_sentence(lead_candidate):
                request_lead = lead_candidate
            elif not is_list_item:
                request_lead = None
            previous_context = context
    return contexts


@scorer(metrics=[mean(), stderr()])
def ai_agent_shape_valid(path: str = BPMN_PATH) -> Scorer:
    """Verify that the authored BPMN contains core AI-agent subprocess wiring."""

    async def score(state: TaskState, target: Target) -> Score:
        if state.sample_id != "ticket-triage-subprocess":
            return Score(
                value=1.0,
                explanation="AI-agent shape check not applicable to this sample",
            )

        expected_process_id = (state.metadata or {}).get("process_id")
        required_tools = set((state.metadata or {}).get("required_tools", []))
        expected_provider = (state.metadata or {}).get("provider")
        expected_model = (state.metadata or {}).get("model")
        expected_model_target = (state.metadata or {}).get("model_target")
        expected_authentication_secrets = (
            (state.metadata or {}).get("authentication_secrets") or {}
        )

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
        missing_configuration = []
        if expected_provider:
            provider_source = host_inputs.get("provider.type")
            if _normalize_literal(provider_source) != expected_provider:
                missing_configuration.append("provider")

        if expected_model:
            if not expected_model_target:
                missing_configuration.append("model target metadata")
            elif (
                _normalize_literal(host_inputs.get(expected_model_target))
                != expected_model
            ):
                missing_configuration.append("model")

        for secret_target, expected_secret in expected_authentication_secrets.items():
            if not _matches_secret_reference(
                host_inputs.get(secret_target, ""), expected_secret
            ):
                missing_configuration.append(f"connector secret ({secret_target})")

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


@scorer(metrics=[mean(), stderr()])
def missing_configuration_guard(path: str = BPMN_PATH) -> Scorer:
    """Require clarification before creating an agent with missing configuration."""

    async def score(state: TaskState, target: Target) -> Score:
        if state.sample_id != MISSING_CONFIGURATION_SAMPLE_ID:
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
                "-not",
                "-path",
                f"{workspace}/skills/*",
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
        if artifact_paths:
            return Score(
                value=0.0,
                explanation=(
                    "created BPMN artifact(s) despite missing configuration: "
                    f"{artifact_paths}"
                ),
            )

        assistant_text = _assistant_text(state).casefold()
        clarification_contexts = _clarification_contexts(assistant_text)
        missing_terms = []
        for term, pattern in (
            ("provider", re.compile(r"\bprovider\b")),
            ("model identifier", MODEL_IDENTIFIER_PATTERN),
            ("connector-secret name", SECRET_NAME_PATTERN),
        ):
            if not any(
                _contains_requested_term(context, pattern)
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
        if any(_requests_secret_material(context) for context in clarification_contexts):
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


SAVE_AND_DEPLOY = (
    "\n\nSave the BPMN to /workspace/process.bpmn. Do not stop until the file is created."
)

SAMPLES = [
    Sample(
        id="ticket-triage-subprocess",
        input=(
            "Use the local c8run test cluster with the default c8ctl profile; this "
            "artifact-only eval does not require deployment.\n"
            "Immediately create /workspace/process.bpmn first (do not do exploratory reads).\n"
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
            "invent another provider or secret name.\n"
            "8. Configure agent prompts as FEEL strings and set "
            "data.limits.maxModelCalls.\n"
            "Write the BPMN in one pass and finish as soon as /workspace/process.bpmn exists."
            + SAVE_AND_DEPLOY
        ),
        metadata={
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
            "invent names, apply a connector template, or create or edit any BPMN "
            "artifact anywhere under /workspace, including /workspace/process.bpmn."
        ),
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
            assert_skill_loaded("camunda-ai-agents", gating=False),
        ],
        sandbox=("docker", str(SANDBOXES_DIR / "compose-with-c8ctl.yaml")),
        metadata=METADATA.model_dump(),
        time_limit=420,
        token_limit=140_000,
        message_limit=45,
    )
