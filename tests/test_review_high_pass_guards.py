import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_SKILL = ROOT / "skills" / "review" / "SKILL.md"
APPROVE_SKILL = ROOT / "skills" / "approve" / "SKILL.md"
PM_CONDUCTOR = ROOT / "agents" / "pm-conductor.md"
DEFAULT_CONFIG = ROOT / "templates" / "defaults" / "config.json"
CODEX_ADAPTER = ROOT / "src" / "core" / "cli-adapter.ts"
PROJECTED_PM_CONDUCTOR = ROOT / "plugins" / "mst" / "agents" / "pm-conductor.md"
PROJECTED_CODEX_ADAPTER = ROOT / "plugins" / "mst" / "src" / "core" / "cli-adapter.ts"


def test_review_minor_only_high_pass_guard_documented():
    assert REVIEW_SKILL.exists(), f"missing file: {REVIEW_SKILL}"
    content = REVIEW_SKILL.read_text(encoding="utf-8")

    assert "MINOR-only high-pass 보호 가드" in content
    assert "auto_accept_guard" in content
    assert "skipped_minor_count" in content
    assert "protection_flags_count" in content
    assert "minor_count <= config.review.severity_auto_fix.minor_skip_threshold" in content


def test_review_executable_dispatch_is_worktree_bound():
    content = REVIEW_SKILL.read_text(encoding="utf-8")

    assert "Step 1.5: 실행형 리뷰 Worktree 바인딩" in content
    assert 'REVIEW_ROLE="review-RV-NNN"' in content
    assert "dispatch validate-worktree --worktree-dir \"$REVIEW_WORKTREE\" --json" in content
    assert "--require-worktree --worktree-dir \"$REVIEW_WORKTREE\"" in content
    assert 'codex exec --approve-for-me -m "$MODEL" -C "$REVIEW_WORKTREE"' in content
    assert 'cd {PROJECT_ROOT} && gemini' not in content
    assert "codex exec --approve-for-me -m \"$MODEL\" -C {PROJECT_ROOT}" not in content


def test_pm_codex_review_fallback_uses_current_writable_contract():
    content = PM_CONDUCTOR.read_text(encoding="utf-8")

    assert '`codex exec --approve-for-me "{prompt}"`' in content
    assert "codex --full-auto" not in content


def test_codex_public_consumers_match_current_cli_permission_contract():
    adapter = CODEX_ADAPTER.read_text(encoding="utf-8")
    pm_conductor = PM_CONDUCTOR.read_text(encoding="utf-8")

    assert "runProcessWithTimeout('codex', args" in adapter
    assert "['--sandbox', 'read-only']" in adapter
    assert "--approve-for-me" in adapter
    assert "new Deno.Command(executable" in adapter
    assert "--full-auto" not in adapter
    assert 'codex exec --approve-for-me "{prompt}"' in pm_conductor
    assert "--full-auto" not in pm_conductor
    assert PROJECTED_CODEX_ADAPTER.read_text(encoding="utf-8") == adapter
    assert PROJECTED_PM_CONDUCTOR.read_text(encoding="utf-8") == pm_conductor


def test_pm_direct_fix_requires_worktree_preflight_and_evidence():
    content = APPROVE_SKILL.read_text(encoding="utf-8")

    assert "dispatch validate-worktree --worktree-dir {worktree_path} --json" in content
    assert "pm_direct_fix_worktree_guard_failed" in content
    assert "`worktree_path`, 수정 파일 목록, 수정 내용 요약, 검증 명령, expected signal, commit 또는 rollback evidence" in content


def test_auto_accept_guard_single_source_in_defaults_config():
    assert DEFAULT_CONFIG.exists(), f"missing file: {DEFAULT_CONFIG}"
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))

    guard = config["workflow"]["auto_accept_guard"]
    assert guard["single_source_of_truth"] == "workflow.auto_accept_guard"
    assert "review_summary.status == passed" in guard["allow_when"]
    assert "review_issues_summary.auto_accept_guard.blocked == false" in guard["allow_when"]
    assert "review_issues_summary.auto_accept_guard.skipped_minor_count > 0" in guard["block_when"]
    assert "review_issues_summary.auto_accept_guard.protection_flags_count > 0" in guard["block_when"]
