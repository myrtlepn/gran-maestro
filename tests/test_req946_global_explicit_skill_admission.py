from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPLICIT_GATE = "<!-- @include _shared/explicit-invocation-gate.md -->"
SESSION_BOOTSTRAP = "<!-- @include _shared/session-bootstrap.md -->"


def _skill_files(root: Path) -> list[Path]:
    return sorted((root / "skills").glob("*/SKILL.md"))


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    block = text.split("---\n", 2)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields


def _user_invocable(root: Path) -> list[Path]:
    return [
        path
        for path in _skill_files(root)
        if _frontmatter(path).get("user-invocable") == "true"
    ]


def test_user_invocable_inventory_is_file_derived_and_explicit_only() -> None:
    source_names = {path.parent.name for path in _user_invocable(REPO_ROOT)}
    projected_names = {
        path.parent.name for path in _user_invocable(REPO_ROOT / "plugins" / "mst")
    }
    assert source_names == projected_names
    assert len(source_names) == 37

    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        invocable = _user_invocable(root)
        for path in invocable:
            fields = _frontmatter(path)
            name = fields["name"].strip('"')
            description = fields["description"]
            assert f"$mst:{name}" in description, path
            assert f"/mst:{name}" in description, path
            assert "MST/Gran Maestro/Maestro" in description, path
            assert "일반 요청에는 자동 활성화하지 않습니다" in description, path
            assert not re.search(
                r"사용자가\s*['\"](?:설정|목록|정리|코드 작업|계속해줘|머지|모니터링)",
                description,
            ), path


def test_every_user_invocable_skill_has_the_first_zero_mutation_gate() -> None:
    forbidden_before_gate = (
        ".gran-maestro/",
        "python3 ",
        "PROJECT_ROOT=",
        "config get",
        "counter next",
        "delegation ",
        "dispatch ",
        "Write(",
        "Edit(",
        "Read(",
    )
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for path in _user_invocable(root):
            text = path.read_text(encoding="utf-8")
            assert text.count(EXPLICIT_GATE) == 1, path
            gate_index = text.index(EXPLICIT_GATE)
            heading = re.search(r"^# maestro:[^\n]+$", text, re.MULTILINE)
            assert heading is not None, path
            assert gate_index > heading.end(), path
            prefix = text[heading.end() : gate_index]
            assert not prefix.strip(), path
            for token in forbidden_before_gate:
                assert token not in text[:gate_index], (path, token)
            gate_end = text.index("<!-- @end-include -->", gate_index)
            gate = text[gate_index:gate_end]
            assert "현재 `SKILL.md` frontmatter의 exact `name`" in gate
            assert "도구 호출, 파일 읽기, 상태 생성" in gate
            assert "인용문·로그·문서 예시, 부정문" in gate
            assert "텍스트 envelope나 임의 SID" in gate


def test_internal_templates_are_explicitly_not_user_invocable() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for path in _skill_files(root):
            fields = _frontmatter(path)
            assert fields.get("user-invocable") in {"true", "false"}, path
            if fields["user-invocable"] == "false":
                assert any(
                    marker in fields["description"].lower()
                    for marker in ("internal", "template", "queue", "템플릿")
                ), path


def test_every_public_skill_declares_session_admission_class() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for path in _user_invocable(root):
            text = path.read_text(encoding="utf-8")
            identity_required = "<!-- mst-session-class: identity-required;" in text
            stateless_utility = "<!-- mst-session-class: stateless-utility -->" in text
            assert identity_required != stateless_utility, path
            if identity_required:
                assert SESSION_BOOTSTRAP in text, path
                assert text.index(EXPLICIT_GATE) < text.index(SESSION_BOOTSTRAP), path
            else:
                assert "session-independent administrative/read/config utility" in text, path


def _fenced_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
            continue
        if current is not None:
            current.append(line)
    return blocks


def test_executable_identity_consumers_are_exhaustively_bound() -> None:
    identity_commands = {
        "agile",
        "archive",
        "counter",
        "delegation",
        "dispatch",
        "intent",
        "on",
        "plan",
        "queue",
        "recover",
        "reference",
        "request",
        "run",
        "state",
        "stitch",
        "task",
        "worktree",
    }
    command_re = re.compile(
        r'python3\s+[\"]?\{PLUGIN_ROOT\}/scripts/mst\.py[\"]?\s+([a-z0-9-]+)'
    )
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        found = 0
        for path in _user_invocable(root):
            text = path.read_text(encoding="utf-8")
            if "<!-- mst-session-class: identity-required;" not in text:
                continue
            for block in _fenced_blocks(text):
                for index, line in enumerate(block):
                    match = command_re.search(line)
                    if match is None or match.group(1) not in identity_commands:
                        continue
                    if match.group(1) == "session" and any(
                        token in line for token in ("session resolve", "session bootstrap")
                    ):
                        continue
                    found += 1
                    prefix = "\n".join(block[max(0, index - 7) : index + 1])
                    assert 'MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}"' in prefix, (
                        path,
                        line,
                    )
                    assert 'MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}"' in prefix, (
                        path,
                        line,
                    )
                    assert "validate=True" in prefix, (path, line)
        assert found >= 100, root


def test_no_permissive_base64_decoder_remains_in_skills() -> None:
    permissive = "base64.urlsafe_b64decode(os.environ"
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for path in _skill_files(root):
            assert permissive not in path.read_text(encoding="utf-8"), path


def test_native_child_calls_do_not_embed_text_capabilities() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for path in _skill_files(root):
            assert "MST_PARENT_BINDING" not in path.read_text(encoding="utf-8"), path

    projected_agile = (
        REPO_ROOT / "plugins" / "mst" / "skills" / "agile" / "SKILL.md"
    ).read_text(encoding="utf-8")
    projected_calls = [
        line
        for line in projected_agile.splitlines()
        if "$mst:agile-plan" in line and "--return-to agile/1" in line
    ]
    assert len(projected_calls) == 2


def test_full_sid_inheritance_resume_and_strict_transport_contracts() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        bootstrap = (root / "skills" / "_shared" / "session-bootstrap.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "context-only identity cannot replace a full MST_SESSION_ID",
            "Native child는 host가 부모의 full SID를 상속",
            "resume preflight",
            "status",
            "base64.b64decode",
            "altchars=b\"-_\"",
            "validate=True",
            "MAX_CONTEXT_BYTES",
            "canonical re-encoding",
            "trailing whitespace",
        ):
            assert token in bootstrap, (root, token)
        assert bootstrap.index("#### 2. Resume preflight") < bootstrap.index(
            "#### 3. Resolve 또는 bootstrap"
        ), root

        request = (root / "skills" / "request" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert request.index("#### 2. Resume preflight") < request.index(
            'python3 "{PLUGIN_ROOT}/scripts/mst.py" session bootstrap'
        ), root


def test_codex_0147_network_examples_use_one_parser_valid_policy() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        codex = (root / "skills" / "codex" / "SKILL.md").read_text(encoding="utf-8")
        assert "codex-cli 0.147" in codex
        assert "--sandbox danger-full-access" in codex
        assert "-a on-request" not in codex
        assert "--sandbox danger-full-access --approve-for-me" not in codex
        assert "--full-auto" not in codex
