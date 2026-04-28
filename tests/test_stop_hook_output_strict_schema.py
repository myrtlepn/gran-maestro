import json
import pathlib
import shlex
import subprocess

ALLOWED_FIELDS = {"decision", "reason"}
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "mst-stop-hook.sh"


def _call_emit(func_name: str, *args: str):
    quoted_args = " ".join(shlex.quote(a) for a in args)
    hook = shlex.quote(str(HOOK_PATH))
    cmd = [
        "bash",
        "-c",
        f"""
source {hook}
if ! declare -F {func_name} >/dev/null; then
  eval "$(awk '/^details_anchor_for_reason\\(\\)/,/^}}/ {{ print }} /^emit_allow_json\\(\\)/,/^}}/ {{ print }}' {hook})"
fi
{func_name} {quoted_args}
""",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return res.stdout.strip(), res.stderr.strip(), res.returncode


def test_emit_approve_json_no_details_anchor():
    stdout, _, rc = _call_emit("emit_approve_json", "test reason", "")
    assert rc == 0
    obj = json.loads(stdout)
    assert set(obj.keys()) == ALLOWED_FIELDS
    assert obj["decision"] == "approve"
    assert obj["reason"] == "test reason"


def test_emit_block_json_no_details_anchor():
    stdout, _, rc = _call_emit("emit_block_json", "blocked reason", "")
    assert rc == 0
    obj = json.loads(stdout)
    assert set(obj.keys()) == ALLOWED_FIELDS
    assert obj["decision"] == "block"


def test_emit_block_json_empty_reason_fallback():
    stdout, _, rc = _call_emit("emit_block_json", "", "")
    assert rc == 0
    obj = json.loads(stdout)
    assert "reason" in obj
    assert len(obj["reason"]) >= 1


def test_decision_enum_only_approve_block():
    for func, expected in [
        ("emit_approve_json", "approve"),
        ("emit_block_json", "block"),
    ]:
        stdout, _, rc = _call_emit(func, "r", "")
        assert rc == 0
        obj = json.loads(stdout)
        assert obj["decision"] in {"approve", "block"}
        assert obj["decision"] == expected


def test_anchor_emitted_to_stderr_when_present():
    stdout, stderr, rc = _call_emit("emit_approve_json", "r", "docs/X.md#section")
    assert rc == 0
    obj = json.loads(stdout)
    assert "details_anchor" not in obj
    assert stderr.splitlines() == ["[stop-hook] anchor=docs/X.md#section"]


def test_emit_allow_json_no_details_anchor():
    """L488 inline approve path (emit_allow_json) keeps the same schema."""
    stdout, _, rc = _call_emit("emit_allow_json", "soft approve")
    assert rc == 0
    obj = json.loads(stdout)
    assert set(obj.keys()) == ALLOWED_FIELDS
    assert obj["decision"] == "approve"
