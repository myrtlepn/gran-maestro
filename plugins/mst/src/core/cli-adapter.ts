/**
 * CLI Adapter abstraction layer for Gran Maestro.
 *
 * Wraps external CLI tools (Codex, Gemini) behind a unified interface
 * so the orchestration engine is decoupled from specific CLI flags and
 * invocation details.
 *
 * @module cli-adapter
 * @see design-decisions.md section 1
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Result returned by every CLI execution. */
export interface CLIResult {
  /** Whether the CLI exited with code 0. */
  success: boolean;
  /** Raw process exit code. */
  exitCode: number;
  /** Captured standard output. */
  stdout: string;
  /** Captured standard error. */
  stderr: string;
  /** Wall-clock execution time in milliseconds. */
  duration_ms: number;
  /** List of files that were created or modified during the run. */
  files_changed: string[];
}

/** Options forwarded to the CLI process. */
export interface CLIOptions {
  /** Worktree (working directory) path for the CLI process. */
  workingDir: string;
  /** Maximum execution time in milliseconds before SIGTERM. */
  timeout_ms: number;
  /** Desired output format. */
  outputFormat?: 'text' | 'json';
  /** When true the CLI should not persist any state between runs. */
  ephemeral?: boolean;
  /** Model identifier to pass via --model flag (e.g. "gemini-3-pro-preview", "gpt-5.3-codex"). */
  model?: string;
  /** Sandbox mode used for Codex execution strategy selection. */
  sandboxMode?: 'workspace-write' | 'danger-full-access';
}

/** Provider-agnostic interface for invoking an external AI CLI. */
export interface CLIAdapter {
  /** Human-readable provider name (e.g. "codex", "gemini"). */
  name: string;
  /** Run a prompt through the CLI and return the structured result. */
  execute(prompt: string, options: CLIOptions): Promise<CLIResult>;
  /** Check whether the CLI binary is installed and reachable. */
  isAvailable(): Promise<boolean>;
  /** Return the CLI version string (e.g. "1.2.3"). */
  version(): Promise<string>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Execute a shell command with a timeout.
 *
 * Uses `Deno.Command` when running under Deno. A Node.js
 * `child_process.execFile` equivalent can be substituted for portability.
 *
 * @param cmd  - The command string to execute.
 * @param cwd  - Working directory for the child process.
 * @param timeoutMs - Maximum allowed execution time in ms.
 * @returns A {@link CLIResult} describing the outcome.
 */
export async function runWithTimeout(
  cmd: string,
  cwd: string,
  timeoutMs: number,
): Promise<CLIResult> {
  const start = Date.now();
  const denoBuild = (globalThis as { Deno?: { build?: { os: string } } }).Deno?.build;
  const isWindows = denoBuild?.os === "windows";

  // Deno-compatible subprocess API
  // Node.js fallback: use child_process.execFile with a timeout option
  const shell = isWindows ? "cmd" : "sh";
  const shellArgs = isWindows ? ["/c", cmd] : ["-c", cmd];
  const command = new Deno.Command(shell, {
    args: shellArgs,
    cwd,
    stdin: 'null',
    stdout: 'piped',
    stderr: 'piped',
  });

  const child = command.spawn();

  // Timeout guard
  const timer = setTimeout(() => {
    try {
      child.kill(isWindows ? "SIGKILL" : "SIGTERM");
    } catch {
      // Process may have already exited
    }
  }, timeoutMs);

  const output = await child.output();
  clearTimeout(timer);

  const duration_ms = Date.now() - start;
  const decoder = new TextDecoder();

  return {
    success: output.code === 0,
    exitCode: output.code,
    stdout: decoder.decode(output.stdout),
    stderr: decoder.decode(output.stderr),
    duration_ms,
    files_changed: [], // Populated by the caller via `git diff --name-only`
  };
}

// ---------------------------------------------------------------------------
// Adapter implementations
// ---------------------------------------------------------------------------

/**
 * Codex CLI adapter.
 *
 * The exact CLI flags are subject to verification against the real binary
 * (`codex --help`). The current implementation uses the best-known invocation.
 */
export class CodexAdapter implements CLIAdapter {
  name = 'codex';

  async execute(prompt: string, opts: CLIOptions): Promise<CLIResult> {
    // Verified: `codex --full-auto` is the non-interactive default mode.
    // For network-required tasks, sandbox can be widened via explicit mode.
    // -C flag / cwd may differ -- using cwd via process spawn.
    const escapedPrompt = prompt.replace(/"/g, '\\"');
    const useDangerSandbox = opts.sandboxMode === 'danger-full-access';
    let cmd = useDangerSandbox
      ? `codex -s danger-full-access -a on-request "${escapedPrompt}"`
      : `codex --full-auto "${escapedPrompt}"`;
    if (opts.model) {
      cmd += ` --model ${opts.model}`;
    }
    if (opts.outputFormat === 'json') {
      cmd += ' --json';
    }
    if (opts.ephemeral) {
      cmd += ' --ephemeral';
    }
    return await runWithTimeout(cmd, opts.workingDir, opts.timeout_ms);
  }

  async review(prompt: string, baseBranch: string, opts: CLIOptions): Promise<CLIResult> {
    const escapedPrompt = prompt.replace(/"/g, '\\"');
    const escapedBaseBranch = baseBranch.replace(/"/g, '\\"');
    let cmd = `codex review --base "${escapedBaseBranch}" "${escapedPrompt}"`;
    if (opts.model) {
      cmd += ` --model ${opts.model}`;
    }
    if (opts.outputFormat === 'json') {
      cmd += ' --json';
    }
    if (opts.ephemeral) {
      cmd += ' --ephemeral';
    }
    return await runWithTimeout(cmd, opts.workingDir, opts.timeout_ms);
  }

  async isAvailable(): Promise<boolean> {
    try {
      const result = await runWithTimeout('codex --version', '.', 10_000);
      return result.success;
    } catch {
      return false;
    }
  }

  async isReviewAvailable(): Promise<boolean> {
    try {
      const result = await runWithTimeout('codex review --help', '.', 10_000);
      return result.success;
    } catch {
      return false;
    }
  }

  async version(): Promise<string> {
    const result = await runWithTimeout('codex --version', '.', 10_000);
    return result.stdout.trim();
  }
}

/**
 * Gemini CLI adapter.
 *
 * The exact CLI flags are subject to verification against the real binary
 * (`gemini --help`). The current implementation uses the best-known invocation.
 */
export class GeminiAdapter implements CLIAdapter {
  name = 'gemini';

  async execute(prompt: string, opts: CLIOptions): Promise<CLIResult> {
    const escapedPrompt = prompt.replace(/"/g, '\\"');
    let cmd = `gemini -p "${escapedPrompt}" --approval-mode yolo --sandbox=false`;
    if (opts.model) {
      cmd += ` --model ${opts.model}`;
    }
    if (opts.outputFormat === 'json') {
      cmd += ' --json';
    }
    return await runWithTimeout(cmd, opts.workingDir, opts.timeout_ms);
  }

  async isAvailable(): Promise<boolean> {
    try {
      const result = await runWithTimeout('gemini --version', '.', 10_000);
      return result.success;
    } catch {
      return false;
    }
  }

  async version(): Promise<string> {
    const result = await runWithTimeout('gemini --version', '.', 10_000);
    return result.stdout.trim();
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Create a {@link CLIAdapter} for the given provider.
 *
 * @param provider - Either `"codex"` or `"gemini"`.
 * @returns A concrete adapter instance.
 */
export function createAdapter(provider: 'codex' | 'gemini'): CLIAdapter {
  switch (provider) {
    case 'codex':
      return new CodexAdapter();
    case 'gemini':
      return new GeminiAdapter();
    default:
      throw new Error(`Unknown CLI provider: ${provider}`);
  }
}
