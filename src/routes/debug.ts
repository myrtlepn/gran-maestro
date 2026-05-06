import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import type { DebugMeta } from "../types.ts";
import { dirExists, listDirs, readJsonFile, readTextFile } from "../utils.ts";
import { resolveBaseDir } from "../config.ts";

const projectDebugApi = new Hono();

type WriterCoverageStatus =
  | "ok"
  | "not_applicable"
  | "not_seen"
  | "stale"
  | "identity_mismatch"
  | "write_failed"
  | "schema_invalid"
  | "unknown";

type WriterCoverageRow = {
  writer_id: string;
  expected: boolean;
  observed: boolean;
  status: WriterCoverageStatus;
  last_event_type: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_source_head: unknown;
  reason: string | null;
  evidence_path: string;
};

type WriterMatrixRow = {
  writer_id?: unknown;
  expected?: unknown;
  expected_events?: unknown;
  evidence_path?: unknown;
};

type CurrentWorkFreshnessStatus =
  | "fresh"
  | "stale"
  | "identity_mismatch"
  | "no_history"
  | "unknown";

type CurrentWorkNextActionType =
  | "continue_skill"
  | "resume_workflow"
  | "run_request"
  | "approve_request"
  | "accept_request"
  | "resume_agile_sprint"
  | "resolve_blocker"
  | "wait_for_user"
  | "no_action_available"
  | "unknown";

type CurrentWorkBlockerType =
  | "pending_dependency"
  | "failed_validation"
  | "missing_accept"
  | "protected_branch"
  | "stale_projection"
  | "identity_mismatch"
  | "policy_blocked"
  | "missing_source"
  | "schema_invalid"
  | "unknown";

const ALLOWED_WRITER_COVERAGE_STATUS: WriterCoverageStatus[] = [
  "ok",
  "not_applicable",
  "not_seen",
  "stale",
  "identity_mismatch",
  "write_failed",
  "schema_invalid",
  "unknown",
];

const WRITER_COVERAGE_ROW_FIELDS = [
  "writer_id",
  "expected",
  "observed",
  "status",
  "last_event_type",
  "last_success_at",
  "last_error_at",
  "last_source_head",
  "reason",
  "evidence_path",
] as const;

const DEFAULT_WRITER_MATRIX: WriterMatrixRow[] = [
  {
    writer_id: "cli_invocation",
    expected: true,
    expected_events: [
      "mst.invocation_start",
      "mst.invocation_end",
      "mst.invocation_error",
    ],
    evidence_path: ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
  },
  {
    writer_id: "state_writer",
    expected: true,
    expected_events: [
      "skill.enter",
      "skill.step",
      "skill.exit",
      "state.evidence",
    ],
    evidence_path: ".gran-maestro/state/{mst_session_id}/snapshot.json",
  },
  {
    writer_id: "dispatch_writer",
    expected: true,
    expected_events: ["dispatch.register", "dispatch.heartbeat"],
    evidence_path: ".gran-maestro/run/*",
  },
  {
    writer_id: "bash_history_writer",
    expected: true,
    expected_events: ["tool_call"],
    evidence_path: ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
  },
  {
    writer_id: "policy_writer",
    expected: true,
    expected_events: [
      "policy_block",
      "confirm_requested",
      "core_block",
      "override_granted",
    ],
    evidence_path: ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
  },
  {
    writer_id: "stop_continuation_writer",
    expected: true,
    expected_events: [
      "continue.*",
      "terminal.*",
      "action.*",
      "guard.*",
      "context.*",
    ],
    evidence_path:
      ".gran-maestro/sessions/{mst_session_id}/execution-flow.json",
  },
  {
    writer_id: "prompt_writer",
    expected: false,
    expected_events: ["prompt.submitted"],
    evidence_path: ".gran-maestro/requests/REQ-823/follow-up-dod004.md",
  },
  {
    writer_id: "hook_lifecycle_ledger",
    expected: true,
    expected_events: ["hook.*.start", "hook.*.complete"],
    evidence_path: ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
  },
];

const CURRENT_WORK_MAX_STACK_ITEMS = 20;
const CURRENT_WORK_FRESHNESS_STATUS: CurrentWorkFreshnessStatus[] = [
  "fresh",
  "stale",
  "identity_mismatch",
  "no_history",
  "unknown",
];
const CURRENT_WORK_NEXT_ACTION_TYPES: CurrentWorkNextActionType[] = [
  "continue_skill",
  "resume_workflow",
  "run_request",
  "approve_request",
  "accept_request",
  "resume_agile_sprint",
  "resolve_blocker",
  "wait_for_user",
  "no_action_available",
  "unknown",
];
const CURRENT_WORK_BLOCKER_TYPES: CurrentWorkBlockerType[] = [
  "pending_dependency",
  "failed_validation",
  "missing_accept",
  "protected_branch",
  "stale_projection",
  "identity_mismatch",
  "policy_blocked",
  "missing_source",
  "schema_invalid",
  "unknown",
];

// ─── API: Debug ────────────────────────────────────────────────────────────

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeSegment(value: unknown): string {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text || text.includes("/") || text.includes("..")) return "";
  return /^[A-Za-z0-9._-]+$/.test(text) ? text : "";
}

function safeRelativeJsonPath(value: unknown): string {
  const text = typeof value === "string" ? value.trim() : "";
  if (
    !text || text.startsWith("/") || text.includes("..") ||
    !text.endsWith(".json")
  ) {
    return "";
  }
  return text
      .split("/")
      .every((part) => part && /^[A-Za-z0-9._-]+$/.test(part))
    ? text
    : "";
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function eventType(event: Record<string, unknown> | null): string | null {
  if (!event) return null;
  return stringValue(event.event_type) ?? stringValue(event.type);
}

function sourceHead(event: Record<string, unknown> | null): unknown {
  if (!event) return null;
  return event.source_history_head ?? event.last_source_head ??
    event.history_head ?? null;
}

function eventCreatedAt(event: Record<string, unknown>): string | null {
  return stringValue(event.created_at) ?? stringValue(event.timestamp);
}

function writeStatus(event: Record<string, unknown>): string {
  return String(event.write_status ?? "success").trim().toLowerCase();
}

function schemaInvalid(event: Record<string, unknown>): boolean {
  return event.schema_version !== 1 || eventType(event) === null;
}

function eventTypeMatches(pattern: unknown, type: string | null): boolean {
  if (typeof pattern !== "string" || !type) return false;
  const trimmed = pattern.trim();
  if (!trimmed) return false;
  return trimmed.endsWith(".*")
    ? type.startsWith(trimmed.slice(0, -1))
    : trimmed === type;
}

function writerMatrix(context: Record<string, unknown>): WriterMatrixRow[] {
  const matrix = context.writer_matrix;
  if (Array.isArray(matrix)) {
    return matrix.filter((row): row is WriterMatrixRow =>
      isRecord(row) && typeof row.writer_id === "string" &&
      row.writer_id.trim().length > 0
    );
  }
  return DEFAULT_WRITER_MATRIX;
}

function observedEvents(
  context: Record<string, unknown>,
): Record<string, unknown>[] {
  const events = context.observed_events;
  if (!Array.isArray(events)) return [];
  return events.filter((event): event is Record<string, unknown> =>
    isRecord(event)
  );
}

function canonicalMstSessionId(context: Record<string, unknown>): string {
  const identity = isRecord(context.identity) ? context.identity : {};
  const env = isRecord(identity.env) ? identity.env : {};
  const structured = isRecord(identity.context) ? identity.context : {};
  return safeSegment(env.MST_SESSION_ID) ||
    safeSegment(structured.mst_session_id) ||
    safeSegment(context.canonical_mst_session_id) ||
    safeSegment(context.mst_session_id);
}

function legacyDiagnostics(
  context: Record<string, unknown>,
): Record<string, unknown> {
  const identity = isRecord(context.identity) ? context.identity : {};
  const diagnostics = isRecord(identity.legacy_diagnostics)
    ? { ...identity.legacy_diagnostics }
    : {};
  const env = isRecord(identity.env) ? identity.env : {};
  const structured = isRecord(identity.context) ? identity.context : {};

  const ownerPid = stringValue(env.MST_STATE_PPID);
  if (ownerPid) diagnostics.owner_pid ??= ownerPid;
  const hookSessionId = stringValue(structured.session_id);
  if (hookSessionId) diagnostics.hook_session_id ??= hookSessionId;
  const ownerSessionId = stringValue(structured.owner_session_id);
  if (ownerSessionId) diagnostics.owner_session_id ??= ownerSessionId;
  const transcriptPath = stringValue(structured.transcript_path);
  if (transcriptPath) {
    const name = transcriptPath.split("/").pop() ?? "";
    const stem = name.endsWith(".jsonl")
      ? name.slice(0, -6)
      : name.replace(/\.[^.]+$/, "");
    if (stem) diagnostics.hook_transcript_stem ??= stem;
  }
  return diagnostics;
}

function eventMatchesWriter(
  matrixRow: WriterMatrixRow,
  event: Record<string, unknown>,
  writerId: string,
): boolean {
  if (event.writer_id === writerId) return true;
  const expectedEvents = matrixRow.expected_events;
  if (!Array.isArray(expectedEvents)) return false;
  const type = eventType(event);
  return expectedEvents.some((pattern) => eventTypeMatches(pattern, type));
}

function evidencePath(
  matrixRow: WriterMatrixRow,
  event: Record<string, unknown> | null,
  mstSessionId: string,
): string {
  const fromEvent = event ? stringValue(event.evidence_path) : null;
  if (fromEvent) return fromEvent;
  const fromMatrix = stringValue(matrixRow.evidence_path);
  if (fromMatrix) {
    return fromMatrix.replaceAll("{mst_session_id}", mstSessionId);
  }
  return mstSessionId
    ? `.gran-maestro/sessions/${mstSessionId}/history.ndjson`
    : ".gran-maestro/sessions/history.ndjson";
}

function writerReason(
  status: WriterCoverageStatus,
  writerId: string,
  event: Record<string, unknown> | null,
  projectionSourceHead: unknown,
): string | null {
  if (status === "ok") return null;
  if (status === "not_applicable") {
    return writerId === "prompt_writer"
      ? "prompt writer is deferred to DOD-004 prompt correlation and not applicable for this session context"
      : "writer is not required for this session context";
  }
  if (status === "not_seen") {
    return "expected writer has no matching event in bounded projection context";
  }
  if (status === "stale") {
    return `writer source head does not match projection source_history_head: expected ${projectionSourceHead} observed ${
      sourceHead(event)
    }`;
  }
  if (status === "identity_mismatch") {
    return "observed writer event mst_session_id does not match canonical mst_session_id";
  }
  if (status === "write_failed") {
    return stringValue(event?.reason) ?? "writer reported write failure";
  }
  if (status === "schema_invalid") {
    return stringValue(event?.reason) ?? "writer event schema is invalid";
  }
  return "writer status could not be determined from bounded diagnostics";
}

function writerCoverageRow(
  matrixRow: WriterMatrixRow,
  events: Record<string, unknown>[],
  mstSessionId: string,
  projectionSourceHead: unknown,
): WriterCoverageRow {
  const writerId = stringValue(matrixRow.writer_id) ?? "unknown";
  const expected = typeof matrixRow.expected === "boolean"
    ? matrixRow.expected
    : true;
  const matches = events.filter((event) =>
    eventMatchesWriter(matrixRow, event, writerId)
  );
  const lastEvent = matches.at(-1) ?? null;
  const observed = matches.length > 0;
  const lastSourceHead = sourceHead(lastEvent);
  let lastSuccessAt: string | null = null;
  let lastErrorAt: string | null = null;

  for (const event of matches) {
    const status = writeStatus(event);
    if (["", "success", "ok", "written"].includes(status)) {
      lastSuccessAt = eventCreatedAt(event);
    }
    if (
      ["error", "failed", "failure", "write_failed"].includes(status) ||
      schemaInvalid(event)
    ) {
      lastErrorAt = eventCreatedAt(event);
    }
  }

  let status: WriterCoverageStatus;
  if (!expected && !observed) status = "not_applicable";
  else if (expected && !observed) status = "not_seen";
  else if (!lastEvent) status = "unknown";
  else if (schemaInvalid(lastEvent)) status = "schema_invalid";
  else if (
    ["error", "failed", "failure", "write_failed"].includes(
      writeStatus(lastEvent),
    )
  ) {
    status = "write_failed";
  } else if (safeSegment(lastEvent.mst_session_id) !== mstSessionId) {
    status = "identity_mismatch";
  } else if (
    projectionSourceHead !== null && lastSourceHead !== null &&
    lastSourceHead !== projectionSourceHead
  ) {
    status = "stale";
  } else if (["unknown", "indeterminate"].includes(writeStatus(lastEvent))) {
    status = "unknown";
  } else status = "ok";

  return {
    writer_id: writerId,
    expected,
    observed,
    status,
    last_event_type: eventType(lastEvent),
    last_success_at: lastSuccessAt,
    last_error_at: lastErrorAt,
    last_source_head: lastSourceHead,
    reason: writerReason(status, writerId, lastEvent, projectionSourceHead),
    evidence_path: evidencePath(matrixRow, lastEvent, mstSessionId),
  };
}

function summary(rows: WriterCoverageRow[]): Record<string, unknown> {
  const byStatus: Record<WriterCoverageStatus, number> = Object.fromEntries(
    ALLOWED_WRITER_COVERAGE_STATUS.map((status) => [status, 0]),
  ) as Record<WriterCoverageStatus, number>;
  for (const row of rows) byStatus[row.status] += 1;
  return {
    total: rows.length,
    ok: byStatus.ok,
    not_applicable: byStatus.not_applicable,
    non_ok: rows.length - byStatus.ok,
    by_status: byStatus,
  };
}

function projectWriterCoverage(
  context: Record<string, unknown>,
): Record<string, unknown> {
  const mstSessionId = canonicalMstSessionId(context);
  const projectionSourceHead = context.source_history_head ?? null;
  const rows = writerMatrix(context).map((matrixRow) =>
    writerCoverageRow(
      matrixRow,
      observedEvents(context),
      mstSessionId,
      projectionSourceHead,
    )
  );
  const generatedAt = stringValue(context.generated_at) ??
    new Date().toISOString();

  return {
    schema_version: 1,
    mst_session_id: mstSessionId,
    canonical_mst_session_id: mstSessionId,
    source_history_head: projectionSourceHead,
    generated_at: generatedAt,
    legacy_diagnostics: legacyDiagnostics(context),
    summary: summary(rows),
    writers: rows,
  };
}

function sanitizeWriterCoveragePayload(
  value: unknown,
): Record<string, unknown> | null {
  if (
    !isRecord(value) || !Array.isArray(value.writers) ||
    !isRecord(value.summary)
  ) return null;
  const writers = value.writers
    .filter((row): row is Record<string, unknown> => isRecord(row))
    .map((row) => {
      const result: Record<string, unknown> = {};
      for (const field of WRITER_COVERAGE_ROW_FIELDS) {
        result[field] = row[field];
      }
      return result;
    });

  return {
    summary: value.summary,
    writers,
    source_history_head: value.source_history_head ?? null,
    generated_at: stringValue(value.generated_at) ?? new Date().toISOString(),
    mst_session_id: stringValue(value.mst_session_id) ?? "",
    canonical_mst_session_id: stringValue(value.canonical_mst_session_id) ??
      stringValue(value.mst_session_id) ??
      "",
    legacy_diagnostics: isRecord(value.legacy_diagnostics)
      ? value.legacy_diagnostics
      : {},
  };
}

function currentWorkEvidencePath(value: unknown, mstSessionId: string): string {
  const text = stringValue(value);
  if (text?.startsWith(".gran-maestro/") && !text.includes("..")) {
    return text;
  }
  return `.gran-maestro/sessions/${mstSessionId || "unknown"}/history.head`;
}

function currentWorkIdentityMismatch(context: Record<string, unknown>): boolean {
  const identity = isRecord(context.identity) ? context.identity : {};
  const env = isRecord(identity.env) ? identity.env : {};
  const structured = isRecord(identity.context) ? identity.context : {};
  const envId = safeSegment(env.MST_SESSION_ID);
  const structuredId = safeSegment(structured.mst_session_id);
  return Boolean(envId && structuredId && envId !== structuredId);
}

function currentWorkFreshnessStatus(
  context: Record<string, unknown>,
): CurrentWorkFreshnessStatus {
  if (context.schema_version !== 1) return "unknown";
  if (currentWorkIdentityMismatch(context)) return "identity_mismatch";
  const source = stringValue(context.source_history_head);
  const current = stringValue(context.current_history_head);
  if (!source && !current) return "no_history";
  if (!source || !current) return "unknown";
  return source === current ? "fresh" : "stale";
}

function currentWorkStack(
  context: Record<string, unknown>,
  mstSessionId: string,
): Record<string, unknown> {
  const sources = Array.isArray(context.task_sources)
    ? context.task_sources.filter(isRecord)
    : [];
  const items = sources.slice(0, CURRENT_WORK_MAX_STACK_ITEMS).map((source) => ({
    kind: stringValue(source.kind) ?? "unknown",
    id: stringValue(source.id) ?? "unknown",
    title: stringValue(source.title) ?? "Untitled current work",
    status: stringValue(source.status) ?? "unknown",
    owner: stringValue(source.owner) ?? "unknown",
    phase: stringValue(source.phase) ?? "unknown",
    source: stringValue(source.source) ?? "unknown",
    evidence_path: currentWorkEvidencePath(source.evidence_path, mstSessionId),
  }));
  return {
    max_items: CURRENT_WORK_MAX_STACK_ITEMS,
    truncated: sources.length > CURRENT_WORK_MAX_STACK_ITEMS,
    total: sources.length,
    items,
  };
}

function currentWorkActiveWorkflow(
  context: Record<string, unknown>,
  mstSessionId: string,
): Record<string, unknown> | null {
  const workflow = isRecord(context.active_workflow)
    ? context.active_workflow
    : null;
  if (!workflow) return null;
  return {
    skill: stringValue(workflow.skill) ?? "unknown",
    source_id: stringValue(workflow.source_id) ?? "",
    auto: Boolean(workflow.auto),
    status: stringValue(workflow.status) ?? "unknown",
    evidence_path: currentWorkEvidencePath(workflow.evidence_path, mstSessionId),
  };
}

function currentWorkNextAction(
  context: Record<string, unknown>,
  mstSessionId: string,
): Record<string, unknown> {
  const raw = isRecord(context.next_action_source)
    ? context.next_action_source
    : isRecord(context.resume_queue)
    ? {
      action_type: "resume_workflow",
      label: `Resume ${stringValue(context.resume_queue.skill) ?? "workflow"}`,
      target: stringValue(context.resume_queue.source_id) ?? "",
      command_hint: `/${stringValue(context.resume_queue.skill) ?? ""} ${
        stringValue(context.resume_queue.args) ?? ""
      }`.trim(),
      reason: "resume queue contains the next bounded action",
      confidence: 0.7,
      evidence_path: context.resume_queue.evidence_path,
    }
    : {
      action_type: "no_action_available",
      label: "No current-work action available",
      target: "",
      command_hint: "",
      reason: "no next action source was present in bounded projection inputs",
      confidence: 0,
    };
  const actionType = CURRENT_WORK_NEXT_ACTION_TYPES.includes(
      stringValue(raw.action_type) as CurrentWorkNextActionType,
    )
    ? stringValue(raw.action_type)
    : "unknown";
  const confidence = typeof raw.confidence === "number" &&
      Number.isFinite(raw.confidence)
    ? Math.max(0, Math.min(1, raw.confidence))
    : 0;
  return {
    action_type: actionType,
    allowed_action_type: CURRENT_WORK_NEXT_ACTION_TYPES,
    label: stringValue(raw.label) ?? "Unknown next action",
    target: stringValue(raw.target) ?? "",
    command_hint: stringValue(raw.command_hint) ?? "",
    reason: stringValue(raw.reason) ??
      "next action was derived from bounded current-work sources",
    confidence,
    evidence_path: currentWorkEvidencePath(raw.evidence_path, mstSessionId),
  };
}

function currentWorkBlocker(
  source: Record<string, unknown>,
  mstSessionId: string,
): Record<string, unknown> {
  const blockerType = CURRENT_WORK_BLOCKER_TYPES.includes(
      stringValue(source.blocker_type) as CurrentWorkBlockerType,
    )
    ? stringValue(source.blocker_type)
    : "unknown";
  const nextActionType = CURRENT_WORK_NEXT_ACTION_TYPES.includes(
      stringValue(source.next_action_type) as CurrentWorkNextActionType,
    )
    ? stringValue(source.next_action_type)
    : "resolve_blocker";
  return {
    blocker_type: blockerType,
    status: stringValue(source.status) ?? "blocked",
    message: stringValue(source.message) ?? "current-work blocker",
    evidence_path: currentWorkEvidencePath(source.evidence_path, mstSessionId),
    recoverable: Boolean(source.recoverable),
    next_action_type: nextActionType,
  };
}

function currentWorkBlockers(
  context: Record<string, unknown>,
  mstSessionId: string,
  freshnessStatus: CurrentWorkFreshnessStatus,
  stack: Record<string, unknown>,
): Record<string, unknown>[] {
  const blockers = Array.isArray(context.blocker_sources)
    ? context.blocker_sources.filter(isRecord).map((source) =>
      currentWorkBlocker(source, mstSessionId)
    )
    : [];
  if (context.schema_version !== 1) {
    blockers.push(currentWorkBlocker({
      blocker_type: "schema_invalid",
      status: "blocked",
      message: "current-work handoff source schema_version is missing or unsupported",
      recoverable: false,
      next_action_type: "resolve_blocker",
      evidence_path: context.schema_evidence_path,
    }, mstSessionId));
  }
  if (freshnessStatus === "identity_mismatch") {
    blockers.push(currentWorkBlocker({
      blocker_type: "identity_mismatch",
      status: "blocked",
      message: "canonical MST_SESSION_ID and structured mst_session_id do not match",
      recoverable: true,
      next_action_type: "resolve_blocker",
      evidence_path: context.identity_evidence_path,
    }, mstSessionId));
  }
  if (freshnessStatus === "stale") {
    blockers.push(currentWorkBlocker({
      blocker_type: "stale_projection",
      status: "blocked",
      message: "current history head differs from projection source_history_head",
      recoverable: true,
      next_action_type: "resolve_blocker",
      evidence_path: context.history_head_evidence_path,
    }, mstSessionId));
  }
  if (!isRecord(context.active_workflow) && Number(stack.total ?? 0) === 0) {
    blockers.push(currentWorkBlocker({
      blocker_type: "missing_source",
      status: "blocked",
      message: "current-work handoff has no active workflow or task source",
      recoverable: true,
      next_action_type: "resume_workflow",
      evidence_path: context.source_evidence_path,
    }, mstSessionId));
  }
  const seen = new Set<string>();
  return blockers.filter((blocker) => {
    const key = `${blocker.blocker_type}\0${blocker.message}\0${blocker.evidence_path}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function currentWorkEvidencePaths(...sections: unknown[]): string[] {
  const paths: string[] = [];
  const collect = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value) collect(item);
      return;
    }
    if (!isRecord(value)) return;
    const path = stringValue(value.evidence_path);
    if (path?.startsWith(".gran-maestro/") && !paths.includes(path)) {
      paths.push(path);
    }
    for (const child of Object.values(value)) collect(child);
  };
  for (const section of sections) collect(section);
  return paths;
}

function projectCurrentWorkHandoff(
  context: Record<string, unknown>,
): Record<string, unknown> {
  const mstSessionId = canonicalMstSessionId(context);
  const generatedAt = stringValue(context.generated_at) ??
    new Date().toISOString();
  const stack = currentWorkStack(context, mstSessionId);
  const workflow = currentWorkActiveWorkflow(context, mstSessionId);
  const action = currentWorkNextAction(context, mstSessionId);
  const freshnessStatus = currentWorkFreshnessStatus(context);
  const freshness = {
    status: freshnessStatus,
    allowed_status: CURRENT_WORK_FRESHNESS_STATUS,
    source_history_head: stringValue(context.source_history_head),
    current_history_head: stringValue(context.current_history_head),
    generated_at: generatedAt,
    evidence_path: currentWorkEvidencePath(
      context.history_head_evidence_path,
      mstSessionId,
    ),
  };
  const blockers = currentWorkBlockers(
    context,
    mstSessionId,
    freshnessStatus,
    stack,
  );
  const evidencePaths = currentWorkEvidencePaths(
    workflow,
    stack,
    action,
    blockers,
    freshness,
  );
  return {
    schema_version: 1,
    mst_session_id: mstSessionId,
    canonical_mst_session_id: mstSessionId,
    lookup_key: mstSessionId,
    partition_key: mstSessionId,
    recovery_selector: mstSessionId,
    source_history_head: stringValue(context.source_history_head),
    generated_at: generatedAt,
    projection_freshness: freshness,
    active_workflow: workflow,
    current_task_stack: stack,
    next_action: action,
    blockers,
    legacy_diagnostics: legacyDiagnostics(context),
    evidence_paths: evidencePaths.length
      ? evidencePaths
      : [currentWorkEvidencePath(null, mstSessionId)],
  };
}

function sanitizeCurrentWorkHandoffPayload(
  value: unknown,
): Record<string, unknown> | null {
  if (!isRecord(value) || value.schema_version !== 1) return null;
  const payload = projectCurrentWorkHandoff(value);
  return {
    ...payload,
    projection_freshness: isRecord(value.projection_freshness)
      ? value.projection_freshness
      : payload.projection_freshness,
    active_workflow: isRecord(value.active_workflow)
      ? currentWorkActiveWorkflow(value, String(payload.mst_session_id ?? ""))
      : null,
    current_task_stack: isRecord(value.current_task_stack)
      ? value.current_task_stack
      : payload.current_task_stack,
    next_action: isRecord(value.next_action) ? value.next_action : payload.next_action,
    blockers: Array.isArray(value.blockers)
      ? value.blockers.filter(isRecord).map((blocker) =>
        currentWorkBlocker(blocker, String(payload.mst_session_id ?? ""))
      )
      : payload.blockers,
    evidence_paths: Array.isArray(value.evidence_paths)
      ? value.evidence_paths.filter((path): path is string =>
        typeof path === "string" && path.startsWith(".gran-maestro/")
      )
      : payload.evidence_paths,
  };
}

async function readCurrentWorkContext(
  baseDir: string,
  sessionId: string,
  relativePath: string,
): Promise<Record<string, unknown>> {
  const candidates = [
    relativePath ? `${baseDir}/${relativePath}` : "",
    sessionId
      ? `${baseDir}/sessions/${sessionId}/current-work-handoff-context.json`
      : "",
    sessionId ? `${baseDir}/sessions/${sessionId}/current-work-handoff.json` : "",
    `${baseDir}/debug/current-work-handoff-context.json`,
    `${baseDir}/debug/current-work-handoff.json`,
  ].filter(Boolean);
  for (const path of candidates) {
    const payload = await readJsonFile<unknown>(path);
    if (isRecord(payload)) return payload;
  }
  return {};
}

async function readWriterCoverageContext(
  baseDir: string,
  sessionId: string,
  relativePath: string,
): Promise<Record<string, unknown>> {
  const candidates = [
    relativePath ? `${baseDir}/${relativePath}` : "",
    sessionId
      ? `${baseDir}/sessions/${sessionId}/writer-coverage-context.json`
      : "",
    sessionId ? `${baseDir}/sessions/${sessionId}/writer-coverage.json` : "",
    `${baseDir}/debug/writer-coverage-context.json`,
    `${baseDir}/debug/writer-coverage.json`,
  ].filter(Boolean);

  for (const path of candidates) {
    const payload = await readJsonFile<unknown>(path);
    if (isRecord(payload)) return payload;
  }
  return {};
}

projectDebugApi.get("/debug", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const debugDir = `${baseDir}/debug`;
  if (!(await dirExists(debugDir))) {
    return c.json([]);
  }

  const sessions: DebugMeta[] = [];
  const debugDirs = (await listDirs(debugDir)).filter((dir) => /^DBG-/.test(dir));
  for (const dir of debugDirs) {
    const sessionJsonPath = `${debugDir}/${dir}/session.json`;
    const sessionJson = await readJsonFile<DebugMeta>(sessionJsonPath);
    if (sessionJson) {
      let createdAt = sessionJson.created_at;
      if (!createdAt || createdAt.includes("T00:00:00")) {
        try {
          const stat = await Deno.stat(sessionJsonPath);
          if (stat.mtime) {
            createdAt = stat.mtime.toISOString();
          }
        } catch (_error) {
          // ignore fallback failure
        }
      }
      sessions.push({ ...sessionJson, id: sessionJson.id || dir, created_at: createdAt });
    }
  }
  sessions.sort((a, b) => {
    const aTime = a.created_at ?? "";
    const bTime = b.created_at ?? "";
    return bTime.localeCompare(aTime);
  });

  return c.json(sessions);
});

projectDebugApi.get("/debug/writer-coverage", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const sessionId = safeSegment(c.req.query("session"));
  const sourceHistoryHead = stringValue(c.req.query("source_head"));
  const relativeContextPath = safeRelativeJsonPath(c.req.query("context"));
  if (c.req.query("context") && !relativeContextPath) {
    return c.json({ error: "Invalid context path" }, 400);
  }

  const context = await readWriterCoverageContext(
    baseDir,
    sessionId,
    relativeContextPath,
  );
  const boundedPayload = sanitizeWriterCoveragePayload(context) ??
    projectWriterCoverage({
      ...context,
      mst_session_id: context.mst_session_id ?? sessionId,
      canonical_mst_session_id: context.canonical_mst_session_id ?? sessionId,
      source_history_head: context.source_history_head ?? sourceHistoryHead ??
        null,
    });

  return c.json(boundedPayload);
});

projectDebugApi.get("/debug/current-work-handoff", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const sessionId = safeSegment(c.req.query("session"));
  const sourceHistoryHead = stringValue(c.req.query("source_head"));
  const currentHistoryHead = stringValue(c.req.query("current_head")) ??
    sourceHistoryHead;
  const relativeContextPath = safeRelativeJsonPath(c.req.query("context"));
  if (c.req.query("context") && !relativeContextPath) {
    return c.json({ error: "Invalid context path" }, 400);
  }

  const context = await readCurrentWorkContext(
    baseDir,
    sessionId,
    relativeContextPath,
  );
  const boundedPayload = sanitizeCurrentWorkHandoffPayload(context) ??
    projectCurrentWorkHandoff({
      ...context,
      schema_version: context.schema_version ?? 1,
      mst_session_id: context.mst_session_id ?? sessionId,
      canonical_mst_session_id: context.canonical_mst_session_id ?? sessionId,
      source_history_head: context.source_history_head ?? sourceHistoryHead ??
        null,
      current_history_head: context.current_history_head ?? currentHistoryHead ??
        null,
    });

  return c.json(boundedPayload);
});

projectDebugApi.get("/debug/:debugId", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const debugId = c.req.param("debugId");
  const sessionDir = `${baseDir}/debug/${debugId}`;
  if (!(await dirExists(sessionDir))) {
    return c.json({ error: "Debug session not found" }, 404);
  }

  const sessionJson = await readJsonFile<DebugMeta>(`${sessionDir}/session.json`);
  if (!sessionJson) {
    return c.json({ error: "Debug session not found" }, 404);
  }
  const content = await readTextFile(`${sessionDir}/debug-report.md`);
  return c.json({ ...sessionJson, id: sessionJson.id || debugId, content: content ?? null });
});

export { projectDebugApi };
