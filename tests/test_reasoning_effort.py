from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.mst_cmds import reasoning_effort as reasoning_effort_mod
from scripts.mst_cmds.native_delegation import _external_command


def _write_config(base_dir: Path, payload: dict) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "config.resolved.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _codex_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reasoning_effort_mod,
        "_codex_model_catalog",
        lambda: {
            "gpt-5.6-sol": {
                "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
                "default": "low",
            },
            "gpt-5.6-luna": {
                "efforts": ["low", "medium", "high", "xhigh", "max"],
                "default": "medium",
            },
        },
    )


def test_agent_effort_overrides_provider_default(tmp_path: Path) -> None:
    base = tmp_path / ".gran-maestro"
    _write_config(
        base,
        {
            "models": {
                "providers": {
                    "codex": {
                        "premium": "gpt-5.6-sol",
                        "default_tier": "premium",
                        "default_reasoning_effort": "medium",
                    }
                }
            },
            "ideation": {
                "agents": {
                    "codex": {
                        "count": 1,
                        "tier": "premium",
                        "reasoning_effort": "ultra",
                    }
                }
            },
        },
    )

    resolved = reasoning_effort_mod.resolve_execution("codex", "ideation", base_dir=base)

    assert resolved["model"] == "gpt-5.6-sol"
    assert resolved["reasoning_effort"] == "ultra"
    assert resolved["reasoning_effort_source"] == "ideation.agents.codex.reasoning_effort"


def test_default_and_inherit_have_distinct_precedence(tmp_path: Path) -> None:
    base = tmp_path / ".gran-maestro"
    config = {
        "models": {
            "providers": {
                "codex": {
                    "premium": "gpt-5.6-sol",
                    "default_tier": "premium",
                    "default_reasoning_effort": "high",
                }
            }
        },
        "ideation": {
            "agents": {
                "codex": {
                    "count": 1,
                    "tier": "premium",
                    "reasoning_effort": "default",
                }
            }
        },
    }
    _write_config(base, config)
    inherited_default = reasoning_effort_mod.resolve_execution("codex", "ideation", base_dir=base)
    assert inherited_default["reasoning_effort"] == "high"

    config["ideation"]["agents"]["codex"]["reasoning_effort"] = "inherit"
    _write_config(base, config)
    host_default = reasoning_effort_mod.resolve_execution("codex", "ideation", base_dir=base)
    assert host_default["reasoning_effort"] is None


def test_unsupported_model_effort_fails_before_launch(tmp_path: Path) -> None:
    base = tmp_path / ".gran-maestro"
    _write_config(
        base,
        {
            "models": {
                "providers": {
                    "codex": {
                        "premium": "gpt-5.6-luna",
                        "default_tier": "premium",
                        "default_reasoning_effort": "ultra",
                    }
                }
            }
        },
    )

    with pytest.raises(reasoning_effort_mod.ReasoningEffortError, match="unsupported"):
        reasoning_effort_mod.resolve_execution("codex", base_dir=base)


@pytest.mark.parametrize(
    ("provider", "effort", "expected"),
    [
        ("codex", "ultra", ['-c', 'model_reasoning_effort="ultra"']),
        ("claude", "max", ["--effort", "max"]),
        ("agy", "high", ["--effort", "high"]),
    ],
)
def test_external_adapters_emit_provider_effort_flag(
    tmp_path: Path,
    provider: str,
    effort: str,
    expected: list[str],
) -> None:
    command, _transport = _external_command(
        provider=provider,
        executable=provider,
        prompt="prompt",
        worktree_dir=tmp_path,
        model="test-model",
        read_only=True,
        reasoning_effort=effort,
    )

    index = command.index(expected[0])
    assert command[index:index + len(expected)] == expected


def test_inherit_omits_external_effort_flag(tmp_path: Path) -> None:
    for provider in ("codex", "claude", "agy"):
        command, _transport = _external_command(
            provider=provider,
            executable=provider,
            prompt="prompt",
            worktree_dir=tmp_path,
            model="test-model",
            read_only=True,
            reasoning_effort=None,
        )
        assert "--effort" not in command
        assert not any(item.startswith("model_reasoning_effort=") for item in command)
