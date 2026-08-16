/**
 * CLI Adapter abstraction layer for Gran Maestro.
 *
 * Wraps external CLI tools (Codex, AGY) behind a unified interface
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
  /** Model identifier to pass via --model flag when the provider supports it. */
  model?: string;
  /** Sandbox mode used for Codex execution strategy selection. */
  sandboxMode?: 'read-only' | 'workspace-write' | 'danger-full-access';
}

/** Provider-agnostic interface for invoking an external AI CLI. */
export interface CLIAdapter {
  /** Human-readable provider name (e.g. "codex", "agy"). */
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
 * Execute an executable and argument vector with a timeout.
 *
 * Uses `Deno.Command` when running under Deno. A Node.js
 * `child_process.execFile` equivalent can be substituted for portability.
 *
 * @param executable - Executable name or path.
 * @param args - Arguments passed directly to the executable.
 * @param cwd  - Working directory for the child process.
 * @param timeoutMs - Maximum allowed execution time in ms.
 * @returns A {@link CLIResult} describing the outcome.
 */
export async function runProcessWithTimeout(
  executable: string,
  args: string[],
  cwd: string,
  timeoutMs: number,
): Promise<CLIResult> {
  const start = Date.now();
  const isWindows = (globalThis as { Deno?: { build?: { os: string } } }).Deno?.build?.os === "windows";
  const command = new Deno.Command(executable, {
    args,
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

/** Compatibility helper for the few callers that still provide a shell command. */
export async function runWithTimeout(
  cmd: string,
  cwd: string,
  timeoutMs: number,
): Promise<CLIResult> {
  const isWindows = (globalThis as { Deno?: { build?: { os: string } } }).Deno?.build?.os === "windows";
  return await runProcessWithTimeout(
    isWindows ? "cmd" : "sh",
    isWindows ? ["/c", cmd] : ["-c", cmd],
    cwd,
    timeoutMs,
  );
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
    // Codex 0.147 requires the `exec` subcommand for non-interactive runs.
    // Writable execution uses the approval-review contract; read-only and
    // danger-full-access remain explicit sandbox selections.
    const permissionArgs = opts.sandboxMode === 'read-only'
      ? ['--sandbox', 'read-only']
      : opts.sandboxMode === 'danger-full-access'
      ? ['--sandbox', 'danger-full-access']
      : ['--approve-for-me'];
    const args = ['exec', ...permissionArgs];
    if (opts.model) {
      args.push('--model', opts.model);
    }
    if (opts.outputFormat === 'json') {
      args.push('--json');
    }
    if (opts.ephemeral) {
      args.push('--ephemeral');
    }
    args.push(prompt);
    return await runProcessWithTimeout('codex', args, opts.workingDir, opts.timeout_ms);
  }

  async review(prompt: string, baseBranch: string, opts: CLIOptions): Promise<CLIResult> {
    if (prompt && baseBranch) {
      throw new Error(
        "Codex 0.147 review cannot combine a base target with custom instructions",
      );
    }
    // `--model` is a global Codex option and must precede the `review`
    // subcommand. Codex 0.147 review targets and custom prompts are mutually
    // exclusive, so the adapter reports the conflict instead of dropping text.
    const args: string[] = [];
    if (opts.model) {
      args.push('--model', opts.model);
    }
    if (opts.sandboxMode) {
      args.push('--sandbox', opts.sandboxMode);
    }
    args.push('review');
    if (baseBranch) {
      args.push('--base', baseBranch);
    } else if (prompt) {
      args.push(prompt);
    }
    return await runProcessWithTimeout('codex', args, opts.workingDir, opts.timeout_ms);
  }

  async isAvailable(): Promise<boolean> {
    try {
      const result = await runProcessWithTimeout('codex', ['--version'], '.', 10_000);
      return result.success;
    } catch {
      return false;
    }
  }

  async isReviewAvailable(): Promise<boolean> {
    try {
      const result = await runProcessWithTimeout('codex', ['review', '--help'], '.', 10_000);
      return result.success;
    } catch {
      return false;
    }
  }

  async version(): Promise<string> {
    const result = await runProcessWithTimeout('codex', ['--version'], '.', 10_000);
    return result.stdout.trim();
  }
}

/**
 * AGY CLI adapter.
 *
 * The exact CLI flags are subject to verification against the real binary
 * (`agy --help`). The current implementation uses the non-interactive print mode.
 */
export class AgyAdapter implements CLIAdapter {
  name = 'agy';

  async execute(prompt: string, opts: CLIOptions): Promise<CLIResult> {
    const args = ['--print', prompt, '--dangerously-skip-permissions'];
    if (opts.workingDir) {
      args.push('--add-dir', opts.workingDir);
    }
    if (opts.model) {
      args.push('--model', opts.model);
    }
    if (opts.outputFormat === 'json') {
      args.push('--output-format', 'json');
    }
    return await runProcessWithTimeout('agy', args, opts.workingDir, opts.timeout_ms);
  }

  async isAvailable(): Promise<boolean> {
    try {
      const result = await runProcessWithTimeout('agy', ['--version'], '.', 10_000);
      return result.success;
    } catch {
      return false;
    }
  }

  async version(): Promise<string> {
    const result = await runProcessWithTimeout('agy', ['--version'], '.', 10_000);
    return result.stdout.trim();
  }
}

/** Deprecated compatibility alias for code that still imports GeminiAdapter. */
export class GeminiAdapter extends AgyAdapter {
  override name = 'agy';
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Create a {@link CLIAdapter} for the given provider.
 *
 * @param provider - Either `"codex"` or `"agy"`; `"gemini"` is a deprecated alias.
 * @returns A concrete adapter instance.
 */
export function createAdapter(provider: 'codex' | 'agy' | 'gemini'): CLIAdapter {
  switch (provider) {
    case 'codex':
      return new CodexAdapter();
    case 'agy':
      return new AgyAdapter();
    case 'gemini':
      return new GeminiAdapter();
    default:
      throw new Error(`Unknown CLI provider: ${provider}`);
  }
}
