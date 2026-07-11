// Run with the minimum filesystem/env permissions used by these route fixtures:
// deno test --no-config --allow-read --allow-write --allow-env src/routes/dispatch.test.ts
import { setRegistry } from "../config.ts";
import { collectDispatchSnapshot, projectDispatchApi } from "./dispatch.ts";

const TEST_PROJECT_ID = "proj-dispatch-test";

async function writeJson(path: string, payload: unknown): Promise<void> {
  await Deno.writeTextFile(path, `${JSON.stringify(payload, null, 2)}\n`);
}

async function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
): Promise<T> {
  let timeoutId: number | null = null;
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timeoutId = setTimeout(
          () => reject(new Error(`Timed out after ${timeoutMs}ms`)),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
  }
}

type SnapshotPayload = {
  event?: string;
  mode?: string;
  limit?: number | null;
  items?: Array<Record<string, unknown>>;
};

async function readSnapshot(response: Response): Promise<SnapshotPayload> {
  assertEquals(response.status, 200);
  const reader = response.body?.getReader();
  assert(reader, "SSE body reader should exist");
  const chunk = await withTimeout(reader.read(), 2_000);
  await reader.cancel();
  assert(!chunk.done, "First SSE read should contain a snapshot payload");
  const text = new TextDecoder().decode(chunk.value);
  const line = text.split("\n").find((candidate) =>
    candidate.startsWith("data: ")
  );
  assert(line, `No SSE data line found: ${text}`);
  return JSON.parse((line as string).slice("data: ".length)) as SnapshotPayload;
}

Deno.test("GET /dispatch/stream emits snapshot events for active dispatch states", async () => {
  const baseDir = await Deno.makeTempDir({ prefix: "dispatch-route-test-" });
  const runDir = `${baseDir}/run`;
  await Deno.mkdir(runDir, { recursive: true });
  await writeJson(`${runDir}/task-native.json`, {
    task_id: "task-native",
    attempt_id: "native-a1",
    phase: "reconciling",
    provider: "codex",
    model: "gpt-5.4",
    execution_transport: "native",
    route_reason: "same_host_native_capable",
    provider_task_id: "provider-native-1",
    completion_signal: null,
    exit_code: null,
    fallback_from: null,
    fallback_to: null,
    provider_reconciliation_required: true,
    reconciliation_action: {
      action_id: "provider-reconcile:abc",
      status: "pending",
      lookup_key: "provider-native-1",
    },
    last_heartbeat: new Date().toISOString(),
  });
  await writeJson(`${runDir}/task-external.json`, {
    task_id: "task-external",
    attempt_id: "external-a2",
    phase: "reconciling",
    provider: "claude",
    model: "claude-opus",
    execution_transport: "external",
    route_reason: "external_fallback_after_definitive_not_created",
    provider_task_id: null,
    completion_signal: null,
    exit_code: null,
    fallback_from: "native-a1",
    fallback_to: null,
    provider_reconciliation_required: true,
    reconciliation_action: {
      kind: "provider_reconcile",
      action_id: "provider-reconcile:external",
      status: "pending",
      lookup_key: "attempt:external-a2",
      next_operation: "reconcile_external_provider_group",
    },
    last_heartbeat: new Date().toISOString(),
  });
  await writeJson(`${runDir}/task-done.json`, {
    task_id: "task-done",
    attempt_id: "native-done-a1",
    phase: "done",
    status: "completed",
    provider: "codex",
    model: "gpt-5.4",
    execution_transport: "native",
    provider_task_id: "provider-done-1",
    completion_signal: "completed",
    exit_code: null,
    mst_session_id: "MST-REQ-939-20260711T131345269Z-test0001",
    root_mst_id: "REQ-939",
    parent_session_id: "MST-REQ-939-20260711T131345269Z-test0001",
    running_log_path: "/tmp/done-running.log",
    trace_path: "/tmp/done-trace.json",
    output_path: "/tmp/done-result.md",
    terminated_at: "2026-07-11T12:00:00.000Z",
    last_heartbeat: "2026-07-11T12:00:00.000Z",
  });
  await writeJson(`${runDir}/task-failed.json`, {
    task_id: "task-failed",
    attempt_id: "native-failed-a1",
    phase: "failed",
    status: "failed",
    provider: "claude",
    model: "claude-opus",
    execution_transport: "native",
    provider_task_id: "provider-failed-1",
    completion_signal: "failed",
    exit_code: null,
    provider_reconciliation_required: false,
    reconciliation_action: {
      action_id: "provider-reconcile:failed",
      status: "resolved",
      completion_accepted: true,
      resolved_at: "2026-07-11T13:00:00.000Z",
      result: {
        provider_state: "failed",
        completion_signal: "failed",
        phase: "failed",
        status: "failed",
        observed_at: "2026-07-11T13:00:00.000Z",
      },
    },
    mst_session_id: "MST-REQ-939-20260711T131345269Z-test0001",
    root_mst_id: "REQ-939",
    parent_session_id: "MST-REQ-939-20260711T131345269Z-test0001",
    running_log_path: "/tmp/failed-running.log",
    trace_path: "/tmp/failed-trace.json",
    output_path: "/tmp/failed-result.md",
    terminated_at: "2026-07-11T13:00:00.000Z",
    last_heartbeat: "2026-07-11T13:00:00.000Z",
  });
  await writeJson(`${runDir}/task-corrupt-terminal.json`, {
    task_id: "task-corrupt-terminal",
    attempt_id: "native-corrupt-a1",
    phase: "done",
    status: "completed",
    provider: "codex",
    execution_transport: "native",
    completion_signal: "completed",
    provider_reconciliation_required: true,
    reconciliation_action: {
      action_id: "provider-reconcile:corrupt",
      status: "pending",
      completion_accepted: false,
    },
    terminated_at: "2026-07-11T11:00:00.000Z",
    last_heartbeat: "2026-07-11T11:00:00.000Z",
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
    const response = await projectDispatchApi.request(
      "http://localhost/dispatch/stream",
    );
    assert(
      response.headers.get("Content-Type")?.includes("text/event-stream"),
    );
    const payload = await readSnapshot(response);

    assertEquals(payload.event, "snapshot");
    assert(Array.isArray(payload.items), "snapshot items must be an array");
    const taskIds = new Set(payload.items?.map((item) => item.task_id));
    assert(
      taskIds.has("task-native"),
      "native active task should be included",
    );
    assert(
      taskIds.has("task-external"),
      "external active task should be included",
    );
    assert(!taskIds.has("task-done"), "terminal task should be excluded");

    const native = payload.items?.find((item) =>
      item.task_id === "task-native"
    );
    assertEquals(native?.attempt_id, "native-a1");
    assertEquals(native?.execution_transport, "native");
    assertEquals(native?.route_reason, "same_host_native_capable");
    assertEquals(native?.provider_task_id, "provider-native-1");
    assertEquals(native?.completion_signal, null);
    assertEquals(native?.exit_code, null);
    assertEquals(native?.reconciliation_action, {
      action_id: "provider-reconcile:abc",
      status: "pending",
      lookup_key: "provider-native-1",
    });
    assertEquals(native?.provider_reconciliation_required, true);
    assertEquals(native?.reconciliation_required, true);
    assertEquals(native?.reconciliation_invariant_gap, false);

    const external = payload.items?.find((item) =>
      item.task_id === "task-external"
    );
    assertEquals(external?.attempt_id, "external-a2");
    assertEquals(external?.execution_transport, "external");
    assertEquals(
      external?.route_reason,
      "external_fallback_after_definitive_not_created",
    );
    assertEquals(external?.exit_code, null);
    assertEquals(external?.fallback_from, "native-a1");
    assertEquals(external?.fallback_to, null);
    assertEquals(external?.reconciliation_action, {
      kind: "provider_reconcile",
      action_id: "provider-reconcile:external",
      status: "pending",
      lookup_key: "attempt:external-a2",
      next_operation: "reconcile_external_provider_group",
    });
    assertEquals(external?.provider_reconciliation_required, true);
    assertEquals(external?.reconciliation_required, true);
    assertEquals(external?.reconciliation_invariant_gap, false);

    const history = await readSnapshot(
      await projectDispatchApi.request(
        "http://localhost/dispatch/stream?mode=history&limit=1",
      ),
    );
    assertEquals(history.mode, "history");
    assertEquals(history.limit, 1);
    assertEquals(history.items?.length, 1);
    const terminal = history.items?.[0];
    assertEquals(terminal?.task_id, "task-failed");
    assertEquals(terminal?.terminal, true);
    assertEquals(terminal?.provider_task_id, "provider-failed-1");
    assertEquals(terminal?.completion_signal, "failed");
    assertEquals(terminal?.exit_code, null);
    assertEquals(
      terminal?.mst_session_id,
      "MST-REQ-939-20260711T131345269Z-test0001",
    );
    assertEquals(terminal?.root_mst_id, "REQ-939");
    assertEquals(terminal?.running_log_path, "/tmp/failed-running.log");
    assertEquals(terminal?.trace_path, "/tmp/failed-trace.json");
    assertEquals(terminal?.output_path, "/tmp/failed-result.md");
    assertEquals(terminal?.provider_reconciliation_required, false);
    assertEquals(terminal?.reconciliation_required, false);
    assertEquals(terminal?.reconciliation_invariant_gap, false);
    assertEquals(terminal?.reconciliation_action, {
      action_id: "provider-reconcile:failed",
      status: "resolved",
      completion_accepted: true,
      resolved_at: "2026-07-11T13:00:00.000Z",
      result: {
        provider_state: "failed",
        completion_signal: "failed",
        phase: "failed",
        status: "failed",
        observed_at: "2026-07-11T13:00:00.000Z",
      },
    });

    const allHistory = await readSnapshot(
      await projectDispatchApi.request(
        "http://localhost/dispatch/stream?mode=history&limit=10",
      ),
    );
    const corrupt = allHistory.items?.find((item) =>
      item.task_id === "task-corrupt-terminal"
    );
    assertEquals(corrupt?.terminal, true);
    assertEquals(corrupt?.provider_reconciliation_required, true);
    assertEquals(corrupt?.reconciliation_required, false);
    assertEquals(corrupt?.reconciliation_invariant_gap, true);
    assertEquals(corrupt?.reconciliation_action, {
      action_id: "provider-reconcile:corrupt",
      status: "pending",
      completion_accepted: false,
    });
  } finally {
    setRegistry({ projects: [] });
    await Deno.remove(baseDir, { recursive: true });
  }
});

Deno.test("status-terminal reconciliation uses the canonical safe union", async () => {
  const baseDir = await Deno.makeTempDir({
    prefix: "dispatch-terminal-status-test-",
  });
  const runDir = `${baseDir}/run`;
  await Deno.mkdir(runDir, { recursive: true });
  const terminalStatuses = [
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
  ];
  try {
    for (const status of terminalStatuses) {
      await writeJson(`${runDir}/terminal-${status}.json`, {
        task_id: `terminal-${status}`,
        attempt_id: `attempt-${status}`,
        phase: "running",
        status,
        provider: "codex",
        execution_transport: "native",
        provider_reconciliation_required: true,
        reconciliation_action: {
          action_id: `provider-reconcile:${status}`,
          status: "pending",
          completion_accepted: false,
        },
        last_heartbeat: new Date().toISOString(),
      });
    }
    await writeJson(`${runDir}/nonterminal-reconciling.json`, {
      task_id: "nonterminal-reconciling",
      attempt_id: "attempt-reconciling",
      phase: "reconciling",
      status: "reconciling",
      provider: "codex",
      execution_transport: "native",
      provider_reconciliation_required: true,
      reconciliation_action: {
        action_id: "provider-reconcile:nonterminal",
        status: "pending",
        completion_accepted: false,
      },
      last_heartbeat: new Date().toISOString(),
    });
    await writeJson(`${runDir}/padded-terminal-phase.json`, {
      task_id: "padded-terminal-phase",
      attempt_id: "attempt-padded-terminal-phase",
      phase: " DONE ",
      status: "running",
      provider: "codex",
      execution_transport: "native",
      provider_reconciliation_required: true,
      reconciliation_action: {
        action_id: "provider-reconcile:padded-phase",
        status: "pending",
        completion_accepted: false,
      },
      last_heartbeat: new Date().toISOString(),
    });
    await writeJson(`${runDir}/padded-terminal-status.json`, {
      task_id: "padded-terminal-status",
      attempt_id: "attempt-padded-terminal-status",
      phase: "running",
      status: " COMPLETED ",
      provider: "codex",
      execution_transport: "native",
      provider_reconciliation_required: true,
      reconciliation_action: {
        action_id: "provider-reconcile:padded-status",
        status: "pending",
        completion_accepted: false,
      },
      last_heartbeat: new Date().toISOString(),
    });
    await writeJson(`${runDir}/padded-pending-action.json`, {
      task_id: "padded-pending-action",
      attempt_id: "attempt-padded-pending-action",
      phase: "reconciling",
      status: "reconciling",
      provider: "codex",
      execution_transport: "native",
      provider_reconciliation_required: false,
      reconciliation_action: {
        action_id: "provider-reconcile:padded-pending",
        status: " PENDING ",
        completion_accepted: true,
      },
      last_heartbeat: new Date().toISOString(),
    });

    const active = await collectDispatchSnapshot(baseDir, 60, {
      mode: "active",
    });
    assertEquals(active.map((item) => item.task_id), [
      "nonterminal-reconciling",
      "padded-pending-action",
    ]);
    for (const item of active) {
      assertEquals(item.terminal, false);
      assertEquals(item.reconciliation_required, true);
      assertEquals(item.reconciliation_invariant_gap, false);
    }

    const history = await collectDispatchSnapshot(baseDir, 60, {
      mode: "history",
      limit: 50,
    });
    assertEquals(history.length, terminalStatuses.length + 2);
    assertEquals(
      history.map((item) => item.task_id).sort(),
      [
        ...terminalStatuses.map((status) => `terminal-${status}`),
        "padded-terminal-phase",
        "padded-terminal-status",
      ].sort(),
    );
    for (const item of history) {
      assertEquals(
        item.phase,
        item.task_id === "padded-terminal-phase" ? " DONE " : "running",
      );
      assertEquals(item.terminal, true);
      assertEquals(item.reconciliation_required, false);
      assertEquals(item.reconciliation_invariant_gap, true);
    }
  } finally {
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
      `Assertion failed: expected ${JSON.stringify(expected)}, got ${
        JSON.stringify(actual)
      }`,
    );
  }
}
