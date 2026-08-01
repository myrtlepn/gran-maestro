import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { resolveBaseDir } from "../config.ts";
import { dirExists, readJsonFile } from "../utils.ts";

const DEFAULT_STALE_THRESHOLD_SEC = 60;
const POLL_INTERVAL_MS = 1_000;
const KEEPALIVE_INTERVAL_MS = 30_000;
const UNKNOWN_AGE_SEC = 10 ** 9;
const TERMINAL_PHASES = new Set(["done", "terminated", "failed"]);
const TERMINAL_STATUSES = new Set([
  "completed",
  "fallback_completed",
  "failed",
  "empty_result",
  "missing_result",
  "unchanged_result",
  "preexisting_result",
  "missing_output_baseline",
  "cancelled",
  "canceled",
  "blocked",
]);
const DEFAULT_HISTORY_LIMIT = 50;
const MAX_HISTORY_LIMIT = 200;

export type DispatchQueryMode = "active" | "history" | "all";

type DispatchStateFile = {
  task_id?: unknown;
  attempt_id?: unknown;
  phase?: unknown;
  status?: unknown;
  provider?: unknown;
  model?: unknown;
  last_heartbeat?: unknown;
  execution_transport?: unknown;
  requested_launch_surface?: unknown;
  launch_surface?: unknown;
  launch_surface_status?: unknown;
  orca_launch_status?: unknown;
  route_reason?: unknown;
  provider_task_id?: unknown;
  completion_signal?: unknown;
  exit_code?: unknown;
  fallback_from?: unknown;
  fallback_to?: unknown;
  provider_reconciliation_required?: unknown;
  reconciliation_action?: unknown;
  mst_session_id?: unknown;
  root_mst_id?: unknown;
  parent_session_id?: unknown;
  running_log_path?: unknown;
  trace_path?: unknown;
  output_path?: unknown;
  updated_at?: unknown;
  terminated_at?: unknown;
};

export type DispatchStreamItem = {
  task_id: string;
  attempt_id: string;
  phase: string;
  provider: string;
  model: string;
  execution_transport: string;
  requested_launch_surface: string;
  launch_surface: string;
  launch_surface_status: string;
  orca_launch_status: string | null;
  route_reason: string;
  provider_task_id: string | null;
  completion_signal: string | null;
  exit_code: number | null;
  fallback_from: string | null;
  fallback_to: string | null;
  provider_reconciliation_required: boolean;
  reconciliation_required: boolean;
  reconciliation_invariant_gap: boolean;
  reconciliation_action: Record<string, unknown> | null;
  mst_session_id: string | null;
  root_mst_id: string | null;
  parent_session_id: string | null;
  running_log_path: string | null;
  trace_path: string | null;
  output_path: string | null;
  terminal: boolean;
  heartbeat_age_sec: number;
  stale: boolean;
};

type DispatchSnapshotEvent = {
  event: "snapshot";
  items: DispatchStreamItem[];
  stale_threshold_sec: number;
  mode: DispatchQueryMode;
  limit: number | null;
  as_of: string;
};

export type DispatchSnapshotOptions = {
  mode?: DispatchQueryMode;
  limit?: number;
};

function asString(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.trim().length > 0) {
    return value;
  }
  return fallback;
}

function asNullableString(value: unknown): string | null {
  if (typeof value === "string" && value.trim().length > 0) {
    return value;
  }
  return null;
}

function asNullableNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function normalizedLower(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function heartbeatAgeSeconds(lastHeartbeat: unknown, nowMs: number): number {
  if (typeof lastHeartbeat !== "string" || lastHeartbeat.trim().length === 0) {
    return UNKNOWN_AGE_SEC;
  }

  const parsedMs = Date.parse(lastHeartbeat);
  if (!Number.isFinite(parsedMs)) {
    return UNKNOWN_AGE_SEC;
  }

  const ageSec = Math.floor((nowMs - parsedMs) / 1_000);
  return ageSec < 0 ? 0 : ageSec;
}

function parseStaleThreshold(raw: string | undefined): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_STALE_THRESHOLD_SEC;
  }
  return parsed;
}

function parseHistoryLimit(raw: string | undefined): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_HISTORY_LIMIT;
  }
  return Math.min(parsed, MAX_HISTORY_LIMIT);
}

function parseDispatchMode(
  rawMode: string | undefined,
  rawIncludeTerminal: string | undefined,
): DispatchQueryMode {
  const mode = (rawMode ?? "").trim().toLowerCase();
  if (mode === "history") return "history";
  if (mode === "all") return "all";
  if ((rawIncludeTerminal ?? "").trim().toLowerCase() === "true") {
    return "all";
  }
  return "active";
}

export async function collectDispatchSnapshot(
  baseDir: string,
  staleThresholdSec: number,
  options: DispatchSnapshotOptions = {},
): Promise<DispatchStreamItem[]> {
  const runDir = `${baseDir}/run`;
  if (!(await dirExists(runDir))) {
    return [];
  }

  const nowMs = Date.now();
  const mode = options.mode ?? "active";
  const limit = Math.max(
    1,
    Math.min(options.limit ?? DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT),
  );
  const items: Array<DispatchStreamItem & { sort_timestamp: string }> = [];

  for await (const entry of Deno.readDir(runDir)) {
    if (!entry.isFile || !entry.name.endsWith(".json")) {
      continue;
    }

    const payload = await readJsonFile<DispatchStateFile>(
      `${runDir}/${entry.name}`,
    );
    if (!payload || typeof payload !== "object") {
      continue;
    }

    const taskId = asString(payload.task_id, entry.name.replace(/\.json$/, ""));
    const phase = asString(payload.phase, "running");
    const normalizedPhase = normalizedLower(payload.phase) || "running";
    const normalizedStatus = normalizedLower(payload.status);
    const terminal = TERMINAL_PHASES.has(normalizedPhase) ||
      TERMINAL_STATUSES.has(normalizedStatus);
    if (mode === "active" && terminal) {
      continue;
    }
    if (mode === "history" && !terminal) {
      continue;
    }

    const heartbeatAgeSec = heartbeatAgeSeconds(payload.last_heartbeat, nowMs);
    const reconciliationAction = asRecord(payload.reconciliation_action);
    const reconciliationActionable = Boolean(
      reconciliationAction &&
        (
          normalizedLower(reconciliationAction.status) === "pending" ||
          reconciliationAction.completion_accepted === false
        ),
    );
    const providerReconciliationRequired =
      payload.provider_reconciliation_required === true;
    items.push({
      task_id: taskId,
      attempt_id: asString(payload.attempt_id, ""),
      phase,
      provider: asString(payload.provider, "unknown"),
      model: asString(payload.model, ""),
      execution_transport: asString(payload.execution_transport, "external")
        .toLowerCase(),
      requested_launch_surface: asString(
        payload.requested_launch_surface,
        payload.launch_surface === "orca" ? "orca" : "direct",
      ).toLowerCase(),
      launch_surface: asString(payload.launch_surface, "direct").toLowerCase(),
      launch_surface_status: asString(payload.launch_surface_status, "disabled")
        .toLowerCase(),
      orca_launch_status: asNullableString(payload.orca_launch_status),
      route_reason: asString(payload.route_reason, ""),
      provider_task_id: asNullableString(payload.provider_task_id),
      completion_signal: asNullableString(payload.completion_signal),
      exit_code: asNullableNumber(payload.exit_code),
      fallback_from: asNullableString(payload.fallback_from),
      fallback_to: asNullableString(payload.fallback_to),
      provider_reconciliation_required: providerReconciliationRequired,
      reconciliation_required: !terminal &&
        (providerReconciliationRequired || reconciliationActionable),
      reconciliation_invariant_gap: terminal &&
        (providerReconciliationRequired || reconciliationActionable),
      reconciliation_action: reconciliationAction,
      mst_session_id: asNullableString(payload.mst_session_id),
      root_mst_id: asNullableString(payload.root_mst_id),
      parent_session_id: asNullableString(payload.parent_session_id),
      running_log_path: asNullableString(payload.running_log_path),
      trace_path: asNullableString(payload.trace_path),
      output_path: asNullableString(payload.output_path),
      terminal,
      heartbeat_age_sec: heartbeatAgeSec,
      stale: heartbeatAgeSec >= staleThresholdSec,
      sort_timestamp: asString(
        payload.terminated_at,
        asString(payload.updated_at, asString(payload.last_heartbeat, "")),
      ),
    });
  }

  if (mode === "active") {
    items.sort((a, b) => a.task_id.localeCompare(b.task_id));
  } else {
    items.sort((a, b) =>
      b.sort_timestamp.localeCompare(a.sort_timestamp) ||
      a.task_id.localeCompare(b.task_id)
    );
  }
  const bounded = mode === "active" ? items : items.slice(0, limit);
  return bounded.map(({ sort_timestamp: _sortTimestamp, ...item }) => item);
}

export const projectDispatchApi = new Hono();

projectDispatchApi.get("/dispatch/stream", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const staleThresholdSec = parseStaleThreshold(
    c.req.query("stale_threshold_sec"),
  );
  const mode = parseDispatchMode(
    c.req.query("mode"),
    c.req.query("include_terminal"),
  );
  const historyLimit = parseHistoryLimit(c.req.query("limit"));

  let teardown = () => {};
  const stream = new ReadableStream({
    start(controller) {
      const encoder = new TextEncoder();
      let closed = false;
      let snapshotInFlight = false;
      let pollTimer: number | null = null;
      let keepAliveTimer: number | null = null;
      let lastSerialized = "";

      const cleanup = () => {
        if (closed) return;
        closed = true;
        if (pollTimer !== null) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
        if (keepAliveTimer !== null) {
          clearInterval(keepAliveTimer);
          keepAliveTimer = null;
        }
        try {
          controller.close();
        } catch {
          // already closed
        }
      };
      teardown = cleanup;

      const sendSnapshot = async () => {
        if (closed || snapshotInFlight) return;
        snapshotInFlight = true;
        try {
          const payload: DispatchSnapshotEvent = {
            event: "snapshot",
            items: await collectDispatchSnapshot(baseDir, staleThresholdSec, {
              mode,
              limit: historyLimit,
            }),
            stale_threshold_sec: staleThresholdSec,
            mode,
            limit: mode === "active" ? null : historyLimit,
            as_of: new Date().toISOString(),
          };
          const serialized = JSON.stringify(payload);
          if (serialized === lastSerialized) {
            return;
          }
          lastSerialized = serialized;
          controller.enqueue(encoder.encode(`data: ${serialized}\n\n`));
        } catch {
          cleanup();
        } finally {
          snapshotInFlight = false;
        }
      };

      void sendSnapshot();

      pollTimer = setInterval(() => {
        void sendSnapshot();
      }, POLL_INTERVAL_MS);

      keepAliveTimer = setInterval(() => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(": ping\n\n"));
        } catch {
          cleanup();
        }
      }, KEEPALIVE_INTERVAL_MS);

      c.req.raw.signal.addEventListener("abort", cleanup, { once: true });
    },
    cancel() {
      teardown();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
});
