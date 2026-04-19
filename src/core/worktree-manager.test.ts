import { WorktreeManager } from "./worktree-manager.ts";
import type { WorktreeConfig, WorktreeInfo } from "./worktree-manager.ts";

type CommandCall = {
  shellCommand: string;
  cwd?: string;
};

type ManagerInternals = {
  worktrees: Map<string, WorktreeInfo>;
  persistMeta: (taskId: string, info: WorktreeInfo) => Promise<void>;
  removeMeta: (taskId: string) => Promise<void>;
};

let serial = Promise.resolve();

function runSerialTest(name: string, fn: () => Promise<void>) {
  Deno.test(name, async () => {
    const prev = serial;
    let release = () => {};
    serial = new Promise<void>((resolve) => {
      release = resolve;
    });

    await prev;
    try {
      await fn();
    } finally {
      release();
    }
  });
}

function installCommandMock(
  calls: CommandCall[],
  onCommand: (shellCommand: string) => Promise<Deno.CommandOutput> | Deno.CommandOutput,
): () => void {
  const denoGlobal = Deno as unknown as { Command: new (...args: unknown[]) => unknown };
  const original = denoGlobal.Command;

  class MockCommand {
    constructor(
      _command: string,
      private readonly options: Deno.CommandOptions = {},
    ) {}

    spawn() {
      return {
        output: async () => {
          const shellCommand = this.options.args?.[1] ?? "";
          calls.push({ shellCommand, cwd: this.options.cwd });
          return await onCommand(shellCommand);
        },
        kill: () => {},
      };
    }
  }

  denoGlobal.Command = MockCommand as unknown as typeof denoGlobal.Command;

  return () => {
    denoGlobal.Command = original;
  };
}

function commandOutput(code: number, stderr = ""): Deno.CommandOutput {
  const encoder = new TextEncoder();
  return {
    code,
    stdout: encoder.encode(""),
    stderr: encoder.encode(stderr),
  };
}

async function setupManager(testName: string): Promise<{
  baseDir: string;
  metaPath: string;
  rootDirectory: string;
  info: WorktreeInfo;
  manager: WorktreeManager;
}> {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const baseDir = `/tmp/gran-maestro-${testName}-${suffix}`;
  const projectRoot = `${baseDir}/project`;
  const rootDirectory = `${baseDir}/worktrees`;
  const taskId = "REQ-680-T02";
  const config: WorktreeConfig = {
    root_directory: rootDirectory,
    max_active: 10,
    base_branch: "main",
    stale_timeout_hours: 24,
    auto_cleanup_on_cancel: true,
  };
  const manager = new WorktreeManager(config, projectRoot);
  const info: WorktreeInfo = {
    taskId,
    path: `${rootDirectory}/${taskId}`,
    branch: `gran-maestro/${taskId}`,
    state: "active",
    created_at: "2026-04-19T00:00:00.000Z",
    last_activity_at: "2026-04-19T00:00:00.000Z",
  };

  await Deno.mkdir(projectRoot, { recursive: true });
  await Deno.mkdir(rootDirectory, { recursive: true });
  getInternals(manager).worktrees.set(taskId, info);

  return {
    baseDir,
    metaPath: `${rootDirectory}/${taskId}.meta.json`,
    rootDirectory,
    info,
    manager,
  };
}

function getInternals(manager: WorktreeManager): ManagerInternals {
  return manager as unknown as ManagerInternals;
}

function spyMetadata(manager: WorktreeManager, events: string[]): void {
  const internals = getInternals(manager);
  const originalPersistMeta = internals.persistMeta.bind(manager);
  const originalRemoveMeta = internals.removeMeta.bind(manager);

  internals.persistMeta = async (taskId: string, info: WorktreeInfo) => {
    events.push(`persist:${info.state}`);
    await originalPersistMeta(taskId, info);
  };

  internals.removeMeta = async (taskId: string) => {
    events.push("removeMeta");
    await originalRemoveMeta(taskId);
  };
}

async function readMetaState(metaPath: string): Promise<string> {
  try {
    const raw = await Deno.readTextFile(metaPath);
    const parsed = JSON.parse(raw) as Partial<WorktreeInfo>;
    return typeof parsed.state === "string" ? parsed.state : "missing";
  } catch {
    return "missing";
  }
}

async function readMeta(metaPath: string): Promise<WorktreeInfo> {
  const raw = await Deno.readTextFile(metaPath);
  return JSON.parse(raw) as WorktreeInfo;
}

async function exists(path: string): Promise<boolean> {
  try {
    await Deno.stat(path);
    return true;
  } catch {
    return false;
  }
}

runSerialTest("remove persists cleaning before git cleanup and deletes meta only after branch deletion", async () => {
  const { baseDir, metaPath, info, manager } = await setupManager("remove-success");
  const events: string[] = [];
  const calls: CommandCall[] = [];
  spyMetadata(manager, events);
  const restore = installCommandMock(calls, async (shellCommand) => {
    if (shellCommand.startsWith("git worktree remove")) {
      events.push(`command:worktree-remove:meta=${await readMetaState(metaPath)}`);
    } else if (shellCommand.startsWith("git branch -D")) {
      events.push("command:branch-delete");
    }
    return commandOutput(0);
  });

  try {
    await manager.remove(info.taskId, true);
  } finally {
    restore();
    await Deno.remove(baseDir, { recursive: true });
  }

  assertEquals(events, [
    "persist:cleaning",
    "command:worktree-remove:meta=cleaning",
    "command:branch-delete",
    "removeMeta",
  ]);
  assertEquals(calls.map((call) => call.shellCommand), [
    `git worktree remove --force "${info.path}"`,
    `git branch -D "${info.branch}"`,
  ]);
  assertEquals(await exists(metaPath), false);
});

runSerialTest("remove preserves clean_failed meta when git worktree remove fails", async () => {
  const { baseDir, metaPath, info, manager } = await setupManager("remove-worktree-fail");
  const events: string[] = [];
  const calls: CommandCall[] = [];
  spyMetadata(manager, events);
  const restore = installCommandMock(calls, async (shellCommand) => {
    if (shellCommand.startsWith("git worktree remove")) {
      events.push(`command:worktree-remove:meta=${await readMetaState(metaPath)}`);
      return commandOutput(1, "worktree remove failed");
    }
    return commandOutput(0);
  });

  try {
    await manager.remove(info.taskId, true);
    const meta = await readMeta(metaPath);

    assertEquals(events, [
      "persist:cleaning",
      "command:worktree-remove:meta=cleaning",
      "persist:clean_failed",
    ]);
    assertEquals(calls.map((call) => call.shellCommand), [
      `git worktree remove --force "${info.path}"`,
    ]);
    assertEquals(await exists(metaPath), true);
    assertEquals(meta.state, "clean_failed");
  } finally {
    restore();
    await Deno.remove(baseDir, { recursive: true });
  }
});

runSerialTest("remove preserves clean_failed meta when git branch deletion fails", async () => {
  const { baseDir, metaPath, info, manager } = await setupManager("remove-branch-fail");
  const events: string[] = [];
  const calls: CommandCall[] = [];
  spyMetadata(manager, events);
  const restore = installCommandMock(calls, async (shellCommand) => {
    if (shellCommand.startsWith("git worktree remove")) {
      events.push(`command:worktree-remove:meta=${await readMetaState(metaPath)}`);
      return commandOutput(0);
    }
    if (shellCommand.startsWith("git branch -D")) {
      events.push("command:branch-delete");
      return commandOutput(1, "branch delete failed");
    }
    return commandOutput(0);
  });

  try {
    await manager.remove(info.taskId, true);
    const meta = await readMeta(metaPath);

    assertEquals(events, [
      "persist:cleaning",
      "command:worktree-remove:meta=cleaning",
      "command:branch-delete",
      "persist:clean_failed",
    ]);
    assertEquals(calls.map((call) => call.shellCommand), [
      `git worktree remove --force "${info.path}"`,
      `git branch -D "${info.branch}"`,
    ]);
    assertEquals(await exists(metaPath), true);
    assertEquals(meta.state, "clean_failed");
  } finally {
    restore();
    await Deno.remove(baseDir, { recursive: true });
  }
});

runSerialTest("listActive filters cleaning worktrees loaded from meta", async () => {
  const { baseDir, rootDirectory, info, manager } = await setupManager("list-active-cleaning");
  const calls: CommandCall[] = [];
  const activeInfo: WorktreeInfo = {
    ...info,
    taskId: "REQ-680-T03",
    path: `${rootDirectory}/REQ-680-T03`,
    branch: "gran-maestro/REQ-680-T03",
    state: "active",
  };
  const cleaningInfo: WorktreeInfo = {
    ...info,
    state: "cleaning",
  };
  getInternals(manager).worktrees.clear();
  await Deno.writeTextFile(
    `${rootDirectory}/${cleaningInfo.taskId}.meta.json`,
    JSON.stringify(cleaningInfo),
  );
  await Deno.writeTextFile(
    `${rootDirectory}/${activeInfo.taskId}.meta.json`,
    JSON.stringify(activeInfo),
  );
  const restore = installCommandMock(calls, () => commandOutput(0));

  try {
    const active = await manager.listActive();

    assertEquals(active.map((worktree) => worktree.taskId), [activeInfo.taskId]);
    assertEquals(calls.map((call) => call.shellCommand), ["git worktree list --porcelain"]);
  } finally {
    restore();
    await Deno.remove(baseDir, { recursive: true });
  }
});

function assertEquals(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Assertion failed: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}
