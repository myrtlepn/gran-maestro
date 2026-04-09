import { setRegistry } from "../config.ts";
import { projectDispatchApi } from "./dispatch.ts";

const TEST_PROJECT_ID = "proj-dispatch-test";

async function writeJson(path: string, payload: unknown): Promise<void> {
  await Deno.writeTextFile(path, `${JSON.stringify(payload, null, 2)}\n`);
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  let timeoutId: number | null = null;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(`Timed out after ${timeoutMs}ms`)), timeoutMs);
      }),
    ]);
  } finally {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
  }
}

Deno.test("GET /dispatch/stream emits snapshot events for active dispatch states", async () => {
  const baseDir = await Deno.makeTempDir({ prefix: "dispatch-route-test-" });
  const runDir = `${baseDir}/run`;
  await Deno.mkdir(runDir, { recursive: true });
  await writeJson(`${runDir}/task-running.json`, {
    task_id: "task-running",
    phase: "running",
    provider: "codex",
    model: "gpt-5.4",
    last_heartbeat: new Date().toISOString(),
  });
  await writeJson(`${runDir}/task-done.json`, {
    task_id: "task-done",
    phase: "done",
    provider: "codex",
    model: "gpt-5.4",
    last_heartbeat: new Date().toISOString(),
  });

  setRegistry({
    projects: [
      {
        id: TEST_PROJECT_ID,
        name: "dispatch-test-project",
        path: baseDir,
        registered_at: "2026-04-09T00:00:00.000Z",
      },
    ],
  });

  try {
    const response = await projectDispatchApi.request("http://localhost/dispatch/stream");
    assertEquals(response.status, 200);
    assert(response.headers.get("Content-Type")?.includes("text/event-stream"));

    const reader = response.body?.getReader();
    assert(reader, "SSE body reader should exist");

    const chunk = await withTimeout(reader.read(), 2_000);
    await reader.cancel();
    assert(!chunk.done, "First SSE read should contain a snapshot payload");

    const text = new TextDecoder().decode(chunk.value);
    const line = text.split("\n").find((candidate) => candidate.startsWith("data: "));
    assert(line, `No SSE data line found: ${text}`);

    const payload = JSON.parse((line as string).slice("data: ".length)) as {
      event?: string;
      items?: Array<{ task_id?: string }>;
    };

    assertEquals(payload.event, "snapshot");
    assert(Array.isArray(payload.items), "snapshot items must be an array");
    const taskIds = new Set(payload.items?.map((item) => item.task_id));
    assert(taskIds.has("task-running"), "running task should be included");
    assert(!taskIds.has("task-done"), "terminal task should be excluded");
  } finally {
    setRegistry({ projects: [] });
    await Deno.remove(baseDir, { recursive: true });
  }
});

function assert(condition: unknown, message?: string): asserts condition {
  if (!condition) {
    throw new Error(message ?? "Assertion failed");
  }
}

function assertEquals(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Assertion failed: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}
