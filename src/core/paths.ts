// AD-008: single source-of-truth for `.gran-maestro/` path resolution.
//
// All callers should obtain `.gran-maestro/` paths through `paths.<method>()`
// instead of joining strings ad-hoc, so that a non-default basePath cannot
// silently desynchronize between modules.

const GRAN_MAESTRO_DIR = '.gran-maestro';

function stripTrailingSeparators(path: string): string {
  return path.replace(/[\\/]+$/, '') || path;
}

function joinPath(base: string, ...segments: string[]): string {
  return segments.reduce((current, segment) => {
    const cleanBase = stripTrailingSeparators(current);
    const cleanSegment = segment.replace(/^[\\/]+/, '');
    if (cleanBase === '/') {
      return `/${cleanSegment}`;
    }
    if (cleanBase === '.' || cleanBase === '') {
      return cleanSegment;
    }
    return `${cleanBase}/${cleanSegment}`;
  }, base);
}

export function isGranMaestroRoot(candidate: string): boolean {
  const normalized = stripTrailingSeparators(candidate.trim()).replace(/\\/g, '/');
  return normalized.endsWith(`/${GRAN_MAESTRO_DIR}`) || normalized === GRAN_MAESTRO_DIR;
}

export function normalizeGranMaestroBasePath(basePath: string): string {
  const normalized = stripTrailingSeparators(basePath.trim());
  return isGranMaestroRoot(normalized) ? normalized : joinPath(normalized, GRAN_MAESTRO_DIR);
}

export class Paths {
  constructor(private readonly basePath: string) {}

  get root(): string {
    return this.basePath;
  }

  requestRoot(reqId: string): string {
    return joinPath(this.basePath, 'requests', reqId);
  }

  taskRoot(reqId: string, taskSeg: string): string {
    return joinPath(this.requestRoot(reqId), 'tasks', taskSeg);
  }

  statusJson(reqId: string, taskSeg: string): string {
    return joinPath(this.taskRoot(reqId, taskSeg), 'status.json');
  }

  worktreeMeta(taskId: string): string {
    return joinPath(this.basePath, 'worktrees', `${taskId}.meta.json`);
  }

  pendingNdjson(): string {
    return joinPath(this.basePath, 'state', 'skill', 'pending.ndjson');
  }

  hooksLedger(): string {
    return joinPath(this.basePath, 'hooks-ledger.ndjson');
  }

  hooksOverflow(): string {
    return joinPath(this.basePath, 'hooks-ledger.overflow.ndjson');
  }

  archiveDir(): string {
    return joinPath(this.basePath, 'archive');
  }

  stateSnapshot(ppid: string): string {
    return joinPath(this.basePath, 'state', 'snapshots', `${ppid}.json`);
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
        return normalizeGranMaestroBasePath(top);
      }
    }
  } catch (_e) {
    // git unavailable -- fall through to cwd
  }

  return normalizeGranMaestroBasePath(Deno.cwd());
}

/** Module-level singleton initialised from {@link resolveBasePath}. */
export const paths = new Paths(resolveBasePath());
