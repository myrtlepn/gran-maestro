from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds.agile import _diagnose_history_lock


CANONICAL_SID = "MST-AGI-030-20260506T010203456Z-dod008"
OWNER_PID = 987654321
LEGACY_SESSION_ID = "legacy-runtime-session-dod008"
OWNER_SESSION_ID = "legacy-owner-session-dod008"
HOOK_SESSION_UUID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
TRANSCRIPT_UUID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
ZERO_HASH = "0" * 64
STALE_SECONDS = 3600


BAD_IDENTITY_WORDS = (
    "canonical",
    "fallback",
    "alias",
    "migration",
    "migrate",
    "takeover",
    "continuation key",
    "recover target",
)


HOOK_FORBIDDEN_PATTERNS = [
    (r"owner_pid\s*=.*\n(?:.*\n){0,8}.*session_id", "owner_pid must not feed hook session selection"),
    (r"session_id\s*=.*owner_pid", "owner_pid must not be assigned as session_id"),
    (r"MST_SESSION_ID=.*owner_pid", "owner_pid must not populate MST_SESSION_ID"),
    (r"mst_session_id.*owner_pid", "owner_pid must not populate mst_session_id"),
    (r"history\.lock.*owner_pid.*session", "process lock owner metadata must not select hook session"),
]


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(*roots: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[f"{root.name}/{path.relative_to(root)}"] = _sha256(path)
    return result


def _diagnostic_only_values() -> tuple[str, ...]:
    return (
        str(OWNER_PID),
        LEGACY_SESSION_ID,
        OWNER_SESSION_ID,
        HOOK_SESSION_UUID,
        TRANSCRIPT_UUID,
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_closed_minimum_artifacts(gm_dir: Path) -> None:
    _write_text(gm_dir / "recovery" / "latest" / f"{CANONICAL_SID}.json", json.dumps({"mst_session_id": CANONICAL_SID}) + "\n")
    _write_text(gm_dir / "handoff" / "latest" / f"{CANONICAL_SID}.json", json.dumps({"canonical_mst_session_id": CANONICAL_SID}) + "\n")
    _write_text(gm_dir / "current-work" / "latest" / f"{CANONICAL_SID}.json", json.dumps({"mst_session_id": CANONICAL_SID}) + "\n")
    _write_text(gm_dir / "active-flow" / f"{CANONICAL_SID}.json", json.dumps({"mst_session_id": CANONICAL_SID}) + "\n")
    _write_text(gm_dir / "run" / f"run-{CANONICAL_SID}.json", json.dumps({"canonical_mst_session_id": CANONICAL_SID}) + "\n")
    _write_text(gm_dir / "sessions" / "index.json", json.dumps({"mst_session_id": CANONICAL_SID}) + "\n")
    _write_text(gm_dir / "locks" / f"{CANONICAL_SID}.json", json.dumps({"owner": {"mst_session_id": CANONICAL_SID}}) + "\n")


def _assert_no_diagnostic_identity_artifact_partition(gm_dir: Path) -> None:
    diagnostic_values = _diagnostic_only_values()
    violations: list[str] = []
    for path in sorted(gm_dir.rglob("*")):
        relative = path.relative_to(gm_dir).as_posix()
        for value in diagnostic_values:
            if value in relative:
                violations.append(f"path uses diagnostic-only identity: {relative}")
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        stack = [("$", payload)]
        while stack:
            prefix, value = stack.pop()
            if isinstance(value, dict):
                for key, child in value.items():
                    child_prefix = f"{prefix}.{key}"
                    if key in {"mst_session_id", "canonical_mst_session_id"} and child in diagnostic_values:
                        violations.append(f"{path.relative_to(gm_dir)}:{child_prefix} uses diagnostic-only identity")
                    stack.append((child_prefix, child))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    stack.append((f"{prefix}[{index}]", child))
    assert not violations, "\n".join(violations)


def _write_history_scope(workspace: Path, *, owner: dict[str, Any]) -> tuple[Path, Path, Path, dict[str, Path]]:
    project_root = workspace / "project"
    home = workspace / "home"
    gm_dir = project_root / ".gran-maestro"
    session_dir = gm_dir / "sessions" / CANONICAL_SID
    state_dir = gm_dir / "state" / CANONICAL_SID
    mirror_dir = home / ".claude" / "gran-maestro-policy" / "ledger-heads"

    session_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    mirror_dir.mkdir(parents=True, exist_ok=True)

    _write_text(session_dir / "history.ndjson", "")
    _write_text(session_dir / "history.head", ZERO_HASH + "\n")
    _write_text(state_dir / "snapshot.json", json.dumps({"mst_session_id": CANONICAL_SID}, sort_keys=True) + "\n")
    _write_text(mirror_dir / f"{CANONICAL_SID}.head", ZERO_HASH + "\n")

    lock_path = session_dir / "history.lock"
    lock_path.mkdir()
    _write_text(lock_path / "owner.json", json.dumps(owner, sort_keys=True) + "\n")

    old = time.time() - STALE_SECONDS - 30
    os.utime(lock_path, (old, old))
    os.utime(lock_path / "owner.json", (old, old))

    paths = {
        "local_head": session_dir / "history.head",
        "mirror_head": mirror_dir / f"{CANONICAL_SID}.head",
        "owner_file": lock_path / "owner.json",
    }
    return project_root, home, lock_path, paths


def _diagnose(project_root: Path, home: Path, lock_path: Path) -> dict[str, Any]:
    payload = _diagnose_history_lock(
        project_root=project_root,
        home=home,
        session_id=CANONICAL_SID,
        lock_path=lock_path,
        stale_after_sec=STALE_SECONDS,
    )
    assert isinstance(payload, dict), payload
    return payload


def test_stale_history_owner_pid_metadata_does_not_create_legacy_identity_artifacts() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        project_root, home, lock_path, _paths = _write_history_scope(
            workspace,
            owner={
                "owner_pid": OWNER_PID,
                "owner_started_at": time.time() - STALE_SECONDS - 30,
                "session_id": LEGACY_SESSION_ID,
                "owner_session_id": OWNER_SESSION_ID,
            },
        )
        before = _snapshot(project_root, home)

        payload = _diagnose(project_root, home, lock_path)

        assert _snapshot(project_root, home) == before
        assert payload.get("category") in {
            "history-lock-stale-candidate",
            "owner-live",
            "diagnosis-inconclusive",
            "owner-unknown",
        }, payload
        assert payload.get("next_action") in {"manual-recovery-approval", "wait-for-owner", "inspect-lock-owner"}, payload
        assert not (project_root / ".gran-maestro" / "state" / str(OWNER_PID)).exists()
        assert not (project_root / ".gran-maestro" / "state" / LEGACY_SESSION_ID).exists()
        assert not (project_root / ".gran-maestro" / "state" / OWNER_SESSION_ID).exists()
        assert not (project_root / ".gran-maestro" / "sessions" / str(OWNER_PID)).exists()
        assert not (project_root / ".gran-maestro" / "sessions" / LEGACY_SESSION_ID).exists()
        assert not (project_root / ".gran-maestro" / "sessions" / OWNER_SESSION_ID).exists()
        policy_heads = home / ".claude" / "gran-maestro-policy" / "ledger-heads"
        assert not (policy_heads / f"{OWNER_PID}.head").exists()
        assert not (policy_heads / f"{LEGACY_SESSION_ID}.head").exists()
        assert not (policy_heads / f"{OWNER_SESSION_ID}.head").exists()


def test_diagnostic_only_ids_do_not_mutate_closed_minimum_artifact_partitions() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        project_root, home, lock_path, _paths = _write_history_scope(
            workspace,
            owner={
                "owner_pid": OWNER_PID,
                "owner_started_at": time.time() - STALE_SECONDS - 30,
                "session_id": LEGACY_SESSION_ID,
                "owner_session_id": OWNER_SESSION_ID,
                "hook_session_id": HOOK_SESSION_UUID,
                "transcript_path": f"/tmp/{TRANSCRIPT_UUID}.jsonl",
            },
        )
        gm_dir = project_root / ".gran-maestro"
        _write_closed_minimum_artifacts(gm_dir)
        before = _snapshot(project_root, home)

        payload = _diagnose(project_root, home, lock_path)

        assert payload.get("category") in {
            "history-lock-stale-candidate",
            "owner-live",
            "diagnosis-inconclusive",
            "owner-unknown",
        }, payload
        assert _snapshot(project_root, home) == before
        _assert_no_diagnostic_identity_artifact_partition(gm_dir)


def test_stale_candidate_keeps_owner_pid_diagnostic_only_and_preserves_heads_and_owner_file() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        project_root, home, lock_path, paths = _write_history_scope(
            workspace,
            owner={
                "owner_pid": OWNER_PID,
                "owner_started_at": time.time() - STALE_SECONDS - 30,
                "session_id": LEGACY_SESSION_ID,
                "owner_session_id": OWNER_SESSION_ID,
            },
        )
        before_hashes = {name: _sha256(path) for name, path in paths.items()}

        payload = _diagnose(project_root, home, lock_path)

        assert payload.get("category") == "history-lock-stale-candidate", payload
        assert payload.get("next_action") == "manual-recovery-approval", payload
        assert payload.get("lock_path") == str(lock_path), payload
        assert payload.get("owner_pid") in (None, ""), "stale candidate must not promote owner_pid into identity payload"
        assert {name: _sha256(path) for name, path in paths.items()} == before_hashes
        assert (project_root / ".gran-maestro" / "sessions" / CANONICAL_SID / "history.head").read_text(
            encoding="utf-8"
        ) == ZERO_HASH + "\n"


def _paragraphs_with(text: str, needle: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text)
    return [paragraph for paragraph in paragraphs if needle in paragraph]


def test_recover_docs_classify_owner_pid_as_diagnostic_only_not_identity_key() -> None:
    paths = [
        REPO_ROOT / "skills" / "recover" / "SKILL.md",
        REPO_ROOT / "docs" / "SESSION-ID-MIGRATION.md",
        REPO_ROOT / "docs" / "CLAUDE.md",
        REPO_ROOT / "README.md",
    ]
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        paragraphs = _paragraphs_with(text, "owner_pid")
        if not paragraphs:
            violations.append(f"{path.relative_to(REPO_ROOT)}: missing owner_pid contract wording")
            continue
        if not any("diagnostic-only" in paragraph for paragraph in paragraphs):
            violations.append(f"{path.relative_to(REPO_ROOT)}: owner_pid is not classified as diagnostic-only")
        for paragraph in paragraphs:
            lowered = paragraph.lower()
            safe_negative = (
                "아니다" in paragraph
                or "아니며" in paragraph
                or "될 수 없다" in paragraph
                or "not " in lowered
                or "diagnostic-only" in lowered
            )
            for word in BAD_IDENTITY_WORDS:
                if word in lowered and not safe_negative:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}: owner_pid paragraph uses identity-key wording without negation: {word}"
                    )
    assert not violations, "\n".join(violations)


def test_hook_sources_do_not_use_owner_pid_or_process_lock_owner_as_session_selector() -> None:
    hook_paths = [
        REPO_ROOT / "hooks" / "lib" / "pre_tool_use_fast.py",
        REPO_ROOT / "hooks" / "mst-pre-tool-use.sh",
    ]
    violations: list[str] = []
    for path in hook_paths:
        text = path.read_text(encoding="utf-8")
        for pattern, reason in HOOK_FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line}: {reason}")

        owner_pid_lines = [line for line in text.splitlines() if "owner_pid" in line]
        if owner_pid_lines:
            allowed_fragments = ("diagnostic", "owner_pid", "payload", "owner_status")
            for line in owner_pid_lines:
                if "session" in line.lower() or "MST_SESSION_ID" in line:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}: owner_pid line appears in session-selection context: {line.strip()}"
                    )
                if not any(fragment in line for fragment in allowed_fragments):
                    violations.append(f"{path.relative_to(REPO_ROOT)}: unexpected owner_pid hook usage: {line.strip()}")

    assert not violations, "\n".join(violations)


def main() -> int:
    tests = [
        test_stale_history_owner_pid_metadata_does_not_create_legacy_identity_artifacts,
        test_stale_candidate_keeps_owner_pid_diagnostic_only_and_preserves_heads_and_owner_file,
        test_recover_docs_classify_owner_pid_as_diagnostic_only_not_identity_key,
        test_hook_sources_do_not_use_owner_pid_or_process_lock_owner_as_session_selector,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
