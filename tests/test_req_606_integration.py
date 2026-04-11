import json
import subprocess
import tempfile
from pathlib import Path


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


def _run_mst(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(MST_SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_mst_json(*args: str, cwd: Path):
    proc = _run_mst(*args, cwd=cwd)
    assert proc.returncode == 0, f"command failed: {proc.args}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return json.loads(proc.stdout)


def _assert_reference_schema(payload: dict):
    missing = REQUIRED_REFERENCE_KEYS - set(payload.keys())
    assert not missing, f"missing schema keys: {sorted(missing)} from payload={payload}"


def test_ac_t01_no_core_summary_placeholder_in_skills():
    matches = []
    for path in (REPO_ROOT / "skills").rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "{핵심 요약}" in text:
            matches.append(str(path.relative_to(REPO_ROOT)))

    assert matches == [], f"found legacy placeholder in skills: {matches}"


def test_ac_t02_reference_add_help_contains_required_keywords():
    proc = _run_mst("reference", "add", "--help", cwd=REPO_ROOT)

    assert proc.returncode == 0
    output = f"{proc.stdout}\n{proc.stderr}"
    for keyword in ("raw 발췌", "결론", "인용", "표", "코드"):
        assert keyword in output


def test_ac_t03_references_directory_has_no_head_diff():
    proc = subprocess.run(
        ["git", "status", "--porcelain", ".gran-maestro/references/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"unexpected references diff:\n{proc.stdout}"


def test_ac_t04_reference_cli_commands_regression_in_isolated_workspace():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        (tmp / ".gran-maestro").mkdir(parents=True, exist_ok=True)

        add_payload = _run_mst_json(
            "reference",
            "add",
            "--topic",
            "REQ-606 integration topic",
            "--url",
            "https://example.com/req-606",
            "--summary",
            "REQ-606 integration summary",
            "--content",
            "raw excerpt\n| key | value |\n|-----|-------|\n| a | 1 |",
            "--json",
            cwd=tmp,
        )
        _assert_reference_schema(add_payload)
        reference_id = add_payload["id"]

        get_payload = _run_mst_json("reference", "get", reference_id, "--json", cwd=tmp)
        _assert_reference_schema(get_payload)

        list_payload = _run_mst_json("reference", "list", "--json", cwd=tmp)
        assert isinstance(list_payload, list) and list_payload
        _assert_reference_schema(list_payload[0])

        search_payload = _run_mst_json(
            "reference",
            "search",
            "--keyword",
            "integration",
            "--json",
            cwd=tmp,
        )
        assert isinstance(search_payload, list) and search_payload
        _assert_reference_schema(search_payload[0])

        update_payload = _run_mst_json(
            "reference",
            "update",
            reference_id,
            "--summary",
            "REQ-606 updated summary",
            "--json",
            cwd=tmp,
        )
        _assert_reference_schema(update_payload)


def test_ac_t05_plan_skill_protocol_section_has_contiguous_checklist_examples_and_lazy_read():
    path = REPO_ROOT / "skills" / "plan" / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    section_title = "### Reference Lookup Protocol (MANDATORY)"

    start = content.find(section_title)
    assert start >= 0, "Reference Lookup Protocol section not found"

    next_section = content.find("\n### ", start + len(section_title))
    section = content[start:] if next_section < 0 else content[start:next_section]

    ordered_markers = [
        "예시 A (인용):",
        "예시 B (표):",
        "예시 C (코드 스니펫):",
        "신규 REF 품질 체크리스트 (저장 전 점검):",
        "Findings:",
        "Quotes:",
        "Data:",
        "Context:",
        "PM lazy-Read 트리거 (`content.md Read` 필수):",
    ]

    previous_index = -1
    for marker in ordered_markers:
        marker_index = section.find(marker)
        assert marker_index >= 0, f"marker missing from protocol section: {marker}"
        assert marker_index > previous_index, f"marker out of order in protocol section: {marker}"
        previous_index = marker_index


def test_ac_t06_reference_add_content_preserves_markdown_table_exactly():
    content = "## Findings\n| col | val |\n|-----|-----|\n| x | 1 |"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        (tmp / ".gran-maestro").mkdir(parents=True, exist_ok=True)

        add_payload = _run_mst_json(
            "reference",
            "add",
            "--topic",
            "test",
            "--url",
            "https://example.com",
            "--summary",
            "test",
            "--content",
            content,
            "--json",
            cwd=tmp,
        )

        content_path = tmp / add_payload["content_path"]
        assert content_path.exists(), f"content.md not found: {content_path}"
        assert content_path.read_text(encoding="utf-8") == content
