from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SKILLS = ("debug", "ideation", "discussion", "explore", "plan", "plan-doc", "request")
EXTERNAL_PROVIDER_SKILLS = ("debug", "ideation", "discussion", "explore")
BOUND_SID = 'MST_SESSION_ID="{CANONICAL_MST_SESSION_ID}"'
BOUND_CONTEXT = 'MST_CONTEXT_JSON="$('
BOUND_CONTEXT_B64 = 'MST_CONTEXT_B64="{CANONICAL_MST_CONTEXT_B64}"'
STRICT_DECODER_TOKENS = (
    "base64.b64decode",
    'altchars=b"-_"',
    "validate=True",
    "MAX_CONTEXT_BYTES",
    "urlsafe_b64encode(raw)",
)


def _skill(root: Path, name: str) -> str:
    return (root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def _has_token(text: str, token: str) -> bool:
    return token in text or token.replace('"', '\\"') in text


def test_context_transport_contract_uses_shell_safe_base64url() -> None:
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        for name in ROOT_SKILLS:
            text = _skill(root, name)
            assert "CANONICAL_MST_CONTEXT_B64" in text, (root, name)
            assert "urlsafe_b64encode" in text, (root, name)
            for token in STRICT_DECODER_TOKENS:
                assert token in text, (root, name, token)
            assert "MST_BOUND_SUBPROCESS" in text, (root, name)
            assert "MST_CONTEXT_JSON='{CANONICAL_MST_CONTEXT_JSON}'" not in text, (root, name)
            assert "raw input byte-equivalence를 약속하지 않습니다" in text, (root, name)


def test_concrete_lifecycle_dispatch_provider_and_state_commands_are_bound() -> None:
    lifecycle_commands = (
        "mst.py delegation route",
        "mst.py delegation start",
        "mst.py delegation claim-spawn",
        "mst.py dispatch authorize-external",
        "mst.py dispatch build",
    )
    provider_re = re.compile(r'^\s*command: ".*(?:codex exec|agy --print).*"$', re.MULTILINE)

    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        shared = (root / "skills" / "_shared" / "delegation-routing.md").read_text(
            encoding="utf-8"
        )
        for command in lifecycle_commands:
            command_index = shared.index(command)
            bound_prefix = shared[max(0, command_index - 1600) : command_index]
            assert BOUND_SID in bound_prefix, (root, command)
            assert BOUND_CONTEXT in bound_prefix, (root, command)
            assert BOUND_CONTEXT_B64 in bound_prefix, (root, command)
            for token in STRICT_DECODER_TOKENS:
                assert token in bound_prefix, (root, command, token)

        for name in EXTERNAL_PROVIDER_SKILLS:
            provider_commands = provider_re.findall(_skill(root, name))
            assert provider_commands, (root, name)
            for command in provider_commands:
                assert f'command: "MST_SESSION_ID=\\"{{CANONICAL_MST_SESSION_ID}}\\"' in command, (
                    root,
                    name,
                    command,
                )
                assert 'MST_CONTEXT_JSON=\\"$(' in command, (root, name, command)
                assert 'MST_CONTEXT_B64=\\"{CANONICAL_MST_CONTEXT_B64}\\"' in command, (
                    root,
                    name,
                    command,
                )
                for token in STRICT_DECODER_TOKENS:
                    assert _has_token(command, token), (
                        root,
                        name,
                        command,
                        token,
                    )

        for name in ("plan", "request"):
            skill = _skill(root, name)
            state_index = skill.index("mst.py state set-workflow")
            bound_prefix = skill[max(0, state_index - 1600) : state_index]
            assert BOUND_SID in bound_prefix, (root, name)
            assert BOUND_CONTEXT in bound_prefix, (root, name)
            assert BOUND_CONTEXT_B64 in bound_prefix, (root, name)


def _fenced_shell_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:bash|sh)\n(.*?)```", text, re.DOTALL)


def test_every_concrete_state_dispatch_lifecycle_and_provider_block_is_bound() -> None:
    command_pattern = re.compile(
        r"(?:scripts/)?mst\.py\s+(?:delegation|dispatch|state|run|recover)\b"
        r"|(?<!mst:)\b(?:codex exec|agy --print|claude --" r"print)\b"
    )
    for root in (REPO_ROOT, REPO_ROOT / "plugins" / "mst"):
        files = sorted((root / "skills").glob("*/SKILL.md"))
        files.extend(sorted((root / "skills" / "_shared").glob("*.md")))
        found = 0
        for path in files:
            text = path.read_text(encoding="utf-8")
            for block in _fenced_shell_blocks(text):
                if not command_pattern.search(block):
                    continue
                found += 1
                assert BOUND_SID in block, path
                assert BOUND_CONTEXT_B64 in block, path
                for token in STRICT_DECODER_TOKENS:
                    assert token in block, (path, token)

            for line in text.splitlines():
                if "command:" not in line or not command_pattern.search(line):
                    continue
                found += 1
                assert "MST_SESSION_ID=" in line, (path, line)
                assert "MST_CONTEXT_B64=" in line, (path, line)
                for token in STRICT_DECODER_TOKENS:
                    assert _has_token(line, token), (path, line, token)
        assert found >= 45, root


def _documented_decoder(root: Path = REPO_ROOT) -> str:
    bootstrap = (root / "skills" / "_shared" / "session-bootstrap.md").read_text(
        encoding="utf-8"
    )
    match = re.search(r"python3 -c '([^']*base64\.b64decode[^']*)'", bootstrap)
    assert match is not None
    return match.group(1)


def _decode_with_documented_contract(encoded: str) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env["MST_CONTEXT_B64"] = encoded
    return subprocess.run(
        ["python3", "-c", _documented_decoder()],
        env=env,
        capture_output=True,
        check=False,
    )


def test_documented_base64url_decoder_rejects_malformed_and_oversized_inputs() -> None:
    canonical = base64.urlsafe_b64encode(b"{}").decode("ascii")
    cases = (
        canonical + "!",
        canonical.rstrip("="),
        canonical + "=",
        base64.urlsafe_b64encode(b"x" * (262144 + 1)).decode("ascii"),
    )
    for encoded in cases:
        result = _decode_with_documented_contract(encoded)
        assert result.returncode != 0, encoded[-20:]
        assert result.stdout == b""


def test_documented_base64url_decoder_accepts_canonical_embedded_newlines() -> None:
    raw = b'{"note":"line one\\nline two"}'
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    result = _decode_with_documented_contract(encoded)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == raw


def test_trailing_json_whitespace_is_normalized_before_transport() -> None:
    raw_with_trailing_whitespace = b'{"schema_version":1}\n\t '
    value = json.loads(raw_with_trailing_whitespace)
    canonical = json.dumps(value, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(canonical).decode("ascii")
    result = _decode_with_documented_contract(encoded)
    assert result.returncode == 0
    assert result.stdout == canonical
    assert result.stdout != raw_with_trailing_whitespace


def test_documented_transport_preserves_arbitrary_json_without_shell_execution(tmp_path: Path) -> None:
    injected = tmp_path / "injected"
    payload = {
        "schema_version": 1,
        "mst_session_id": "MST-REQ-946-20260816T024447456Z-h2xnj1eg",
        "root_mst_id": "REQ-946",
        "note": f"O'Reilly $(touch {injected}) ; `touch {injected}` & | < > $HOME \"quoted\"",
        "unicode": "세션 컨텍스트",
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    output = tmp_path / "output.bin"
    decoder = _documented_decoder()
    shell = rf'''
MST_SESSION_ID="$SID" \
MST_CONTEXT_JSON="$(MST_CONTEXT_B64="$CTX" python3 -c '{decoder}')" \
python3 -c 'import os,sys; sys.stdout.buffer.write(os.environ["MST_CONTEXT_JSON"].encode("utf-8"))'
'''
    env = os.environ.copy()
    env.update({"SID": payload["mst_session_id"], "CTX": encoded})
    result = subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", shell],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        check=False,
    )
    output.write_bytes(result.stdout)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert output.read_bytes() == raw
    assert not injected.exists()
