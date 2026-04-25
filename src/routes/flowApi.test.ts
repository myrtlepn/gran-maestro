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
