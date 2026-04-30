// AD-008: single source-of-truth for `.gran-maestro/` path resolution.
//
// All callers should obtain `.gran-maestro/` paths through `paths.<method>()`
// instead of joining strings ad-hoc, so that a non-default basePath cannot
// silently desynchronize between modules.

// @ts-ignore: Node resolution may be unavailable in non-Node type-check envs; shimmed for runtime usage.
import { join } from 'node:path';

export class Paths {
  constructor(private readonly basePath: string) {}

  get root(): string {
    return this.basePath;
  }

  requestRoot(reqId: string): string {
    return join(this.basePath, 'requests', reqId);
  }

  taskRoot(reqId: string, taskSeg: string): string {
    return join(this.requestRoot(reqId), 'tasks', taskSeg);
  }

  statusJson(reqId: string, taskSeg: string): string {
    return join(this.taskRoot(reqId, taskSeg), 'status.json');
  }

  worktreeMeta(taskId: string): string {
    return join(this.basePath, 'worktrees', `${taskId}.meta.json`);
  }

  pendingNdjson(): string {
    return join(this.basePath, 'state', 'skill', 'pending.ndjson');
  }

  hooksLedger(): string {
    return join(this.basePath, 'hooks-ledger.ndjson');
  }

  hooksOverflow(): string {
    return join(this.basePath, 'hooks-ledger.overflow.ndjson');
  }

  archiveDir(): string {
    return join(this.basePath, 'archive');
  }

  stateSnapshot(ppid: string): string {
    return join(this.basePath, 'state', 'snapshots', `${ppid}.json`);
  }
}

/**
 * Resolve the active `.gran-maestro/` base path.
 *
 * Priority: (1) `MST_BASE_PATH` environment variable,
 *           (2) `<git toplevel>/.gran-maestro` if inside a git repository,
 *           (3) `<cwd>/.gran-maestro` as a final fallback.
 */
export function resolveBasePath(): string {
  const envPath = Deno.env.get('MST_BASE_PATH');
  if (envPath && envPath.trim().length > 0) {
    return envPath.trim();
  }

  try {
    const cmd = new Deno.Command('git', {
      args: ['rev-parse', '--show-toplevel'],
      stdout: 'piped',
      stderr: 'null',
    });
    const output = cmd.outputSync();
    if (output.code === 0) {
      const top = new TextDecoder().decode(output.stdout).trim();
      if (top.length > 0) {
        return join(top, '.gran-maestro');
      }
    }
  } catch (_e) {
    // git unavailable -- fall through to cwd
  }

  return join(Deno.cwd(), '.gran-maestro');
}

/** Module-level singleton initialised from {@link resolveBasePath}. */
export const paths = new Paths(resolveBasePath());
