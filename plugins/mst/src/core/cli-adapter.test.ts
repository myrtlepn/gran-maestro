import { AgyAdapter, CodexAdapter, runProcessWithTimeout, runWithTimeout } from "./cli-adapter.ts";

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

function getSpawnedProcess(calls: CommandCall[]): { command: string; args: string[] } {
  return { command: calls[0]?.command ?? "", args: calls[0]?.options.args ?? [] };
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

runSerialTest("runProcessWithTimeout passes spaces and quotes as one argument", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const value = 'ordinary prompt with spaces and "quotes"';
  try {
    await runProcessWithTimeout("probe", [value], ".", 1000);
  } finally {
    restore();
  }
  assertEquals(getSpawnedProcess(calls), { command: "probe", args: [value] });
});

runSerialTest("CodexAdapter.execute uses the explicit danger sandbox", async () => {
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

  assertEquals(getSpawnedProcess(calls), {
    command: "codex",
    args: ["exec", "--sandbox", "danger-full-access", "network task"],
  });
});

runSerialTest("CodexAdapter.execute uses approval review for default writable execution", async () => {
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

  assertEquals(getSpawnedProcess(calls), {
    command: "codex",
    args: ["exec", "--approve-for-me", "safe task"],
  });
});

runSerialTest("CodexAdapter.execute keeps explicit workspace-write on the approval-review path", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new CodexAdapter();

  try {
    await adapter.execute("write task", {
      workingDir: ".",
      timeout_ms: 1000,
      sandboxMode: "workspace-write",
    });
  } finally {
    restore();
  }

  assertEquals(getSpawnedProcess(calls), {
    command: "codex",
    args: ["exec", "--approve-for-me", "write task"],
  });
});

runSerialTest("CodexAdapter.execute uses the read-only sandbox without writable approval", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new CodexAdapter();

  try {
    await adapter.execute("inspect task", {
      workingDir: ".",
      timeout_ms: 1000,
      sandboxMode: "read-only",
    });
  } finally {
    restore();
  }

  assertEquals(getSpawnedProcess(calls), {
    command: "codex",
    args: ["exec", "--sandbox", "read-only", "inspect task"],
  });
});

runSerialTest("CodexAdapter.execute preserves prompt and model argv", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new CodexAdapter();

  try {
    await adapter.execute('explain the "quoted value"', {
      workingDir: ".",
      timeout_ms: 1000,
      model: "gpt model preview",
      sandboxMode: "read-only",
    });
  } finally {
    restore();
  }

  assertEquals(getSpawnedProcess(calls), {
    command: "codex",
    args: [
      "exec",
      "--sandbox",
      "read-only",
      "--model",
      "gpt model preview",
      'explain the "quoted value"',
    ],
  });
});

runSerialTest("CodexAdapter.review keeps global model before the review subcommand", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new CodexAdapter();

  try {
    await adapter.review("", "release branch", {
      workingDir: ".",
      timeout_ms: 1000,
      model: "gpt-5.6-sol",
      outputFormat: "json",
      ephemeral: true,
      sandboxMode: "read-only",
    });
  } finally {
    restore();
  }

  assertEquals(
    getSpawnedProcess(calls),
    {
      command: "codex",
      args: [
        "--model",
        "gpt-5.6-sol",
        "--sandbox",
        "read-only",
        "review",
        "--base",
        "release branch",
      ],
    },
  );
});

runSerialTest("CodexAdapter.review rejects instructions plus base", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new CodexAdapter();
  let rejected = false;

  try {
    await adapter.review("custom instructions", "master", {
      workingDir: ".",
      timeout_ms: 1000,
    });
  } catch (error) {
    rejected = String(error).includes("cannot combine a base target with custom instructions");
  } finally {
    restore();
  }

  assert(rejected);
  assertEquals(calls.length, 0);
});

runSerialTest("CodexAdapter.review uses prompt only when no target is supplied", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new CodexAdapter();

  try {
    await adapter.review("focus on parser safety", "", {
      workingDir: ".",
      timeout_ms: 1000,
    });
  } finally {
    restore();
  }

  assertEquals(
    getSpawnedProcess(calls),
    { command: "codex", args: ["review", "focus on parser safety"] },
  );
});

runSerialTest("AgyAdapter preserves prompt, model, and working directory argv", async () => {
  const calls: CommandCall[] = [];
  const restore = installCommandMock(calls);
  const adapter = new AgyAdapter();

  try {
    await adapter.execute('review "normal quotes"', {
      workingDir: "/tmp/project with spaces",
      timeout_ms: 1000,
      model: "agy model preview",
      outputFormat: "json",
    });
  } finally {
    restore();
  }

  assertEquals(getSpawnedProcess(calls), {
    command: "agy",
    args: [
      "--print",
      'review "normal quotes"',
      "--dangerously-skip-permissions",
      "--add-dir",
      "/tmp/project with spaces",
      "--model",
      "agy model preview",
      "--output-format",
      "json",
    ],
  });
});

runSerialTest("Codex 0.147 parser accepts current review and network shapes", async () => {
  const codexVersion = await new Deno.Command("codex", {
    args: ["--version"],
    stdout: "piped",
    stderr: "piped",
  }).output();
  assertEquals(codexVersion.code, 0);
  assert(
    new TextDecoder().decode(codexVersion.stdout).includes("codex-cli 0.147."),
    "real parser smoke requires Codex CLI 0.147.x",
  );

  const runParser = async (args: string[]) => {
    return await new Deno.Command("codex", {
      args,
      cwd: ".",
      stdin: "null",
      stdout: "piped",
      stderr: "piped",
    }).output();
  };

  const invalidConfigOverride = "definitely_unknown_req946_key=true";
  const validShapes = [
    [
      "-c",
      invalidConfigOverride,
      "--model",
      "parser-probe",
      "--sandbox",
      "read-only",
      "review",
      "--strict-config",
      "--base",
      "HEAD",
    ],
    [
      "exec",
      "-c",
      invalidConfigOverride,
      "--strict-config",
      "--sandbox",
      "danger-full-access",
      "--model",
      "parser-probe",
      "--ephemeral",
      "parser probe",
    ],
  ];
  for (const args of validShapes) {
    const output = await runParser(args);
    const stderr = new TextDecoder().decode(output.stderr);
    assertEquals(output.code, 1);
    assert(
      stderr.includes("unknown configuration field `definitely_unknown_req946_key`"),
      `expected current shape to reach strict config validation: codex ${args.join(" ")}`,
    );
  }

  const invalidHistoricalShapes = [
    ["review", "--model", "parser-probe", "--base", "HEAD"],
    ["review", "--json", "--base", "HEAD"],
    ["review", "--ephemeral", "--base", "HEAD"],
    ["review", "--base", "HEAD", "custom prompt"],
    [
      "exec",
      "--sandbox",
      "danger-full-access",
      "-a",
      "on-request",
      "parser probe",
    ],
  ];
  for (const args of invalidHistoricalShapes) {
    const output = await runParser(args);
    assertEquals(output.code, 2);
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
