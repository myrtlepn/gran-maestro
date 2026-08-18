from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"

REQUIRED_REFERENCE_KEYS = {
    "id",
    "topic",
    "url",
    "summary",
    "searched_at",
    "expires_at",
    "freshness",
    "content_path",
}

ALL_ADD_FAILPOINTS = [
    "after_counter_reserve",
    "after_staging_create",
    "after_metadata_fsync",
    "after_content_fsync",
    "after_staging_fsync",
    "before_publish",
    "after_final_reserve",
    "after_final_content",
    "after_publish",
    "before_success",
]

ALL_UPDATE_FAILPOINTS = [
    "update_after_backup",
    "update_after_final_reserve",
    "update_after_final_content",
    "update_after_publish",
]


# ==============================================================================
# Harness and Utility Functions
# ==============================================================================

def _setup_workspace(tmp_path: Path) -> Path:
    base_dir = tmp_path / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def _run_mst(
    *args: str,
    cwd: Path,
    env: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    full_env["PYTHONUNBUFFERED"] = "1"
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=timeout,
        check=False,
    )


def _run_mst_json(
    *args: str,
    cwd: Path,
    env: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
) -> Any:
    proc = _run_mst(*args, cwd=cwd, env=env, timeout=timeout)
    assert proc.returncode == 0, (
        f"MST command failed (exit {proc.returncode}): {' '.join(args)}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert proc.stdout.strip(), f"Expected JSON stdout but got empty output. stderr: {proc.stderr}"
    return json.loads(proc.stdout)


def _assert_valid_reference_pair(
    workspace: Path,
    ref_id: str,
    expected_topic: Optional[str] = None,
    expected_content: Optional[str] = None,
) -> Dict[str, Any]:
    ref_dir = workspace / ".gran-maestro" / "references" / ref_id
    assert ref_dir.is_dir(), f"Expected reference directory missing: {ref_dir}"

    json_path = ref_dir / "reference.json"
    content_path = ref_dir / "content.md"

    assert json_path.is_file(), f"Missing reference.json in {ref_dir}"
    assert content_path.is_file(), f"Missing content.md in {ref_dir}"

    raw_text = json_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    assert isinstance(data, dict), f"reference.json must be a JSON object, got {type(data)}"

    missing_keys = REQUIRED_REFERENCE_KEYS - set(data.keys())
    assert not missing_keys, f"Missing required keys in {json_path}: {sorted(missing_keys)}"

    assert data["id"] == ref_id, f"ID mismatch in {json_path}: expected {ref_id}, got {data.get('id')}"
    assert data["freshness"] in {"fresh", "stale", "expired"}, f"Invalid freshness: {data.get('freshness')}"
    assert data["content_path"] == f".gran-maestro/references/{ref_id}/content.md"

    if expected_topic is not None:
        assert data.get("topic") == expected_topic, f"Topic mismatch: {data.get('topic')} != {expected_topic}"

    if expected_content is not None:
        actual_content = content_path.read_text(encoding="utf-8")
        assert actual_content == expected_content, f"Content mismatch in {content_path}"

    return data


def _calculate_tree_hash(path: Path) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    if not path.exists():
        return hashes
    if path.is_file() or path.is_symlink():
        try:
            content = path.read_bytes()
            hashes[str(path.name)] = hashlib.sha256(content).hexdigest()
        except OSError:
            hashes[str(path.name)] = "unreadable"
        return hashes

    for root, _, files in os.walk(path):
        for file_name in sorted(files):
            file_path = Path(root) / file_name
            rel = str(file_path.relative_to(path))
            try:
                content = file_path.read_bytes()
                hashes[rel] = hashlib.sha256(content).hexdigest()
            except OSError:
                hashes[rel] = "unreadable"
    return hashes


def _wait_for_barrier_ready(barrier_dir: Path, timeout: float = 10.0) -> bool:
    ready_file = barrier_dir / "ready"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ready_file.exists():
            return True
        time.sleep(0.02)
    return False


def _release_barrier(barrier_dir: Path) -> None:
    release_file = barrier_dir / "release"
    release_file.touch()


def _create_mock_transaction_manifest(
    target_dir: Path,
    txid: str,
    ref_id: str,
    operation: str,
    state: str,
    reference_data: Dict[str, Any],
    content_text: str,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    ref_json_path = target_dir / "reference.json"
    content_md_path = target_dir / "content.md"
    tx_json_path = target_dir / "transaction.json"

    ref_json_path.write_text(json.dumps(reference_data, ensure_ascii=False, indent=2), encoding="utf-8")
    content_md_path.write_text(content_text, encoding="utf-8")

    hasher = hashlib.sha256()
    hasher.update(ref_json_path.read_bytes())
    hasher.update(content_md_path.read_bytes())
    payload_sha256 = hasher.hexdigest()

    manifest = {
        "schema_version": 1,
        "transaction_id": txid,
        "reference_id": ref_id,
        "operation": operation,
        "state": state,
        "payload_sha256": payload_sha256,
        "created_at": "2026-08-18T12:00:00+00:00",
    }
    tx_json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_single_add_worker(
    cwd_str: str,
    worker_index: int,
    barrier_dir_str: Optional[str] = None,
) -> Tuple[int, int, str, str]:
    cwd = Path(cwd_str)
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    if barrier_dir_str:
        env["MST_TEST_MODE"] = "1"
        env["MST_TEST_BARRIER_DIR"] = barrier_dir_str

    cmd = [
        sys.executable,
        str(MST_SCRIPT),
        "reference",
        "add",
        "--topic",
        f"Concurrent Topic {worker_index:03d}",
        "--url",
        f"https://example.com/concurrent/{worker_index:03d}",
        "--summary",
        f"Summary for worker {worker_index:03d}",
        "--content",
        f"## Excerpt {worker_index:03d}\n| worker | {worker_index} |\n",
        "--json",
    ]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=45.0,
        check=False,
    )
    return worker_index, proc.returncode, proc.stdout, proc.stderr


def _run_single_counter_worker(
    cwd_str: str,
    worker_index: int,
) -> Tuple[int, int, str, str]:
    cwd = Path(cwd_str)
    cmd = [
        sys.executable,
        str(MST_SCRIPT),
        "counter",
        "next",
        "--type",
        "ref",
    ]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=45.0,
        check=False,
    )
    return worker_index, proc.returncode, proc.stdout, proc.stderr


# ==============================================================================
# AC-001: Parallel Add Subprocess Concurrency Tests
# ==============================================================================

def test_ac001_parallel_add_32_concurrent_subprocesses(tmp_path: Path):
    """
    AC-001 [MUST] [parallel_add]
    Given: 하나의 격리 프로젝트에 빈 .gran-maestro가 있고 동일 CLI를 여러 subprocess에서 실행함
    When: 최소 32개의 reference add를 동시에 실행함
    Then: 성공 ID는 모두 고유하고 모든 final directory의 JSON/Markdown pair가 유효하며
          정상 성공 경로에는 임시·staging 잔존물이 없음
    """
    ws = _setup_workspace(tmp_path)
    concurrency = 32

    results: List[Tuple[int, int, str, str]] = []
    with ProcessPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(_run_single_add_worker, str(ws), idx)
            for idx in range(concurrency)
        ]
        for f in as_completed(futures):
            results.append(f.result())

    # 1. 모든 subprocess 반환값 검증
    failed_workers = [r for r in results if r[1] != 0]
    assert not failed_workers, (
        f"{len(failed_workers)} workers failed during parallel_add.\n"
        f"First failure: index={failed_workers[0][0]}, code={failed_workers[0][1]}\n"
        f"stderr: {failed_workers[0][3]}\nstdout: {failed_workers[0][2]}"
    )

    # 2. 모든 발행 ID 수집 및 고유성 검증
    issued_ids: List[str] = []
    for _, _, stdout, _ in results:
        parsed = json.loads(stdout)
        assert isinstance(parsed, dict)
        ref_id = parsed.get("id")
        assert ref_id is not None and re.fullmatch(r"REF-\d+", ref_id), f"Invalid ID in stdout: {stdout}"
        issued_ids.append(ref_id)

    assert len(issued_ids) == concurrency, f"Expected {concurrency} IDs, got {len(issued_ids)}"
    unique_ids = set(issued_ids)
    assert len(unique_ids) == concurrency, (
        f"Duplicate IDs detected in parallel_add! Total={len(issued_ids)}, Unique={len(unique_ids)}. "
        f"Duplicates: {[x for x in issued_ids if issued_ids.count(x) > 1]}"
    )

    # 3. 모든 final directory의 pair 유효성 검증
    references_dir = ws / ".gran-maestro" / "references"
    assert references_dir.is_dir()

    for ref_id in unique_ids:
        _assert_valid_reference_pair(ws, ref_id)

    # 4. 임시/staging/backup 잔존물이 없음을 검증
    staging_dir = references_dir / ".staging"
    if staging_dir.exists():
        staged_items = list(staging_dir.iterdir())
        assert not staged_items, f"Staging residues left after normal parallel_add: {staged_items}"

    backup_dir = references_dir / ".backup"
    if backup_dir.exists():
        backup_items = list(backup_dir.iterdir())
        assert not backup_items, f"Backup residues left after normal parallel_add: {backup_items}"

    # .*.tmp 임시 파일 잔존 검사
    tmp_residues = list(references_dir.rglob(".*.tmp")) + list(references_dir.rglob("*.tmp"))
    assert not tmp_residues, f"Temporary file residues found: {tmp_residues}"


# ==============================================================================
# AC-002: Mixed Allocator Concurrency & Crash Reservation Ledger Tests
# ==============================================================================

def test_ac002_mixed_allocator_concurrent_counter_and_add_with_crash_ledger(tmp_path: Path):
    """
    AC-002 [MUST] [mixed_allocator]
    Given: 같은 ref namespace에서 reference add와 counter next --type ref가 경쟁함
    When: 실제 subprocess 혼합 실행을 반복함
    Then: raw-counter, add success, counter 예약 뒤 crash한 add를 포함한 모든 durable reservation ID가
          중복 없이 예약 범위에 속하고, final directory ID는 add success ID의 부분집합이며,
          counter high-water mark는 모든 durable reservation의 최댓값과 같고 unpublished reservation만 gap으로 허용됨
    """
    ws = _setup_workspace(tmp_path)
    counter_file = ws / ".gran-maestro" / "references" / "counter.json"

    ledger_crash_ids: Set[str] = set()
    ledger_raw_counter_ids: Set[str] = set()
    ledger_add_success_ids: Set[str] = set()

    # 1. Baseline counter 확인
    initial_last_id = 0
    if counter_file.exists():
        data = json.loads(counter_file.read_text(encoding="utf-8"))
        initial_last_id = data.get("last_id", 0)

    # 2. after_counter_reserve failpoint add subprocess 1개를 단독 실행해 SIGKILL outcome 확인
    fail_env = {
        "MST_TEST_MODE": "1",
        "MST_REFERENCE_FAILPOINT": "after_counter_reserve",
        "MST_REFERENCE_FAIL_ACTION": "sigkill",
    }
    crash_proc = _run_mst(
        "reference", "add",
        "--topic", "Crash injected topic",
        "--url", "https://example.com/crash",
        "--summary", "Crash summary",
        "--content", "Crash content",
        cwd=ws,
        env=fail_env,
        timeout=10.0,
    )
    # SIGKILL (-9 또는 137 또는 non-zero crash returncode)
    assert crash_proc.returncode in (-signal.SIGKILL, 137, 128 + signal.SIGKILL, -9), (
        f"Expected SIGKILL exit from after_counter_reserve failpoint, got returncode={crash_proc.returncode}\n"
        f"stdout={crash_proc.stdout}\nstderr={crash_proc.stderr}"
    )

    # 3. 종료 직후 counter가 정확히 1 증가했음을 확인하고 그 ID를 crash reservation ledger에 기록
    assert counter_file.exists(), "counter.json must exist after counter reservation"
    after_crash_counter = json.loads(counter_file.read_text(encoding="utf-8"))
    crashed_last_id = after_crash_counter.get("last_id", 0)
    assert crashed_last_id == initial_last_id + 1, (
        f"Counter should increment by 1 on after_counter_reserve crash. Expected {initial_last_id + 1}, got {crashed_last_id}"
    )
    crashed_id = f"REF-{crashed_last_id:03d}"
    ledger_crash_ids.add(crashed_id)

    # 4. 이후 raw counter/add concurrent wave를 실행해 stdout ID를 각각 ledger에 추가
    num_raw_counter = 16
    num_concurrent_add = 16
    total_wave = num_raw_counter + num_concurrent_add

    futures_map = {}
    with ProcessPoolExecutor(max_workers=total_wave) as executor:
        for idx in range(num_raw_counter):
            fut = executor.submit(_run_single_counter_worker, str(ws), idx)
            futures_map[fut] = ("counter", idx)
        for idx in range(num_concurrent_add):
            fut = executor.submit(_run_single_add_worker, str(ws), idx + 100)
            futures_map[fut] = ("add", idx + 100)

        for fut in as_completed(futures_map):
            kind, idx = futures_map[fut]
            worker_idx, retcode, stdout, stderr = fut.result()
            assert retcode == 0, (
                f"Worker ({kind} #{worker_idx}) failed with returncode {retcode}.\n"
                f"stdout: {stdout}\nstderr: {stderr}"
            )
            if kind == "counter":
                raw_id = stdout.strip().splitlines()[-1].strip()
                assert re.fullmatch(r"REF-\d+", raw_id), f"Invalid counter output: {stdout}"
                ledger_raw_counter_ids.add(raw_id)
            else:
                parsed = json.loads(stdout)
                add_id = parsed["id"]
                assert re.fullmatch(r"REF-\d+", add_id), f"Invalid add output: {stdout}"
                ledger_add_success_ids.add(add_id)

    # 5. Ledger Invariants 검증
    all_durable_reservations = ledger_crash_ids | ledger_raw_counter_ids | ledger_add_success_ids
    total_expected = 1 + num_raw_counter + num_concurrent_add

    # 중복 ID 검사
    assert len(ledger_raw_counter_ids) == num_raw_counter, "Duplicate IDs within raw counter wave!"
    assert len(ledger_add_success_ids) == num_concurrent_add, "Duplicate IDs within add wave!"
    assert len(all_durable_reservations) == total_expected, (
        f"Cross-category ID collision detected! Total={total_expected}, Unique={len(all_durable_reservations)}.\n"
        f"Crash IDs: {ledger_crash_ids}\n"
        f"Raw Counter IDs: {ledger_raw_counter_ids}\n"
        f"Add Success IDs: {ledger_add_success_ids}"
    )

    # 1..counter.last_id 범위와 단조성 검증
    numeric_ids = {int(ref_id.split("-")[1]) for ref_id in all_durable_reservations}
    expected_numeric_range = set(range(1, total_expected + 1))
    assert numeric_ids == expected_numeric_range, (
        f"Reservation IDs have unexpected gap or overflow. Expected {expected_numeric_range}, got {numeric_ids}"
    )

    # counter.last_id == max(all ledger IDs)
    final_counter_data = json.loads(counter_file.read_text(encoding="utf-8"))
    final_last_id = final_counter_data.get("last_id", 0)
    assert final_last_id == max(numeric_ids) == total_expected, (
        f"Counter high-water mark mismatch: counter.last_id={final_last_id}, max_ledger={max(numeric_ids)}"
    )

    # final directory IDs가 add-success IDs의 부분집합인지 검증 (정확히 일치해야 함)
    references_dir = ws / ".gran-maestro" / "references"
    actual_final_dirs = {p.name for p in references_dir.glob("REF-*") if p.is_dir()}
    assert actual_final_dirs == ledger_add_success_ids, (
        f"Final directory IDs mismatch! Expected add successes {ledger_add_success_ids}, got {actual_final_dirs}"
    )

    # 모든 final pair 유효성 검증
    for ref_id in actual_final_dirs:
        _assert_valid_reference_pair(ws, ref_id)


# ==============================================================================
# AC-003: Failpoint Crash Safety & State Matrix Tests
# ==============================================================================

@pytest.mark.parametrize("failpoint", ALL_ADD_FAILPOINTS)
def test_ac003_failpoint_add_crash_matrix(tmp_path: Path, failpoint: str):
    """
    AC-003 [MUST] [failpoint]
    Given: add failpoint 중 하나가 활성화됨
    When: writer가 강제 종료되고 후속 add/get/list가 실행됨
    Then: ID rollback·재사용·committed/reader-visible partial pair·false success가 없으며,
          matrix에 명시된 physical uncommitted final/staging residue는 valid reference에서 제외된 채 보존·진단됨
    """
    ws = _setup_workspace(tmp_path)
    counter_file = ws / ".gran-maestro" / "references" / "counter.json"
    references_dir = ws / ".gran-maestro" / "references"

    fail_env = {
        "MST_TEST_MODE": "1",
        "MST_REFERENCE_FAILPOINT": failpoint,
        "MST_REFERENCE_FAIL_ACTION": "sigkill",
    }

    # 1. Injected Failpoint writer 실행
    crash_proc = _run_mst(
        "reference", "add",
        "--topic", f"Failpoint topic for {failpoint}",
        "--url", "https://example.com/failpoint",
        "--summary", "Failpoint summary",
        "--content", "Failpoint content",
        cwd=ws,
        env=fail_env,
        timeout=10.0,
    )
    assert crash_proc.returncode in (-signal.SIGKILL, 137, 128 + signal.SIGKILL, -9), (
        f"Failpoint {failpoint} did not terminate with SIGKILL: returncode={crash_proc.returncode}\n"
        f"stdout={crash_proc.stdout}\nstderr={crash_proc.stderr}"
    )

    # 2. Counter 예약 상태 검증: 모든 failpoint에서 counter는 1로 예약되어 있어야 함
    assert counter_file.exists(), f"Counter file must exist after failpoint {failpoint}"
    counter_data = json.loads(counter_file.read_text(encoding="utf-8"))
    assert counter_data.get("last_id") == 1, (
        f"Failpoint {failpoint}: expected counter.last_id=1, got {counter_data.get('last_id')}"
    )

    # 3. Failpoint별 Staging / Final / 후속 진단 검증
    staging_dir = references_dir / ".staging"
    staged_subdirs = [p for p in staging_dir.iterdir() if p.is_dir()] if staging_dir.exists() else []
    final_ref_dir = references_dir / "REF-001"

    if failpoint in ("after_counter_reserve", "after_publish", "before_success"):
        # staging 없음
        assert not staged_subdirs, f"Failpoint {failpoint} should not leave staging subdirs, found: {staged_subdirs}"
    else:
        # staging에 residue 존재
        assert len(staged_subdirs) == 1, f"Failpoint {failpoint} must leave exactly 1 staging subdir, found: {staged_subdirs}"

    if failpoint in ("after_publish", "before_success"):
        # final pair가 commit 완료됨
        assert final_ref_dir.is_dir(), f"Failpoint {failpoint} should have committed final pair"
        _assert_valid_reference_pair(ws, "REF-001")
    elif failpoint == "after_final_reserve":
        # metadata 없는 reserved dir
        assert final_ref_dir.is_dir()
        assert not (final_ref_dir / "reference.json").exists()
    elif failpoint == "after_final_content":
        # content-only reserved dir
        assert final_ref_dir.is_dir()
        assert (final_ref_dir / "content.md").exists()
        assert not (final_ref_dir / "reference.json").exists()
    else:
        # final dir 없음
        assert not final_ref_dir.exists(), f"Failpoint {failpoint} must not create final dir"

    # 4. 후속 add 실행: ID rollback이나 충돌 없이 REF-002를 정상 발급해야 함
    next_add_payload = _run_mst_json(
        "reference", "add",
        "--topic", "Follow-up topic",
        "--url", "https://example.com/follow-up",
        "--summary", "Follow-up summary",
        "--content", "Follow-up content",
        "--json",
        cwd=ws,
        timeout=10.0,
    )
    assert next_add_payload["id"] == "REF-002", (
        f"Failpoint {failpoint}: next add must issue REF-002, got {next_add_payload['id']}"
    )
    _assert_valid_reference_pair(ws, "REF-002", expected_topic="Follow-up topic")

    # 5. Doctor 진단 검증
    doctor_res = _run_mst_json("reference", "doctor", "--json", cwd=ws, timeout=10.0)
    assert doctor_res["schema_version"] == 1

    if failpoint in ("after_counter_reserve", "after_publish", "before_success"):
        assert doctor_res["summary"]["staging"] == 0
    else:
        assert doctor_res["summary"]["staging"] >= 1


@pytest.mark.parametrize("failpoint", ALL_UPDATE_FAILPOINTS)
def test_ac003_failpoint_update_crash_matrix(tmp_path: Path, failpoint: str):
    """
    AC-003 & AC-004 [MUST] [failpoint] [update_snapshot]
    Update failpoints crash safety matrix:
    - update_after_backup
    - update_after_final_reserve
    - update_after_final_content
    - update_after_publish
    """
    ws = _setup_workspace(tmp_path)

    # 초기 REF-001 커밋
    _run_mst_json(
        "reference", "add",
        "--topic", "Initial v1 topic",
        "--url", "https://example.com/v1",
        "--summary", "Initial v1 summary",
        "--content", "Initial v1 content",
        "--json",
        cwd=ws,
    )
    _assert_valid_reference_pair(ws, "REF-001", expected_topic="Initial v1 topic")

    fail_env = {
        "MST_TEST_MODE": "1",
        "MST_REFERENCE_FAILPOINT": failpoint,
        "MST_REFERENCE_FAIL_ACTION": "sigkill",
    }

    # Injected update writer 실행
    crash_proc = _run_mst(
        "reference", "update", "REF-001",
        "--topic", "Updated v2 topic",
        "--summary", "Updated v2 summary",
        "--content", "Updated v2 content",
        cwd=ws,
        env=fail_env,
        timeout=10.0,
    )
    assert crash_proc.returncode in (-signal.SIGKILL, 137, 128 + signal.SIGKILL, -9)

    references_dir = ws / ".gran-maestro" / "references"
    backup_dir = references_dir / ".backup"
    final_dir = references_dir / "REF-001"

    # Backup 상태 확인
    assert backup_dir.is_dir()
    backup_subdirs = [p for p in backup_dir.iterdir() if p.is_dir() and p.name.startswith("REF-001.")]
    assert len(backup_subdirs) == 1, f"Expected 1 backup directory for REF-001, got {backup_subdirs}"

    if failpoint == "update_after_backup":
        # final missing, valid backup + complete staging
        assert not final_dir.exists()
    elif failpoint == "update_after_final_reserve":
        # empty reserved final
        assert final_dir.is_dir()
        assert not (final_dir / "reference.json").exists()
    elif failpoint == "update_after_final_content":
        # content-only final
        assert final_dir.is_dir()
        assert (final_dir / "content.md").exists()
        assert not (final_dir / "reference.json").exists()
    elif failpoint == "update_after_publish":
        # valid final committed v2 + backup residue
        assert final_dir.is_dir()
        _assert_valid_reference_pair(ws, "REF-001", expected_topic="Updated v2 topic")


# ==============================================================================
# AC-004: Update Snapshot and Backup Recovery Tests
# ==============================================================================

def test_ac004_update_snapshot_reader_observes_atomic_version(tmp_path: Path):
    """
    AC-004 [MUST] [update_snapshot]
    Given: update writer와 get/list/search reader가 같은 reference에서 경합함
    When: concurrent snapshot 테스트를 실행함
    Then: read-only reader는 old/new complete pair 중 하나만 관찰하거나 진단만 반환하고 mutation하지 않음
    """
    ws = _setup_workspace(tmp_path)
    barrier_dir = tmp_path / "barrier_update_snapshot"
    barrier_dir.mkdir(parents=True, exist_ok=True)

    # 1. 초기 REF-001 (v1) 커밋
    _run_mst_json(
        "reference", "add",
        "--topic", "Original Topic v1",
        "--url", "https://example.com/v1",
        "--summary", "Original Summary v1",
        "--content", "Original Content v1 markdown",
        "--json",
        cwd=ws,
    )

    # 2. Update writer subprocess를 before_publish barrier 상태로 백그라운드 시작
    writer_env = {
        "MST_TEST_MODE": "1",
        "MST_REFERENCE_FAILPOINT": "before_publish",
        "MST_REFERENCE_FAIL_ACTION": "barrier",
        "MST_TEST_BARRIER_DIR": str(barrier_dir),
    }

    writer_proc = subprocess.Popen(
        [
            sys.executable,
            str(MST_SCRIPT),
            "reference",
            "update",
            "REF-001",
            "--topic", "Updated Topic v2",
            "--summary", "Updated Summary v2",
            "--content", "Updated Content v2 markdown",
            "--json",
        ],
        cwd=ws,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, **writer_env},
    )

    try:
        # 3. Writer가 barrier ready 상태에 도달할 때까지 대기
        ready = _wait_for_barrier_ready(barrier_dir, timeout=10.0)
        assert ready, "Writer did not reach before_publish barrier in time"

        # 4. Reader가 get/list/search 실행 시 old complete pair(v1)를 정상 관찰해야 함
        get_res = _run_mst_json("reference", "get", "REF-001", "--json", cwd=ws)
        assert get_res["topic"] == "Original Topic v1"
        assert get_res["summary"] == "Original Summary v1"
        assert get_res["content"] == "Original Content v1 markdown"

        list_res = _run_mst_json("reference", "list", "--json", cwd=ws)
        assert len(list_res) == 1
        assert list_res[0]["topic"] == "Original Topic v1"

        search_res = _run_mst_json("reference", "search", "--keyword", "Original", "--json", cwd=ws)
        assert len(search_res) == 1
        assert search_res[0]["topic"] == "Original Topic v1"

        # 5. Barrier release 하여 writer 재개
        _release_barrier(barrier_dir)

        writer_stdout, writer_stderr = writer_proc.communicate(timeout=10.0)
        assert writer_proc.returncode == 0, f"Writer update failed:\nstdout: {writer_stdout}\nstderr: {writer_stderr}"

        # 6. Writer 완료 후 reader는 new complete pair(v2)를 관찰
        get_v2 = _run_mst_json("reference", "get", "REF-001", "--json", cwd=ws)
        assert get_v2["topic"] == "Updated Topic v2"
        assert get_v2["summary"] == "Updated Summary v2"
        assert get_v2["content"] == "Updated Content v2 markdown"

    finally:
        if writer_proc.poll() is None:
            writer_proc.kill()
            writer_proc.wait()


@pytest.mark.parametrize(
    "case_name",
    [
        "valid_final_plus_any_residue",
        "final_missing_single_valid_backup",
        "final_missing_valid_backup_plus_staging",
        "invalid_final_with_valid_backup",
        "multiple_valid_backups_ambiguous",
    ],
)
def test_ac004_backup_recovery_5_authoritative_fixtures(tmp_path: Path, case_name: str):
    """
    AC-004 [MUST] [backup_recovery]
    5 Authoritative Backup Recovery Fixtures:
    1. valid final + any backup/staging -> final bytes unchanged, residues only warned.
    2. update writer 호출 시 final missing + exactly one valid backup -> backup restored to final.
    3. update writer 호출 시 final missing + exactly one valid backup + valid staging -> backup restored, staging remains stale diagnostic.
    4. invalid final + one valid backup -> no mutation, confirmed failure with both diagnostics.
    5. multiple valid backups or no unique authoritative candidate -> no mutation, REFERENCE_OUTCOME_UNKNOWN.
    """
    ws = _setup_workspace(tmp_path)
    ref_dir = ws / ".gran-maestro" / "references" / "REF-001"
    staging_dir = ws / ".gran-maestro" / "references" / ".staging"
    backup_dir = ws / ".gran-maestro" / "references" / ".backup"

    v0_data = {
        "id": "REF-001",
        "topic": "V0 Topic",
        "url": "https://example.com/v0",
        "summary": "V0 Summary",
        "searched_at": "2026-08-18T10:00:00+00:00",
        "expires_at": "2026-09-17T10:00:00+00:00",
        "freshness": "fresh",
        "content_path": ".gran-maestro/references/REF-001/content.md",
    }
    v0_content = "V0 Content markdown"

    v1_data = {
        "id": "REF-001",
        "topic": "V1 Final Topic",
        "url": "https://example.com/v1",
        "summary": "V1 Final Summary",
        "searched_at": "2026-08-18T11:00:00+00:00",
        "expires_at": "2026-09-17T11:00:00+00:00",
        "freshness": "fresh",
        "content_path": ".gran-maestro/references/REF-001/content.md",
    }
    v1_content = "V1 Final Content markdown"

    txid_backup_1 = "11111111222233334444555566667777"
    txid_backup_2 = "8888888899990000aaaabbbbccccdddd"
    txid_staging = "aaaabbbbccccdddd1111222233334444"

    if case_name == "valid_final_plus_any_residue":
        # 1. valid final + backup + staging
        ref_dir.mkdir(parents=True, exist_ok=True)
        (ref_dir / "reference.json").write_text(json.dumps(v1_data, ensure_ascii=False, indent=2), encoding="utf-8")
        (ref_dir / "content.md").write_text(v1_content, encoding="utf-8")
        initial_tree_hash = _calculate_tree_hash(ref_dir)

        _create_mock_transaction_manifest(
            backup_dir / f"REF-001.{txid_backup_1}",
            txid_backup_1, "REF-001", "update", "backup",
            v0_data, v0_content,
        )
        _create_mock_transaction_manifest(
            staging_dir / f"REF-001.{txid_staging}",
            txid_staging, "REF-001", "update", "staged",
            v1_data, v1_content,
        )

        # Reader get
        get_res = _run_mst_json("reference", "get", "REF-001", "--json", cwd=ws)
        assert get_res["topic"] == "V1 Final Topic"

        # Final bytes must remain unchanged
        after_tree_hash = _calculate_tree_hash(ref_dir)
        assert initial_tree_hash == after_tree_hash

        # Doctor reports warnings for residues
        doctor_res = _run_mst_json("reference", "doctor", "--json", cwd=ws)
        assert doctor_res["summary"]["valid"] == 1
        assert doctor_res["summary"]["staging"] >= 1
        assert doctor_res["summary"]["backups"] >= 1

    elif case_name == "final_missing_single_valid_backup":
        # 2. final missing + exactly one valid backup -> update writer restores backup to final
        _create_mock_transaction_manifest(
            backup_dir / f"REF-001.{txid_backup_1}",
            txid_backup_1, "REF-001", "update", "backup",
            v0_data, v0_content,
        )
        assert not ref_dir.exists()

        # Update writer called
        update_proc = _run_mst(
            "reference", "update", "REF-001",
            "--summary", "Summary after backup restoration",
            "--json",
            cwd=ws,
        )
        assert update_proc.returncode == 0, f"Update writer recovery failed:\nstdout: {update_proc.stdout}\nstderr: {update_proc.stderr}"
        updated_data = json.loads(update_proc.stdout)
        assert updated_data["topic"] == "V0 Topic"
        assert updated_data["summary"] == "Summary after backup restoration"

        # Final dir must now exist and be valid
        _assert_valid_reference_pair(ws, "REF-001", expected_topic="V0 Topic")

    elif case_name == "final_missing_valid_backup_plus_staging":
        # 3. final missing + exactly one valid backup + valid staging -> backup restored, staging remains stale
        _create_mock_transaction_manifest(
            backup_dir / f"REF-001.{txid_backup_1}",
            txid_backup_1, "REF-001", "update", "backup",
            v0_data, v0_content,
        )
        _create_mock_transaction_manifest(
            staging_dir / f"REF-001.{txid_staging}",
            txid_staging, "REF-001", "update", "staged",
            v1_data, v1_content,
        )

        update_proc = _run_mst(
            "reference", "update", "REF-001",
            "--topic", "Topic after restore with stale staging",
            "--json",
            cwd=ws,
        )
        assert update_proc.returncode == 0
        _assert_valid_reference_pair(ws, "REF-001")

        # Staging remains stale diagnostic
        doctor_res = _run_mst_json("reference", "doctor", "--json", cwd=ws)
        assert doctor_res["summary"]["staging"] >= 1

    elif case_name == "invalid_final_with_valid_backup":
        # 4. invalid final + one valid backup -> no mutation, confirmed failure with both diagnostics
        ref_dir.mkdir(parents=True, exist_ok=True)
        (ref_dir / "reference.json").write_text("MALFORMED JSON {{{", encoding="utf-8")
        (ref_dir / "content.md").write_text("Some content", encoding="utf-8")
        initial_tree_hash = _calculate_tree_hash(ref_dir)

        _create_mock_transaction_manifest(
            backup_dir / f"REF-001.{txid_backup_1}",
            txid_backup_1, "REF-001", "update", "backup",
            v0_data, v0_content,
        )

        # Update writer must fail and NOT mutate final directory
        update_proc = _run_mst(
            "reference", "update", "REF-001",
            "--topic", "Should fail",
            cwd=ws,
        )
        assert update_proc.returncode == 1
        assert "Error [" in update_proc.stderr
        assert "outcome=confirmed_failure" in update_proc.stderr

        after_tree_hash = _calculate_tree_hash(ref_dir)
        assert initial_tree_hash == after_tree_hash, "Invalid final directory must not be mutated"

    elif case_name == "multiple_valid_backups_ambiguous":
        # 5. multiple valid backups -> no mutation, REFERENCE_OUTCOME_UNKNOWN
        assert not ref_dir.exists()
        _create_mock_transaction_manifest(
            backup_dir / f"REF-001.{txid_backup_1}",
            txid_backup_1, "REF-001", "update", "backup",
            v0_data, v0_content,
        )
        _create_mock_transaction_manifest(
            backup_dir / f"REF-001.{txid_backup_2}",
            txid_backup_2, "REF-001", "update", "backup",
            v1_data, v1_content,
        )

        update_proc = _run_mst(
            "reference", "update", "REF-001",
            "--summary", "Should fail due to ambiguity",
            cwd=ws,
        )
        assert update_proc.returncode == 1
        assert "Error [REFERENCE_OUTCOME_UNKNOWN]" in update_proc.stderr
        assert "outcome=unknown_outcome" in update_proc.stderr
        assert not ref_dir.exists(), "Final directory must not be created when multiple backups are ambiguous"


def test_ac004_update_omitted_content_and_field_merge(tmp_path: Path):
    """
    AC-004 [MUST] [update_snapshot]
    - update --content omitted이면 existing content bytes를 그대로 staged pair에 복사한다.
    - concurrent update는 lock 안에서 current committed pair를 다시 load한 뒤 provided fields만 적용한다.
      Non-overlap fields는 누적되고 overlap fields는 lock을 나중에 획득한 update가 이긴다.
    """
    ws = _setup_workspace(tmp_path)

    # 1. 초기 add
    initial_content = "## Initial Excerpt\n| row1 | data1 |\n| row2 | data2 |\n"
    add_res = _run_mst_json(
        "reference", "add",
        "--topic", "Original Topic",
        "--url", "https://example.com/initial",
        "--summary", "Original Summary",
        "--content", initial_content,
        "--json",
        cwd=ws,
    )
    ref_id = add_res["id"]

    # 2. update without --content
    update_res1 = _run_mst_json(
        "reference", "update", ref_id,
        "--topic", "Merged Topic 1",
        "--json",
        cwd=ws,
    )
    assert update_res1["topic"] == "Merged Topic 1"
    assert update_res1["summary"] == "Original Summary"

    # content.md bytes preserved
    ref_dir = ws / ".gran-maestro" / "references" / ref_id
    assert (ref_dir / "content.md").read_text(encoding="utf-8") == initial_content

    # 3. update another non-overlapping field without --content
    update_res2 = _run_mst_json(
        "reference", "update", ref_id,
        "--summary", "Merged Summary 2",
        "--json",
        cwd=ws,
    )
    assert update_res2["topic"] == "Merged Topic 1"
    assert update_res2["summary"] == "Merged Summary 2"
    assert (ref_dir / "content.md").read_text(encoding="utf-8") == initial_content


# ==============================================================================
# AC-005: Strict Diagnostics & Doctor JSON Tests
# ==============================================================================

@pytest.mark.parametrize(
    "code,setup_fn",
    [
        (
            "REFERENCE_NOT_FOUND",
            lambda ws: None,  # no ref exists
        ),
        (
            "REFERENCE_INCOMPLETE",
            lambda ws: (
                (ws / ".gran-maestro" / "references" / "REF-001").mkdir(parents=True, exist_ok=True),
                (ws / ".gran-maestro" / "references" / "REF-001" / "reference.json").write_text(
                    json.dumps({
                        "id": "REF-001", "topic": "T", "url": "U", "summary": "S",
                        "searched_at": "2026-08-18T10:00:00+00:00",
                        "expires_at": "2026-09-17T10:00:00+00:00",
                        "freshness": "fresh", "content_path": ".gran-maestro/references/REF-001/content.md"
                    }),
                    encoding="utf-8"
                ),
                # content.md missing
            ),
        ),
        (
            "REFERENCE_CORRUPT",
            lambda ws: (
                (ws / ".gran-maestro" / "references" / "REF-001").mkdir(parents=True, exist_ok=True),
                (ws / ".gran-maestro" / "references" / "REF-001" / "reference.json").write_text(
                    '{"malformed_json": ',
                    encoding="utf-8"
                ),
                (ws / ".gran-maestro" / "references" / "REF-001" / "content.md").write_text("Content", encoding="utf-8"),
            ),
        ),
        (
            "REFERENCE_SCHEMA_INVALID",
            lambda ws: (
                (ws / ".gran-maestro" / "references" / "REF-001").mkdir(parents=True, exist_ok=True),
                (ws / ".gran-maestro" / "references" / "REF-001" / "reference.json").write_text(
                    json.dumps({
                        "id": "REF-999",  # ID mismatch with directory REF-001
                        "topic": "T",
                        "freshness": "invalid_freshness_value",
                    }),
                    encoding="utf-8"
                ),
                (ws / ".gran-maestro" / "references" / "REF-001" / "content.md").write_text("Content", encoding="utf-8"),
            ),
        ),
        (
            "REFERENCE_UNREADABLE",
            lambda ws: (
                (ws / ".gran-maestro" / "references" / "REF-001").mkdir(parents=True, exist_ok=True),
                (ws / ".gran-maestro" / "references" / "REF-001" / "reference.json").write_text(
                    json.dumps({
                        "id": "REF-001", "topic": "T", "url": "U", "summary": "S",
                        "searched_at": "2026-08-18T10:00:00+00:00",
                        "expires_at": "2026-09-17T10:00:00+00:00",
                        "freshness": "fresh", "content_path": ".gran-maestro/references/REF-001/content.md"
                    }),
                    encoding="utf-8"
                ),
                (ws / ".gran-maestro" / "references" / "REF-001" / "content.md").write_text("Content", encoding="utf-8"),
                (ws / ".gran-maestro" / "references" / "REF-001" / "reference.json").chmod(0o000),
            ),
        ),
    ],
)
def test_ac005_diagnostic_cli_exit_codes_and_stderr(tmp_path: Path, code: str, setup_fn: Any):
    """
    AC-005 [MUST] [diagnostic]
    CLI diagnostic contract:
    - 모든 일반 runtime failure: exit 1, stdout empty, stderr 'Error [CODE] outcome=confirmed_failure: message'
    - REFERENCE_NOT_FOUND, REFERENCE_CORRUPT, REFERENCE_UNREADABLE, REFERENCE_SCHEMA_INVALID, REFERENCE_INCOMPLETE 구분
    """
    ws = _setup_workspace(tmp_path)
    try:
        setup_fn(ws)
        proc = _run_mst("reference", "get", "REF-001" if code != "REFERENCE_NOT_FOUND" else "REF-999", cwd=ws)

        assert proc.returncode == 1, f"Expected exit 1 for {code}, got {proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        assert proc.stdout.strip() == "", f"Expected empty stdout on failure, got: {proc.stdout}"

        expected_pattern = rf"^Error \[{code}\] outcome=confirmed_failure:"
        assert re.search(expected_pattern, proc.stderr, re.MULTILINE), (
            f"Stderr did not match expected grammar '{expected_pattern}'. Actual stderr:\n{proc.stderr}"
        )
    finally:
        # Cleanup unreadable chmod if set
        ref_json = ws / ".gran-maestro" / "references" / "REF-001" / "reference.json"
        if ref_json.exists():
            ref_json.chmod(0o644)


def test_ac005_diagnostic_list_and_search_mixed_state_warning(tmp_path: Path):
    """
    AC-005 [MUST] [diagnostic]
    list/search mixed state:
    - exit 0, valid stdout schema 유지
    - invalid item마다 stderr 'Warning [CODE]: REF-NNN ...' 노출
    """
    ws = _setup_workspace(tmp_path)
    ref_dir = ws / ".gran-maestro" / "references"

    # 1. Valid REF-001
    (ref_dir / "REF-001").mkdir(parents=True, exist_ok=True)
    (ref_dir / "REF-001" / "reference.json").write_text(
        json.dumps({
            "id": "REF-001",
            "topic": "Searchable Topic Valid",
            "url": "https://example.com/1",
            "summary": "Valid summary",
            "searched_at": "2026-08-18T10:00:00+00:00",
            "expires_at": "2026-09-17T10:00:00+00:00",
            "freshness": "fresh",
            "content_path": ".gran-maestro/references/REF-001/content.md",
        }),
        encoding="utf-8",
    )
    (ref_dir / "REF-001" / "content.md").write_text("Valid content", encoding="utf-8")

    # 2. Corrupt REF-002
    (ref_dir / "REF-002").mkdir(parents=True, exist_ok=True)
    (ref_dir / "REF-002" / "reference.json").write_text("MALFORMED JSON {{{", encoding="utf-8")
    (ref_dir / "REF-002" / "content.md").write_text("Content 2", encoding="utf-8")

    # 3. Incomplete REF-003 (missing content.md)
    (ref_dir / "REF-003").mkdir(parents=True, exist_ok=True)
    (ref_dir / "REF-003" / "reference.json").write_text(
        json.dumps({
            "id": "REF-003",
            "topic": "Incomplete Topic",
            "url": "https://example.com/3",
            "summary": "Incomplete summary",
            "searched_at": "2026-08-18T10:00:00+00:00",
            "expires_at": "2026-09-17T10:00:00+00:00",
            "freshness": "fresh",
            "content_path": ".gran-maestro/references/REF-003/content.md",
        }),
        encoding="utf-8",
    )

    # Test list
    list_proc = _run_mst("reference", "list", "--json", cwd=ws)
    assert list_proc.returncode == 0, f"reference list must return 0, got {list_proc.returncode}"
    list_data = json.loads(list_proc.stdout)
    assert isinstance(list_data, list)
    assert len(list_data) == 1, f"Expected 1 valid item in list stdout, got {len(list_data)}"
    assert list_data[0]["id"] == "REF-001"

    # stderr warnings for corrupt & incomplete
    assert re.search(r"Warning \[REFERENCE_CORRUPT\]: REF-002", list_proc.stderr), f"Missing corrupt warning in stderr:\n{list_proc.stderr}"
    assert re.search(r"Warning \[REFERENCE_INCOMPLETE\]: REF-003", list_proc.stderr), f"Missing incomplete warning in stderr:\n{list_proc.stderr}"

    # Test search
    search_proc = _run_mst("reference", "search", "--keyword", "Searchable", "--json", cwd=ws)
    assert search_proc.returncode == 0
    search_data = json.loads(search_proc.stdout)
    assert isinstance(search_data, list)
    assert len(search_data) == 1
    assert search_data[0]["id"] == "REF-001"
    assert re.search(r"Warning \[REFERENCE_CORRUPT\]: REF-002", search_proc.stderr)


def test_ac005_diagnostic_doctor_json_contract(tmp_path: Path):
    """
    AC-005 [MUST] [diagnostic]
    Doctor JSON contract:
    - exit 0
    - schema_version: 1
    - status: "issues" | "ok"
    - references: numeric REF ID sorted
    - staging & backups: path sorted
    """
    ws = _setup_workspace(tmp_path)
    ref_dir = ws / ".gran-maestro" / "references"
    staging_dir = ref_dir / ".staging"
    backup_dir = ref_dir / ".backup"

    # Setup 1 valid, 1 invalid, 1 staging, 1 backup
    # REF-001 (valid)
    (ref_dir / "REF-001").mkdir(parents=True, exist_ok=True)
    (ref_dir / "REF-001" / "reference.json").write_text(
        json.dumps({
            "id": "REF-001", "topic": "T1", "url": "U1", "summary": "S1",
            "searched_at": "2026-08-18T10:00:00+00:00",
            "expires_at": "2026-09-17T10:00:00+00:00",
            "freshness": "fresh", "content_path": ".gran-maestro/references/REF-001/content.md"
        }),
        encoding="utf-8"
    )
    (ref_dir / "REF-001" / "content.md").write_text("C1", encoding="utf-8")

    # REF-002 (invalid - corrupt)
    (ref_dir / "REF-002").mkdir(parents=True, exist_ok=True)
    (ref_dir / "REF-002" / "reference.json").write_text("CORRUPT {", encoding="utf-8")
    (ref_dir / "REF-002" / "content.md").write_text("C2", encoding="utf-8")

    # Staging residue
    txid_staging = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _create_mock_transaction_manifest(
        staging_dir / f"REF-003.{txid_staging}",
        txid_staging, "REF-003", "add", "staged",
        {"id": "REF-003", "topic": "T3", "url": "U3", "summary": "S3",
         "searched_at": "2026-08-18T10:00:00+00:00", "expires_at": "2026-09-17T10:00:00+00:00",
         "freshness": "fresh", "content_path": ".gran-maestro/references/REF-003/content.md"},
        "C3"
    )

    # Backup residue
    txid_backup = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    _create_mock_transaction_manifest(
        backup_dir / f"REF-001.{txid_backup}",
        txid_backup, "REF-001", "update", "backup",
        {"id": "REF-001", "topic": "T0", "url": "U0", "summary": "S0",
         "searched_at": "2026-08-18T09:00:00+00:00", "expires_at": "2026-09-17T09:00:00+00:00",
         "freshness": "fresh", "content_path": ".gran-maestro/references/REF-001/content.md"},
        "C0"
    )

    doctor_data = _run_mst_json("reference", "doctor", "--json", cwd=ws)

    assert doctor_data["schema_version"] == 1
    assert doctor_data["status"] == "issues"

    assert isinstance(doctor_data["references"], list)
    assert len(doctor_data["references"]) == 2
    # numeric REF ID sort
    assert doctor_data["references"][0]["id"] == "REF-001"
    assert doctor_data["references"][0]["status"] == "valid"
    assert doctor_data["references"][1]["id"] == "REF-002"
    assert doctor_data["references"][1]["status"] == "invalid"
    assert any(d["code"] == "REFERENCE_CORRUPT" for d in doctor_data["references"][1]["diagnostics"])

    assert isinstance(doctor_data["staging"], list)
    assert len(doctor_data["staging"]) == 1
    assert doctor_data["staging"][0]["status"] == "stale"
    assert any(d["code"] == "REFERENCE_STAGING_STALE" for d in doctor_data["staging"][0]["diagnostics"])

    assert isinstance(doctor_data["backups"], list)
    assert len(doctor_data["backups"]) == 1
    assert doctor_data["backups"][0]["status"] in ("stale", "ambiguous")
    assert any(d["code"] == "REFERENCE_BACKUP_STALE" for d in doctor_data["backups"][0]["diagnostics"])

    assert doctor_data["summary"] == {
        "valid": 1,
        "invalid": 1,
        "staging": 1,
        "backups": 1,
    }


# ==============================================================================
# AC-005/AC-015: Durable raw counter and high-water repair
# ==============================================================================

@pytest.mark.parametrize(
    ("residue_kind", "evidence_id"),
    [("final", 9), ("staging", 12), ("backup", 15)],
)
def test_counter_state_missing_or_regressed_repairs_forward(
    tmp_path: Path, residue_kind: str, evidence_id: int
):
    ws = _setup_workspace(tmp_path)
    refs_root = ws / ".gran-maestro" / "references"
    refs_root.mkdir(parents=True, exist_ok=True)
    txid = "1234567890abcdef1234567890abcdef"
    if residue_kind == "final":
        (refs_root / f"REF-{evidence_id:03d}").mkdir()
    else:
        residue_root = refs_root / (".staging" if residue_kind == "staging" else ".backup")
        residue_root.mkdir()
        (residue_root / f"REF-{evidence_id:03d}.{txid}").mkdir()

    # A missing counter and a regressed counter must both advance beyond disk evidence.
    if residue_kind != "final":
        (refs_root / "counter.json").write_text('{"last_id": 1}', encoding="utf-8")
    proc = _run_mst("counter", "next", "--type", "ref", cwd=ws)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"REF-{evidence_id + 1:03d}"
    assert json.loads((refs_root / "counter.json").read_text(encoding="utf-8"))["last_id"] == evidence_id + 1


@pytest.mark.parametrize("counter_bytes", [b"{not-json", b'{"last_id": "7"}', b'{"last_id": -1}'])
def test_counter_state_corrupt_fails_closed(tmp_path: Path, counter_bytes: bytes):
    ws = _setup_workspace(tmp_path)
    refs_root = ws / ".gran-maestro" / "references"
    refs_root.mkdir(parents=True, exist_ok=True)
    (refs_root / "counter.json").write_bytes(counter_bytes)
    proc = _run_mst("counter", "next", "--type", "ref", cwd=ws)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "Error [REFERENCE_COUNTER_CORRUPT] outcome=confirmed_failure:" in proc.stderr


def test_counter_state_symlink_evidence_fails_path_unsafe(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    refs_root = ws / ".gran-maestro" / "references"
    refs_root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (refs_root / "REF-007").symlink_to(outside, target_is_directory=True)
    proc = _run_mst("counter", "next", "--type", "ref", cwd=ws)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "Error [REFERENCE_PATH_UNSAFE] outcome=confirmed_failure:" in proc.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_counter_state_unreadable_fails_counter_corrupt(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    refs_root = ws / ".gran-maestro" / "references"
    refs_root.mkdir(parents=True, exist_ok=True)
    counter_path = refs_root / "counter.json"
    counter_path.write_text('{"last_id": 3}', encoding="utf-8")
    counter_path.chmod(0)
    try:
        proc = _run_mst("counter", "next", "--type", "ref", cwd=ws)
    finally:
        counter_path.chmod(0o600)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "Error [REFERENCE_COUNTER_CORRUPT] outcome=confirmed_failure:" in proc.stderr


@pytest.mark.parametrize(
    ("failpoint", "expected_next"),
    [
        ("counter_after_temp_fsync", "REF-001"),
        ("counter_after_replace", "REF-002"),
        ("counter_after_parent_sync", "REF-002"),
    ],
)
def test_counter_state_crash_persistence_boundary(
    tmp_path: Path, failpoint: str, expected_next: str
):
    ws = _setup_workspace(tmp_path)
    refs_root = ws / ".gran-maestro" / "references"
    refs_root.mkdir(parents=True, exist_ok=True)
    (refs_root / "counter.json").write_text('{"last_id": 0}', encoding="utf-8")
    crashed = _run_mst(
        "counter", "next", "--type", "ref", cwd=ws,
        env={
            "MST_TEST_MODE": "1",
            "MST_REFERENCE_FAILPOINT": failpoint,
            "MST_REFERENCE_FAIL_ACTION": "sigkill",
        },
    )
    assert crashed.returncode in (-signal.SIGKILL, 137, 128 + signal.SIGKILL, -9)

    resumed = _run_mst("counter", "next", "--type", "ref", cwd=ws)
    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stdout.strip() == expected_next


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [("topic", 7), ("content_path", ".gran-maestro/references/REF-999/content.md")],
)
def test_reference_schema_rejects_non_string_and_wrong_content_path(
    tmp_path: Path, field_name: str, bad_value: Any
):
    ws = _setup_workspace(tmp_path)
    _run_mst_json(
        "reference", "add",
        "--topic", "Schema topic",
        "--url", "https://example.com/schema",
        "--summary", "Schema summary",
        "--content", "schema content",
        "--json",
        cwd=ws,
    )
    metadata_path = ws / ".gran-maestro" / "references" / "REF-001" / "reference.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata[field_name] = bad_value
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    proc = _run_mst("reference", "get", "REF-001", "--json", cwd=ws)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "Error [REFERENCE_SCHEMA_INVALID] outcome=confirmed_failure:" in proc.stderr


def test_reference_doctor_reports_orphaned_counter_temp(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    refs_root = ws / ".gran-maestro" / "references"
    refs_root.mkdir(parents=True, exist_ok=True)
    temp_path = refs_root / ".counter.orphan.tmp"
    temp_path.write_text('{"last_id": 1}', encoding="utf-8")

    doctor = _run_mst_json("reference", "doctor", "--json", cwd=ws)
    assert doctor["status"] == "issues"
    assert doctor["summary"]["staging"] == 1
    assert doctor["staging"][0]["path"] == str(temp_path)
    assert doctor["staging"][0]["diagnostics"][0]["code"] == "REFERENCE_STAGING_STALE"


@pytest.mark.parametrize("error_number", [18, 13, 30, 28])  # EXDEV, EACCES, EROFS, ENOSPC
def test_filesystem_failure_consumes_reserved_id_without_partial_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error_number: int,
):
    from argparse import Namespace
    from scripts.mst_cmds import reference as reference_module

    ws = _setup_workspace(tmp_path)
    refs_root = ws / ".gran-maestro" / "references"

    def fail_final_reservation(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(error_number, "injected publish failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(reference_module._common, "BASE_DIR", ws / ".gran-maestro")
        scoped.setattr(reference_module, "_secure_mkdir_no_overwrite", fail_final_reservation)
        rc = reference_module.cmd_reference_add(
            Namespace(
                topic="Failure topic",
                url="https://example.com/failure",
                summary="Failure summary",
                content="Failure content",
                json=False,
            )
        )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "Error [REFERENCE_PUBLISH_FAILED] outcome=confirmed_failure:" in captured.err
    assert json.loads((refs_root / "counter.json").read_text(encoding="utf-8"))["last_id"] == 1
    assert not (refs_root / "REF-001").exists()

    resumed = _run_mst(
        "reference", "add",
        "--topic", "Resume topic",
        "--url", "https://example.com/resume",
        "--summary", "Resume summary",
        cwd=ws,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stdout.strip() == "REF-002"


def test_filesystem_failure_reports_platform_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    from argparse import Namespace
    from scripts.mst_cmds import reference as reference_module

    ws = _setup_workspace(tmp_path)

    def unsupported(*_args: Any, **_kwargs: Any) -> None:
        raise reference_module.ReferenceError(
            "REFERENCE_PLATFORM_UNSUPPORTED",
            "injected missing no-reparse primitive",
        )

    with monkeypatch.context() as scoped:
        scoped.setattr(reference_module._common, "BASE_DIR", ws / ".gran-maestro")
        scoped.setattr(reference_module, "_secure_mkdir_no_overwrite", unsupported)
        rc = reference_module.cmd_reference_add(
            Namespace(
                topic="Unsupported topic",
                url="https://example.com/unsupported",
                summary="Unsupported summary",
                content=None,
                json=False,
            )
        )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "Error [REFERENCE_PLATFORM_UNSUPPORTED] outcome=confirmed_failure:" in captured.err


# ==============================================================================
# AC-006: Collision, Symlink, and Path Race Tests
# ==============================================================================

def test_ac006_collision_existing_target_preserves_bytes(tmp_path: Path):
    """
    AC-006 [MUST] [collision]
    Given: existing final target이 writer가 일시 중지된 사이에 생성됨
    When: 동일한 ID로 publish를 시도함
    Then: REFERENCE_COLLISION으로 실패하고 기존 target bytes가 byte-for-byte 동일함
    """
    ws = _setup_workspace(tmp_path)
    barrier_dir = tmp_path / "barrier_collision"
    barrier_dir.mkdir(parents=True, exist_ok=True)

    env = {
        "MST_TEST_MODE": "1",
        "MST_REFERENCE_FAILPOINT": "before_publish",
        "MST_REFERENCE_FAIL_ACTION": "barrier",
        "MST_TEST_BARRIER_DIR": str(barrier_dir),
    }

    proc = subprocess.Popen(
        [
            sys.executable,
            str(MST_SCRIPT),
            "reference",
            "add",
            "--topic", "Collision Attacker Topic",
            "--url", "https://example.com/collision",
            "--summary", "Collision Attacker Summary",
            "--content", "Attacker content",
            "--json",
        ],
        cwd=ws,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, **env},
    )

    try:
        # Barrier 도달 대기
        ready = _wait_for_barrier_ready(barrier_dir, timeout=10.0)
        assert ready, "Writer did not reach before_publish barrier in time"

        # Writer가 일시 중지된 동안 대상 디렉터리(REF-001)와 보호 대상 바이트 생성
        ref_dir = ws / ".gran-maestro" / "references" / "REF-001"
        ref_dir.mkdir(parents=True, exist_ok=True)

        original_json_bytes = b'{"id": "REF-001", "topic": "Pre-existing Unchanged", "protected": true}'
        original_content_bytes = b"# Pre-existing Content\nMust not be overwritten.\n"

        (ref_dir / "reference.json").write_bytes(original_json_bytes)
        (ref_dir / "content.md").write_bytes(original_content_bytes)

        initial_tree_hash = _calculate_tree_hash(ref_dir)

        # Release barrier
        _release_barrier(barrier_dir)

        stdout, stderr = proc.communicate(timeout=10.0)

        assert proc.returncode == 1, (
            f"Expected failure on collision, got exit {proc.returncode}\nstdout: {stdout}\nstderr: {stderr}"
        )
        assert "Error [REFERENCE_COLLISION]" in stderr
        assert "outcome=confirmed_failure" in stderr

        # 바이트 레벨 무변경 검증
        after_tree_hash = _calculate_tree_hash(ref_dir)
        assert initial_tree_hash == after_tree_hash, "Pre-existing target was corrupted or overwritten during collision!"
        assert (ref_dir / "reference.json").read_bytes() == original_json_bytes
        assert (ref_dir / "content.md").read_bytes() == original_content_bytes

    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_ac006_symlink_target_rejected_and_safe(tmp_path: Path):
    """
    AC-006 [MUST] [symlink]
    Given: references/REF-001이 외부 디렉터리를 가리키는 symlink임
    When: add/update publish를 실행함
    Then: REFERENCE_PATH_UNSAFE 또는 REFERENCE_COLLISION으로 실패하고 외부 디렉터리 tree hash가 보존됨
    """
    ws = _setup_workspace(tmp_path)
    outside_dir = tmp_path / "sensitive_outside_directory"
    outside_dir.mkdir(parents=True, exist_ok=True)

    (outside_dir / "secret.txt").write_text("SENSITIVE DATA - DO NOT OVERWRITE", encoding="utf-8")
    initial_outside_hash = _calculate_tree_hash(outside_dir)

    references_dir = ws / ".gran-maestro" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    symlink_target = references_dir / "REF-001"
    symlink_target.symlink_to(outside_dir, target_is_directory=True)

    # Counter를 0으로 설정하여 REF-001 symlink 타겟에 add 유도
    counter_file = references_dir / "counter.json"
    counter_file.write_text(json.dumps({"last_id": 0}), encoding="utf-8")

    proc = _run_mst(
        "reference", "add",
        "--topic", "Symlink Attacker Topic",
        "--url", "https://example.com/symlink",
        "--summary", "Symlink Attacker Summary",
        cwd=ws,
    )

    assert proc.returncode == 1
    assert any(code in proc.stderr for code in ("Error [REFERENCE_PATH_UNSAFE]", "Error [REFERENCE_COLLISION]")), (
        f"Expected REFERENCE_PATH_UNSAFE or REFERENCE_COLLISION in stderr:\n{proc.stderr}"
    )

    # 외부 디렉터리 내용이 변경되지 않았음을 검증
    after_outside_hash = _calculate_tree_hash(outside_dir)
    assert initial_outside_hash == after_outside_hash, "External directory was modified through symlink traversal!"


def test_ac006_path_race_before_publish_ancestor_swap(tmp_path: Path):
    """
    AC-006 [MUST] [path_race]
    Given: before_publish barrier에서 ancestor/target 교체가 준비됨
    When: add publish를 재개함
    Then: REFERENCE_COLLISION 또는 REFERENCE_PATH_UNSAFE로 실패하고 기존 target bytes와 외부 path tree hash가 유지됨
    """
    ws = _setup_workspace(tmp_path)
    barrier_dir = tmp_path / "barrier_path_race"
    barrier_dir.mkdir(parents=True, exist_ok=True)

    outside_dir = tmp_path / "victim_outside_tree"
    outside_dir.mkdir(parents=True, exist_ok=True)
    (outside_dir / "safe_file.txt").write_text("PRESERVED CONTENT", encoding="utf-8")
    initial_outside_hash = _calculate_tree_hash(outside_dir)

    env = {
        "MST_TEST_MODE": "1",
        "MST_REFERENCE_FAILPOINT": "before_publish",
        "MST_REFERENCE_FAIL_ACTION": "barrier",
        "MST_TEST_BARRIER_DIR": str(barrier_dir),
    }

    proc = subprocess.Popen(
        [
            sys.executable,
            str(MST_SCRIPT),
            "reference",
            "add",
            "--topic", "Race Topic",
            "--url", "https://example.com/race",
            "--summary", "Race Summary",
            "--json",
        ],
        cwd=ws,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, **env},
    )

    try:
        # Barrier 도달 대기
        ready = _wait_for_barrier_ready(barrier_dir, timeout=10.0)
        assert ready, "Writer did not reach before_publish barrier in time"

        # 대기하는 동안 타겟 디렉터리 REF-001을 외부 디렉터리 symlink로 바꿔치기
        references_dir = ws / ".gran-maestro" / "references"
        target_ref_dir = references_dir / "REF-001"
        target_ref_dir.symlink_to(outside_dir, target_is_directory=True)

        # Release barrier
        _release_barrier(barrier_dir)

        stdout, stderr = proc.communicate(timeout=10.0)
        assert proc.returncode == 1, f"Expected path race failure, got exit {proc.returncode}\nstdout: {stdout}\nstderr: {stderr}"
        assert any(code in stderr for code in ("Error [REFERENCE_PATH_UNSAFE]", "Error [REFERENCE_COLLISION]"))

        # 외부 디렉터리가 손상되지 않았음을 검증
        after_outside_hash = _calculate_tree_hash(outside_dir)
        assert initial_outside_hash == after_outside_hash, "External directory victim was modified during path race!"

    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
