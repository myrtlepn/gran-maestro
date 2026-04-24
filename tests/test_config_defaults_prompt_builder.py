import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"
CONFIG_DEFAULTS = REPO_ROOT / "templates" / "defaults" / "config.json"


def _workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with an empty .gran-maestro/ directory."""
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def test_config_defaults_prompt_builder():
    """AC-004: templates/defaults/config.json에 prompt_builder 섹션이 올바른 기본값으로 존재한다."""
    with open(CONFIG_DEFAULTS, encoding="utf-8") as f:
        config = json.load(f)

    assert "prompt_builder" in config, "prompt_builder 섹션이 config.json에 없습니다"
    pb = config["prompt_builder"]

    assert "enabled" in pb, "prompt_builder.enabled 키가 없습니다"
    assert pb["enabled"] is True, f"prompt_builder.enabled 기본값이 True여야 합니다 (실제: {pb['enabled']})"
    assert isinstance(pb["enabled"], bool), f"prompt_builder.enabled 타입이 bool이어야 합니다 (실제: {type(pb['enabled'])})"

    assert "fallback_on_error" in pb, "prompt_builder.fallback_on_error 키가 없습니다"
    assert pb["fallback_on_error"] is True, f"prompt_builder.fallback_on_error 기본값이 True여야 합니다 (실제: {pb['fallback_on_error']})"
    assert isinstance(pb["fallback_on_error"], bool), f"prompt_builder.fallback_on_error 타입이 bool이어야 합니다 (실제: {type(pb['fallback_on_error'])})"

    assert "metrics_path" in pb, "prompt_builder.metrics_path 키가 없습니다"
    assert pb["metrics_path"] == ".gran-maestro/metrics/prompt-builder.ndjson", (
        f"prompt_builder.metrics_path 기본값이 올바르지 않습니다 (실제: {pb['metrics_path']})"
    )
    assert isinstance(pb["metrics_path"], str), f"prompt_builder.metrics_path 타입이 str이어야 합니다 (실제: {type(pb['metrics_path'])})"

    assert "max_inline_ask_chars" in pb, "prompt_builder.max_inline_ask_chars 키가 없습니다"
    assert pb["max_inline_ask_chars"] == 200, (
        f"prompt_builder.max_inline_ask_chars 기본값이 200이어야 합니다 (실제: {pb['max_inline_ask_chars']})"
    )
    assert isinstance(pb["max_inline_ask_chars"], int), (
        f"prompt_builder.max_inline_ask_chars 타입이 int이어야 합니다 (실제: {type(pb['max_inline_ask_chars'])})"
    )


def test_mst_py_config_get_prompt_builder(tmp_path):
    """AC-005: mst.py config get prompt_builder.enabled → stdout='True', exit 0."""
    workspace = _workspace(tmp_path)
    result = subprocess.run(
        [sys.executable, str(MST), "config", "get", "prompt_builder.enabled"],
        capture_output=True,
        text=True,
        cwd=str(workspace),
    )
    assert result.returncode == 0, (
        f"exit code가 0이어야 합니다 (실제: {result.returncode})\n"
        f"stderr: {result.stderr}"
    )
    stdout = result.stdout.strip()
    assert stdout == "True", (
        f"stdout이 'True'여야 합니다 (실제: '{stdout}')"
    )
