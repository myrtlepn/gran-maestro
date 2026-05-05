#!/usr/bin/env python3
import fnmatch
import hashlib
import json
import os
import re
import secrets
import shlex
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ZERO_HASH = "0" * 64
LLM_MST_CLI_RULE_ID = "MST-LLM-MST-CLI-BLOCK"
ANSI_C_QUOTING_SENTINEL = "__ANSI_C_QUOTING_DETECTED__"
PROCESS_SUBSTITUTION_SENTINEL = "__PROCESS_SUBSTITUTION_DETECTED__"
EXECUTION_SINK_SUBSTITUTION_SENTINEL = "__EXECUTION_SINK_SUBSTITUTION_DETECTED__"
MUTATING_RE = re.compile(r"(^|[ \t;|&])(rm|mv|cp|mkdir|rmdir|truncate|chmod|chown|touch|tee)([ \t]|$)")
INLINE_MUTATING_RE = re.compile(r"(^|[ \t;|&])((sed[ \t]+-i)|(perl[ \t]+-pi))([ \t]|$)")
SESSION_RENAME_RE = re.compile(r"(^|[ \t;|&])(mkdir|mv|rename)([ \t]|$)")
PROCESS_SUBSTITUTION_RE = re.compile(r"<\s*<\(")
COMMAND_SEPARATORS = {";", "|", "||", "&&", "&"}
TEXT_COMMANDS = {"echo", "printf", "grep", "cat", "head", "tail", "less", "man", "cmp", "diff"}
ALLOWLIST = {
    "tool_match",
    "arg_pattern",
    "history_exists",
    "history_not_exists_after",
    "path_protected",
}
PROTECTED_PATH_PATTERNS = (
    ".gran-maestro/sessions/**",
    ".gran-maestro/policy/**",
    "~/.claude/gran-maestro-policy/**",
)
ALLOWLIST_PROTECTED_TARGET_TOOLS = {"Write", "Edit", "MultiEdit"}
PHASE_GATE_RULE_ID = "GM-PHASE-GATE"
PHASE_MUTATING_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
PHASE_READONLY_COMMANDS = {
    "cat",
    "date",
    "echo",
    "env",
    "file",
    "grep",
    "head",
    "id",
    "ls",
    "printf",
    "pwd",
    "stat",
    "tail",
    "wc",
    "which",
    "whoami",
}
PHASE_READONLY_GIT_COMMANDS = {"branch", "diff", "log", "show", "status"}
PHASE_READONLY_MST_SKILLS = {"mst:approve", "mst:request"}
PHASE_FIND_MUTATING_OPTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint", "-fprint0"}
SCHEDULE_WAKEUP_BLOCK_RULE_ID = "MST-SCHEDULE-WAKEUP-BLOCK"
SCHEDULE_WAKEUP_BLOCK_REASON = (
    "ScheduleWakeup is blocked during MST workflow chain (workflow_active=true).\n"
    "Sprint/task progression must continue in-turn. Do not wait or end the turn.\n"
    "If the turn must end due to external interruption, instruct the user to run\n"
    "`/mst:resume` or use `scripts/mst-loop.sh`. Do not schedule a wakeup."
)
SCHEDULE_WAKEUP_RESUME_HINT = (
    "[mst] ScheduleWakeup이 차단되었습니다. 'scripts/mst-loop.sh' 또는 '/mst:resume'으로 재개하세요."
)
ASK_USER_QUESTION_BLOCK_RULE_ID = "MST-ASK-USER-QUESTION-BLOCK"
ASK_USER_QUESTION_BLOCK_REASON = (
    "AskUserQuestion is blocked during MST workflow chain (workflow_active=true).\n"
    "This is an attempted user-wait boundary transition; continue the queued MST action instead."
)
SCHEDULE_WAKEUP_STATE_TTL_SECONDS = 30 * 60
SCHEDULE_WAKEUP_GRACE_SECONDS = 30
PHASE_MUTATING_PYTHON_RE = re.compile(
    r"("
    r"\bopen\s*\([^)]*,\s*['\"][^'\"]*[wax+][^'\"]*['\"]|"
    r"\b(write_text|write_bytes|unlink|remove|rename|replace|rmdir|mkdir)\s*\(|"
    r"\bos\.(remove|unlink|rename|replace|rmdir|mkdir)\s*\(|"
    r"\bshutil\.(rmtree|move|copy|copyfile|copytree)\s*\("
    r")",
    re.IGNORECASE,
)
PHASE_SHELL_SEPARATORS = {";", "&&", "||", "|", "|&"}
PHASE_SHELL_CONTROL_TOKENS = {"(", ")", "{", "}"}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stderr(message: str) -> None:
    print(message, file=sys.stderr)


def block(prefix: str, rule_id: str, message: str) -> int:
    stderr(f"[{prefix}] rule={rule_id} {message}")
    return 2


def command_basename(token: str) -> str:
    return Path(token).name


def shell_tokens(command: str) -> Optional[List[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def shell_tokens_with_operators(command: str) -> List[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return re.findall(r"[^\s;|&]+|&&|\|\||[;|<>]", command)


def is_env_assignment(token: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token))


def is_mst_command_token(token: str) -> bool:
    return command_basename(token) == "mst"


def is_mst_script_token(token: str) -> bool:
    return command_basename(token) == "mst.py"


def is_python_token(token: str) -> bool:
    name = command_basename(token)
    return bool(re.match(r"^python[0-9.]*$", name))


def is_shell_wrapper_token(token: str) -> bool:
    return command_basename(token) in {"bash", "sh", "zsh", "dash", "ksh"}


def blocked_mst_sequence(tokens: List[str], command_index: int = 0) -> Optional[str]:
    if command_index >= len(tokens):
        return None

    token = tokens[command_index]
    rest = tokens[command_index + 1 :]
    if is_mst_command_token(token) or is_mst_script_token(token):
        if rest[:1] == ["confirm"]:
            return "mst confirm"
        if rest[:2] == ["hook", "allow"]:
            return "mst hook allow"
        if len(rest) >= 2 and rest[0] == "policy" and rest[1] in {"edit", "install"}:
            return f"mst policy {rest[1]}"

    if is_python_token(token):
        for module_index in range(command_index + 1, len(tokens) - 2):
            if tokens[module_index] == "-m" and tokens[module_index + 1] == "mst":
                rest = tokens[module_index + 2 :]
                if rest[:1] == ["confirm"]:
                    return "mst confirm"
                if rest[:2] == ["hook", "allow"]:
                    return "mst hook allow"
                if len(rest) >= 2 and rest[0] == "policy" and rest[1] in {"edit", "install"}:
                    return f"mst policy {rest[1]}"
        for script_index in range(command_index + 1, len(tokens)):
            if tokens[script_index].startswith("-"):
                continue
            if not is_mst_script_token(tokens[script_index]):
                return None
            rest = tokens[script_index + 1 :]
            if rest[:1] == ["confirm"]:
                return "mst confirm"
            if rest[:2] == ["hook", "allow"]:
                return "mst hook allow"
            if len(rest) >= 2 and rest[0] == "policy" and rest[1] in {"edit", "install"}:
                return f"mst policy {rest[1]}"
            return None
    return None


def has_blocked_mst_words(tokens: List[str]) -> bool:
    for index, token in enumerate(tokens):
        rest = tokens[index + 1 :]
        if (is_mst_command_token(token) or is_mst_script_token(token)) and (
            rest[:1] == ["confirm"]
            or rest[:2] == ["hook", "allow"]
            or (len(rest) >= 2 and rest[0] == "policy" and rest[1] in {"edit", "install"})
        ):
            return True
        if is_python_token(token) and blocked_mst_sequence(tokens, index):
            return True
    return False


def command_path_candidate(token: str, project_root: Path, home: Path) -> Optional[Path]:
    if not token or token.startswith("-") or is_env_assignment(token):
        return None
    if token.startswith("~/"):
        candidate = home / token[2:]
    else:
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = project_root / candidate
    if not candidate.is_file():
        return None
    if "/" not in token and not token.endswith((".sh", ".bash", ".zsh", ".ksh")):
        return None
    return candidate


def read_small_text(path: Path) -> str:
    try:
        if path.stat().st_size > 65536:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _line_command_segment_before_offset(line: str, offset: int) -> Optional[List[str]]:
    prefix = line[:offset]
    tokens = shell_tokens(prefix)
    if tokens is None:
        return None
    segments = _command_segments(tokens)
    if not segments:
        return None
    return segments[-1]


def _shell_reads_stdin_script(segment: Optional[List[str]]) -> bool:
    if not segment:
        return False
    command_index = _command_index(segment)
    if command_index is None or not is_shell_wrapper_token(segment[command_index]):
        return False

    for token in segment[command_index + 1 :]:
        if token in {"-c", "--command"}:
            return False
        if token.startswith("-") and "c" in token:
            return False
        if token.startswith("-") or is_env_assignment(token):
            continue
        return False
    return True


def _heredoc_body_blocked_action(
    command: str,
    project_root: Optional[Path],
    home: Optional[Path],
    visited: set,
) -> Optional[str]:
    lines = command.splitlines()
    pending: List[Tuple[str, bool, List[str]]] = []
    marker_re = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

    for line in lines:
        if pending:
            marker, inspect_body, body = pending[0]
            if line.strip() == marker:
                if inspect_body:
                    nested = _nested_blocked_action("\n".join(body), project_root, home, visited)
                    if nested:
                        return nested
                pending.pop(0)
            elif inspect_body:
                body.append(line)
            continue

        for match in marker_re.finditer(line):
            if _shell_quoted_at(line, match.start()):
                continue
            segment = _line_command_segment_before_offset(line, match.start())
            pending.append((match.group(2), _shell_reads_stdin_script(segment), []))

    return None


def _strip_heredoc_bodies(command: str) -> str:
    lines = command.splitlines()
    kept: List[str] = []
    pending: List[str] = []
    marker_re = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

    for line in lines:
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue

        kept.append(line)
        for match in marker_re.finditer(line):
            if _shell_quoted_at(line, match.start()):
                continue
            segment = _line_command_segment_before_offset(line, match.start())
            if _shell_reads_stdin_script(segment):
                continue
            pending.append(match.group(2))

    return "\n".join(kept)


def _find_unquoted_operator(value: str, operator: str) -> List[int]:
    offsets: List[int] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(value):
        char = value[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if value.startswith(operator, index):
            offsets.append(index)
            index += len(operator)
            continue
        index += 1
    return offsets


def _has_shell_ansi_c_quoting(value: str) -> bool:
    quote = ""
    escaped = False
    index = 0
    while index < len(value):
        char = value[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if value.startswith("$'", index) or value.startswith('$"', index):
            return True
        index += 1
    return False


def _has_execution_sink_substitution(value: str, include_process: bool = False) -> bool:
    quote = ""
    escaped = False
    index = 0
    while index < len(value):
        char = value[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if quote:
            if char == quote:
                quote = ""
            elif quote != "'" and (
                char == "`" or value.startswith("$(", index) or value.startswith("${", index)
            ):
                return True
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "`" or value.startswith("$(", index) or value.startswith("${", index):
            return True
        if include_process and value.startswith("<(", index):
            return True
        index += 1
    return False


def _herestring_payloads(command: str) -> List[str]:
    payloads: List[str] = []
    for line in command.splitlines():
        for offset in _find_unquoted_operator(line, "<<<"):
            segment = _line_command_segment_before_offset(line, offset)
            if not _shell_reads_stdin_script(segment):
                continue
            rhs = line[offset + 3 :].strip()
            if _has_execution_sink_substitution(rhs, include_process=True):
                payloads.append(EXECUTION_SINK_SUBSTITUTION_SENTINEL)
                continue
            if _has_shell_ansi_c_quoting(rhs):
                payloads.append(ANSI_C_QUOTING_SENTINEL)
                continue
            try:
                parts = shlex.split(rhs, posix=True)
            except ValueError:
                payloads.append(rhs)
                continue
            if parts:
                payloads.append(parts[0])
    return payloads


def _process_substitution_payloads(command: str) -> List[str]:
    payloads: List[str] = []
    for line in command.splitlines():
        for match in PROCESS_SUBSTITUTION_RE.finditer(line):
            if _shell_quoted_at(line, match.start()):
                continue
            segment = _line_command_segment_before_offset(line, match.start())
            if _shell_reads_stdin_script(segment):
                payloads.append(PROCESS_SUBSTITUTION_SENTINEL)
    return payloads


def _shell_quoted_at(value: str, offset: int) -> bool:
    quote = ""
    escaped = False
    for char in value[:offset]:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
    return bool(quote)


def _command_substitutions(command: str) -> Optional[List[str]]:
    substitutions: List[str] = []
    index = 0
    quote = ""
    escaped = False

    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if quote:
            if char == quote:
                quote = ""
            elif quote != "'" and char == "`":
                end = index + 1
                while end < len(command):
                    if command[end] == "`" and command[end - 1] != "\\":
                        substitutions.append(command[index + 1 : end])
                        index = end + 1
                        break
                    end += 1
                else:
                    return None
                continue
            elif quote != "'" and command.startswith("$(", index):
                depth = 1
                end = index + 2
                inner_quote = ""
                inner_escaped = False
                while end < len(command):
                    inner_char = command[end]
                    if inner_escaped:
                        inner_escaped = False
                        end += 1
                        continue
                    if inner_char == "\\":
                        inner_escaped = True
                        end += 1
                        continue
                    if inner_quote:
                        if inner_char == inner_quote:
                            inner_quote = ""
                        end += 1
                        continue
                    if inner_char in {"'", '"'}:
                        inner_quote = inner_char
                    elif command.startswith("$(", end):
                        depth += 1
                        end += 1
                    elif inner_char == ")":
                        depth -= 1
                        if depth == 0:
                            substitutions.append(command[index + 2 : end])
                            index = end + 1
                            break
                    end += 1
                else:
                    return None
                continue
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "`":
            end = index + 1
            while end < len(command):
                if command[end] == "`" and command[end - 1] != "\\":
                    substitutions.append(command[index + 1 : end])
                    index = end + 1
                    break
                end += 1
            else:
                return None
            continue
        if command.startswith("$(", index):
            depth = 1
            end = index + 2
            inner_quote = ""
            inner_escaped = False
            while end < len(command):
                inner_char = command[end]
                if inner_escaped:
                    inner_escaped = False
                    end += 1
                    continue
                if inner_char == "\\":
                    inner_escaped = True
                    end += 1
                    continue
                if inner_quote:
                    if inner_char == inner_quote:
                        inner_quote = ""
                    end += 1
                    continue
                if inner_char in {"'", '"'}:
                    inner_quote = inner_char
                elif command.startswith("$(", end):
                    depth += 1
                    end += 1
                elif inner_char == ")":
                    depth -= 1
                    if depth == 0:
                        substitutions.append(command[index + 2 : end])
                        index = end + 1
                        break
                end += 1
            else:
                return None
            continue
        index += 1

    return substitutions


def _shell_newlines_to_separators(command: str) -> str:
    output: List[str] = []
    quote = ""
    escaped = False
    for char in command:
        if escaped:
            output.append(char)
            escaped = False
            continue
        if char == "\\":
            output.append(char)
            escaped = True
            continue
        if quote:
            output.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            output.append(char)
            quote = char
        elif char == "\n":
            output.append(" ; ")
        else:
            output.append(char)
    return "".join(output)


def _command_segments(tokens: List[str]) -> List[List[str]]:
    segments: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in COMMAND_SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _command_index(segment: List[str]) -> Optional[int]:
    index = 0
    while index < len(segment) and is_env_assignment(segment[index]):
        index += 1
    if index >= len(segment):
        return None

    if command_basename(segment[index]) == "env":
        index += 1
        while index < len(segment):
            if segment[index].startswith("-") or is_env_assignment(segment[index]):
                index += 1
                continue
            return index
        return None

    return index


def _is_safe_text_command(segment: List[str], command_index: int) -> bool:
    name = command_basename(segment[command_index])
    if name in TEXT_COMMANDS:
        return True
    if name == "awk":
        return not any("{" in token or "system(" in token for token in segment[command_index + 1 :])
    if name == "sed":
        return not any(token == "-i" or token.startswith("-i") for token in segment[command_index + 1 :])
    return False


def _has_process_substitution_tokens(tokens: List[str]) -> bool:
    return any(
        token == "<" and index + 1 < len(tokens) and tokens[index + 1] == "("
        for index, token in enumerate(tokens)
    )


def _nested_blocked_action(
    command: str,
    project_root: Optional[Path],
    home: Optional[Path],
    visited: set,
) -> Optional[str]:
    return _blocked_mst_action(command, project_root, home, visited)


def _script_blocked_action(
    token: str,
    project_root: Optional[Path],
    home: Optional[Path],
    visited: set,
) -> Optional[str]:
    if project_root is None or home is None:
        return None
    candidate = command_path_candidate(token, project_root, home)
    if candidate is None:
        return None
    real = str(candidate.resolve())
    if real in visited:
        return None
    visited.add(real)
    return _blocked_mst_action(read_small_text(candidate), project_root, home, visited)


def _segment_blocked_action(
    segment: List[str],
    project_root: Optional[Path],
    home: Optional[Path],
    visited: set,
) -> Optional[str]:
    command_index = _command_index(segment)
    if command_index is None:
        return None

    if _is_safe_text_command(segment, command_index):
        return None

    command = segment[command_index]
    name = command_basename(command)
    if not name and command.strip() == ".":
        name = "."

    if name == "alias":
        for token in segment[command_index + 1 :]:
            if "=" not in token:
                continue
            nested = _nested_blocked_action(token.split("=", 1)[1], project_root, home, visited)
            if nested:
                return nested
        return None

    if is_shell_wrapper_token(command):
        for index in range(command_index + 1, len(segment) - 1):
            if segment[index] in {"-c", "--command"} or (segment[index].startswith("-") and "c" in segment[index]):
                nested = _nested_blocked_action(segment[index + 1], project_root, home, visited)
                if nested:
                    return nested
                return None
        for token in segment[command_index + 1 :]:
            if token.startswith("-") or is_env_assignment(token):
                continue
            nested = _script_blocked_action(token, project_root, home, visited)
            if nested:
                return nested
            return None

    if name == "eval":
        script = " ".join(segment[command_index + 1 :])
        if _has_execution_sink_substitution(script):
            return "mst confirm"
        nested = _nested_blocked_action(script, project_root, home, visited)
        if nested:
            return nested
        return None

    if name in {"source", "."}:
        arguments = segment[command_index + 1 :]
        if _has_process_substitution_tokens(arguments) or any(
            _has_execution_sink_substitution(token, include_process=True) for token in arguments
        ):
            return "mst confirm"
        return None

    direct_match = blocked_mst_sequence(segment, command_index)
    if direct_match:
        return direct_match

    nested = _script_blocked_action(command, project_root, home, visited)
    if nested:
        return nested

    if has_blocked_mst_words(segment[command_index + 1 :]):
        return "mst confirm"

    return None


def _blocked_mst_action(
    command: str,
    project_root: Optional[Path],
    home: Optional[Path],
    visited: set,
) -> Optional[str]:
    if not command:
        return None
    if len(visited) > 8:
        return None

    heredoc_nested = _heredoc_body_blocked_action(command, project_root, home, visited)
    if heredoc_nested:
        return heredoc_nested

    for payload in _herestring_payloads(command):
        if payload in {ANSI_C_QUOTING_SENTINEL, EXECUTION_SINK_SUBSTITUTION_SENTINEL}:
            return "mst confirm"
        nested = _nested_blocked_action(payload, project_root, home, visited)
        if nested:
            return nested

    for payload in _process_substitution_payloads(command):
        if payload == PROCESS_SUBSTITUTION_SENTINEL:
            return "mst confirm"
        nested = _nested_blocked_action(payload, project_root, home, visited)
        if nested:
            return nested

    command_without_heredocs = _strip_heredoc_bodies(command)
    substitutions = _command_substitutions(command_without_heredocs)
    if substitutions is None:
        return "mst confirm"
    for nested_command in substitutions:
        nested = _nested_blocked_action(nested_command, project_root, home, visited)
        if nested:
            return nested

    normalized = _shell_newlines_to_separators(command_without_heredocs)
    tokens = shell_tokens(normalized)
    if tokens is None:
        return "mst confirm"

    for segment in _command_segments(tokens):
        blocked = _segment_blocked_action(segment, project_root, home, visited)
        if blocked:
            return blocked

    return None


def _classify_command_intent(command: str) -> str:
    if not command:
        return "safe_text"
    if shell_tokens(_shell_newlines_to_separators(_strip_heredoc_bodies(command))) is None:
        return "unknown"
    if _blocked_mst_action(command, None, None, set()):
        return "execute_blocked"
    return "safe_text"


def blocked_mst_command(command: str, project_root: Path, home: Path, visited: Optional[set] = None) -> Optional[str]:
    if not command:
        return None
    if visited is None:
        visited = set()
    return _blocked_mst_action(command, project_root, home, visited)


def sanitize_session_id(value: str) -> Optional[str]:
    if not value or "/" in value or ".." in value:
        return None
    if re.search(r"[^A-Za-z0-9._-]", value):
        return None
    return value


def normalize_path(raw_path: str, project_root: Path, home: Path) -> str:
    if raw_path == "~":
        return str(home)
    if raw_path.startswith("~/"):
        return str(home / raw_path[2:])
    if raw_path.startswith("/"):
        return raw_path
    if not raw_path:
        return ""
    return str(project_root / raw_path)


def is_mutating_command(command: str) -> bool:
    return bool(
        MUTATING_RE.search(command)
        or INLINE_MUTATING_RE.search(command)
        or ">" in command
    )


def split_phase_shell_segments(tokens: List[str]) -> Optional[List[List[str]]]:
    segments: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if ">" in token:
            return None
        if token in PHASE_SHELL_CONTROL_TOKENS:
            return None
        if token in PHASE_SHELL_SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        if token == "<":
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def phase_effective_command(segment: List[str]) -> Tuple[str, List[str]]:
    index = 0
    while index < len(segment) and is_env_assignment(segment[index]):
        index += 1
    while index < len(segment) and command_basename(segment[index]) in {"command", "builtin", "time"}:
        index += 1
    if index < len(segment) and command_basename(segment[index]) == "env":
        index += 1
        while index < len(segment) and is_env_assignment(segment[index]):
            index += 1
        if index >= len(segment):
            return "env", []
    if index >= len(segment):
        return "", []
    return command_basename(segment[index]), segment[index + 1 :]


def is_phase_readonly_git(args: List[str]) -> bool:
    if not args:
        return False
    subcommand = args[0]
    if subcommand not in PHASE_READONLY_GIT_COMMANDS:
        return False
    if subcommand == "branch":
        allowed_flags = {
            "-a",
            "-r",
            "-v",
            "-vv",
            "--all",
            "--remotes",
            "--verbose",
            "--list",
            "--show-current",
            "--contains",
            "--merged",
            "--no-merged",
            "--points-at",
        }
        for arg in args[1:]:
            if arg.startswith("--format"):
                continue
            if arg.startswith("-") and arg in allowed_flags:
                continue
            return False
        return True
    if subcommand == "diff":
        return not any(arg == "--output" or arg.startswith("--output=") for arg in args[1:])
    return True


def is_phase_readonly_find(args: List[str]) -> bool:
    return not any(arg in PHASE_FIND_MUTATING_OPTIONS for arg in args)


def is_phase_readonly_python(args: List[str]) -> bool:
    if not args:
        return False
    if args in (["-V"], ["--version"]):
        return True
    if args[:2] == ["-m", "py_compile"] and len(args) > 2:
        return True
    for index, arg in enumerate(args):
        if arg in {"-c", "--command"}:
            if index + 1 >= len(args):
                return False
            return PHASE_MUTATING_PYTHON_RE.search(args[index + 1]) is None
    return False


def is_phase_readonly_shell_wrapper(args: List[str]) -> bool:
    for index, arg in enumerate(args):
        if arg == "-c" or (arg.startswith("-") and "c" in arg[1:]):
            if index + 1 >= len(args):
                return False
            return not is_phase_gate_mutating_command(args[index + 1])
    return False


def is_phase_readonly_segment(segment: List[str]) -> bool:
    command, args = phase_effective_command(segment)
    if not command:
        return True
    if command in PHASE_READONLY_MST_SKILLS:
        return True
    if command in PHASE_READONLY_COMMANDS:
        return True
    if command == "find":
        return is_phase_readonly_find(args)
    if command == "git":
        return is_phase_readonly_git(args)
    if is_python_token(command):
        return is_phase_readonly_python(args)
    if is_shell_wrapper_token(command):
        return is_phase_readonly_shell_wrapper(args)
    return False


def is_phase_gate_mutating_command(command: str) -> bool:
    tokens = shell_tokens_with_operators(command)
    if not tokens:
        return False
    segments = split_phase_shell_segments(tokens)
    if segments is None:
        return True
    return any(not is_phase_readonly_segment(segment) for segment in segments)


def project_key(project_root: Path) -> str:
    return sha256_text(os.path.realpath(project_root))[:16]


def policy_home(home: Path) -> Path:
    raw = os.environ.get("MST_POLICY_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return home / ".claude" / "gran-maestro-policy"


def allowlist_path(home: Path) -> Path:
    return policy_home(home) / "allowlist.json"


def parse_allowlist_expiry(value) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def allowlist_target(tool_input: dict) -> str:
    for key in ("command", "file_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def protected_allowlist_target(tool_input: dict) -> str:
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def is_protected_target(target_path: str) -> bool:
    if not target_path:
        return False
    expanded_target = os.path.expanduser(target_path)
    target_abs = os.path.abspath(expanded_target)
    for pattern in PROTECTED_PATH_PATTERNS:
        expanded_pattern = os.path.expanduser(pattern)
        pattern_abs = os.path.abspath(expanded_pattern)
        if (
            fnmatch.fnmatch(target_abs, pattern_abs)
            or fnmatch.fnmatch(expanded_target, expanded_pattern)
            or fnmatch.fnmatch(target_path, pattern)
        ):
            return True
    return False


def check_allowlist(home: Path, tool_name: str, tool_input: dict) -> bool:
    if tool_name in ALLOWLIST_PROTECTED_TARGET_TOOLS and is_protected_target(
        protected_allowlist_target(tool_input)
    ):
        return False

    path = allowlist_path(home)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    now = datetime.now(timezone.utc)
    target = allowlist_target(tool_input)
    for entry in data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("tool") != tool_name:
            continue
        expires_at = entry.get("expires_at")
        if expires_at:
            expiry = parse_allowlist_expiry(expires_at)
            if expiry is None or now >= expiry:
                continue
        if fnmatch.fnmatch(target, str(entry.get("args_pattern") or "*")):
            return True
    return False


def history_paths(project_root: Path, home: Path, session_id: str) -> Tuple[Path, Path, Path, Path]:
    session_dir = project_root / ".gran-maestro" / "sessions" / session_id
    history_file = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    mirror_head = policy_home(home) / "ledger-heads" / f"{session_id}.head"
    verify_state = session_dir / "history.verify"
    return history_file, local_head, mirror_head, verify_state


def file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def read_head(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def sanitize_log_value(value: str) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ").replace("\t", " ")


def resolve_flow_logger_script(project_root: Path) -> Path:
    project_script = project_root / "scripts" / "_flow_logger.py"
    if project_script.is_file():
        return project_script

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "scripts" / "_flow_logger.py"
        if candidate.is_file():
            return candidate
    return project_script


def warn_helper_failed(helper: str, status: int, detail: str = "") -> None:
    helper = sanitize_log_value(helper)
    detail = sanitize_log_value(detail)
    if detail:
        stderr(f"[mst-pre-tool-use] helper_failed helper={helper} exit={status} {detail}")
    else:
        stderr(f"[mst-pre-tool-use] helper_failed helper={helper} exit={status}")


def append_flow_event(
    project_root: Path,
    session_id: str,
    event_type: str,
    data: str,
    snapshot_path: Path,
    stdin_digest: str,
) -> None:
    flow_logger = resolve_flow_logger_script(project_root)
    if not flow_logger.is_file():
        warn_helper_failed("flow_logger", 127, f"path={flow_logger}")
        return

    import subprocess

    result = subprocess.run(
        [
            "python3",
            str(flow_logger),
            "append",
            "--project-root",
            str(project_root),
            "--session-id",
            session_id or "unknown",
            "--event-type",
            event_type,
            "--data",
            data,
            "--snapshot-path",
            str(snapshot_path) if snapshot_path else "",
            "--stdin-digest",
            stdin_digest,
            "--ppid",
            str(os.getppid()),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        warn_helper_failed("flow_logger", result.returncode, f"event_type={event_type}")


def resolve_durable_owner_session_id(project_root: Path) -> Optional[str]:
    base_dir = project_root / ".gran-maestro"
    request_terminal = {"done", "completed", "accepted", "cancelled"}
    plan_terminal = {"done", "completed", "cancelled"}
    values: List[str] = []

    def add_owner(path: Path, terminal_statuses=None, require_active: bool = False) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return

        status = str(payload.get("status") or "").strip().lower()
        if terminal_statuses is not None and status in terminal_statuses:
            return
        if require_active and status != "active":
            return

        owner_session_id = payload.get("owner_session_id")
        if isinstance(owner_session_id, str) and owner_session_id.strip():
            values.append(owner_session_id.strip())

    for path in (base_dir / "requests").glob("REQ-*/request.json"):
        add_owner(path, request_terminal)
    for path in (base_dir / "plans").glob("PLN-*/plan.json"):
        add_owner(path, plan_terminal)
    for path in (base_dir / "agile").glob("AGI-*/session.json"):
        add_owner(path, require_active=True)

    unique: List[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique[0] if len(unique) == 1 else None


def warn_session_id_mismatch_once_if_any(
    project_root: Path,
    payload: dict,
    raw: str,
    session_id: str,
) -> None:
    if not session_id:
        return

    gm_dir = project_root / ".gran-maestro"
    if not ((gm_dir / "requests").exists() or (gm_dir / "plans").exists() or (gm_dir / "agile").exists()):
        return

    snapshot_path = gm_dir / "state" / session_id / "snapshot.json"
    if not snapshot_path.is_file():
        return

    mst_tmp = project_root / ".gran-maestro" / "tmp"
    sentinel = mst_tmp / f"mst-mismatch-warn-{os.getppid()}-{session_id}.flag"
    if sentinel.is_file():
        return

    durable_sid = resolve_durable_owner_session_id(project_root)
    if not durable_sid:
        return

    snapshot_sid = ""
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        snapshot = {}
    if isinstance(snapshot, dict):
        for key in ("session_id", "sessionId"):
            value = snapshot.get(key)
            if isinstance(value, str) and value.strip():
                snapshot_sid = value.strip()
                break
    if not snapshot_sid:
        snapshot_sid = snapshot_path.parent.name.strip()
    if not snapshot_sid:
        return

    stdin_sid = payload.get("session_id")
    stdin_sid = stdin_sid.strip() if isinstance(stdin_sid, str) else ""
    if not stdin_sid or len({stdin_sid, snapshot_sid, durable_sid}) == 1:
        return

    try:
        mst_tmp.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(sentinel), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return
    except OSError:
        return

    data = {
        "stdin_sid": stdin_sid,
        "snapshot_sid": snapshot_sid,
        "durable_sid": durable_sid,
        "hook": "mst-pre-tool-use",
    }
    stderr(
        "[session-id mismatch] stdin={} snapshot={} durable={} hook=mst-pre-tool-use".format(
            sanitize_log_value(stdin_sid),
            sanitize_log_value(snapshot_sid),
            sanitize_log_value(durable_sid),
        )
    )
    append_flow_event(
        project_root,
        session_id,
        "session_id_mismatch",
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        snapshot_path,
        sha256_text(raw),
    )


def read_verify_state(path: Path) -> Optional[Tuple[str, str, int]]:
    if not path.is_file():
        return None
    try:
        head_hash, fingerprint, seq = path.read_text(encoding="utf-8").rstrip("\n").split("\t")
        return head_hash, fingerprint, int(seq)
    except Exception:
        return None


def write_verify_state(path: Path, head_hash: str, fingerprint: str, seq: int) -> None:
    tmp_path = Path(f"{path}.tmp.{os.getpid()}")
    tmp_path.write_text(f"{head_hash}\t{fingerprint}\t{seq}\n", encoding="utf-8")
    os.replace(tmp_path, path)


def last_event_hash(history_file: Path) -> Optional[str]:
    if not history_file.is_file():
        return None
    try:
        with history_file.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size == 0:
                return None
            offset = min(size, 8192)
            handle.seek(-offset, os.SEEK_END)
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        chunk = history_file.read_text(encoding="utf-8")
    lines = [line for line in chunk.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        row = json.loads(lines[-1])
    except Exception:
        return None
    value = row.get("event_hash")
    return str(value) if isinstance(value, str) else None


def verify_history(project_root: Path, home: Path, session_id: str) -> Tuple[bool, Optional[str], int]:
    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, session_id)
    cached = read_verify_state(verify_state)
    if cached is not None:
        cached_head, cached_fingerprint, cached_seq = cached
        local_value = read_head(local_head)
        mirror_value = read_head(mirror_head)
        if local_value and local_value == mirror_value == cached_head:
            current_fingerprint = file_fingerprint(history_file)
            if current_fingerprint == cached_fingerprint:
                if current_fingerprint == "missing":
                    return True, cached_head, cached_seq
                last_hash = last_event_hash(history_file)
                if last_hash and last_hash == cached_head:
                    return True, cached_head, cached_seq

    expected_prev = ZERO_HASH
    expected_seq = 1
    last_hash = ZERO_HASH
    if history_file.is_file():
        with history_file.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:
                    stderr(f"history ledger mismatch: invalid json line={line_no}: {exc}")
                    return False, None, 0
                if not isinstance(row, dict):
                    stderr(f"history ledger mismatch: row is not object line={line_no}")
                    return False, None, 0
                if row.get("seq") != expected_seq:
                    stderr(f"history ledger mismatch: seq line={line_no}")
                    return False, None, 0
                if row.get("prev_hash") != expected_prev:
                    stderr(f"history ledger mismatch: prev_hash line={line_no}")
                    return False, None, 0
                event = row.get("event")
                if not isinstance(event, dict):
                    stderr(f"history ledger mismatch: event line={line_no}")
                    return False, None, 0
                canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
                computed = sha256_text(expected_prev + "\n" + canonical)
                if row.get("event_hash") != computed:
                    stderr(f"history ledger mismatch: event_hash line={line_no}")
                    return False, None, 0
                expected_prev = computed
                last_hash = computed
                expected_seq += 1

    local_value = read_head(local_head)
    mirror_value = read_head(mirror_head)
    has_entries = expected_seq > 1

    if not has_entries:
        if local_value is not None and local_value != ZERO_HASH:
            stderr("history ledger mismatch: self-heal failed: ndjson empty but heads non-zero (rotation suspected)")
            return False, None, 0
        if mirror_value is not None and mirror_value != ZERO_HASH:
            stderr("history ledger mismatch: self-heal failed: ndjson empty but heads non-zero (rotation suspected)")
            return False, None, 0

    if has_entries and local_value is None:
        stderr("history ledger mismatch: missing history.head")
        return False, None, 0
    if has_entries and mirror_value is None:
        stderr("history ledger mismatch: missing home mirror head")
        return False, None, 0
    if has_entries and local_value == ZERO_HASH:
        stderr("history ledger mismatch: history.head")
        return False, None, 0
    if has_entries and mirror_value == ZERO_HASH:
        stderr("history ledger mismatch: home mirror head")
        return False, None, 0

    def head_within_ndjson(head: Optional[str]) -> bool:
        if head is None or head == last_hash or head == ZERO_HASH:
            return True
        if not history_file.is_file():
            return False
        with history_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict) and row.get("event_hash") == head:
                    return True
        return False

    if local_value is not None and not head_within_ndjson(local_value):
        stderr("history ledger mismatch: self-heal failed: head ahead of ndjson last_hash")
        return False, None, 0
    if mirror_value is not None and not head_within_ndjson(mirror_value):
        stderr("history ledger mismatch: self-heal failed: head ahead of ndjson last_hash")
        return False, None, 0

    if last_hash != ZERO_HASH and (
        (local_value is not None and local_value != last_hash)
        or (mirror_value is not None and mirror_value != last_hash)
    ):
        prev_local = local_value or ZERO_HASH
        prev_mirror = mirror_value or ZERO_HASH
        targets = []

        def atomic_write_head(path: Path, value: str) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = Path(f"{path}.tmp.{os.getpid()}")
            tmp_path.write_text(value + "\n", encoding="utf-8")
            os.replace(tmp_path, path)

        if mirror_value != last_hash:
            atomic_write_head(mirror_head, last_hash)
            targets.append("mirror")
        if local_value != last_hash:
            atomic_write_head(local_head, last_hash)
            targets.append("local")
        stderr(
            f"[mst-history-self-heal] session={session_id} restored={last_hash[:12]} "
            f"targets={','.join(targets)} prev_local={prev_local[:12]} prev_mirror={prev_mirror[:12]}"
        )

    verify_state.parent.mkdir(parents=True, exist_ok=True)
    write_verify_state(verify_state, last_hash, file_fingerprint(history_file), expected_seq - 1)
    return True, last_hash, expected_seq - 1


def verify_history_locked(project_root: Path, home: Path, session_id: str) -> Tuple[bool, Optional[str], int]:
    history_file, _, _, _ = history_paths(project_root, home, session_id)
    session_dir = history_file.parent
    lock_dir = session_dir / "history.lock"
    session_dir.mkdir(parents=True, exist_ok=True)
    if not acquire_lock(lock_dir):
        stderr("history ledger mismatch: lock timeout")
        return False, None, 0
    try:
        return verify_history(project_root, home, session_id)
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def acquire_lock(lock_dir: Path) -> bool:
    tries = int(os.environ.get("MST_HISTORY_LOCK_TRIES", "20"))
    while tries > 0:
        try:
            lock_dir.mkdir()
            return True
        except FileExistsError:
            time.sleep(0.05)
            tries -= 1
    return False


def build_history_row(event: dict, prev_hash: str, seq: int, session_id: str) -> Tuple[dict, str]:
    stamped_event = dict(event)
    stamped_event["session_id"] = session_id
    canonical_event = canonical_json(stamped_event)
    event_hash = sha256_text(prev_hash + "\n" + canonical_event)
    row = {
        "event": stamped_event,
        "event_hash": event_hash,
        "prev_hash": prev_hash,
        "seq": seq,
        "session_id": session_id,
    }
    for key in ("tool", "args_sha256", "timestamp"):
        if key in stamped_event:
            row[key] = stamped_event[key]
    return row, event_hash


def append_tool_call(project_root: Path, home: Path, session_id: str, tool_name: str, tool_input: dict) -> int:
    if not session_id:
        return 0
    clean_sid = sanitize_session_id(session_id)
    if clean_sid is None:
        stderr("history ledger mismatch: invalid session_id")
        return 2

    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, clean_sid)
    session_dir = history_file.parent
    lock_dir = session_dir / "history.lock"
    session_dir.mkdir(parents=True, exist_ok=True)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)
    if not acquire_lock(lock_dir):
        stderr("history ledger mismatch: lock timeout")
        return 2

    try:
        ok, prev_hash, seq = verify_history(project_root, home, clean_sid)
        if not ok:
            return 2
        prev_hash = prev_hash or ZERO_HASH
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        args_json = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event = {
            "args_sha256": sha256_text(args_json),
            "timestamp": timestamp,
            "tool": tool_name or "unknown",
            "type": "tool_call",
        }
        row, event_hash = build_history_row(event, prev_hash, seq + 1, clean_sid)
        with history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
        local_head.write_text(event_hash + "\n", encoding="utf-8")
        mirror_head.write_text(event_hash + "\n", encoding="utf-8")
        write_verify_state(verify_state, event_hash, file_fingerprint(history_file), seq + 1)
        return 0
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def append_tool_call_after_verified(project_root: Path, home: Path, session_id: str, tool_name: str, tool_input: dict) -> int:
    if not session_id:
        return 0

    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, session_id)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)

    prev_hash = read_head(local_head) or ZERO_HASH
    seq = 0
    cached = read_verify_state(verify_state)
    if cached is not None and cached[0] == prev_hash:
        seq = cached[2]
    elif history_file.is_file():
        try:
            with history_file.open("rb") as handle:
                seq = sum(1 for line in handle if line.strip())
        except OSError:
            seq = 0

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args_json = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    event = {
        "args_sha256": sha256_text(args_json),
        "timestamp": timestamp,
        "tool": tool_name or "unknown",
        "type": "tool_call",
    }
    row, event_hash = build_history_row(event, prev_hash, seq + 1, session_id)
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    local_head.write_text(event_hash + "\n", encoding="utf-8")
    mirror_head.write_text(event_hash + "\n", encoding="utf-8")
    write_verify_state(verify_state, event_hash, file_fingerprint(history_file), seq + 1)
    return 0


def append_event_after_verified(project_root: Path, home: Path, session_id: str, event: dict) -> int:
    if not session_id:
        return 0

    history_file, local_head, mirror_head, verify_state = history_paths(project_root, home, session_id)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)

    prev_hash = read_head(local_head) or ZERO_HASH
    seq = 0
    cached = read_verify_state(verify_state)
    if cached is not None and cached[0] == prev_hash:
        seq = cached[2]
    elif history_file.is_file():
        try:
            with history_file.open("rb") as handle:
                seq = sum(1 for line in handle if line.strip())
        except OSError:
            seq = 0

    row, event_hash = build_history_row(event, prev_hash, seq + 1, session_id)
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(row) + "\n")
    local_head.write_text(event_hash + "\n", encoding="utf-8")
    mirror_head.write_text(event_hash + "\n", encoding="utf-8")
    write_verify_state(verify_state, event_hash, file_fingerprint(history_file), seq + 1)
    return 0


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def workflow_state_file(project_root: Path) -> Path:
    # MST_STATE_PPID is a deprecated diagnostic alias only; it must not select
    # workflow state or alter pre-tool-use block/allow return codes.
    parent_pid = str(os.getppid())
    return project_root / ".gran-maestro" / "tmp" / f"mst-state-{parent_pid}.json"


def load_workflow_state(project_root: Path) -> Optional[dict]:
    path = workflow_state_file(project_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def schedule_wakeup_block_active(project_root: Path, now: Optional[datetime] = None) -> bool:
    payload = load_workflow_state(project_root)
    if not isinstance(payload, dict):
        return False

    now = now or utc_now()
    updated_at = parse_utc(payload.get("updated_at"))
    if updated_at is not None and (now - updated_at).total_seconds() > SCHEDULE_WAKEUP_STATE_TTL_SECONDS:
        return False

    if payload.get("workflow_active") is True:
        return True

    last_active_at = parse_utc(payload.get("last_active_at"))
    if last_active_at is None:
        return False
    return (now - last_active_at).total_seconds() <= SCHEDULE_WAKEUP_GRACE_SECONDS


def pending_confirm_ttl() -> int:
    raw = os.environ.get("MST_PENDING_CONFIRM_TTL_SECONDS") or os.environ.get("MST_CONFIRM_TTL_SECONDS") or "86400"
    try:
        value = int(raw)
    except ValueError:
        return 86400
    return value if value > 0 else 86400


def pending_confirm_path(project_root: Path, session_id: str) -> Path:
    return project_root / ".gran-maestro" / "sessions" / session_id / "pending-confirm.json"


def read_pending_confirm(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_pending_confirm(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp_path = Path(f"{path}.tmp.{os.getpid()}")
    tmp_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)


def expire_pending_confirm(project_root: Path, session_id: str, now: datetime) -> None:
    path = pending_confirm_path(project_root, session_id)
    payload = read_pending_confirm(path)
    if not payload or payload.get("consumed") is not False:
        return
    expires_at = parse_utc(str(payload.get("expires_at") or ""))
    if expires_at is None or expires_at > now:
        return
    payload["consumed"] = "expired"
    write_pending_confirm(path, payload)


def request_pending_confirm(
    project_root: Path,
    home: Path,
    session_id: str,
    tool_name: str,
    tool_input: dict,
    rule_id: str,
) -> int:
    now = utc_now()
    path = pending_confirm_path(project_root, session_id)
    args_canonical = tool_input if isinstance(tool_input, dict) else {}
    args_json = canonical_json(args_canonical)
    args_sha256 = sha256_text(args_json)
    existing = read_pending_confirm(path)

    if existing and existing.get("consumed") is False:
        expires_at = parse_utc(str(existing.get("expires_at") or ""))
        if expires_at is not None and expires_at <= now:
            existing["consumed"] = "expired"
            write_pending_confirm(path, existing)
        elif existing.get("tool") == tool_name and existing.get("args_sha256") == args_sha256:
            return 0

    created_at = format_utc(now)
    expires_at = format_utc(now + timedelta(seconds=pending_confirm_ttl()))
    pending_id = f"cf_{now.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(6)}"
    payload = {
        "args_canonical": args_canonical,
        "args_sha256": args_sha256,
        "consumed": False,
        "created_at": created_at,
        "expires_at": expires_at,
        "id": pending_id,
        "tool": tool_name,
    }
    write_pending_confirm(path, payload)
    return append_event_after_verified(
        project_root,
        home,
        session_id,
        {
            "args_sha256": args_sha256,
            "expires_at": expires_at,
            "pending_id": pending_id,
            "rule_id": rule_id,
            "timestamp": created_at,
            "tool": tool_name,
            "type": "confirm_requested",
        },
    )


def has_unconsumed_override_grant(
    project_root: Path,
    session_id: str,
    pending_id: str,
    tool_name: str,
    args_sha256: str,
) -> bool:
    grants = 0
    consumes = 0
    for event in load_history_events(project_root, session_id, {}):
        if (
            event.get("pending_id") == pending_id
            and event.get("tool") == tool_name
            and event.get("args_sha256") == args_sha256
        ):
            if event.get("type") == "override_granted":
                grants += 1
            elif event.get("type") == "override_consumed":
                consumes += 1
    return grants > consumes


def consume_pending_override(
    project_root: Path,
    home: Path,
    session_id: str,
    tool_name: str,
    tool_input: dict,
) -> Optional[int]:
    path = pending_confirm_path(project_root, session_id)
    pending = read_pending_confirm(path)
    if not pending or pending.get("consumed") is not False:
        return None

    pending_id = str(pending.get("id") or "")
    pending_tool = str(pending.get("tool") or "")
    pending_args_sha = str(pending.get("args_sha256") or "")
    args_sha256 = sha256_text(canonical_json(tool_input if isinstance(tool_input, dict) else {}))
    if pending_tool != tool_name:
        return None

    if pending_args_sha != args_sha256:
        if has_unconsumed_override_grant(project_root, session_id, pending_id, pending_tool, pending_args_sha):
            stderr("args_sha256 mismatch on subsequent call")
        return None

    if not has_unconsumed_override_grant(project_root, session_id, pending_id, tool_name, args_sha256):
        return None

    timestamp = format_utc(utc_now())
    pending["consumed"] = True
    write_pending_confirm(path, pending)
    return append_event_after_verified(
        project_root,
        home,
        session_id,
        {
            "args_sha256": args_sha256,
            "pending_id": pending_id,
            "timestamp": timestamp,
            "tool": tool_name,
            "type": "override_consumed",
        },
    )


def core_block_event(tool_name: str, tool_input: dict, rule_id: str, reason: str) -> dict:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args_json = canonical_json(tool_input if isinstance(tool_input, dict) else {})
    return {
        "args_sha256": sha256_text(args_json),
        "reason": reason,
        "rule_id": rule_id,
        "timestamp": timestamp,
        "tool": tool_name or "unknown",
        "type": "core_block",
    }


def emit_core_block_and_return(
    project_root: Path,
    home: Path,
    session_id: str,
    tool_name: str,
    tool_input: dict,
    rule_id: str,
    reason: str,
) -> int:
    if session_id:
        append_event_after_verified(
            project_root,
            home,
            session_id,
            core_block_event(tool_name, tool_input, rule_id, reason),
        )
    return block("core-block", rule_id, reason)


def load_history_events(project_root: Path, session_id: str, cache: Dict) -> List[dict]:
    if "history_events" in cache:
        return cache["history_events"]
    clean_sid = sanitize_session_id(session_id)
    if clean_sid is None:
        cache["history_events"] = []
        return cache["history_events"]
    history_file = project_root / ".gran-maestro" / "sessions" / clean_sid / "history.ndjson"
    rows: List[dict] = []
    if history_file.is_file():
        for line in history_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            item = row.get("event", row)
            if isinstance(item, dict):
                rows.append(item)
    cache["history_events"] = rows
    return rows


def load_tail_history_events(project_root: Path, session_id: str, limit: int = 500) -> List[dict]:
    clean_sid = sanitize_session_id(session_id)
    if clean_sid is None:
        return []
    history_file = project_root / ".gran-maestro" / "sessions" / clean_sid / "history.ndjson"
    if not history_file.is_file():
        return []
    truncated = False
    try:
        with history_file.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            offset = min(size, 1024 * 1024)
            truncated = offset < size
            handle.seek(-offset, os.SEEK_END)
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        chunk = history_file.read_text(encoding="utf-8")

    lines = [line for line in chunk.splitlines() if line.strip()]
    if truncated and lines:
        lines = lines[1:]
    rows: List[dict] = []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        event = row.get("event", row) if isinstance(row, dict) else {}
        if isinstance(event, dict):
            rows.append(event)
    return rows


def payload_scope(project_root: Path, payload: dict, tool_input: dict) -> Tuple[str, str]:
    req_id = ""
    task_id = ""
    for source in (payload, tool_input):
        for key in ("req_id", "request_id", "requestId"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str) and value.strip():
                req_id = value.strip().upper()
                break
        for key in ("task_id", "taskId"):
            value = source.get(key) if isinstance(source, dict) else None
            if isinstance(value, str) and value.strip():
                task_id = value.strip().upper()
                break
    req_id = req_id or str(os.environ.get("MST_REQ_ID") or os.environ.get("REQ_ID") or "").strip().upper()
    task_id = task_id or str(os.environ.get("MST_TASK_ID") or os.environ.get("TASK_ID") or "").strip().upper()

    if not req_id or not task_id:
        match = re.search(r"(REQ-\d+)-(T\d+)", project_root.name, re.IGNORECASE)
        if match:
            req_id = req_id or match.group(1).upper()
            task_id = task_id or match.group(2).upper()
    return req_id, task_id


def event_scope_value(event: dict, *keys: str) -> str:
    for key in keys:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return ""


def event_scope_matches(event: dict, req_id: str, task_id: str) -> bool:
    event_req = event_scope_value(event, "req_id", "request_id", "requestId")
    event_task = event_scope_value(event, "task_id", "taskId")
    if not req_id or not task_id or not event_req or not event_task:
        return False
    return event_req == req_id and event_task == task_id


def has_phase_evidence(project_root: Path, session_id: str, req_id: str, task_id: str) -> bool:
    for event in reversed(load_tail_history_events(project_root, session_id)):
        event_type = str(event.get("type") or "")
        if event_type == "spec.accepted" and event_scope_matches(event, req_id, task_id):
            return True
    return False


def active_override_event(project_root: Path, session_id: str, tool_name: str, args_sha256: str) -> Optional[dict]:
    events = load_tail_history_events(project_root, session_id)
    consumed_ids = set()
    consumed_pairs = set()
    now = utc_now()
    for event in events:
        if str(event.get("type") or "") != "override_consumed":
            continue
        override_id = str(
            event.get("override_id")
            or event.get("pending_id")
            or event.get("confirm_id")
            or event.get("id")
            or ""
        )
        if override_id:
            consumed_ids.add(override_id)
        consumed_pairs.add((str(event.get("tool") or ""), str(event.get("args_sha256") or "")))

    for event in reversed(events):
        if str(event.get("type") or "") != "override_granted":
            continue
        if str(event.get("tool") or "") != tool_name:
            continue
        if str(event.get("args_sha256") or "") != args_sha256:
            continue
        override_id = str(
            event.get("override_id")
            or event.get("pending_id")
            or event.get("confirm_id")
            or event.get("id")
            or ""
        )
        if override_id and override_id in consumed_ids:
            continue
        if not override_id and (tool_name, args_sha256) in consumed_pairs:
            continue
        expires_at = parse_utc(str(event.get("expires_at") or ""))
        if expires_at is not None and expires_at <= now:
            continue
        return event
    return None


def active_pending_override(project_root: Path, session_id: str, tool_name: str, args_sha256: str) -> Optional[dict]:
    pending = read_pending_confirm(pending_confirm_path(project_root, session_id))
    if not pending:
        return None
    if pending.get("approved") is not True:
        return None
    if pending.get("consumed") is not False:
        return None
    if pending.get("tool") != tool_name or pending.get("args_sha256") != args_sha256:
        return None
    expires_at = parse_utc(str(pending.get("expires_at") or ""))
    if expires_at is not None and expires_at <= utc_now():
        return None
    return pending


def consume_phase_override(
    project_root: Path,
    home: Path,
    session_id: str,
    tool_name: str,
    args_sha256: str,
    override: dict,
) -> int:
    timestamp = format_utc(utc_now())
    override_id = str(
        override.get("override_id")
        or override.get("pending_id")
        or override.get("confirm_id")
        or override.get("id")
        or ""
    )
    pending_path = pending_confirm_path(project_root, session_id)
    pending = read_pending_confirm(pending_path)
    if pending and pending.get("tool") == tool_name and pending.get("args_sha256") == args_sha256:
        if not override_id or pending.get("id") == override_id:
            pending["consumed"] = True
            pending["consumed_at"] = timestamp
            write_pending_confirm(pending_path, pending)

    return append_event_after_verified(
        project_root,
        home,
        session_id,
        {
            "args_sha256": args_sha256,
            "override_id": override_id,
            "timestamp": timestamp,
            "tool": tool_name,
            "type": "override_consumed",
        },
    )


def is_phase_gate_mutating_tool(tool_name: str, tool_input: dict) -> bool:
    if tool_name in PHASE_MUTATING_TOOLS:
        return True
    if tool_name == "Bash":
        return is_phase_gate_mutating_command(str(tool_input.get("command") or ""))
    return False


def path_is_under(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def is_phase_gate_draft_path(tool_input: dict, project_root: Path, home: Path) -> bool:
    draft_root = (project_root / ".gran-maestro" / "drafts").resolve()
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(normalize_path(value.strip(), project_root, home)).expanduser().resolve()
        if path_is_under(candidate, draft_root):
            return True
    return False


def evaluate_phase_gate(project_root: Path, home: Path, payload: dict, session_id: str) -> Tuple[int, List[dict]]:
    tool_name = str(payload.get("tool_name") or "").strip() or "unknown"
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if is_phase_gate_draft_path(tool_input, project_root, home):
        return 0, []
    if not is_phase_gate_mutating_tool(tool_name, tool_input):
        return 0, []

    args_sha256 = sha256_text(canonical_json(tool_input))
    req_id, task_id = payload_scope(project_root, payload, tool_input)
    if has_phase_evidence(project_root, session_id, req_id, task_id):
        return 0, [
            {
                "args_sha256": args_sha256,
                "decision": "normal_allow",
                "message": "phase gate satisfied",
                "rule_id": PHASE_GATE_RULE_ID,
                "tool": tool_name,
            }
        ]

    override = active_override_event(project_root, session_id, tool_name, args_sha256) or active_pending_override(
        project_root,
        session_id,
        tool_name,
        args_sha256,
    )
    if override is not None:
        status = consume_phase_override(project_root, home, session_id, tool_name, args_sha256, override)
        return status, [{"decision": "override_allow", "rule_id": PHASE_GATE_RULE_ID, "message": "override consumed"}]

    message = "mutating tool requires spec.accepted or approved override"
    stderr(f"[policy-block] rule={PHASE_GATE_RULE_ID} {message}")
    return 2, [
        {
            "args_sha256": args_sha256,
            "decision": "policy_block",
            "message": message,
            "rule_id": PHASE_GATE_RULE_ID,
            "tool": tool_name,
        }
    ]


def get_arg(tool_input: dict, key: str) -> str:
    value = tool_input.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def arg_pattern(tool_input: dict, key: str, op: str, value) -> bool:
    observed = get_arg(tool_input, str(key or ""))
    if op == "equals":
        return observed == str(value)
    if op == "contains":
        return str(value) in observed
    if op == "regex":
        return re.search(str(value), observed) is not None
    if op == "in":
        return observed in [str(item) for item in value] if isinstance(value, list) else False
    return False


def match_object(row: dict, expected) -> bool:
    if not isinstance(expected, dict):
        return False
    for key, value in expected.items():
        observed = row.get(key)
        if isinstance(value, dict) and "in" in value:
            if observed not in value.get("in", []):
                return False
        elif observed != value:
            return False
    return True


def evaluate_policy(project_root: Path, home: Path, payload: dict) -> Tuple[int, List[dict]]:
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    policy_dir = policy_home(home) / "projects" / project_key(project_root)
    manifest = policy_dir / "manifest.json"
    if not manifest.is_file():
        return 0, []

    cache_path = policy_dir / ".rule-engine-cache.json"

    def fingerprint(path: Path) -> str:
        stat = path.stat()
        return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"

    def verified_rule_files():
        try:
            manifest_bytes = manifest.read_bytes()
            manifest_payload = json.loads(manifest_bytes.decode("utf-8"))
        except Exception:
            stderr(f"[policy-block] manifest_invalid file={manifest}")
            raise SystemExit(2)
        if not isinstance(manifest_payload, dict) or manifest_payload.get("version") != 1 or not isinstance(manifest_payload.get("rules"), list):
            stderr(f"[policy-block] manifest_invalid file={manifest}")
            raise SystemExit(2)
        verified_files = []
        aggregate = hashlib.sha256()
        for item in manifest_payload.get("rules", []):
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "")
            expected_hash = str(item.get("sha256") or "")
            if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                stderr(f"[policy-block] manifest_path_invalid file={manifest} path={rel}")
                raise SystemExit(2)
            rule_path = policy_dir / rel
            if not rule_path.is_file():
                stderr(f"[policy-block] manifest_rule_missing file={rel}")
                raise SystemExit(2)
            actual_hash = hashlib.sha256(rule_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                stderr(f"[policy-block] manifest_sha256_mismatch file={rel} expected={expected_hash} actual={actual_hash}")
                raise SystemExit(2)
            aggregate.update(rel.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(actual_hash.encode("ascii"))
            aggregate.update(b"\n")
            verified_files.append(
                {
                    "path": rel,
                    "sha256": actual_hash,
                    "rule_path": rule_path,
                }
            )
        return {
            "manifest_fingerprint": fingerprint(manifest),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "rule_content_aggregate_sha256": aggregate.hexdigest(),
            "rule_count": len(verified_files),
            "files": verified_files,
        }

    def cache_valid(verification: dict):
        if not cache_path.is_file():
            return None
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(cached, dict):
            return None
        if cached.get("manifest_fingerprint") != verification["manifest_fingerprint"]:
            return None
        if cached.get("manifest_sha256") != verification["manifest_sha256"]:
            return None
        if cached.get("rule_content_aggregate_sha256") != verification["rule_content_aggregate_sha256"]:
            return None
        if cached.get("rule_count") != verification["rule_count"]:
            return None
        files = cached.get("files")
        rules = cached.get("rules")
        if not isinstance(files, list) or not isinstance(rules, list):
            return None
        if cached.get("predicates_validated") is not True:
            return None
        cached_paths = [str(item.get("path") or "") for item in files if isinstance(item, dict)]
        verified_paths = [str(item["path"]) for item in verification["files"]]
        if cached_paths != verified_paths:
            return None
        return rules

    def unknown_predicate(rule_id: str, name: str) -> None:
        stderr(f"[policy-block] unknown_predicate rule={rule_id} predicate={name}")

    def validate_predicates(rule_id: str, condition) -> bool:
        if not isinstance(condition, dict):
            return True
        if "predicate" in condition or "name" in condition:
            name = str(condition.get("predicate") or condition.get("name") or "")
            if name not in ALLOWLIST:
                unknown_predicate(rule_id, name)
                return False
        for key in ("all", "any"):
            predicates = condition.get(key)
            if isinstance(predicates, list):
                for item in predicates:
                    if not validate_predicates(rule_id, item):
                        return False
        return True

    verification = verified_rule_files()
    verified_files = verification["files"]
    compiled_rules = cache_valid(verification)
    if compiled_rules is None:
        compiled_rules = []
        for item in verified_files:
            rule_path = item["rule_path"]
            try:
                rule_payload = json.loads(rule_path.read_text(encoding="utf-8"))
            except Exception as exc:
                stderr(f"[policy-warning] rule_file_invalid file={rule_path.name} error={exc}")
                continue
            raw_rules = rule_payload.get("rules")
            if not isinstance(raw_rules, list) and isinstance(rule_payload, dict) and rule_payload.get("id"):
                raw_rules = [rule_payload]
            if not isinstance(raw_rules, list):
                continue
            for rule in raw_rules:
                if not isinstance(rule, dict):
                    continue
                if "match" in rule or "predicate" in rule or "decision" in rule:
                    compiled_rules.append(
                        {
                            "id": str(rule.get("id") or rule_path.name),
                            "trigger": rule.get("match"),
                            "condition": rule.get("predicate"),
                            "action": {
                                "decision": rule.get("decision"),
                                "message": rule.get("reason") or rule.get("message"),
                            },
                            "severity": rule.get("severity"),
                            "message": rule.get("reason") or rule.get("message"),
                        }
                    )
                    continue
                compiled_rules.append(
                    {
                        "id": str(rule.get("id") or rule_path.name),
                        "trigger": rule.get("trigger"),
                        "condition": rule.get("condition"),
                        "action": rule.get("action"),
                        "severity": rule.get("severity"),
                        "message": rule.get("message"),
                    }
                )
        for rule in compiled_rules:
            rule_id = str(rule.get("id") or "rule")
            if not validate_predicates(rule_id, rule.get("condition")):
                return 2, [{"decision": "policy_block", "rule_id": rule_id, "message": "unknown_predicate"}]
        tmp_path = Path(str(cache_path) + ".tmp")
        tmp_path.write_text(
            json.dumps(
                {
                    "manifest_fingerprint": verification["manifest_fingerprint"],
                    "manifest_sha256": verification["manifest_sha256"],
                    "rule_content_aggregate_sha256": verification["rule_content_aggregate_sha256"],
                    "rule_count": verification["rule_count"],
                    "files": [
                        {
                            "path": item["path"],
                            "sha256": item["sha256"],
                        }
                        for item in verified_files
                    ],
                    "predicates_validated": True,
                    "rules": compiled_rules,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(tmp_path, cache_path)

    history_cache: dict = {}
    unknown_predicate_seen = False
    decisions: List[dict] = []

    def path_protected(path_glob: str) -> bool:
        raw_glob = str(path_glob or "")
        expanded_glob = os.path.expanduser(raw_glob)
        target = (
            get_arg(tool_input, "file_path")
            or get_arg(tool_input, "notebook_path")
            or get_arg(tool_input, "path")
            or get_arg(tool_input, "command")
        )
        if not target:
            return False
        expanded_target = os.path.expanduser(target)
        target_abs = os.path.abspath(expanded_target)
        glob_abs = os.path.abspath(expanded_glob)
        return (
            fnmatch.fnmatch(target_abs, glob_abs)
            or fnmatch.fnmatch(expanded_target, expanded_glob)
            or fnmatch.fnmatch(target, raw_glob)
        )

    def history_exists(type_filter) -> bool:
        return any(match_object(row, type_filter) for row in load_history_events(project_root, str(payload.get("session_id") or ""), history_cache))

    def history_not_exists_after(anchor, target) -> bool:
        rows = load_history_events(project_root, str(payload.get("session_id") or ""), history_cache)
        anchor_index = -1
        for index, row in enumerate(rows):
            if match_object(row, anchor):
                anchor_index = index
        if anchor_index < 0:
            return False
        return not any(match_object(row, target) for row in rows[anchor_index + 1 :])

    def eval_predicate(rule_id: str, predicate) -> bool:
        nonlocal unknown_predicate_seen
        if not isinstance(predicate, dict):
            return True
        if "predicate" in predicate or "name" in predicate:
            name = str(predicate.get("predicate") or predicate.get("name") or "")
            if name not in ALLOWLIST:
                unknown_predicate(rule_id, name)
                raise SystemExit(2)
            if name == "tool_match":
                return tool_name == predicate.get("name")
            if name == "arg_pattern":
                return arg_pattern(tool_input, predicate.get("key"), predicate.get("op"), predicate.get("value"))
            if name == "path_protected":
                return path_protected(predicate.get("path_glob"))
            if name == "history_exists":
                return history_exists(predicate.get("type_filter"))
            if name == "history_not_exists_after":
                return history_not_exists_after(predicate.get("anchor"), predicate.get("target"))
        if "history" in predicate:
            history = predicate.get("history")
            if isinstance(history, dict) and "exists" in history:
                return history_exists(history.get("exists"))
            if isinstance(history, dict) and "not_exists_after" in history:
                payload_value = history.get("not_exists_after")
                if isinstance(payload_value, dict):
                    return history_not_exists_after(payload_value.get("anchor"), payload_value.get("target"))
        return True

    def trigger_matches(trigger) -> bool:
        if not isinstance(trigger, dict):
            return True
        if "all" in trigger:
            items = trigger.get("all")
            return all(trigger_matches(item) for item in items) if isinstance(items, list) else True
        if "any" in trigger:
            items = trigger.get("any")
            return any(trigger_matches(item) for item in items) if isinstance(items, list) else True
        tool = trigger.get("tool")
        if isinstance(tool, str) and tool and tool_name != tool:
            return False
        args = trigger.get("args")
        if isinstance(args, dict):
            for key, condition in args.items():
                if isinstance(condition, dict):
                    for op, value in condition.items():
                        if not arg_pattern(tool_input, key, op, value):
                            return False
                elif get_arg(tool_input, key) != str(condition):
                    return False
        return True

    def condition_matches(rule_id: str, condition) -> bool:
        if not isinstance(condition, dict):
            return True
        if "all" in condition:
            return all(eval_predicate(rule_id, item) for item in condition.get("all", []))
        if "any" in condition:
            return any(eval_predicate(rule_id, item) for item in condition.get("any", []))
        return eval_predicate(rule_id, condition)

    for rule in compiled_rules:
        rule_id = str(rule.get("id") or "rule")
        if not trigger_matches(rule.get("trigger")):
            continue
        if not condition_matches(rule_id, rule.get("condition")):
            continue
        action = rule.get("action") if isinstance(rule.get("action"), dict) else {}
        decision = action.get("decision") or ("block" if rule.get("severity") == "block" else "warn")
        message = str(action.get("message") or rule.get("message") or rule_id)
        if decision == "block":
            stderr(f"[policy-block] rule={rule_id} {message}")
            return 2, [{"decision": "policy_block", "rule_id": rule_id, "message": message}]
        if decision == "warn":
            stderr(f"[policy-warning] rule={rule_id} {message}")
            decisions.append({"decision": "warn", "rule_id": rule_id, "message": message})
    if unknown_predicate_seen:
        stderr("[policy-block] unknown_predicate fail_closed")
        return 2, [{"decision": "policy_block", "rule_id": "unknown_predicate", "message": "fail_closed"}]
    return 0, decisions


def hardcoded_core_check(project_root: Path, home: Path, payload: dict) -> int:
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    session_id = str(payload.get("session_id") or "").strip()
    clean_sid = sanitize_session_id(session_id) if session_id else None
    raw_file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    command = str(tool_input.get("command") or "")
    file_path = normalize_path(raw_file_path, project_root, home)
    policy_root = str(policy_home(home))
    sessions_root = str(project_root / ".gran-maestro" / "sessions")

    def core_block(rule_id: str, reason: str) -> int:
        return emit_core_block_and_return(
            project_root,
            home,
            clean_sid or "",
            tool_name,
            tool_input,
            rule_id,
            reason,
        )

    if tool_name == "ScheduleWakeup" and schedule_wakeup_block_active(project_root):
        if os.environ.get("MST_ALLOW_SCHEDULE_WAKEUP") == "1":
            stderr("[mst] ScheduleWakeup escape hatch used")
            return 0
        stderr(SCHEDULE_WAKEUP_RESUME_HINT)
        return core_block(SCHEDULE_WAKEUP_BLOCK_RULE_ID, SCHEDULE_WAKEUP_BLOCK_REASON)

    if tool_name == "AskUserQuestion" and schedule_wakeup_block_active(project_root):
        return core_block(ASK_USER_QUESTION_BLOCK_RULE_ID, ASK_USER_QUESTION_BLOCK_REASON)

    if tool_name in {"Write", "Edit", "MultiEdit"} and file_path.startswith(policy_root + "/"):
        if "/rules.d/" in file_path or file_path.endswith("/manifest.json"):
            return core_block(
                "META-BYPASS-RULE-FILE",
                "정책 디렉토리는 LLM이 수정할 수 없습니다.",
            )
        return core_block(
            "META-BYPASS-POLICY-DIR",
            "정책 디렉토리는 LLM이 수정할 수 없습니다.",
        )

    if tool_name == "Bash" and is_mutating_command(command):
        if ".claude/gran-maestro-policy" in command or policy_root in command:
            if "/ledger-heads/" in command:
                return core_block(
                    "META-BYPASS-LEDGER-SENTINEL",
                    "ledger sentinel은 LLM이 직접 수정할 수 없습니다.",
                )
            if "/rules.d/" in command or "manifest.json" in command:
                return core_block(
                    "META-BYPASS-RULE-FILE",
                    "정책 디렉토리는 LLM이 수정할 수 없습니다.",
                )
            return core_block(
                "META-BYPASS-POLICY-DIR",
                "정책 디렉토리는 LLM이 수정할 수 없습니다.",
            )

    if tool_name in {"Write", "Edit", "MultiEdit"} and (
        file_path.startswith(sessions_root + "/") or "/.gran-maestro/sessions/" in file_path
    ) and file_path.endswith("history.ndjson"):
        return core_block(
            "META-BYPASS-HISTORY-NDJSON",
            "history.ndjson은 LLM이 직접 수정할 수 없습니다.",
        )

    if tool_name == "Bash" and is_mutating_command(command):
        if ".gran-maestro/sessions/" in command and "history.ndjson" in command:
            return core_block(
                "META-BYPASS-HISTORY-NDJSON",
                "history.ndjson은 LLM이 직접 수정할 수 없습니다.",
            )
        if ".gran-maestro/sessions/" in command and (
            "history.head" in command or "history.verify" in command
        ):
            return core_block(
                "META-BYPASS-LEDGER-SENTINEL",
                "ledger sentinel은 LLM이 직접 수정할 수 없습니다.",
            )
        if ".gran-maestro/sessions/" in command and SESSION_RENAME_RE.search(command):
            return core_block(
                "META-BYPASS-SESSION-ID-FORGERY",
                "session_id 디렉토리는 LLM이 직접 생성하거나 이름 변경할 수 없습니다.",
            )

    if tool_name in {"Write", "Edit", "MultiEdit"} and (
        file_path.startswith(sessions_root + "/") or "/.gran-maestro/sessions/" in file_path
    ) and file_path.endswith("history.head"):
        return core_block(
            "META-BYPASS-LEDGER-SENTINEL",
            "ledger sentinel은 LLM이 직접 수정할 수 없습니다.",
        )

    if tool_name in {"Write", "Edit", "MultiEdit"} and file_path.startswith(policy_root + "/ledger-heads/"):
        return core_block(
            "META-BYPASS-LEDGER-SENTINEL",
            "ledger sentinel은 LLM이 직접 수정할 수 없습니다.",
        )

    return 0


def main() -> int:
    if len(sys.argv) != 2:
        stderr("usage: pre_tool_use_fast.py <project_root>")
        return 2

    project_root = Path(sys.argv[1]).resolve()
    home = Path(os.environ.get("HOME") or Path.home())
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    session_id = str(payload.get("session_id") or "").strip()
    clean_sid = ""
    lock_dir: Optional[Path] = None
    if session_id:
        clean_sid = sanitize_session_id(session_id)
        if clean_sid is None:
            stderr("history ledger mismatch: invalid session_id")
            return 2
        history_file, _, _, _ = history_paths(project_root, home, clean_sid)
        session_dir = history_file.parent
        lock_dir = session_dir / "history.lock"
        session_dir.mkdir(parents=True, exist_ok=True)
        if not acquire_lock(lock_dir):
            stderr("history ledger mismatch: lock timeout")
            return 2
        ok, _, _ = verify_history(project_root, home, clean_sid)
        if not ok:
            try:
                lock_dir.rmdir()
            except OSError:
                pass
            lock_dir = None
            return 2
        warn_session_id_mismatch_once_if_any(project_root, payload, raw, clean_sid)

    try:
        tool_name = str(payload.get("tool_name") or "").strip() or "unknown"
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = {}

        if clean_sid:
            expire_pending_confirm(project_root, clean_sid, utc_now())

        if tool_name == "Bash":
            command = str(tool_input.get("command") or "")
            blocked_command = blocked_mst_command(command, project_root, home)
            if blocked_command:
                reason = (
                    f"LLM Bash cannot execute {blocked_command}; "
                    "use an out-of-band user terminal approval path or fix the cause."
                )
                if clean_sid:
                    append_event_after_verified(
                        project_root,
                        home,
                        clean_sid,
                        core_block_event(tool_name, tool_input, LLM_MST_CLI_RULE_ID, reason),
                    )
                return block("core-block", LLM_MST_CLI_RULE_ID, reason)

        status = hardcoded_core_check(project_root, home, payload)
        if status:
            return status

        if clean_sid:
            override_status = consume_pending_override(project_root, home, clean_sid, tool_name, tool_input)
            if override_status is not None:
                return override_status

        allowlisted = check_allowlist(home, tool_name, tool_input)
        policy_decisions: List[dict] = []
        if allowlisted:
            policy_decisions.append(
                {
                    "decision": "normal_allow",
                    "rule_id": "MST-HOOK-ALLOWLIST",
                    "message": "allowlist matched",
                }
            )
        else:
            status, policy_decisions = evaluate_policy(project_root, home, payload)
            if status:
                if clean_sid and policy_decisions:
                    decision = policy_decisions[0]
                    if decision.get("decision") == "policy_block":
                        timestamp = format_utc(utc_now())
                        args_sha256 = sha256_text(canonical_json(tool_input))
                        side_effect_status = append_event_after_verified(
                            project_root,
                            home,
                            clean_sid,
                            {
                                "args_sha256": args_sha256,
                                "message": str(decision.get("message") or ""),
                                "rule_id": str(decision.get("rule_id") or "policy_block"),
                                "timestamp": timestamp,
                                "tool": str(payload.get("tool_name") or "").strip() or "unknown",
                                "type": "policy_block",
                            },
                        )
                        if side_effect_status:
                            return side_effect_status
                        side_effect_status = request_pending_confirm(
                            project_root,
                            home,
                            clean_sid,
                            tool_name,
                            tool_input,
                            str(decision.get("rule_id") or "policy_block"),
                        )
                        if side_effect_status:
                            return side_effect_status
                return status

        phase_decisions: List[dict] = []
        if clean_sid and not allowlisted:
            status, phase_decisions = evaluate_phase_gate(project_root, home, payload, clean_sid)
            if status:
                if phase_decisions and phase_decisions[0].get("decision") == "policy_block":
                    decision = phase_decisions[0]
                    timestamp = format_utc(utc_now())
                    args_sha256 = str(decision.get("args_sha256") or sha256_text(canonical_json(tool_input)))
                    side_effect_status = append_event_after_verified(
                        project_root,
                        home,
                        clean_sid,
                        {
                            "args_sha256": args_sha256,
                            "message": str(decision.get("message") or ""),
                            "rule_id": str(decision.get("rule_id") or "policy_block"),
                            "timestamp": timestamp,
                            "tool": str(payload.get("tool_name") or "").strip() or "unknown",
                            "type": "policy_block",
                        },
                    )
                    if side_effect_status:
                        return side_effect_status
                    side_effect_status = request_pending_confirm(
                        project_root,
                        home,
                        clean_sid,
                        str(payload.get("tool_name") or "").strip() or "unknown",
                        tool_input,
                        str(decision.get("rule_id") or "policy_block"),
                    )
                    if side_effect_status:
                        return side_effect_status
                return status

        if clean_sid:
            args_json = canonical_json(tool_input)
            args_sha256 = sha256_text(args_json)
            for decision in policy_decisions + phase_decisions:
                decision_type = decision.get("decision")
                if decision_type not in {"warn", "normal_allow"}:
                    continue
                timestamp = format_utc(utc_now())
                side_effect_status = append_event_after_verified(
                    project_root,
                    home,
                    clean_sid,
                    {
                        "args_sha256": args_sha256,
                        "message": str(decision.get("message") or ""),
                        "rule_id": str(decision.get("rule_id") or decision_type),
                        "timestamp": timestamp,
                        "tool": tool_name,
                        "type": "warn_auto_allow" if decision_type == "warn" else "normal_allow",
                    },
                )
                if side_effect_status:
                    return side_effect_status
        if clean_sid:
            return append_tool_call_after_verified(
                project_root,
                home,
                clean_sid,
                tool_name,
                tool_input,
            )
        return append_tool_call(
            project_root,
            home,
            session_id,
            tool_name,
            tool_input,
        )
    finally:
        if lock_dir is not None:
            try:
                lock_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
