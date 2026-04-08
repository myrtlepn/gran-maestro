"""REQ-585 / Task 01: /mst:resume 스킬 + queue 통합 테스트.

Phase 2 범위:
- skills/resume/SKILL.md 파일 존재 및 frontmatter 유효성
- queue peek → pop → complete 경로 시뮬레이션 (실제 Skill 호출 없이 CLI 시퀀스만 검증)
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MST = [sys.executable, str(ROOT / "scripts/mst.py")]


def _run_mst(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        MST + list(args),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_resume_skill_file_exists_and_valid():
    """skills/resume/SKILL.md가 존재하고 frontmatter + 핵심 프로토콜 섹션을 포함한다."""
    skill_path = ROOT / "skills/resume/SKILL.md"
    assert skill_path.exists(), f"skills/resume/SKILL.md must exist at {skill_path}"

    content = skill_path.read_text(encoding="utf-8")

    # frontmatter
    assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"
    assert "name: resume" in content, "frontmatter must contain 'name: resume'"
    assert "description:" in content, "frontmatter must contain 'description:'"

    # 실행 프로토콜 Step 필수
    assert "queue peek" in content, "SKILL.md must mention 'queue peek' command"
    assert "queue pop" in content, "SKILL.md must mention 'queue pop' command"
    assert "queue complete" in content or "queue fail" in content, (
        "SKILL.md must mention 'queue complete' or 'queue fail' command"
    )

    # AUTO_MODE / -a 전파 문서화
    assert "AUTO_MODE" in content, "SKILL.md must document AUTO_MODE propagation"
    assert "-a" in content, "SKILL.md must document -a flag propagation"

    # 5단계 Step 구조 (Step 1/5 ~ Step 5/5)
    step_count = sum(1 for i in range(1, 6) if f"Step {i}/5" in content)
    assert step_count == 5, f"SKILL.md must have 5 steps (Step 1/5 ~ 5/5), found {step_count}"


def test_queue_peek_pop_complete_simulation(tmp_path, monkeypatch):
    """resume 스킬이 수행하는 CLI 시퀀스를 시뮬레이션: enqueue → peek → pop → complete → list."""
    (tmp_path / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path

    # 1. enqueue a test action
    enq = _run_mst(
        workspace,
        "queue",
        "enqueue",
        "--skill",
        "mst:request",
        "--args",
        "--plan PLN-437 -a",
        "--source-skill",
        "mst:plan",
        "--source-id",
        "PLN-437",
        "--auto",
        "true",
        "--json",
    )
    assert enq.returncode == 0, f"enqueue failed: {enq.stderr}"
    entry = json.loads(enq.stdout)
    action_id = entry["id"]
    assert entry["skill"] == "mst:request"
    assert entry["args"] == "--plan PLN-437 -a"
    assert entry["auto"] is True
    assert entry["status"] == "queued"

    # 2. peek — should return the same entry without state change
    peek = _run_mst(workspace, "queue", "peek", "--json")
    assert peek.returncode == 0, f"peek failed: {peek.stderr}"
    peek_entry = json.loads(peek.stdout)
    assert peek_entry["id"] == action_id
    assert peek_entry["status"] == "queued", "peek must not change status"

    # 3. pop — transition queued → running
    pop = _run_mst(workspace, "queue", "pop", "--json")
    assert pop.returncode == 0, f"pop failed: {pop.stderr}"
    pop_entry = json.loads(pop.stdout)
    assert pop_entry["id"] == action_id
    assert pop_entry["status"] == "running"
    assert pop_entry["skill"] == "mst:request"
    assert pop_entry["args"] == "--plan PLN-437 -a"  # args preserved

    # 4. simulate successful Skill call → complete
    comp = _run_mst(
        workspace,
        "queue",
        "complete",
        "--id",
        action_id,
        "--result",
        "ok",
        "--json",
    )
    assert comp.returncode == 0, f"complete failed: {comp.stderr}"

    # 5. verify entry is in done list and not in queued/running
    lst_done = _run_mst(workspace, "queue", "list", "--status", "done", "--json")
    assert lst_done.returncode == 0
    done_items = json.loads(lst_done.stdout)
    assert any(it["id"] == action_id for it in done_items), "action should be in done list"

    lst_queued = _run_mst(workspace, "queue", "list", "--status", "queued", "--json")
    assert lst_queued.returncode == 0
    queued_items = json.loads(lst_queued.stdout)
    assert not any(it["id"] == action_id for it in queued_items), "action must not be in queued list"

    lst_running = _run_mst(workspace, "queue", "list", "--status", "running", "--json")
    assert lst_running.returncode == 0
    running_items = json.loads(lst_running.stdout)
    assert not any(it["id"] == action_id for it in running_items), "action must not be in running list"


def test_resume_skill_queue_empty_graceful(tmp_path, monkeypatch):
    """빈 queue에서 peek/pop이 graceful하게 null을 반환 (resume 스킬의 'queue empty' 분기 검증)."""
    (tmp_path / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)

    peek = _run_mst(tmp_path, "queue", "peek", "--json")
    assert peek.returncode == 0, f"peek on empty queue should succeed: {peek.stderr}"
    # null 또는 빈 객체 허용
    peek_out = peek.stdout.strip()
    assert peek_out in ("null", "{}", "") or json.loads(peek_out) in (None, {}), (
        f"peek on empty queue must return null/empty, got: {peek_out}"
    )

    pop = _run_mst(tmp_path, "queue", "pop", "--json")
    assert pop.returncode == 0, f"pop on empty queue should succeed: {pop.stderr}"
    pop_out = pop.stdout.strip()
    assert pop_out in ("null", "{}", "") or json.loads(pop_out) in (None, {}), (
        f"pop on empty queue must return null/empty, got: {pop_out}"
    )

    count = _run_mst(tmp_path, "queue", "count")
    assert count.returncode == 0
    assert count.stdout.strip() == "0"


def test_mst_loop_script_help():
    """scripts/mst-loop.sh --help이 0으로 종료하고 usage + 옵션 3개를 출력한다."""
    script = ROOT / "scripts/mst-loop.sh"
    assert script.exists(), f"scripts/mst-loop.sh must exist at {script}"

    result = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"--help should exit 0: {result.stderr}"
    assert "max-iterations" in result.stdout or "max-iterations" in result.stderr
    assert "sleep" in result.stdout or "sleep" in result.stderr
    assert "dry-run" in result.stdout or "dry-run" in result.stderr


def test_mst_loop_script_content():
    """scripts/mst-loop.sh가 queue count 체크와 claude 호출을 포함한다."""
    script = ROOT / "scripts/mst-loop.sh"
    content = script.read_text(encoding="utf-8")
    assert "queue count" in content, "mst-loop.sh must call 'queue count'"
    assert "max-iterations" in content, "mst-loop.sh must support --max-iterations"
    assert "dangerously-skip-permissions" in content, (
        "mst-loop.sh must use --dangerously-skip-permissions"
    )
    assert "/mst:resume" in content, "mst-loop.sh must call /mst:resume"


def test_mst_loop_docs_exist():
    """docs/mst-loop.md 문서에 필수 섹션이 포함되어 있다."""
    doc = ROOT / "docs/mst-loop.md"
    assert doc.exists(), f"docs/mst-loop.md must exist at {doc}"
    content = doc.read_text(encoding="utf-8")
    # 4가지 핵심 섹션 키워드
    assert "인라인" in content, "docs must compare inline chaining vs mst-loop"
    assert "mst-loop.sh" in content, "docs must show mst-loop.sh usage"
    assert "queue " in content, "docs must document queue commands"
    assert "제한" in content, "docs must list current limitations"
