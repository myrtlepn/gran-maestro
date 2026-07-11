from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.mst_cmds import config as config_mod
from scripts.mst_cmds.native_delegation import plan_delegation_route


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("capability_status", ["available", "unknown"])
def test_same_host_enabled_scope_is_native_candidate(provider: str, capability_status: str) -> None:
    route = plan_delegation_route(
        host=provider,
        provider=provider,
        transport_policy="same-host-native-first",
        scope="implementation",
        native_enabled=True,
        configured_scope="all",
        capability_status=capability_status,
        external_adapter_available=False,
    )

    assert route["route"] == "native_candidate"
    assert route["execution_transport"] == "native"
    assert route["capability_status"] == capability_status
    assert route["handshake_required"] is (capability_status == "unknown")
    assert route["required_capability"] == "native_agent_delegation"


@pytest.mark.parametrize(
    ("host", "provider", "policy", "configured_scope", "capability", "reason"),
    [
        ("codex", "claude", "same-host-native-first", "all", "available", "cross_provider"),
        ("headless", "codex", "same-host-native-first", "all", "available", "headless_host"),
        ("codex", "codex", "external-only", "all", "available", "policy_disabled"),
        ("codex", "codex", "same-host-native-first", "review-only", "available", "scope_disabled"),
        ("codex", "codex", "same-host-native-first", "all", "unavailable", "capability_unavailable"),
    ],
)
def test_non_native_routes_use_available_external_adapter(
    host: str,
    provider: str,
    policy: str,
    configured_scope: str,
    capability: str,
    reason: str,
) -> None:
    route = plan_delegation_route(
        host=host,
        provider=provider,
        transport_policy=policy,
        scope="implementation",
        native_enabled=True,
        configured_scope=configured_scope,
        capability_status=capability,
        external_adapter_available=True,
    )

    assert route["route"] == "external"
    assert route["execution_transport"] == "external"
    assert route["reason_code"] == reason
    assert route["external_adapter"]["available"] is True


def test_route_is_blocked_only_when_external_adapter_is_missing() -> None:
    route = plan_delegation_route(
        host="headless",
        provider="claude",
        transport_policy="same-host-native-first",
        scope="implementation",
        native_enabled=True,
        configured_scope="all",
        capability_status="unavailable",
        external_adapter_available=False,
    )

    assert route["route"] == "blocked"
    assert route["reason_code"] == "missing_cli"
    assert route["route_cause"] == "headless_host"


def test_legacy_opt_out_migrates_and_migration_is_idempotent() -> None:
    defaults = {
        "delegation": {
            "transport_policy": "same-host-native-first",
            "native": {"enabled": True, "scope": "all"},
        }
    }
    legacy = {
        "delegation": {
            "native_codex_subagents": {
                "enabled": False,
                "scope": "review-and-exploration-only",
            }
        }
    }

    migrated, warnings = config_mod._migrate_config(legacy, defaults)
    migrated_twice, warnings_twice = config_mod._migrate_config(copy.deepcopy(migrated), defaults)

    assert migrated["delegation"]["transport_policy"] == "external-only"
    assert migrated["delegation"]["native"] == {
        "enabled": False,
        "scope": "review-and-exploration-only",
    }
    assert "native_codex_subagents" not in migrated["delegation"]
    assert migrated_twice == migrated
    assert warnings_twice == []
    assert any("native_codex_subagents" in warning for warning in warnings)


def test_explicit_canonical_policy_wins_over_conflicting_legacy_opt_out() -> None:
    defaults = {
        "delegation": {
            "transport_policy": "same-host-native-first",
            "native": {"enabled": True, "scope": "all"},
        }
    }
    overrides = {
        "delegation": {
            "transport_policy": "same-host-native-first",
            "native": {"enabled": True, "scope": "all"},
            "native_codex_subagents": {"enabled": False},
        }
    }

    migrated, warnings = config_mod._migrate_config(overrides, defaults)

    assert migrated["delegation"]["transport_policy"] == "same-host-native-first"
    assert migrated["delegation"]["native"]["enabled"] is True
    assert "native_codex_subagents" not in migrated["delegation"]
    assert any("canonical" in warning and "conflict" in warning for warning in warnings)


def test_route_cli_honors_project_local_legacy_opt_out_after_resolve(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    (base / "config.json").write_text(
        json.dumps(
            {
                "delegation": {
                    "native_codex_subagents": {
                        "enabled": False,
                        "scope": "review-and-exploration-only",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    resolved = subprocess.run(
        [sys.executable, str(MST_SCRIPT), "config", "resolve"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resolved.returncode == 0, resolved.stderr

    routed = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "delegation",
            "route",
            "--host",
            "codex",
            "--provider",
            "codex",
            "--external-available",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert routed.returncode == 0, routed.stderr
    payload = json.loads(routed.stdout)
    assert payload["route"] == "external"
    assert payload["transport_policy"] == "external-only"
    assert payload["native_enabled"] is False
    assert payload["config_provenance"].endswith("config.resolved.json")


def test_capability_cli_uses_same_config_aware_external_only_route(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    (base / "config.resolved.json").write_text(
        json.dumps(
            {
                "delegation": {
                    "transport_policy": "external-only",
                    "native": {"enabled": False, "scope": "all"},
                }
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "delegation",
            "capability",
            "--host",
            "codex",
            "--provider",
            "codex",
            "--capability-status",
            "available",
            "--external-available",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["route"] == "external"
    assert payload["transport_policy"] == "external-only"
    assert payload["native_enabled"] is False
    assert payload["route_fingerprint"].startswith("sha256:")
