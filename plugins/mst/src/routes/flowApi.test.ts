import { Hono } from "https://deno.land/x/hono@v4.3.11/mod.ts";
import { join } from "https://deno.land/std@0.224.0/path/mod.ts";
import { setRegistry } from "../config.ts";
import { closeFlowWatchersForTest } from "../flow-watcher.ts";
import { flowApi } from "./flowApi.ts";

type TestFixture = {
  app: Hono;
  baseDir: string;
  cleanup: () => Promise<void>;
};

function assert(
  condition: unknown,
  message = "Assertion failed",
): asserts condition {
  if (!condition) throw new Error(message);
}

function valuesEqual(actual: unknown, expected: unknown): boolean {
  if (actual instanceof Set && expected instanceof Set) {
    if (actual.size !== expected.size) return false;
    for (const value of actual) {
      if (!expected.has(value)) return false;
    }
    return true;
  }
  return JSON.stringify(actual) === JSON.stringify(expected);
}

function assertEquals(actual: unknown, expected: unknown): void {
  if (!valuesEqual(actual, expected)) {
    throw new Error(
      `Values are not equal: ${JSON.stringify(actual)} !== ${
        JSON.stringify(expected)
      }`,
    );
  }
}

async function setupFixture(): Promise<TestFixture> {
  const tempRoot = await Deno.makeTempDir({ prefix: "flow-api-test-" });
  const baseDir = join(tempRoot, ".gran-maestro");
  await Deno.mkdir(join(baseDir, "state"), { recursive: true });

  setRegistry({
    projects: [
      {
        id: "proj-flow",
        name: "flow-test",
        path: baseDir,
        registered_at: "2026-04-25T00:00:00.000Z",
      },
    ],
  });

  const app = new Hono();
  app.route("/api", flowApi);

  return {
    app,
    baseDir,
    cleanup: async () => {
      closeFlowWatchersForTest();
      setRegistry({ projects: [] });
      await sleep(20);
      await Deno.remove(tempRoot, { recursive: true });
    },
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ensureFlowFile(
  baseDir: string,
  sessionId: string,
): Promise<string> {
  const sessionDir = join(baseDir, "state", sessionId);
  await Deno.mkdir(sessionDir, { recursive: true });
  const path = join(sessionDir, "flow-detail.ndjson");
  await Deno.writeTextFile(path, "", { append: true });
  return path;
}

async function appendFlowLine(
  baseDir: string,
  sessionId: string,
  event: Record<string, unknown>,
): Promise<void> {
  const path = await ensureFlowFile(baseDir, sessionId);
  await Deno.writeTextFile(path, `${JSON.stringify(event)}\n`, {
    append: true,
  });
}

async function writeExecutionFlow(
  baseDir: string,
  mstSessionId: string,
  overrides: Record<string, unknown> = {},
): Promise<void> {
  const sessionDir = join(baseDir, "sessions", mstSessionId);
  await Deno.mkdir(sessionDir, { recursive: true });
  await Deno.writeTextFile(join(sessionDir, "history.head"), "head-a");
  const projection = {
    schema_version: 1,
    projection_schema_version: 1,
    mst_session_id: mstSessionId,
    root_mst_id: "AGI-001",
    source: {
      source_kind: "verified_history_ledger",
      ledger_path: `.gran-maestro/sessions/${mstSessionId}/history.ndjson`,
      history_head: "head-a",
      source_hash: "head-a",
      projection_created_at: "2026-05-15T00:00:00.000Z",
    },
    projection_hash: "projection-a",
    current_node: "mst:request.step-2",
    last_transition: "mst:plan.step-4->mst:request.step-1",
    next_action: { skill: "mst:approve", source_id: "REQ-873" },
    blocker: { code: "child_dirty_blocked", detail: "child worktree is dirty" },
    nodes: [
      { id: "mst:plan.step-4", label: "Plan saved", status: "done" },
      { id: "mst:request.step-1", label: "Request created", status: "done" },
      { id: "mst:request.step-2", label: "Spec ready", status: "active" },
    ],
    edges: [
      { from: "mst:plan.step-4", to: "mst:request.step-1", transition: "request.created" },
      { from: "mst:request.step-1", to: "mst:request.step-2", transition: "spec.ready" },
    ],
    coverage: {
      recognized_event_families: ["plan", "request"],
      missing_event_families: [],
      required_event_families: ["plan", "request"],
    },
    worktrees: {
      session: { path: "/tmp/session", state: "active", branch: "gran-maestro/master/AGI-038/session" },
      children: [{ id: "REQ-873-T01", path: "/tmp/child", state: "dirty", merge_target: "session" }],
    },
    recovery_action: "cleanup_child",
    ...overrides,
  };
  await Deno.writeTextFile(join(sessionDir, "execution-flow.json"), JSON.stringify(projection));
}

async function readDataEvents(
  response: Response,
  expectedCount: number,
  timeoutMs = 3_000,
): Promise<Record<string, unknown>[]> {
  assert(response.body);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const deadline = Date.now() + timeoutMs;
  const events: Record<string, unknown>[] = [];
  let buffer = "";

  try {
    while (Date.now() < deadline && events.length < expectedCount) {
      const remaining = deadline - Date.now();
      let timeout: number | undefined;
      const timeoutPromise = new Promise<"timeout">((resolve) => {
        timeout = setTimeout(() => resolve("timeout"), remaining);
      });
      const result = await Promise.race([reader.read(), timeoutPromise]);
      if (timeout !== undefined) clearTimeout(timeout);

      if (result === "timeout" || result.done) break;

      buffer += decoder.decode(result.value, { stream: true });
      let frameEnd = buffer.indexOf("\n\n");
      while (frameEnd >= 0) {
        const frame = buffer.slice(0, frameEnd);
        buffer = buffer.slice(frameEnd + 2);

        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice("data:".length).trimStart())
          .join("\n");

        if (data) {
          const parsed = JSON.parse(data);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            events.push(parsed as Record<string, unknown>);
          }
        }

        frameEnd = buffer.indexOf("\n\n");
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
  }

  return events;
}

Deno.test("backfill GET returns sorted events with session ids", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "session-a", {
      timestamp: "2026-04-25T00:00:02Z",
      event_type: "second",
    });
    await appendFlowLine(fixture.baseDir, "session-b", {
      timestamp: "2026-04-25T00:00:01Z",
      event_type: "first",
    });
    const path = await ensureFlowFile(fixture.baseDir, "session-c");
    await Deno.writeTextFile(path, "not-json\n", { append: true });

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow",
    );
    assertEquals(response.status, 200);

    const events = await response.json();
    assertEquals(events.length, 2);
    assertEquals(
      events.map((event: Record<string, unknown>) => event.event_type),
      [
        "first",
        "second",
      ],
    );
    assertEquals(
      events.map((event: Record<string, unknown>) => event.session_id),
      [
        "session-b",
        "session-a",
      ],
    );
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view returns session graph contract", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "legacy-session-a", {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "legacy_display_event",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
      session_id: "legacy-session-a",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    assertEquals(response.status, 200);

    const body = await response.json();
    assertEquals(body.view_kind, "gran-maestro.flow-view");
    assert(Array.isArray(body.events), "events should be preserved");
    assert(Array.isArray(body.execution_flow_views), "execution_flow_views should be preserved");
    assert(Array.isArray(body.session_graphs), "session_graphs should be present");
    assertEquals(body.session_graphs.length, 1);

    const graph = body.session_graphs[0];
    assertEquals(graph.view_kind, "gran-maestro.session-graph.dashboard-view");
    assertEquals(graph.mst_session_id, "MST-AGI-001-20260515T000000Z-aaa111");
    assert(Array.isArray(graph.nodes) && graph.nodes.length === 3, "nodes should be projected");
    assert(Array.isArray(graph.edges) && graph.edges.length === 2, "edges should be projected");
    assert(Array.isArray(graph.events) && graph.events.length === 1, "events should be joined");
    assertEquals(graph.current_node, "mst:request.step-2");
    assertEquals(graph.recovery_action, "cleanup_child");
    assertEquals(graph.worktrees.session.state, "active");
    assertEquals(graph.worktrees.children[0].state, "dirty");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view uses canonical mst session id", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "legacy-session-a", {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "canonical_event",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
      session_id: "legacy-session-a",
    });
    await appendFlowLine(fixture.baseDir, "legacy-session-a", {
      timestamp: "2026-05-15T00:00:02Z",
      event_type: "legacy_only_event",
      session_id: "legacy-session-a",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(graph.mst_session_id, "MST-AGI-001-20260515T000000Z-aaa111");
    assertEquals(graph.events.length, 1);
    assertEquals(graph.events[0].event_type, "canonical_event");
    assertEquals(graph.events[0].session_id, "legacy-session-a");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view remains display only", async () => {
  const fixture = await setupFixture();

  try {
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(body.display_only, true);
    assertEquals(body.next_action_authority, false);
    assertEquals(body.transition_authority, "dod016_transition_graph");
    assertEquals(graph.display_only, true);
    assertEquals(graph.next_action_authority, false);
    assertEquals(graph.transition_authority, "dod016_transition_graph");
    assertEquals(Object.prototype.hasOwnProperty.call(graph, "cleanup_authority"), false);
    assertEquals(Object.prototype.hasOwnProperty.call(graph, "final_merge_retry_authority"), false);
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view tolerates legacy projections", async () => {
  const fixture = await setupFixture();

  try {
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", {
      worktrees: undefined,
      recovery_action: undefined,
      child_worktrees: undefined,
      session_worktree: undefined,
    });

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    assertEquals(response.status, 200);
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(graph.worktrees.session, null);
    assertEquals(graph.worktrees.children, []);
    assertEquals(graph.recovery_action, null);
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view reports graph consistency for canonical lifecycle events", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "session_worktree_created",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", {
      worktrees: {
        session: {
          path: "/tmp/session",
          state: "active",
          mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
        },
        children: [{
          id: "REQ-874-T01",
          state: "merged",
          parent_mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
        }],
      },
    });

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    assertEquals(response.status, 200);
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(graph.events.length, 1);
    assertEquals(graph.graph_consistency.status, "consistent");
    assertEquals(graph.graph_consistency.diagnostics, []);
    assertEquals(body.graph_consistency.status, "consistent");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view diagnoses legacy session id mismatch", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "legacy-session-a", {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "session_worktree_created",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
      session_id: "legacy-session-a",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(graph.events.length, 1);
    assertEquals(graph.graph_consistency.status, "degraded");
    assertEquals(graph.graph_consistency.diagnostics[0].code, "legacy_session_id_mismatch");
    assertEquals(graph.graph_consistency.diagnostics[0].legacy_session_id, "legacy-session-a");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view diagnoses legacy-only events without canonical fallback", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "legacy-session-a", {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "legacy_only_lifecycle",
      session_id: "legacy-session-a",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(graph.events.length, 0);
    assertEquals(body.events.length, 1);
    assertEquals(body.graph_consistency.status, "degraded");
    assertEquals(body.graph_consistency.diagnostics[0].code, "legacy_only_event");
    assertEquals(body.graph_consistency.diagnostics[0].legacy_session_id, "legacy-session-a");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view diagnoses worktree session metadata mismatch", async () => {
  const fixture = await setupFixture();

  try {
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", {
      worktrees: {
        session: {
          path: "/tmp/session",
          state: "active",
          mst_session_id: "MST-OTHER-20260515T000000Z-bbb222",
        },
        children: [{
          id: "REQ-874-T01",
          state: "active",
          parent_mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
        }],
      },
    });

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(graph.graph_consistency.status, "mismatch");
    assertEquals(graph.graph_consistency.diagnostics[0].code, "worktree_session_mismatch");
    assertEquals(graph.display_only, true);
    assertEquals(graph.next_action_authority, false);
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("flow view diagnoses orphan canonical flow events", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "legacy-session-b", {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "child_created",
      mst_session_id: "MST-AGI-001-20260515T000000Z-bbb222",
      session_id: "legacy-session-b",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(graph.events.length, 0);
    assertEquals(body.graph_consistency.status, "degraded");
    assertEquals(body.graph_consistency.diagnostics[0].code, "orphan_flow_event");
    assertEquals(body.graph_consistency.diagnostics[0].mst_session_id, "MST-AGI-001-20260515T000000Z-bbb222");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("DOD-017 lifecycle schema normalizes replay-compatible canonical events", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "child_merged_to_session",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
      child_id: "REQ-882-T01",
      idempotency_key: "child-merge:REQ-882-T01",
      ordering_key: "2026-05-15T00:00:01Z#001",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const body = await response.json();
    const graph = body.session_graphs[0];
    const event = graph.events[0];

    assertEquals(event.schema_version, 1);
    assertEquals(event.event_id, "child-merge:REQ-882-T01");
    assertEquals(event.idempotency_key, "child-merge:REQ-882-T01");
    assertEquals(event.ordering_key, "2026-05-15T00:00:01Z#001");
    assertEquals(event.event_family, "child");
    assertEquals(event.replay_compatible, true);
    assertEquals(graph.graph_consistency.status, "consistent");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("DOD-017 live and persisted replay graph equivalence", async () => {
  const fixture = await setupFixture();

  try {
    const liveEvent = {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "session_worktree_created",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
      event_id: "evt-session-created",
      ordering_key: "2026-05-15T00:00:01Z#001",
    };
    await appendFlowLine(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", liveEvent);
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const replayResponse = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const replayGraph = (await replayResponse.json()).session_graphs[0];

    const streamResponse = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/stream",
    );
    await sleep(100);
    await appendFlowLine(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", {
      ...liveEvent,
      event_id: "evt-session-created-live",
      idempotency_key: "evt-session-created-live",
      ordering_key: "2026-05-15T00:00:02Z#002",
      timestamp: "2026-05-15T00:00:02Z",
    });
    const liveEvents = await readDataEvents(streamResponse, 1);

    assertEquals(replayGraph.mst_session_id, "MST-AGI-001-20260515T000000Z-aaa111");
    assertEquals(replayGraph.graph_consistency.status, "consistent");
    assertEquals(replayGraph.events[0].replay_compatible, true);
    assertEquals(liveEvents[0].replay_compatible, true);
    assertEquals(liveEvents[0].event_family, "session");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("DOD-017 duplicate lifecycle events are diagnosed and deduplicated", async () => {
  const fixture = await setupFixture();

  try {
    const duplicate = {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "child_created",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
      idempotency_key: "child-created:REQ-882-T01",
      ordering_key: "2026-05-15T00:00:01Z#001",
    };
    await appendFlowLine(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", duplicate);
    await appendFlowLine(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", duplicate);
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const graph = (await response.json()).session_graphs[0];

    assertEquals(graph.events.length, 1);
    assertEquals(graph.graph_consistency.status, "degraded");
    assertEquals(graph.graph_consistency.diagnostics[0].code, "duplicate_lifecycle_event");
    assertEquals(graph.graph_consistency.diagnostics[0].idempotency_key, "child-created:REQ-882-T01");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("DOD-017 out-of-order lifecycle events remain deterministic", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", {
      timestamp: "2026-05-15T00:00:03Z",
      event_type: "child_merged_to_session",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
      ordering_key: "2026-05-15T00:00:03Z#003",
    });
    await appendFlowLine(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111", {
      timestamp: "2026-05-15T00:00:02Z",
      event_type: "child_created",
      mst_session_id: "MST-AGI-001-20260515T000000Z-aaa111",
      ordering_key: "2026-05-15T00:00:02Z#002",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const graph = (await response.json()).session_graphs[0];

    assertEquals(graph.events.map((event: Record<string, unknown>) => event.event_type), [
      "child_created",
      "child_merged_to_session",
    ]);
    assertEquals(graph.graph_consistency.status, "degraded");
    assertEquals(graph.graph_consistency.diagnostics[0].code, "out_of_order_lifecycle_event");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("DOD-017 legacy lifecycle events stay degraded without canonical fallback", async () => {
  const fixture = await setupFixture();

  try {
    await appendFlowLine(fixture.baseDir, "legacy-session-a", {
      timestamp: "2026-05-15T00:00:01Z",
      event_type: "session_worktree_created",
      session_id: "legacy-session-a",
      idempotency_key: "legacy-event",
    });
    await writeExecutionFlow(fixture.baseDir, "MST-AGI-001-20260515T000000Z-aaa111");

    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/view",
    );
    const body = await response.json();
    const graph = body.session_graphs[0];

    assertEquals(graph.events.length, 0);
    assertEquals(body.graph_consistency.status, "degraded");
    assertEquals(body.graph_consistency.diagnostics[0].code, "legacy_only_event");
    assertEquals(body.graph_consistency.diagnostics[0].legacy_session_id, "legacy-session-a");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("smoke: stream returns text/event-stream", async () => {
  const fixture = await setupFixture();

  try {
    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/stream",
    );

    assertEquals(response.status, 200);
    assert(response.headers.get("content-type")?.includes("text/event-stream"));
    await response.body?.cancel();
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("watchBroadcast: new flow line is sent as SSE data", async () => {
  const fixture = await setupFixture();

  try {
    await ensureFlowFile(fixture.baseDir, "session-a");
    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/stream",
    );

    await sleep(100);
    await appendFlowLine(fixture.baseDir, "session-a", {
      timestamp: "2026-04-25T00:00:03Z",
      event_type: "line_appended",
    });

    const events = await readDataEvents(response, 1);
    assertEquals(events.length, 1);
    assertEquals(events[0].event_type, "line_appended");
    assertEquals(events[0].session_id, "session-a");
  } finally {
    await fixture.cleanup();
  }
});

Deno.test("multiSession: new lines from two sessions are broadcast", async () => {
  const fixture = await setupFixture();

  try {
    await ensureFlowFile(fixture.baseDir, "session-a");
    await ensureFlowFile(fixture.baseDir, "session-b");
    const response = await fixture.app.request(
      "http://localhost/api/agile/AGI-001/flow/stream",
    );

    await sleep(100);
    await appendFlowLine(fixture.baseDir, "session-a", {
      timestamp: "2026-04-25T00:00:04Z",
      event_type: "from_a",
    });
    await appendFlowLine(fixture.baseDir, "session-b", {
      timestamp: "2026-04-25T00:00:05Z",
      event_type: "from_b",
    });

    const events = await readDataEvents(response, 2);
    assertEquals(events.length, 2);
    assertEquals(
      new Set(events.map((event) => event.session_id)),
      new Set(["session-a", "session-b"]),
    );
    assertEquals(
      new Set(events.map((event) => event.event_type)),
      new Set(["from_a", "from_b"]),
    );
  } finally {
    await fixture.cleanup();
  }
});
