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
CANONICAL_MST_SESSION_ID_RE = re.compile(
    r"^MST-[A-Z][A-Z0-9]*-[0-9]+-[0-9]{8}T[0-9]{9}Z-[a-z0-9]{8,}$"
)
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
PHASE_MUTATING_RUBY_RE = re.compile(
    r"("
    r"\bFile\.(write|open|delete|unlink|rename)\s*\(|"
    r"\bDir\.(mkdir|rmdir)\s*\(|"
    r"\bFileUtils\.(rm|rm_rf|mv|cp|mkdir_p)\s*\("
    r")",
    re.IGNORECASE,
)
PHASE_MUTATING_NODE_RE = re.compile(
    r"("
    r"\bfs\.(writeFileSync|appendFileSync|rmSync|unlinkSync|renameSync|mkdirSync|rmdirSync|copyFileSync)\s*\(|"
    r"\brequire\s*\(\s*['\"]fs['\"]\s*\)\s*\."
    r"(writeFileSync|appendFileSync|rmSync|unlinkSync|renameSync|mkdirSync|rmdirSync|copyFileSync)\s*\("
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
def is_ruby_token(token: str) -> bool:
    name = command_basename(token)
    return bool(re.match(r"^ruby[0-9.]*$", name))
def is_node_token(token: str) -> bool:
    return command_basename(token) in {"node", "nodejs"}
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
def canonical_mst_session_id_from_payload(payload: dict) -> str:
    for value in (os.environ.get("MST_SESSION_ID"), payload.get("mst_session_id")):
        if isinstance(value, str):
            candidate = value.strip()
            if CANONICAL_MST_SESSION_ID_RE.fullmatch(candidate):
                return candidate
    return ""
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
