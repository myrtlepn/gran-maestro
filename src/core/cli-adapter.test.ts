import { CodexAdapter, runWithTimeout } from "./cli-adapter.ts";

type CommandCall = {
  command: string;
  options: {
    args?: string[];
    cwd?: string;
    stdout?: "piped" | "inherit" | "null";
    stderr?: "piped" | "inherit" | "null";
    stdin?: "piped" | "inherit" | "null";
  };
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
): () => void {
  const denoGlobal = Deno as unknown as { Command: new (...args: unknown[]) => unknown };
  const original = denoGlobal.Command;

  class MockCommand {
    constructor(command: string, options: CommandCall["options"]) {
      calls.push({ command, options });
    }

    spawn() {
      return {
        output: async () => ({
          code: 0,
          stdout: new Uint8Array(),
          stderr: new Uint8Array(),
        }),
        kill: () => {},
      };
    }
  }

  denoGlobal.Command = MockCommand as unknown as typeof denoGlobal.Command;

  return () => {
    denoGlobal.Command = original;
  };
}

function getSpawnedShellCommand(calls: CommandCall[]): string {
  const args = calls[0]?.options.args ?? [];
  return args[1] ?? "";
}

runSerialTest("runWithTimeout sets stdin to null for background-safe execution", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);

  try {
    await runWithTimeout("echo ok", ".", 1000);
  } finally {
    restore();
  }

  assertEquals(calls.length, 1);
  assertEquals(calls[0].options.stdin, "null");
});

runSerialTest("CodexAdapter.execute uses danger sandbox flags when sandboxMode is set", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new CodexAdapter();

  try {
    await adapter.execute("network task", {
      workingDir: ".",
      timeout_ms: 1000,
      sandboxMode: "danger-full-access",
    });
  } finally {
    restore();
  }

  const command = getSpawnedShellCommand(calls);
  assert(command.includes("-s danger-full-access"));
  assert(command.includes("-a on-request"));
  assert(!command.includes("--full-auto"));
});

runSerialTest("CodexAdapter.execute keeps --full-auto when sandboxMode is not provided", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new CodexAdapter();

  try {
    await adapter.execute("safe task", {
      workingDir: ".",
      timeout_ms: 1000,
    });
  } finally {
    restore();
  }

  const command = getSpawnedShellCommand(calls);
  assert(command.includes("--full-auto"));
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
