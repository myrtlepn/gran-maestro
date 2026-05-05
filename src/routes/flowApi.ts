import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { resolveBaseDir } from "../config.ts";
import {
  getExecutionFlowViews,
  getFlowEvents,
  initFlowWatcher,
  subscribeFlowSse,
} from "../flow-watcher.ts";

const HEARTBEAT_INTERVAL_MS = 5_000;

export const flowApi = new Hono();

function baseDirFromContext(c: { req: { param: (name: string) => string } }) {
  return resolveBaseDir(c.req.param("projectId"));
}

flowApi.get("/agile/:agiId/flow", async (c) => {
  const baseDir = baseDirFromContext(c);
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const events = await getFlowEvents(c.req.param("agiId"), baseDir);
  return c.json(events);
});

flowApi.get("/agile/:agiId/flow/view", async (c) => {
  const baseDir = baseDirFromContext(c);
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  const [events, executionFlowViews] = await Promise.all([
    getFlowEvents(agiId, baseDir),
    getExecutionFlowViews(agiId, baseDir),
  ]);
  return c.json({
    schema_version: 1,
    view_kind: "gran-maestro.flow-view",
    events,
    execution_flow_views: executionFlowViews,
    display_only: true,
    next_action_authority: false,
    transition_authority: "dod016_transition_graph",
  });
});

flowApi.get("/agile/:agiId/flow/stream", async (c) => {
  const baseDir = baseDirFromContext(c);
  if (!baseDir) {
    return c.json({ error: "Project not found" }, 404);
  }

  const agiId = c.req.param("agiId");
  await initFlowWatcher(baseDir);

  const encoder = new TextEncoder();
  let heartbeat: number | undefined;
  let unsubscribe: (() => void) | undefined;
  let closed = false;

  const cleanup = () => {
    if (closed) return;
    closed = true;
    if (heartbeat !== undefined) {
      clearInterval(heartbeat);
      heartbeat = undefined;
    }
    unsubscribe?.();
    unsubscribe = undefined;
  };

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const enqueue = (payload: string) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(payload));
        } catch {
          cleanup();
        }
      };

      unsubscribe = subscribeFlowSse(agiId, (event) => {
        enqueue(`data: ${JSON.stringify(event)}\n\n`);
      }, baseDir);

      heartbeat = setInterval(() => {
        enqueue(": heartbeat\n\n");
      }, HEARTBEAT_INTERVAL_MS);

      c.req.raw.signal?.addEventListener("abort", () => {
        cleanup();
        try {
          controller.close();
        } catch {
          // stream already closed
        }
      }, { once: true });
    },
    cancel() {
      cleanup();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    },
  });
});

export { initFlowWatcher };
