import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_PATH = REPO_ROOT / "templates" / "defaults" / "config.json"
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"

EXPECTED_AGILE_DEFAULTS = {
    "evidence_gate": {
        "enabled": True,
        "required_globs": [],
    },
    "drift": {
        "enabled": True,
        "threshold": 0.7,
        "warn_streak_limit": 2,
    },
    "recall": {
        "enabled": True,
        "cooldown_ratio": 0.10,
        "cooldown_floor": 1,
        "cooldown_ceiling": 4,
        "cap_ratio": 0.10,
        "cap_floor": 3,
        "cap_ceiling": 6,
        "level3_cooldown_multiplier": 2,
        "patch_budget_max": 3,
        "patch_budget_ratio": 0.20,
    },
    "unlock": {
        "enabled": True,
        "reason_min_length": 20,
        "reason_max_length": 500,
        "forbidden_patterns": ["lgtm", "ok", "fix"],
    },
}


def _load_defaults() -> dict:
    return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def test_agile_sections_exist():
    defaults = _load_defaults()
    agile = defaults["agile"]

    for section_name, expected_section in EXPECTED_AGILE_DEFAULTS.items():
        assert section_name in agile
        assert agile[section_name] == expected_section


def test_codex_primary_defaults_do_not_require_claude_provider():
    defaults = _load_defaults()

    assert defaults["workflow"]["default_agent"] == "codex-dev"
    assert defaults["models"]["roles"]["pm_conductor"]["provider"] == "codex"
    assert defaults["models"]["roles"]["architect"]["provider"] == "codex"
    assert defaults["models"]["roles"]["developer_claude"]["enabled"] is False
    assert defaults["fact_check"]["agent"]["provider"] == "codex"
    assert defaults["agile"]["dispatch"]["provider"] == "codex"
    assert defaults["delegation"]["host"] == "auto"
    assert defaults["delegation"]["default_provider"] == "codex"
    assert defaults["delegation"]["transport_policy"] == "same-host-native-first"
    assert defaults["delegation"]["native"] == {"enabled": True, "scope": "all"}
    assert "native_codex_subagents" not in defaults["delegation"]

    assignments = defaults["agent_assignments"]
    assert "docs" in assignments["codex-dev"]
    assert "config" in assignments["codex-dev"]
    assert "claude-dev" not in assignments

    for section in ("ideation", "discussion", "prereview", "debug"):
        agents = defaults[section]["agents"]
        assert agents["codex"]["count"] >= 1
        assert "agy" in agents
        assert "gemini" not in agents
        assert agents["claude"]["count"] == 0


def test_agy_is_canonical_provider_in_defaults():
    defaults = _load_defaults()

    assert "agy" in defaults["models"]["providers"]
    assert "gemini" not in defaults["models"]["providers"]
    assert defaults["models"]["providers"]["agy"]["premium"] == "agy-default"
    assert defaults["models"]["providers"]["agy"]["economy"] == "agy-default"
    assert defaults["delegation"]["provider_priority"] == ["codex", "agy", "claude"]
    assert defaults["models"]["roles"]["developer"][1]["provider"] == "agy"
    assert defaults["models"]["roles"]["reviewer"][1]["provider"] == "agy"


def test_native_delegation_setting_options_are_canonical():
    options_path = REPO_ROOT / "templates" / "defaults" / "setting-options.json"
    options = json.loads(options_path.read_text(encoding="utf-8"))

    assert options["delegation.transport_policy"] == ["same-host-native-first", "external-only"]
    assert "all" in options["delegation.native.scope"]
    assert not any("native_codex_subagents" in key for key in options)


def test_codex_primary_presets_use_canonical_native_first_policy():
    preset_dir = REPO_ROOT / "templates" / "defaults" / "presets" / "provider"
    for profile in ("budget", "efficient", "performance"):
        preset = json.loads((preset_dir / f"codex-primary-{profile}.json").read_text(encoding="utf-8"))
        delegation = preset["delegation"]
        assert delegation["transport_policy"] == "same-host-native-first"
        assert delegation["native"] == {"enabled": True, "scope": "all"}
        assert "native_codex_subagents" not in delegation


def test_resolve_model_normalizes_legacy_gemini_provider_to_agy():
    proc = _run_mst(REPO_ROOT, "resolve-model", "gemini", "default")

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "agy-default"
    assert "deprecated provider 'gemini' normalized to 'agy'" in proc.stderr
    assert "gemini-3.1" not in proc.stdout


def test_resolve_model_preserves_legacy_gemini_provider_config(tmp_path):
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".gran-maestro"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.resolved.json").write_text(
        json.dumps(
            {
                "models": {
                    "providers": {
                        "gemini": {
                            "default_tier": "premium",
                            "premium": "legacy-custom-model",
                        }
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    proc = _run_mst(workspace, "resolve-model", "gemini", "default")

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "legacy-custom-model"
    assert "deprecated provider 'gemini' normalized to 'agy'" in proc.stderr


def test_resolve_model_preserves_legacy_gemini_section_config(tmp_path):
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".gran-maestro"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.resolved.json").write_text(
        json.dumps(
            {
                "models": {
                    "providers": {
                        "gemini": {
                            "default_tier": "premium",
                            "premium": "legacy-premium-model",
                            "economy": "legacy-economy-model",
                        }
                    }
                },
                "ideation": {
                    "agents": {
                        "gemini": {
                            "tier": "economy",
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    proc = _run_mst(workspace, "resolve-model", "gemini", "ideation")

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "legacy-economy-model"
    assert "deprecated provider 'gemini' normalized to 'agy'" in proc.stderr


def test_agile_field_types():
    defaults = _load_defaults()
    agile = defaults["agile"]

    assert isinstance(agile["evidence_gate"]["enabled"], bool)
    assert isinstance(agile["evidence_gate"]["required_globs"], list)
    assert all(isinstance(item, str) for item in agile["evidence_gate"]["required_globs"])

    assert isinstance(agile["drift"]["enabled"], bool)
    assert isinstance(agile["drift"]["threshold"], (int, float))
    assert isinstance(agile["drift"]["warn_streak_limit"], int)

    assert isinstance(agile["recall"]["enabled"], bool)
    for key in ("cooldown_ratio", "cap_ratio", "patch_budget_ratio"):
        assert isinstance(agile["recall"][key], (int, float))
    for key in (
        "cooldown_floor",
        "cooldown_ceiling",
        "cap_floor",
        "cap_ceiling",
        "level3_cooldown_multiplier",
        "patch_budget_max",
    ):
        assert isinstance(agile["recall"][key], int)

    assert isinstance(agile["unlock"]["enabled"], bool)
    assert isinstance(agile["unlock"]["reason_min_length"], int)
    assert isinstance(agile["unlock"]["reason_max_length"], int)
    assert isinstance(agile["unlock"]["forbidden_patterns"], list)
    assert all(isinstance(item, str) for item in agile["unlock"]["forbidden_patterns"])


def test_fallback_to_defaults(tmp_path):
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".gran-maestro"
    config_dir.mkdir(parents=True, exist_ok=True)

    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "workflow": {"auto_accept_result": False},
                "agile": {
                    "drift": {"enabled": True},
                    "unlock": {"enabled": True},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    proc = _run_mst(workspace, "config", "resolve")

    assert proc.returncode == 0, proc.stderr

    resolved = json.loads((config_dir / "config.resolved.json").read_text(encoding="utf-8"))
    agile = resolved["agile"]

    assert resolved["workflow"]["auto_accept_result"] is False

    assert agile["evidence_gate"] == EXPECTED_AGILE_DEFAULTS["evidence_gate"]
    assert agile["drift"] == {
        **EXPECTED_AGILE_DEFAULTS["drift"],
        "enabled": True,
    }
    assert agile["recall"] == EXPECTED_AGILE_DEFAULTS["recall"]
    assert agile["unlock"] == {
        **EXPECTED_AGILE_DEFAULTS["unlock"],
        "enabled": True,
    }
