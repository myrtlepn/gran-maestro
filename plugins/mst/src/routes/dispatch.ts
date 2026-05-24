import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { resolveBaseDir } from "../config.ts";
import { dirExists, readJsonFile } from "../utils.ts";

const DEFAULT_STALE_THRESHOLD_SEC = 60;
const POLL_INTERVAL_MS = 1_000;
const KEEPALIVE_INTERVAL_MS = 30_000;
const UNKNOWN_AGE_SEC = 10 ** 9;
const TERMINAL_PHASES = new Set(["done", "terminated", "failed"]);

type DispatchStateFile = {
  task_id?: unknown;
  phase?: unknown;
  provider?: unknown;
  model?: unknown;
  last_heartbeat?: unknown;
};

export type DispatchStreamItem = {
  task_id: string;
  phase: string;
  provider: string;
  model: string;
  heartbeat_age_sec: number;
  stale: boolean;
};

type DispatchSnapshotEvent = {
  event: "snapshot";
  items: DispatchStreamItem[];
  stale_threshold_sec: number;
  as_of: string;
};

function asString(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.trim().length > 0) {
    return value;
  }
  return fallback;
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

export async function collectDispatchSnapshot(
  baseDir: string,
  staleThresholdSec: number,
): Promise<DispatchStreamItem[]> {
  const runDir = `${baseDir}/run`;
  if (!(await dirExists(runDir))) {
    return [];
  }

  const nowMs = Date.now();
  const items: DispatchStreamItem[] = [];

  for await (const entry of Deno.readDir(runDir)) {
    if (!entry.isFile || !entry.name.endsWith(".json")) {
      continue;
    }

    const payload = await readJsonFile<DispatchStateFile>(`${runDir}/${entry.name}`);
    if (!payload || typeof payload !== "object") {
      continue;
    }

    const taskId = asString(payload.task_id, entry.name.replace(/\.json$/, ""));
    const phase = asString(payload.phase, "running");
    const normalizedPhase = phase.toLowerCase();
    if (TERMINAL_PHASES.has(normalizedPhase)) {
      continue;
    }

    const heartbeatAgeSec = heartbeatAgeSeconds(payload.last_heartbeat, nowMs);
    items.push({
      task_id: taskId,
      phase,
      provider: asString(payload.provider, "unknown"),
      model: asString(payload.model, ""),
      heartbeat_age_sec: heartbeatAgeSec,
      stale: heartbeatAgeSec >= staleThresholdSec,
    });
  }

  items.sort((a, b) => a.task_id.localeCompare(b.task_id));
  return items;
}

export const projectDispatchApi = new Hono();

projectDispatchApi.get("/dispatch/stream", async (c) => {
  const baseDir = resolveBaseDir(c.req.param("projectId"));
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const staleThresholdSec = parseStaleThreshold(c.req.query("stale_threshold_sec"));

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
            items: await collectDispatchSnapshot(baseDir, staleThresholdSec),
            stale_threshold_sec: staleThresholdSec,
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
