/**
 * Git worktree lifecycle manager for Gran Maestro.
 *
 * Handles creation, merge (rebase + squash), stale detection, and
 * cleanup of task-level git worktrees.
 *
 * @module worktree-manager
 * @see design-decisions.md section 5
 */

import { runWithTimeout } from './cli-adapter.ts';
import { atomicWriteJSON } from './concurrency.ts';
// @ts-ignore: Node resolution may be unavailable in non-Node type-check envs; shimmed for runtime usage.
import { isAbsolute, resolve } from 'node:path';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Lifecycle state of a single worktree.
 *
 * Follows the state diagram from design-decisions.md section 5.
 */
export type WorktreeState =
  | 'creating'
  | 'active'
  | 'stale'
  | 'pre_merge'
  | 'merged'
  | 'cleaning'
  | 'cleaned'
  | 'create_failed'
  | 'error'
  | 'conflict'
  | 'clean_failed';

/** Configuration for the worktree subsystem. */
export interface WorktreeConfig {
  /** Root directory where worktrees are created. */
  root_directory: string;
  /** Maximum number of active worktrees allowed. */
  max_active: number;
  /** Branch from which worktrees are forked. */
  base_branch: string;
  /** Hours after which an unused worktree is considered stale. */
  stale_timeout_hours: number;
  /** Whether to auto-clean worktrees when a task is cancelled. */
  auto_cleanup_on_cancel: boolean;
}

/** Default worktree settings from design-decisions.md section 5. */
export const DEFAULT_WORKTREE_CONFIG: Readonly<WorktreeConfig> = {
  root_directory: '.gran-maestro/worktrees',
  max_active: 10,
  base_branch: 'main',
  stale_timeout_hours: 24,
  auto_cleanup_on_cancel: true,
} as const;

/** Metadata about a single worktree instance. */
const MST_HOOK_MARKER_FILES = new Set([
  '.mst-hook-version',
  'stop-agile-gate-reasons.json',
]);

function isMstOwnedWorktreeHookFile(name: string): boolean {
  return (name.startsWith('mst-') && name.endsWith('.sh')) || MST_HOOK_MARKER_FILES.has(name);
}

export interface WorktreeInfo {
  /** Task identifier that owns this worktree. */
  taskId: string;
  /** Absolute path to the worktree directory. */
  path: string;
  /** Git branch name backing this worktree. */
  branch: string;
  /** Current lifecycle state. */
  state: WorktreeState;
  /** ISO 8601 timestamp of when the worktree was created. */
  created_at: string;
  /** ISO 8601 timestamp of last activity in the worktree. */
  last_activity_at: string;
}

/** Result of a merge attempt. */
export type MergeResult =
  | { status: 'success' }
  | { status: 'conflict'; details: string }
  | { status: 'error'; message: string };

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

/**
 * Manages the full lifecycle of task-level git worktrees.
 *
 * Each task gets its own worktree so that multiple tasks can execute
 * in parallel without interfering with each other.
 */
export class WorktreeManager {
  private worktrees: Map<string, WorktreeInfo> = new Map();
  private readonly rootDirectory: string;
  private readonly projectRoot: string;

  constructor(
    private readonly config: WorktreeConfig = DEFAULT_WORKTREE_CONFIG,
    /** Project root (the main git repo). */
    projectRoot: string = '.',
  ) {
    this.projectRoot = isAbsolute(projectRoot)
      ? projectRoot
      : resolve(Deno.cwd(), projectRoot);
    this.rootDirectory = isAbsolute(config.root_directory)
      ? config.root_directory
      : resolve(this.projectRoot, config.root_directory);
  }

  private getMetaPath(taskId: string): string {
    return resolve(this.rootDirectory, `${taskId}.meta.json`);
  }

  private async persistMeta(taskId: string, info: WorktreeInfo): Promise<void> {
    try {
      await atomicWriteJSON(this.getMetaPath(taskId), info);
    } catch {
      // Non-fatal: metadata persistence failure should not break worktree lifecycle.
    }
  }

  private async loadMeta(taskId: string): Promise<WorktreeInfo | null> {
    try {
      const raw = await Deno.readTextFile(this.getMetaPath(taskId));
      const parsed = JSON.parse(raw) as Partial<WorktreeInfo>;

      if (
        typeof parsed === 'object' &&
        parsed !== null &&
        typeof parsed.taskId === 'string' &&
        typeof parsed.path === 'string' &&
        typeof parsed.branch === 'string' &&
        typeof parsed.state === 'string' &&
        typeof parsed.created_at === 'string' &&
        typeof parsed.last_activity_at === 'string'
      ) {
        return {
          taskId: parsed.taskId,
          path: isAbsolute(parsed.path)
            ? parsed.path
            : resolve(this.projectRoot, parsed.path),
          branch: parsed.branch,
          state: parsed.state as WorktreeState,
          created_at: parsed.created_at,
          last_activity_at: parsed.last_activity_at,
        };
      }
    } catch {
      // Ignore malformed/missing metadata.
    }
    return null;
  }

  private async removeMeta(taskId: string): Promise<void> {
    try {
      await Deno.remove(this.getMetaPath(taskId));
    } catch {
      // Best-effort cleanup.
    }
  }

  /**
   * Create a new git worktree for a task.
   *
   * @param taskId     - Task identifier (e.g. "REQ-001-01").
   * @param baseBranch - Branch to fork from (defaults to config.base_branch).
   * @returns Absolute path to the created worktree.
   * @throws {Error} If the maximum number of active worktrees is reached.
   */
  async create(taskId: string, baseBranch?: string): Promise<string> {
    const activeCount = await this.listActive();
    if (activeCount.length >= this.config.max_active) {
      throw new Error(
        `Maximum active worktrees reached (${this.config.max_active}). ` +
          'Clean up stale worktrees before creating new ones.',
      );
    }

    const branch = `gran-maestro/${taskId}`;
    const worktreePath = resolve(this.rootDirectory, taskId);
    const base = baseBranch ?? this.config.base_branch;

    const info: WorktreeInfo = {
      taskId,
      path: worktreePath,
      branch,
      state: 'creating',
      created_at: new Date().toISOString(),
      last_activity_at: new Date().toISOString(),
    };
    this.worktrees.set(taskId, info);

    try {
      // Ensure the root directory exists
      // Node.js fallback: fs.promises.mkdir
      try {
        await Deno.mkdir(this.rootDirectory, { recursive: true });
      } catch {
        // May already exist
      }

      const cmd = `git worktree add -b "${branch}" "${worktreePath}" "${base}"`;
      const result = await runWithTimeout(cmd, this.projectRoot, 30_000);

      if (!result.success) {
        info.state = 'create_failed';
        throw new Error(`Failed to create worktree: ${result.stderr}`);
      }

      info.state = 'active';
      try {
        const sourceHooksDir = resolve(this.projectRoot, '.claude/hooks');
        const targetHooksDir = resolve(worktreePath, '.claude/hooks');
        const denoFs = Deno as typeof Deno & {
          copyFile: (src: string, dest: string) => Promise<void>;
          chmod: (path: string, mode: number) => Promise<void>;
        };
        let targetHooksCreated = false;

        for await (const entry of Deno.readDir(sourceHooksDir)) {
          if (!entry.isFile || isMstOwnedWorktreeHookFile(entry.name)) continue;
          if (!targetHooksCreated) {
            await Deno.mkdir(targetHooksDir, { recursive: true });
            targetHooksCreated = true;
          }

          const sourcePath = resolve(sourceHooksDir, entry.name);
          const targetPath = resolve(targetHooksDir, entry.name);
          await denoFs.copyFile(sourcePath, targetPath);
          await denoFs.chmod(targetPath, 0o755);
        }
      } catch {
        // Non-fatal: custom hook copy failure should not block worktree creation.
      }
      await this.persistMeta(taskId, info);
      return worktreePath;
    } catch (err) {
      info.state = 'create_failed';
      await this.persistMeta(taskId, info);
      throw err;
    }
  }

  /**
   * Remove a worktree and clean up its branch.
   *
   * @param taskId - Task identifier.
   * @param force  - Pass `true` to use `--force` removal.
   */
  async remove(taskId: string, force = false): Promise<void> {
    const info = this.worktrees.get(taskId);
    const worktreePath =
      info?.path ?? resolve(this.rootDirectory, taskId);
    const branch = info?.branch ?? `gran-maestro/${taskId}`;

    if (info) {
      info.state = 'cleaning';
      await this.persistMeta(taskId, info);
    }

    try {
      const forceFlag = force ? ' --force' : '';
      const removeCmd = `git worktree remove${forceFlag} "${worktreePath}"`;
      const removeResult = await runWithTimeout(removeCmd, this.projectRoot, 30_000);
      if (!removeResult.success) {
        throw new Error(`Failed to remove worktree: ${removeResult.stderr}`);
      }

      // Clean up branch
      const branchCmd = `git branch -D "${branch}"`;
      const branchResult = await runWithTimeout(branchCmd, this.projectRoot, 10_000);
      if (!branchResult.success) {
        throw new Error(`Failed to delete worktree branch: ${branchResult.stderr}`);
      }

      if (info) {
        info.state = 'cleaned';
      }
      await this.removeMeta(taskId);
    } catch {
      if (info) {
        info.state = 'clean_failed';
        await this.persistMeta(taskId, info);
      }
    }
  }

  /**
   * Merge a task's worktree into the target branch using rebase + squash.
   *
   * @param taskId       - Task identifier.
   * @param targetBranch - Branch to merge into (usually `main`).
   * @returns A {@link MergeResult} indicating success, conflict, or error.
   */
  async merge(taskId: string, targetBranch: string): Promise<MergeResult> {
    const info = this.worktrees.get(taskId);
    const worktreePath =
      info?.path ?? resolve(this.rootDirectory, taskId);
    const branch = info?.branch ?? `gran-maestro/${taskId}`;

    if (info) {
      info.state = 'pre_merge';
      await this.persistMeta(taskId, info);
    }

    try {
      // Step 1: rebase onto target
      const rebaseCmd = `git rebase "${targetBranch}"`;
      const rebaseResult = await runWithTimeout(rebaseCmd, worktreePath, 60_000);

      if (!rebaseResult.success) {
        // Abort rebase on conflict
        await runWithTimeout('git rebase --abort', worktreePath, 10_000);
        if (info) info.state = 'conflict';
        if (info) await this.persistMeta(taskId, info);
        return { status: 'conflict', details: rebaseResult.stderr };
      }

      // Step 2: squash merge from the project root
      const mergeCmd = `git merge --squash "${branch}"`;
      const mergeResult = await runWithTimeout(mergeCmd, this.projectRoot, 60_000);

      if (!mergeResult.success) {
        if (info) info.state = 'conflict';
        if (info) await this.persistMeta(taskId, info);
        return { status: 'conflict', details: mergeResult.stderr };
      }

      // Step 3: commit the squash
      const commitCmd = `git commit -m "[${taskId}] squash merge from ${branch}"`;
      const commitResult = await runWithTimeout(commitCmd, this.projectRoot, 10_000);

      if (!commitResult.success) {
        let resetNote = '';
        try {
          const resetResult = await runWithTimeout(
            'git reset --merge',
            this.projectRoot,
            10_000,
          );
          if (!resetResult.success) {
            resetNote = `Reset failed: ${resetResult.stderr}`;
          }
        } catch (err) {
          resetNote = `Reset failed: ${
            err instanceof Error ? err.message : String(err)
          }`;
        }

        if (info) {
          info.state = 'error';
          await this.persistMeta(taskId, info);
        }

        const message = resetNote
          ? `${commitResult.stderr}\n${resetNote}`
          : commitResult.stderr;
        return { status: 'error', message };
      }

      if (info) info.state = 'merged';
      if (info) await this.persistMeta(taskId, info);
      return { status: 'success' };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (info) {
        info.state = 'error';
        await this.persistMeta(taskId, info);
      }
      return { status: 'error', message };
    }
  }

  /**
   * List all currently tracked (non-cleaned) worktrees.
   *
   * @returns Array of {@link WorktreeInfo} for active worktrees.
   */
  async listActive(): Promise<WorktreeInfo[]> {
    try {
      for await (const entry of Deno.readDir(this.rootDirectory)) {
        if (!entry.isFile || !entry.name.endsWith('.meta.json')) {
          continue;
        }

        const taskId = entry.name.replace('.meta.json', '');
        if (this.worktrees.has(taskId)) {
          continue;
        }

        const meta = await this.loadMeta(taskId);
        if (!meta) {
          continue;
        }
        this.worktrees.set(taskId, meta);
      }
    } catch {
      // Directory may not exist yet.
    }

    // Also refresh from git for worktrees we might not be tracking in memory
    try {
      const result = await runWithTimeout(
        'git worktree list --porcelain',
        this.projectRoot,
        10_000,
      );
      if (result.success) {
        // Parse porcelain output to discover worktrees we haven't tracked yet
        const lines = result.stdout.split('\n');
        for (const line of lines) {
          if (line.startsWith('worktree ') && line.includes('gran-maestro')) {
            const wtPath = line.replace('worktree ', '').trim();
            // Extract task ID from path
            const parts = wtPath.split('/');
            const taskId = parts[parts.length - 1];
            if (taskId && !this.worktrees.has(taskId)) {
              const meta = await this.loadMeta(taskId);
              if (meta) {
                this.worktrees.set(taskId, meta);
                continue;
              }

              this.worktrees.set(taskId, {
                taskId,
                path: wtPath,
                branch: `gran-maestro/${taskId}`,
                state: 'active',
                created_at: new Date().toISOString(),
                last_activity_at: new Date().toISOString(),
              });
            }
          }
        }
      }
    } catch {
      // Non-critical -- fall back to in-memory tracking only
    }

    return Array.from(this.worktrees.values()).filter(
      (wt) => !['cleaning', 'cleaned', 'create_failed', 'clean_failed'].includes(wt.state),
    );
  }

  /**
   * Detect worktrees that have been inactive longer than `timeoutHours`.
   *
   * @param timeoutHours - Inactivity threshold in hours.
   * @returns Array of stale {@link WorktreeInfo} entries.
   */
  async detectStale(timeoutHours?: number): Promise<WorktreeInfo[]> {
    const threshold = (timeoutHours ?? this.config.stale_timeout_hours) * 60 * 60 * 1_000;
    const now = Date.now();
    const active = await this.listActive();

    return active.filter((wt) => {
      const lastActivity = new Date(wt.last_activity_at).getTime();
      return now - lastActivity > threshold;
    });
  }

  /**
   * Full cleanup of a task's worktree.
   *
   * Kills any running CLI process (by convention), removes the worktree
   * and branch, and marks the internal state as cleaned.
   *
   * @param taskId - Task identifier.
   */
  async cleanup(taskId: string): Promise<void> {
    // Attempt to kill any running CLI process associated with this worktree.
    // The actual PID tracking is done by the orchestration engine; here we
    // do a best-effort pkill by working directory pattern.
    const worktreePath = resolve(this.rootDirectory, taskId);
    try {
      await runWithTimeout(
        `pkill -f "${worktreePath}" || true`,
        this.projectRoot,
        5_000,
      );
    } catch {
      // Non-fatal
    }

    // Remove worktree + branch
    await this.remove(taskId, true);
  }
}
