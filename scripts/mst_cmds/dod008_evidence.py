from __future__ import annotations

import hashlib
import json
from typing import Any


SCHEMA_VERSION = 1
HASH_LENGTH = 64
ZERO_HISTORY_HASH = "0" * 64
DEFAULT_EVIDENCE_PATH = ".gran-maestro/sessions/{mst_session_id}/history.verify"


class _HashableDict(dict):
    __hash__ = object.__hash__


class _HashableList(list):
    __hash__ = object.__hash__


def _hashable_json(value: Any) -> Any:
    if isinstance(value, dict):
        return _HashableDict((key, _hashable_json(child)) for key, child in value.items())
    if isinstance(value, list):
        return _HashableList(_hashable_json(child) for child in value)
    return value


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _safe_session_id(value: Any) -> str:
    text = _text(value)
    if not text or "/" in text or ".." in text:
        return ""
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
    return text if all(char in allowed for char in text) else ""


def _hash(value: Any) -> str:
    text = _text(value)
    return text if len(text) == HASH_LENGTH else ""


def _evidence_path(value: Any, mst_session_id: str = "") -> str:
    text = _text(value)
    if text.startswith(".gran-maestro/") and ".." not in text:
        return text
    return DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown")


def _canonical_history_event(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _history_event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical_history_event(event)).encode("utf-8")).hexdigest()


def canonical_selector(context: dict[str, Any]) -> str:
    identity = context.get("identity") if isinstance(context.get("identity"), dict) else {}
    env = identity.get("env") if isinstance(identity.get("env"), dict) else {}
    structured = identity.get("context") if isinstance(identity.get("context"), dict) else {}
    return (
        _safe_session_id(env.get("MST_SESSION_ID"))
        or _safe_session_id(structured.get("mst_session_id"))
        or _safe_session_id(context.get("canonical_mst_session_id"))
        or _safe_session_id(context.get("mst_session_id"))
    )


def _identity_boundary(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    identity = context.get("identity") if isinstance(context.get("identity"), dict) else {}
    env = identity.get("env") if isinstance(identity.get("env"), dict) else {}
    structured = identity.get("context") if isinstance(identity.get("context"), dict) else {}
    env_sid = _safe_session_id(env.get("MST_SESSION_ID"))
    structured_sid = _safe_session_id(structured.get("mst_session_id"))
    evidence_path = f".gran-maestro/sessions/{mst_session_id or 'unknown'}/identity.json"
    if env_sid and structured_sid and env_sid != structured_sid:
        return {
            "status": "fail",
            "code": "canonical_mst_session_id_mismatch",
            "reason": "canonical MST_SESSION_ID and structured mst_session_id do not match",
            "evidence_path": evidence_path,
        }
    if not (env_sid or structured_sid or _safe_session_id(context.get("canonical_mst_session_id")) or _safe_session_id(context.get("mst_session_id"))):
        return {
            "status": "unknown",
            "code": "canonical_mst_session_id_missing",
            "reason": "canonical mst_session_id was not available",
            "evidence_path": evidence_path,
        }
    return {
        "status": "pass",
        "code": "canonical_identity_valid",
        "reason": "canonical mst_session_id is available and diagnostic IDs were not used as selectors",
        "evidence_path": evidence_path,
    }


def _row_event_hash(row: dict[str, Any], fallback: str = "") -> str:
    return _hash(row.get("event_hash")) or fallback


def _result(
    status: str,
    code: str,
    reason: str,
    *,
    evidence_path: Any = None,
    event_hash: Any = None,
    mst_session_id: str = "",
    **details: Any,
) -> dict[str, Any]:
    result = {
        "status": status,
        "code": code,
        "reason": reason,
    }
    bounded_hash = _hash(event_hash)
    if bounded_hash:
        result["event_hash"] = bounded_hash
    else:
        result["evidence_path"] = _evidence_path(evidence_path, mst_session_id)
    for key, value in details.items():
        if value is not None:
            result[key] = value
    return result


def _legacy_snapshot_only(context: dict[str, Any]) -> bool:
    snapshot = context.get("snapshot")
    if not isinstance(snapshot, dict):
        return False
    return snapshot.get("schema_version") != 1 or "mst_session_id" not in snapshot or "workflow" not in snapshot


def _linkage_event_hash(context: dict[str, Any], ledger: dict[str, Any], verified_head: str) -> str:
    linkage = context.get("history_linkage") if isinstance(context.get("history_linkage"), dict) else {}
    return _hash(linkage.get("event_hash")) or _hash(ledger.get("event_hash")) or verified_head


def _verify_rows(rows: list[dict[str, Any]], evidence_path: str, mst_session_id: str) -> tuple[dict[str, Any] | None, int, str]:
    expected_seq = 1
    expected_prev = ZERO_HISTORY_HASH
    for row in rows:
        if row.get("seq") != expected_seq:
            return (
                _result(
                    "fail",
                    "history_hash_chain_broken",
                    "corrupt history ledger sequence does not match deterministic order",
                    evidence_path=evidence_path,
                    event_hash=_row_event_hash(row),
                    mst_session_id=mst_session_id,
                ),
                expected_seq - 1,
                expected_prev,
            )
        if row.get("prev_hash") != expected_prev:
            return (
                _result(
                    "fail",
                    "history_prev_hash_mismatch",
                    "corrupt history ledger prev_hash does not match the previous event hash",
                    evidence_path=evidence_path,
                    event_hash=_row_event_hash(row),
                    mst_session_id=mst_session_id,
                ),
                expected_seq - 1,
                expected_prev,
            )
        event = row.get("event")
        if not isinstance(event, dict):
            return (
                _result(
                    "fail",
                    "history_hash_chain_broken",
                    "corrupt history ledger row is missing a bounded event object",
                    evidence_path=evidence_path,
                    event_hash=_row_event_hash(row),
                    mst_session_id=mst_session_id,
                ),
                expected_seq - 1,
                expected_prev,
            )
        computed = _history_event_hash(expected_prev, event)
        if row.get("event_hash") != computed:
            return (
                _result(
                    "fail",
                    "history_event_hash_mismatch",
                    "corrupt history ledger event_hash does not match deterministic recomputation",
                    evidence_path=evidence_path,
                    event_hash=_row_event_hash(row, computed),
                    mst_session_id=mst_session_id,
                ),
                expected_seq - 1,
                expected_prev,
            )
        expected_prev = computed
        expected_seq += 1
    return None, expected_seq - 1, expected_prev


def _history_integrity(context: dict[str, Any], mst_session_id: str) -> tuple[dict[str, Any], str]:
    ledger = context.get("history_ledger") if isinstance(context.get("history_ledger"), dict) else None
    if ledger is None:
        code = "legacy_snapshot_only" if _legacy_snapshot_only(context) else "history_ledger_missing"
        reason = "legacy snapshot-only evidence is insufficient for hash-chain verification" if code == "legacy_snapshot_only" else "history ledger evidence is missing"
        result = _result(
            "unknown",
            code,
            reason,
            evidence_path=context.get("history_head_evidence_path"),
            mst_session_id=mst_session_id,
        )
        return result, _hash(context.get("verified_history_head") or context.get("current_verified_head")) or ZERO_HISTORY_HASH

    evidence_path = _evidence_path(ledger.get("evidence_path") or ledger.get("ledger_path"), mst_session_id)
    rows = ledger.get("rows")
    if not isinstance(rows, list) or not rows:
        result = _result(
            "unknown",
            "history_ledger_missing",
            "history ledger rows are missing",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
        return result, _hash(ledger.get("verified_ledger_head") or context.get("verified_history_head")) or ZERO_HISTORY_HASH

    safe_rows = [row for row in rows if isinstance(row, dict)]
    failure, seq, tail_head = _verify_rows(safe_rows, evidence_path, mst_session_id)
    verified_head = _hash(ledger.get("verified_ledger_head")) or tail_head
    if failure is not None:
        failure["verified_history_head"] = verified_head
        return failure, verified_head

    for key, code in (
        ("sidecar_head", "history_sidecar_missing"),
        ("verify_head", "history_verify_missing"),
    ):
        if ledger.get(key) is None:
            result = _result(
                "unknown",
                code,
                f"{key} evidence is missing",
                evidence_path=evidence_path,
                mst_session_id=mst_session_id,
                verified_history_head=verified_head,
            )
            return result, verified_head

    for key, code in (
        ("mirror_head", "history_mirror_missing"),
        ("policy_mirror_head", "history_policy_mirror_missing"),
    ):
        if key in ledger and ledger.get(key) is None:
            result = _result(
                "unknown",
                code,
                f"{key} evidence is missing",
                evidence_path=evidence_path,
                mst_session_id=mst_session_id,
                verified_history_head=verified_head,
            )
            return result, verified_head

    if verified_head != tail_head:
        result = _result(
            "mismatch",
            "history_verified_head_mismatch",
            "verified ledger head does not match deterministic ledger tail",
            evidence_path=evidence_path,
            event_hash=_linkage_event_hash(context, ledger, verified_head),
            mst_session_id=mst_session_id,
            verified_history_head=verified_head,
            verified_seq=seq,
        )
        return result, verified_head

    for key, code in (
        ("sidecar_head", "history_sidecar_head_mismatch"),
        ("mirror_head", "history_mirror_head_mismatch"),
        ("policy_mirror_head", "history_policy_mirror_head_mismatch"),
        ("verify_head", "history_verify_head_mismatch"),
    ):
        head = _hash(ledger.get(key))
        if head and head != verified_head:
            result = _result(
                "mismatch",
                code,
                f"{key} does not match verified ledger head",
                evidence_path=evidence_path,
                event_hash=_linkage_event_hash(context, ledger, verified_head),
                mst_session_id=mst_session_id,
                verified_history_head=verified_head,
                verified_seq=seq,
            )
            return result, verified_head

    result = _result(
        "pass",
        "history_integrity_valid",
        "history ledger hash-chain and head mirrors match",
        evidence_path=evidence_path,
        event_hash=_linkage_event_hash(context, ledger, verified_head),
        mst_session_id=mst_session_id,
        verified_history_head=verified_head,
        verified_seq=seq,
    )
    return result, verified_head


def _head_from_context(context: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in context:
            return _hash(context.get(key))
    return ""


def _projection_freshness(
    context: dict[str, Any],
    mst_session_id: str,
    generated_at: str,
    verified_head: str,
) -> dict[str, Any]:
    projection = context.get("execution_flow_projection") if isinstance(context.get("execution_flow_projection"), dict) else {}
    source_head = _head_from_context(context, "source_history_head")
    if not source_head and "source_history_head" not in context:
        source_head = _hash(projection.get("source_history_head"))
    current_head = (
        _head_from_context(context, "current_verified_head", "verified_history_head", "current_history_head")
        or verified_head
        or _hash(projection.get("current_verified_head"))
    )
    evidence_path = projection.get("evidence_path") or context.get("history_head_evidence_path")
    if not _text(generated_at) or generated_at == "unknown":
        return _result(
            "unknown",
            "projection_generated_at_missing",
            "projection generated_at is missing",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
            source_history_head=source_head or None,
            current_history_head=current_head or None,
            basis="verified_ledger_head",
        )
    if not source_head:
        return _result(
            "unknown",
            "projection_source_history_head_missing",
            "projection source_history_head is missing",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
            source_history_head=None,
            current_history_head=current_head or None,
            basis="verified_ledger_head",
        )
    if not current_head:
        return _result(
            "unknown",
            "projection_current_history_head_missing",
            "current verified history head is missing",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
            source_history_head=source_head,
            current_history_head=None,
            basis="verified_ledger_head",
        )
    if source_head == current_head:
        return _result(
            "fresh",
            "projection_fresh",
            "projection source_history_head matches current verified history head",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
            source_history_head=source_head,
            current_history_head=current_head,
            generated_at=generated_at,
            basis="verified_ledger_head",
        )
    return _result(
        "stale",
        "projection_stale",
        "projection source_history_head differs from current verified history head",
        evidence_path=evidence_path,
        mst_session_id=mst_session_id,
        source_history_head=source_head,
        current_history_head=current_head,
        generated_at=generated_at,
        basis="verified_ledger_head",
    )


def _collect_evidence_paths(*values: Any, mst_session_id: str) -> list[str]:
    paths: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            path = value.get("evidence_path")
            if isinstance(path, str) and path.startswith(".gran-maestro/") and ".." not in path and path not in paths:
                paths.append(path)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for value in values:
        collect(value)
    if not paths:
        paths.append(DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown"))
    return paths


def project_dod008_evidence(
    fixture_or_context: Any,
    *,
    mst_session_id: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    context = fixture_or_context if isinstance(fixture_or_context, dict) else {}
    canonical_id = mst_session_id or canonical_selector(context)
    source_generated_at = _text(generated_at) if generated_at is not None else _text(context.get("generated_at"))
    if not source_generated_at:
        source_generated_at = "unknown"
    integrity, verified_head = _history_integrity(context, canonical_id)
    freshness = _projection_freshness(context, canonical_id, source_generated_at, verified_head)
    identity = _identity_boundary(context, canonical_id)
    source_head = freshness.get("source_history_head")
    current_head = freshness.get("current_history_head") or verified_head
    detail = {
        "schema_version": SCHEMA_VERSION,
        "panel_id": "integrity_freshness",
        "source_projection": "DOD-008",
        "history_integrity": integrity,
        "projection_freshness": freshness,
        "identity_boundary": identity,
        "source_history_head": source_head,
        "current_history_head": current_head,
        "verified_history_head": verified_head,
        "generated_at": source_generated_at,
    }
    detail["evidence_paths"] = _collect_evidence_paths(integrity, freshness, identity, mst_session_id=canonical_id)
    return _hashable_json(detail)


def axis_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    result = {
        "source_projection": "DOD-008",
        "source_history_head": evidence.get("source_history_head"),
        "current_history_head": evidence.get("current_history_head"),
        "verified_history_head": evidence.get("verified_history_head"),
    }
    integrity = evidence.get("history_integrity") if isinstance(evidence.get("history_integrity"), dict) else {}
    freshness = evidence.get("projection_freshness") if isinstance(evidence.get("projection_freshness"), dict) else {}
    event_hash = _hash(integrity.get("event_hash"))
    if event_hash:
        result["event_hash"] = event_hash
    else:
        result["evidence_path"] = _evidence_path(freshness.get("evidence_path") or integrity.get("evidence_path"))
    return result
