#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


def find_mode_file(cwd: str):
    path = Path(cwd or ".").resolve()
    while True:
        candidate = path / ".gran-maestro" / "mode.json"
        if candidate.is_file():
            return candidate

        parent = path.parent
        if parent == path:
            return None
        path = parent


def count_active_requests(base_dir: Path):
    requests_dir = base_dir / "requests"
    if not requests_dir.is_dir():
        return 0

    count = 0
    for req_dir in requests_dir.iterdir():
        if not req_dir.is_dir():
            continue
        req_file = req_dir / "request.json"
        if not req_file.is_file():
            continue
        try:
            data = json.loads(req_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = str(data.get("status", ""))
        if status not in {"done", "completed", "cancelled", "failed"}:
            count += 1
    return count


def print_json_mode_not_found():
    print(json.dumps({"active": False, "error": "mode.json not found"}))


def main():
    mode_file = find_mode_file(os.environ.get("MAESTRO_PROJECT_DIR", os.getcwd()))
    if mode_file is None:
        if len(sys.argv) > 1 and sys.argv[1] == "--json":
            print_json_mode_not_found()
        elif len(sys.argv) > 1 and sys.argv[1] in {"-q", "--quiet"}:
            pass
        elif len(sys.argv) > 1 and sys.argv[1] == "--field":
            print("null")
        else:
            print("off")
        sys.exit(1)

    try:
        mode = json.loads(mode_file.read_text(encoding="utf-8"))
    except Exception:
        mode = {}

    active = bool(mode.get("active", False))
    base_dir = mode_file.parent

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "--json":
        print(json.dumps(mode))
    elif arg in {"-q", "--quiet"}:
        pass
    elif arg == "--field":
        field = sys.argv[2] if len(sys.argv) > 2 else "active"
        if field == "active_requests":
            print(count_active_requests(base_dir))
        else:
            value = mode.get(field, "")
            if value is None:
                print("")
            elif isinstance(value, bool):
                print("true" if value else "false")
            else:
                print(value)
    else:
        if active:
            print(f"on (requests: {count_active_requests(base_dir)})")
        else:
            print("off")

    sys.exit(0 if active else 1)


if __name__ == "__main__":
    main()
