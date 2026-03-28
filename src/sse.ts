import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import type { SSEEvent } from "./types.ts";
import {
  BASE_DIR,
  HUB_MODE,
  SSE_DEBOUNCE_MS,
  registry,
  stripBasePath,
} from "./config.ts";

// 전역 SSE 브로드캐스트 함수 (모든 연결에 전송)
const activeSenders: Set<(event: SSEEvent) => void> = new Set();
const completedAlerts = new Set<string>();

const sseApi = new Hono();
sseApi.get("/events", async (c) => {
  // Auth check is handled by middleware already

  const stream = new ReadableStream({
    start(controller) {
      const encoder = new TextEncoder();

      function send(event: SSEEvent) {
        const data = `data: ${JSON.stringify(event)}\n\n`;
        try {
          controller.enqueue(encoder.encode(data));
        } catch {
          // stream closed
        }
      }

      // Register this sender for broadcast
      activeSenders.add(send);

      // Send initial heartbeat
      send({ type: "connected", data: { timestamp: new Date().toISOString() } });

      // Heartbeat every 30s to keep connection alive
      const heartbeatInterval = setInterval(() => {
        send({ type: "heartbeat", data: { timestamp: new Date().toISOString() } });
      }, 30000);

      // Watch .gran-maestro/ for changes
      interface EventWatcherState {
        watcher: Deno.FsWatcher;
        debounceTimer: number | undefined;
        pendingPaths: Map<string, string>; // path → last kind (dedup)
        baseDir: string;
        projectId?: string;
      }

      const watchers = new Map<string, EventWatcherState>();

      function addWatcher(baseDir: string, projectId?: string) {
        const watcherKey = projectId ?? "legacy";
        if (watchers.has(watcherKey)) {
          return;
        }

        try {
          const watcher = Deno.watchFs(baseDir, { recursive: true });
          const state: EventWatcherState = {
            watcher,
            debounceTimer: undefined,
            pendingPaths: new Map(),
            baseDir,
            projectId,
          };
          watchers.set(watcherKey, state);

          void (async () => {
            try {
              for await (const event of watcher) {
                if (state.debounceTimer) {
                  clearTimeout(state.debounceTimer);
                }
                for (const p of event.paths) {
                  state.pendingPaths.set(p, event.kind); // dedup: same path → latest kind
                }
                state.debounceTimer = setTimeout(async () => {
                  const pending = [...state.pendingPaths.entries()];
                  state.pendingPaths.clear();
                  for (const [p, kind] of pending) {
                    const relPath = stripBasePath(p, state.baseDir);
                    const sseEvent = classifyFsEvent(
                      relPath,
                      kind,
                      state.projectId
                    );
                    if (sseEvent) {
                      send(sseEvent);
                    }
                    await checkCompletionAlert(p, kind, send, state.projectId);
                  }
                }, SSE_DEBOUNCE_MS);
              }
            } catch {
              // watcher closed or directory doesn't exist
            }
          })();
        } catch {
          // cannot watch project
        }
      }

      if (HUB_MODE) {
        for (const project of registry.projects) {
          addWatcher(project.path, project.id);
        }
      } else {
        addWatcher(BASE_DIR);
      }

      // Cleanup when client disconnects
      c.req.raw.signal.addEventListener("abort", () => {
        activeSenders.delete(send);
        clearInterval(heartbeatInterval);
        for (const state of watchers.values()) {
          if (state.debounceTimer) {
            clearTimeout(state.debounceTimer);
          }
          try {
            state.watcher.close();
          } catch {
            // already closed
          }
        }
        watchers.clear();
        try {
          controller.close();
        } catch {
          // already closed
        }
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "Access-Control-Allow-Origin": "*",
    },
  });
});

sseApi.post("/notify", async (c) => {
  const body = await c.req.json();
  for (const send of activeSenders) {
    try { send(body as SSEEvent); } catch { /* ignore */ }
  }
  return c.json({ ok: true });
});

      /** Classify a filesystem change into an SSE event type. */
export function classifyFsEvent(
  path: string,
  kind: string,
  projectId?: string
): SSEEvent | null {
  const normPath = path.replace(/\\/g, "/");

  // Pattern: .gran-maestro/requests/REQ-XXX/tasks/NN/traces/...
  // (must be checked before generic task_update to avoid being swallowed)
  const traceMatch = normPath.match(
    /\.gran-maestro\/requests\/([^/]+)\/tasks\/([^/]+)\/traces\/(.+)/
  );
  if (traceMatch) {
    return {
      type: "trace_update",
      projectId,
      requestId: traceMatch[1],
      taskId: traceMatch[2],
      data: { path, kind, traceFile: traceMatch[3], timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/requests/REQ-XXX/tasks/NN/...
  const taskMatch = normPath.match(
    /\.gran-maestro\/requests\/([^/]+)\/tasks\/([^/]+)/
  );
  if (taskMatch) {
    return {
      type: "task_update",
      projectId,
      requestId: taskMatch[1],
      taskId: taskMatch[2],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/requests/REQ-XXX/...
  const reqMatch = normPath.match(/\.gran-maestro\/requests\/([^/]+)/);
  if (reqMatch) {
    return {
      type: "request_update",
      projectId,
      requestId: reqMatch[1],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/captures/CAP-***
  const captureMatch = normPath.match(/\.gran-maestro\/captures\/(CAP-[^/]+)/);
  if (captureMatch) {
    return {
      type: "capture_update",
      projectId,
      captureId: captureMatch[1],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/plans/PLN-***
  const planMatch = normPath.match(/\.gran-maestro\/plans\/(PLN-[^/]+)/);
  if (planMatch) {
    return {
      type: "plan_update",
      projectId,
      planId: planMatch[1],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/agile/AGI-***
  const agileMatch = normPath.match(/\.gran-maestro\/agile\/(AGI-[^/]+)/);
  if (agileMatch) {
    return {
      type: "agile_update",
      projectId,
      sessionId: agileMatch[1],
      data: { path, kind, agiId: agileMatch[1], timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/debug/DBG-***
  const debugMatch = normPath.match(/\.gran-maestro\/debug\/(DBG-[^/]+)/);
  if (debugMatch) {
    return {
      type: "debug_update",
      projectId,
      sessionId: debugMatch[1],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/config.json
  if (normPath.includes("config.json")) {
    return {
      type: "config_change",
      projectId,
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/mode.json
  if (normPath.includes("mode.json")) {
    return {
      type: "phase_change",
      projectId,
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/ideation/IDN-XXX/...
  const ideationMatch = normPath.match(/\.gran-maestro\/ideation\/([^/]+)/);
  if (ideationMatch) {
    return {
      type: "ideation_update",
      projectId,
      sessionId: ideationMatch[1],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/discussion/DSC-XXX/...
  const discussionMatch = normPath.match(/\.gran-maestro\/discussion\/([^/]+)/);
  if (discussionMatch) {
    return {
      type: "discussion_update",
      projectId,
      sessionId: discussionMatch[1],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/designs/DES-XXX/...
  const designMatch = normPath.match(/\.gran-maestro\/designs\/(DES-[^/]+)/);
  if (designMatch) {
    return {
      type: "design_update",
      projectId,
      designId: designMatch[1],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Pattern: .gran-maestro/explore/EXP-XXX/...
  const exploreMatch = normPath.match(
    /\.gran-maestro\/explore\/(EXP-\d+)\/[^/]+/
  );
  if (exploreMatch) {
    return {
      type: "explore_update",
      projectId,
      sessionId: exploreMatch[1],
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  // Generic agent activity for log files
  if (normPath.includes("exec-log") || normPath.includes("activity")) {
    return {
      type: "agent_activity",
      projectId,
      data: { path, kind, timestamp: new Date().toISOString() },
    };
  }

  return null;
}

async function checkCompletionAlert(
  absPath: string,
  kind: string,
  send: (event: SSEEvent) => void,
  projectId?: string
): Promise<void> {
  if (kind === "remove") return;

  const normPath = absPath.replace(/\\/g, "/");
  let id: string | null = null;

  const reqMatch = normPath.match(
    /requests\/(?:completed\/)?(REQ-[^/]+)\/request\.json$/
  );
  if (reqMatch) id = reqMatch[1];

  const planMatch = normPath.match(/plans\/(PLN-[^/]+)\/plan\.json$/);
  if (planMatch) id = planMatch[1];

  const ideationMatch = normPath.match(/ideation\/(IDN-[^/]+)\/session\.json$/);
  if (ideationMatch) id = ideationMatch[1];

  const debugMatch = normPath.match(/debug\/(DBG-[^/]+)\/session\.json$/);
  if (debugMatch) id = debugMatch[1];

  const discussionMatch = normPath.match(/discussion\/(DSC-[^/]+)\/session\.json$/);
  if (discussionMatch) id = discussionMatch[1];

  const designMatch = normPath.match(/designs\/(DES-[^/]+)\/design\.json$/);
  if (designMatch) id = designMatch[1];

  if (!id || completedAlerts.has(id)) return;

  try {
    const text = await Deno.readTextFile(absPath);
    const json = JSON.parse(text);
    const isCompleted =
      json.status === "completed" ||
      (typeof json.phase === "number" && json.phase >= 5);
    if (isCompleted) {
      completedAlerts.add(id);
      send({
        type: "completion_alert",
        projectId,
        data: { id, timestamp: new Date().toISOString() },
      });
    }
  } catch {
    // ignore read/parse errors
  }
}

export { sseApi };
