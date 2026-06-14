from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.mst_cmds import _common
from scripts.mst_cmds._common import _compact_json, _parse_bool_arg


QUESTION_ID_RE = re.compile(r"^Q-[0-9]{8}T[0-9]{6}Z-[a-z0-9]{8}$")


def _base_dir() -> Path:
    if _common.BASE_DIR is None:
        return _common.find_base_dir()
    return _common.BASE_DIR


def _questions_dir() -> Path:
    return _base_dir() / "questions"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_question_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"Q-{stamp}-{uuid.uuid4().hex[:8]}"


def _question_path(question_id: str) -> Path:
    if not QUESTION_ID_RE.match(question_id):
        raise ValueError(f"invalid question id: {question_id}")
    return _questions_dir() / f"{question_id}.json"


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"payload file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"payload file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("question payload must be a JSON object")
    return payload


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def question_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_option(option: Any, index: int) -> None:
    if isinstance(option, str):
        if not option.strip():
            raise ValueError(f"option {index} label is empty")
        return
    if not isinstance(option, dict):
        raise ValueError(f"option {index} must be a string or object")
    label = option.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"option {index} label is required")


def _validate_question_payload(payload: dict[str, Any]) -> None:
    questions = payload.get("questions")
    if questions is not None:
        if not isinstance(questions, list) or not questions:
            raise ValueError("questions must be a non-empty array")
        for q_index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                raise ValueError(f"questions[{q_index}] must be an object")
            text = question.get("question") or question.get("prompt")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"questions[{q_index}] question is required")
            options = question.get("options")
            if options is not None:
                _validate_options(options, f"questions[{q_index}].options")
        return

    text = payload.get("question") or payload.get("prompt")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("question is required")
    options = payload.get("options")
    if options is not None:
        _validate_options(options, "options")


def _validate_options(options: Any, field: str) -> None:
    if not isinstance(options, list):
        raise ValueError(f"{field} must be an array")
    if len(options) > 4:
        raise ValueError(f"{field} must contain at most 4 options")
    if len(options) == 1:
        raise ValueError(f"{field} must contain at least 2 options when provided")
    for index, option in enumerate(options, start=1):
        _validate_option(option, index)


def _host_context(host_value: str, event: str) -> dict[str, Any]:
    from scripts.mst_cmds import host as host_cmd

    return host_cmd.build_host_context(host=host_value, event=event, payload={})


def _workflow_state_path() -> Path:
    return _common._workflow_state_file(_base_dir())


def _load_workflow_state(now: str) -> dict[str, Any]:
    path = _workflow_state_path()
    payload = _common._workflow_state_load(path)
    if isinstance(payload, dict):
        return payload
    return _common._workflow_state_default_payload(now)


def _update_workflow_user_input(
    *,
    question_id: str,
    expected_hash: str,
    skill: str,
    step: str,
    resume_skill: str,
    resume_args: str,
    host_context: dict[str, Any],
) -> str:
    now = _now()
    session_id = _common.require_mst_session_id_for_mutation("question boundary state")
    state_path = _workflow_state_path()
    payload = _load_workflow_state(now)
    error = _common.canonical_state_payload_error(payload, session_id)
    if error is not None:
        if "missing" not in error:
            raise ValueError(error)
        payload.update(_common.canonical_state_payload_fields(session_id))

    payload["awaiting_user_input"] = True
    payload["question_id"] = question_id
    payload["expected_question_hash"] = expected_hash
    payload["user_input"] = {
        "awaiting": True,
        "question_id": question_id,
        "expected_question_hash": expected_hash,
        "skill": skill,
        "step": step,
        "resume_skill": resume_skill,
        "resume_args": resume_args,
        "host": host_context.get("host"),
        "updated_at": now,
    }
    payload["updated_at"] = now
    payload.update(_common.canonical_state_payload_fields(session_id))
    _common._workflow_state_atomic_write(state_path, payload)
    return session_id


def _clear_workflow_user_input(question_id: str | None = None) -> None:
    session_id = _common.require_mst_session_id_for_mutation("question boundary state")
    state_path = _workflow_state_path()
    payload = _common._workflow_state_load(state_path)
    if not isinstance(payload, dict):
        return
    error = _common.canonical_state_payload_error(payload, session_id)
    if error is not None:
        raise ValueError(error)
    if question_id and str(payload.get("question_id") or "") != question_id:
        return
    payload["awaiting_user_input"] = False
    payload["question_id"] = ""
    payload["expected_question_hash"] = ""
    user_input = payload.get("user_input")
    if isinstance(user_input, dict):
        user_input["awaiting"] = False
        user_input["answered_at"] = _now()
    payload["updated_at"] = _now()
    _common._workflow_state_atomic_write(state_path, payload)


def _format_user_message(question_id: str, payload: dict[str, Any], resume_command: str) -> str:
    lines = [f"[MST 사용자 입력 대기] {question_id}"]
    if isinstance(payload.get("question"), str):
        lines.append(payload["question"].strip())
    elif isinstance(payload.get("prompt"), str):
        lines.append(payload["prompt"].strip())
    elif isinstance(payload.get("questions"), list):
        for index, question in enumerate(payload["questions"], start=1):
            if isinstance(question, dict):
                text = str(question.get("question") or question.get("prompt") or "").strip()
                if text:
                    lines.append(f"{index}. {text}")
    options = payload.get("options")
    if isinstance(options, list) and options:
        lines.append("")
        lines.append("선택지:")
        for option in options:
            if isinstance(option, str):
                lines.append(f"- {option}")
            elif isinstance(option, dict):
                label = str(option.get("label") or "").strip()
                description = str(option.get("description") or option.get("preview") or "").strip()
                lines.append(f"- {label}" + (f": {description}" if description else ""))
    lines.append("")
    lines.append("다음 단계 실행 명령:")
    lines.append(f"  {resume_command}")
    return "\n".join(lines)


def _write_pending_artifact(
    *,
    question_id: str,
    payload: dict[str, Any],
    payload_hash: str,
    skill: str,
    step: str,
    resume_skill: str,
    resume_args: str,
    host_context: dict[str, Any],
    mst_session_id: str,
) -> Path:
    path = _question_path(question_id)
    artifact = {
        "schema_version": 1,
        "id": question_id,
        "status": "pending",
        "created_at": _now(),
        "payload_hash": payload_hash,
        "payload": payload,
        "skill": skill,
        "step": step,
        "resume_skill": resume_skill,
        "resume_args": resume_args,
        "mst_session_id": mst_session_id,
        "host_context": host_context,
        "answer": None,
        "answered_at": None,
        "consumed_at": None,
    }
    _common.save_json(path, artifact)
    return path


def _load_question(question_id: str) -> tuple[Path, dict[str, Any]]:
    path = _question_path(question_id)
    payload = _common.load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"question not found: {question_id}")
    return path, payload


def cmd_question_prepare(args) -> int:
    try:
        payload = _read_json_file(Path(args.payload_file).expanduser())
        _validate_question_payload(payload)
        payload_hash = question_hash(payload)
        context = _host_context(args.host, "question-prepare")
        host_name = str(context.get("host") or "headless")
        auto_mode = bool(args.auto) if args.auto is not None else False
        if auto_mode:
            result = {
                "mode": "auto_decision",
                "status": "skipped",
                "reason": "AUTO_MODE=true",
                "payload_hash": payload_hash,
            }
            print(_compact_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        question_id = _new_question_id()
        resume_skill = args.resume_skill or args.skill
        resume_args = args.resume_args or ""
        mst_session_id = _update_workflow_user_input(
            question_id=question_id,
            expected_hash=payload_hash,
            skill=args.skill,
            step=args.step,
            resume_skill=resume_skill,
            resume_args=resume_args,
            host_context=context,
        )

        if host_name == "claude":
            result = {
                "mode": "claude_tool",
                "tool": "AskUserQuestion",
                "question_id": question_id,
                "payload_hash": payload_hash,
                "payload": payload,
            }
            print(_compact_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        resume_command = f"/mst:resume --answer {question_id}"
        path = _write_pending_artifact(
            question_id=question_id,
            payload=payload,
            payload_hash=payload_hash,
            skill=args.skill,
            step=args.step,
            resume_skill=resume_skill,
            resume_args=resume_args,
            host_context=context,
            mst_session_id=mst_session_id,
        )
        result = {
            "mode": "pending_artifact",
            "question_id": question_id,
            "path": str(path),
            "payload_hash": payload_hash,
            "user_message": _format_user_message(question_id, payload, resume_command),
            "resume_command": resume_command,
        }
        print(_compact_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        result = {"mode": "error", "status": "blocked", "reason": str(exc)}
        print(_compact_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
        return 2


def cmd_question_pending(args) -> int:
    questions = []
    if _questions_dir().is_dir():
        for path in sorted(_questions_dir().glob("Q-*.json")):
            payload = _common.load_json(path)
            if isinstance(payload, dict) and payload.get("status") == "pending":
                questions.append(payload)
    print(_compact_json(questions) if args.json else json.dumps(questions, ensure_ascii=False, indent=2))
    return 0


def cmd_question_answer(args) -> int:
    try:
        path, payload = _load_question(args.question_id)
        if args.answer_file:
            answer_value: Any = _read_json_file(Path(args.answer_file).expanduser())
        else:
            answer_value = args.answer
        payload["answer"] = answer_value
        payload["answered_at"] = _now()
        payload["status"] = "answered"
        _common.save_json(path, payload)
        result = {"status": "answered", "question_id": args.question_id, "path": str(path)}
        print(_compact_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        result = {"status": "error", "reason": str(exc)}
        print(_compact_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
        return 2


def cmd_question_consume(args) -> int:
    try:
        path, payload = _load_question(args.question_id)
        if payload.get("status") not in {"answered", "pending"}:
            raise ValueError(f"question is not consumable: {args.question_id}")
        payload["status"] = "consumed"
        payload["consumed_at"] = _now()
        _common.save_json(path, payload)
        _clear_workflow_user_input(args.question_id)
        result = {"status": "consumed", "question_id": args.question_id, "answer": payload.get("answer")}
        print(_compact_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        result = {"status": "error", "reason": str(exc)}
        print(_compact_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
        return 2


def cmd_question_list(args) -> int:
    rows = []
    if _questions_dir().is_dir():
        for path in sorted(_questions_dir().glob("Q-*.json")):
            payload = _common.load_json(path)
            if not isinstance(payload, dict):
                continue
            if args.status != "all" and payload.get("status") != args.status:
                continue
            rows.append(payload)
    print(_compact_json(rows) if args.json else json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def register(subparsers) -> None:
    question = subparsers.add_parser("question")
    sub = question.add_subparsers(dest="subcommand")

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--skill", required=True)
    prepare.add_argument("--step", default="")
    prepare.add_argument("--resume-skill", dest="resume_skill", default="")
    prepare.add_argument("--resume-args", dest="resume_args", default="")
    prepare.add_argument("--payload-file", dest="payload_file", required=True)
    prepare.add_argument("--host", choices=["auto", "claude", "codex", "headless"], default="auto")
    prepare.add_argument("--auto", type=_parse_bool_arg, default=None)
    prepare.add_argument("--json", action="store_true")

    pending = sub.add_parser("pending")
    pending.add_argument("--json", action="store_true")

    answer = sub.add_parser("answer")
    answer.add_argument("question_id")
    answer.add_argument("--answer", default="")
    answer.add_argument("--answer-file", dest="answer_file", default="")
    answer.add_argument("--json", action="store_true")

    consume = sub.add_parser("consume")
    consume.add_argument("question_id")
    consume.add_argument("--json", action="store_true")

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--status", choices=["pending", "answered", "consumed", "all"], default="all")
    list_cmd.add_argument("--json", action="store_true")
