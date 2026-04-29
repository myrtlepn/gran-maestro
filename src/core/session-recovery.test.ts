import {
  determineRecoveryAction,
  getMergeConflictAlternatives,
  reconcileTaskAndWorktree,
  type RecoverableTask,
  type ReconcileInput,
} from "./session-recovery.ts";

let serial = Promise.resolve();

function runSerialTest(name: string, fn: () => void) {
  Deno.test(name, async () => {
    const prev = serial;
    let release = () => {};
    serial = new Promise<void>((resolve) => {
      release = resolve;
    });

    await prev;
    try {
      fn();
    } finally {
      release();
    }
  });
}

runSerialTest("reconcile: terminal task + active worktree -> cleanup_worktree", () => {
  const input: ReconcileInput = {
    taskId: "REQ-001-01",
    taskStatus: "done",
    worktreeState: "active",
  };

  const result = reconcileTaskAndWorktree(input);

  assertEquals(result.action, "cleanup_worktree");
  assertEquals(result.taskStatus, "done");
  assertEquals(result.worktreeState, "active");
});

runSerialTest("reconcile: terminal task + cleaned worktree -> noop", () => {
  const result = reconcileTaskAndWorktree({
    taskId: "REQ-001-02",
    taskStatus: "failed",
    worktreeState: "cleaned",
  });

  assertEquals(result.action, "noop");
});

runSerialTest("reconcile: active task + active worktree -> noop", () => {
  const result = reconcileTaskAndWorktree({
    taskId: "REQ-001-03",
    taskStatus: "executing",
    worktreeState: "active",
  });

  assertEquals(result.action, "noop");
});

runSerialTest("reconcile: active task + cleaned worktree -> user_decision", () => {
  const result = reconcileTaskAndWorktree({
    taskId: "REQ-002-01",
    taskStatus: "review",
    worktreeState: "cleaned",
  });

  assertEquals(result.action, "user_decision");
  assert(typeof result.prompt === "string" && result.prompt.length > 0);
});

runSerialTest("reconcile: merge_conflict + active worktree -> explicit_recovery_required", () => {
  const result = reconcileTaskAndWorktree({
    taskId: "REQ-003-01",
    taskStatus: "merge_conflict",
    worktreeState: "active",
  });

  assertEquals(result.action, "explicit_recovery_required");
});

runSerialTest("reconcile: merge_conflict + cleaned worktree -> user_decision + warn", () => {
  const result = reconcileTaskAndWorktree({
    taskId: "REQ-003-02",
    taskStatus: "merge_conflict",
    worktreeState: "cleaned",
  });

  assertEquals(result.action, "user_decision");
  assert(typeof result.warn === "string" && result.warn.length > 0);
});

runSerialTest("reconcile: any task + error worktree -> user_decision", () => {
  const result = reconcileTaskAndWorktree({
    taskId: "REQ-004-01",
    taskStatus: "executing",
    worktreeState: "error",
  });

  assertEquals(result.action, "user_decision");
});

runSerialTest("reconcile: idempotent", () => {
  const input: ReconcileInput = {
    taskId: "REQ-005-01",
    taskStatus: "done",
    worktreeState: "active",
  };

  const first = reconcileTaskAndWorktree(input);
  const second = reconcileTaskAndWorktree(input);

  assertEquals(first, second);
});

runSerialTest("reconcile: read-only (input unchanged)", () => {
  const input: ReconcileInput = {
    taskId: "REQ-006-01",
    taskStatus: "done",
    worktreeState: "active",
  };
  const before = JSON.stringify(input);

  reconcileTaskAndWorktree(input);

  assertEquals(JSON.stringify(input), before);
});

function makeTask(
  overrides: Partial<RecoverableTask> = {},
): RecoverableTask {
  return {
    taskId: "REQ-001-01",
    reqId: "REQ-001",
    lastStatus: "executing",
    lastPhase: "phase2_execution",
    worktreePath: "/tmp/test-worktree",
    hasRunningProcess: false,
    basePath: "/tmp/test-base",
    ...overrides,
  };
}

runSerialTest(
  "determineRecoveryAction: merge_conflict (running) -> resolve_conflict_interactive",
  () => {
    const action = determineRecoveryAction(
      makeTask({ lastStatus: "merge_conflict", hasRunningProcess: true }),
    );
    assertEquals(action, "resolve_conflict_interactive");
  },
);

runSerialTest(
  "determineRecoveryAction: merge_conflict (no process) -> resolve_conflict_interactive",
  () => {
    const action = determineRecoveryAction(
      makeTask({ lastStatus: "merge_conflict", hasRunningProcess: false }),
    );
    assertEquals(action, "resolve_conflict_interactive");
  },
);

runSerialTest(
  "getMergeConflictAlternatives returns the two explicit candidates",
  () => {
    const task = makeTask({ lastStatus: "merge_conflict" });
    const alternatives = getMergeConflictAlternatives(task);
    assertEquals(alternatives, [
      "resolve_conflict_interactive",
      "abort_and_revert",
    ]);
  },
);

runSerialTest(
  "determineRecoveryAction: merging unchanged -> user_decision",
  () => {
    const action = determineRecoveryAction(
      makeTask({ lastStatus: "merging" }),
    );
    assertEquals(action, "user_decision");
  },
);

runSerialTest(
  "determineRecoveryAction: executing with running process -> resume_monitoring",
  () => {
    const action = determineRecoveryAction(
      makeTask({ lastStatus: "executing", hasRunningProcess: true }),
    );
    assertEquals(action, "resume_monitoring");
  },
);

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
