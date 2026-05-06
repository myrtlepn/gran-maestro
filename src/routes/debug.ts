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
