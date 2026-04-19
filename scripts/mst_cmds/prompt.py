from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.mst_cmds import _common


def _base_dir() -> Path:
    if _common.BASE_DIR is not None:
        return _common.BASE_DIR
    return _common.find_base_dir()


def _resolve_reference_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    base_dir = _base_dir()
    if path.parts and path.parts[0] == ".gran-maestro":
        return base_dir.parent / path
    return base_dir / path


def _structured_errors(errors: list[dict]) -> None:
    print(json.dumps({"errors": errors}, ensure_ascii=False, indent=2))


def _load_doc(input_path: str):
    path = Path(input_path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: input file not found: {path}", file=sys.stderr)
        return None, 1
    except PermissionError as exc:
        print(f"Error: failed to read input file {path}: {exc}", file=sys.stderr)
        return None, 1

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        _structured_errors([{
            "path": f"<root:line{exc.lineno}:col{exc.colno}>",
            "reason": f"JSON decode error: {exc.msg}",
        }])
        return None, 2

    if not isinstance(data, dict):
        _structured_errors([{"path": "<root>", "reason": "input must be a JSON object"}])
        return None, 2
    return data, 0


def _validate(doc: dict) -> list[dict]:
    errors: list[dict] = []

    if doc.get("format") != "mst.dispatch":
        errors.append({"path": "format", "reason": 'must equal "mst.dispatch"'})
    if doc.get("schema_version") != 1:
        errors.append({"path": "schema_version", "reason": "must equal 1"})

    common = doc.get("common")
    if not isinstance(common, dict):
        errors.append({"path": "common", "reason": "must be an object"})
    else:
        topic = common.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            errors.append({"path": "common.topic", "reason": "must be a non-empty string"})
        constraints = common.get("constraints")
        if constraints is not None and not isinstance(constraints, list):
            errors.append({"path": "common.constraints", "reason": "must be a list when provided"})
        ref_file = common.get("reference_context_file")
        if ref_file is not None and (not isinstance(ref_file, str) or not ref_file.strip()):
            errors.append({
                "path": "common.reference_context_file",
                "reason": "must be a non-empty string when provided",
            })
        if "reference_context" in common:
            errors.append({
                "path": "common.reference_context",
                "reason": "inline long body is forbidden — use common.reference_context_file instead (DSC-059)",
            })

    tasks = doc.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append({"path": "tasks", "reason": "must be a non-empty list"})
        return errors

    for index, task in enumerate(tasks):
        task_path = f"tasks[{index}]"
        if not isinstance(task, dict):
            errors.append({"path": task_path, "reason": "must be an object"})
            continue

        role = task.get("role")
        if not isinstance(role, str) or not role.strip():
            errors.append({"path": f"{task_path}.role", "reason": "must be a non-empty string"})

        ask = task.get("ask")
        ask_file = task.get("ask_file")
        has_ask = isinstance(ask, str) and bool(ask.strip())
        has_ask_file = isinstance(ask_file, str) and bool(ask_file.strip())

        if ask is not None and not isinstance(ask, str):
            errors.append({"path": f"{task_path}.ask", "reason": "must be a string when provided"})
        if ask_file is not None and not isinstance(ask_file, str):
            errors.append({"path": f"{task_path}.ask_file", "reason": "must be a string when provided"})
        if not has_ask and not has_ask_file:
            errors.append({"path": task_path, "reason": "ask or ask_file is required"})

        if has_ask and not has_ask_file:
            if len(ask) > 200:
                errors.append({
                    "path": f"{task_path}.ask",
                    "reason": "exceeds 200 chars - use ask_file instead",
                })
            if len(ask.splitlines()) >= 3:
                errors.append({
                    "path": f"{task_path}.ask",
                    "reason": "contains 3 or more lines - use ask_file instead",
                })
            if ask.count('"') >= 3:
                errors.append({
                    "path": f"{task_path}.ask",
                    "reason": 'contains 3 or more " characters - use ask_file instead',
                })
            if "```" in ask:
                errors.append({
                    "path": f"{task_path}.ask",
                    "reason": "ask contains code fence — use ask_file instead",
                })

    return errors


def _missing_files(doc: dict) -> list[tuple[str, str, Path]]:
    missing: list[tuple[str, str, Path]] = []

    common = doc.get("common")
    if isinstance(common, dict):
        ref_file = common.get("reference_context_file")
        if isinstance(ref_file, str) and ref_file.strip():
            resolved = _resolve_reference_path(ref_file)
            if not resolved.exists():
                missing.append(("common.reference_context_file", ref_file, resolved))

    tasks = doc.get("tasks")
    if isinstance(tasks, list):
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                continue
            ask_file = task.get("ask_file")
            if isinstance(ask_file, str) and ask_file.strip():
                resolved = _resolve_reference_path(ask_file)
                if not resolved.exists():
                    missing.append((f"tasks[{index}].ask_file", ask_file, resolved))

    return missing


def _emit_missing_files(missing: list[tuple[str, str, Path]]) -> None:
    for path_name, original, resolved in missing:
        print(f"Error: {path_name} not found: {original} ({resolved})", file=sys.stderr)


def _warn_ask_file_wins(doc: dict) -> None:
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        return
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        ask = task.get("ask")
        ask_file = task.get("ask_file")
        if isinstance(ask, str) and ask.strip() and isinstance(ask_file, str) and ask_file.strip():
            print(
                f"warning: tasks[{index}] includes both ask and ask_file; using ask_file",
                file=sys.stderr,
            )


def _read_text_file(path: Path):
    try:
        return path.read_text(encoding="utf-8"), 0
    except OSError as exc:
        print(f"Error: failed to read {path}: {exc}", file=sys.stderr)
        return None, 1


def _role_filename(role: str) -> str:
    safe = str(role).strip().replace("/", "-").replace("\\", "-")
    safe = "_".join(safe.split())
    return f"{safe}-prompt.md"


def _task_ask(task: dict):
    ask_file = task.get("ask_file")
    if isinstance(ask_file, str) and ask_file.strip():
        return _read_text_file(_resolve_reference_path(ask_file))
    return str(task.get("ask", "")), 0


def _assemble(doc: dict):
    common = doc.get("common") or {}
    topic = str(common.get("topic", "")).strip()
    constraints = common.get("constraints")
    constraints = constraints if isinstance(constraints, list) else []

    reference_context = ""
    ref_file = common.get("reference_context_file")
    if isinstance(ref_file, str) and ref_file.strip():
        reference_context, code = _read_text_file(_resolve_reference_path(ref_file))
        if code != 0:
            return None, code

    prompts = []
    for task in doc.get("tasks", []):
        role = str(task.get("role", "")).strip()
        angle = str(task.get("angle", "")).strip()
        ask, code = _task_ask(task)
        if code != 0:
            return None, code

        lines = [
            "# MST Dispatch Prompt",
            "",
            "## Topic",
            topic,
            "",
            "## Constraints",
        ]
        if constraints:
            lines.extend(f"- {item}" for item in constraints)
        else:
            lines.append("- none")

        lines.extend(["", "## Reference Context", reference_context or "none", "", "## Role", role])
        if angle:
            lines.extend(["", "## Angle", angle])
        lines.extend(["", "## Ask", ask or ""])

        prompts.append({
            "role": role,
            "filename": _role_filename(role),
            "prompt": "\n".join(lines).rstrip() + "\n",
        })

    return prompts, 0


def _combined_text(prompts: list[dict]) -> str:
    chunks = []
    for item in prompts:
        chunks.append(f"===SPLIT: {item['filename']}===\n{item['prompt'].rstrip()}\n")
    return "\n".join(chunks).rstrip() + "\n"


def _token_count_estimate(prompts: list[dict]) -> int:
    text = "\n".join(item.get("prompt", "") for item in prompts)
    return max(1, len(text) // 4)


def _append_metrics(metrics_file: str, prompts: list[dict], sid: str | None = None) -> int:
    path = Path(metrics_file)
    payload = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "parse_status": "ok",
        "token_count_estimate": _token_count_estimate(prompts),
        "fallback_reason": None,
    }
    if sid:
        payload["sid"] = sid

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
            f.write("\n")
    except OSError as exc:
        print(f"Error: failed to write metrics file {path}: {exc}", file=sys.stderr)
        return 1
    return 0


def _load_and_validate(args):
    doc, code = _load_doc(args.input)
    if code != 0:
        return None, code

    errors = _validate(doc)
    if errors:
        _structured_errors(errors)
        return None, 2

    missing = _missing_files(doc)
    if missing:
        _emit_missing_files(missing)
        return None, 3

    return doc, 0


def cmd_prompt_validate(args):
    doc, code = _load_and_validate(args)
    if code != 0:
        return code
    _warn_ask_file_wins(doc)
    print(json.dumps({"ok": True}, ensure_ascii=False, indent=2))
    return 0


def cmd_prompt_build(args):
    doc, code = _load_and_validate(args)
    if code != 0:
        return code

    _warn_ask_file_wins(doc)
    prompts, code = _assemble(doc)
    if code != 0:
        return code

    if args.metrics_file:
        code = _append_metrics(args.metrics_file, prompts, sid=args.sid)
        if code != 0:
            return code

    if args.dry_run:
        print(json.dumps(prompts, ensure_ascii=False, indent=2))
        return 0

    out_dir = Path(args.out_dir)
    combined_path = out_dir / "combined-prompts.txt"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        combined_path.write_text(_combined_text(prompts), encoding="utf-8")
    except OSError as exc:
        print(f"Error: failed to write {combined_path}: {exc}", file=sys.stderr)
        return 1

    print(str(combined_path))
    return 0


def cmd_prompt_write_context(args):
    content_path = Path(args.content_file)
    if not content_path.exists():
        print(f"Error: content file not found: {content_path}", file=sys.stderr)
        return 1

    dest = _base_dir() / "tmp" / f"{args.prefix}-{args.sid}.md"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(content_path, dest)
    except OSError as exc:
        print(f"Error: failed to write context file {dest}: {exc}", file=sys.stderr)
        return 1

    print(str(dest.resolve()))
    return 0


def register(subparsers):
    prompt = subparsers.add_parser("prompt")
    prompt_sub = prompt.add_subparsers(dest="subcommand")

    build = prompt_sub.add_parser("build")
    build.add_argument("--input", required=True)
    build.add_argument("--out-dir", required=True)
    build.add_argument("--sid")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--metrics-file")

    validate = prompt_sub.add_parser("validate")
    validate.add_argument("--input", required=True)

    write_context = prompt_sub.add_parser("write-context")
    write_context.add_argument("--sid", required=True)
    write_context.add_argument("--content-file", required=True)
    write_context.add_argument("--prefix", default="ctx")
