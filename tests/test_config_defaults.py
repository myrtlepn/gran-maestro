import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_PATH = REPO_ROOT / "templates" / "defaults" / "config.json"
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"

EXPECTED_AGILE_DEFAULTS = {
    "evidence_gate": {
        "enabled": False,
        "required_globs": [],
    },
    "drift": {
        "enabled": False,
        "threshold": 0.7,
        "warn_streak_limit": 2,
    },
    "recall": {
        "enabled": False,
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
        "enabled": False,
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
