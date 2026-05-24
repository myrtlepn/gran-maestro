/**
 * Concurrency control primitives for Gran Maestro.
 *
 * Provides atomic file writes, advisory file locks, CAS-style status
 * updates, atomic request-ID allocation, and a bounded task queue.
 *
 * @module concurrency
 * @see design-decisions.md section 4
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Handle returned by {@link acquireLock}. Must be passed to {@link releaseLock}. */
export interface LockHandle {
  /** Path to the lock file. */
  path: string;
  /** Timestamp (ms) when the lock was acquired. */
  acquired_at: number;
}

/** Configuration knobs for parallel execution limits. */
export interface ConcurrencyConfig {
  /** Maximum tasks executing simultaneously. */
  max_parallel_tasks: number;
  /** Maximum reviews executing simultaneously. */
  max_parallel_reviews: number;
  /** Queue ordering strategy. */
  queue_strategy: 'fifo' | 'priority';
}

/** Default concurrency settings from design-decisions.md section 4. */
export const DEFAULT_CONCURRENCY_CONFIG: Readonly<ConcurrencyConfig> = {
  max_parallel_tasks: 5,
  max_parallel_reviews: 3,
  queue_strategy: 'fifo',
} as const;

// ---------------------------------------------------------------------------
// Atomic file operations
// ---------------------------------------------------------------------------

/**
 * Write JSON data atomically using the write-to-temp + rename pattern.
 *
 * POSIX `rename(2)` is atomic on the same filesystem, preventing partial
 * reads by concurrent processes.
 *
 * @param path - Destination file path.
 * @param data - Serializable data to write.
 */
export async function atomicWriteJSON(
  path: string,
  data: unknown,
): Promise<void> {
  const tmp = `${path}.${Date.now()}.tmp`;
  const content = JSON.stringify(data, null, 2);

  // Deno API -- Node.js fallback: fs.promises.writeFile + fs.promises.rename
  await Deno.writeTextFile(tmp, content);
  await Deno.rename(tmp, path);
}

// ---------------------------------------------------------------------------
// Advisory file lock
// ---------------------------------------------------------------------------

/**
 * Acquire an advisory file lock by atomically creating a lock file.
 *
 * Spins with exponential backoff until the lock is obtained or the
 * timeout expires.
 *
 * @param lockPath  - Path to the `.lock` file.
 * @param timeoutMs - Maximum time to wait for the lock (ms).
 * @returns A {@link LockHandle} that must be released via {@link releaseLock}.
 * @throws {Error} If the lock cannot be acquired within the timeout.
 */
export async function acquireLock(
  lockPath: string,
  timeoutMs: number,
): Promise<LockHandle> {
  const deadline = Date.now() + timeoutMs;
  let delay = 50; // initial backoff ms

  while (Date.now() < deadline) {
    try {
      // Deno.mkdir with recursive:false fails if dir already exists -- acts as an atomic test-and-set.
      // Node.js fallback: fs.promises.mkdir(lockPath, { recursive: false })
      await Deno.mkdir(lockPath, { recursive: false });
      return { path: lockPath, acquired_at: Date.now() };
    } catch (e) {
      if (e instanceof Deno.errors.AlreadyExists) {
        // Check for stale lock (> 30s old)
        try {
          const info = await Deno.stat(lockPath);
          if (info.mtime && Date.now() - info.mtime.getTime() > 30_000) {
            // Stale lock -- force remove and retry
            await Deno.remove(lockPath, { recursive: true });
            continue;
          }
        } catch {
          // stat failed -- lock may have been released between check and stat
        }
        // Wait with exponential backoff
        await new Promise((r) => setTimeout(r, delay));
        delay = Math.min(delay * 2, 1000);
        continue;
      }
      throw e;
    }
  }

  throw new Error(`Failed to acquire lock at ${lockPath} within ${timeoutMs}ms`);
}

/**
 * Release an advisory file lock.
 *
 * @param lock - The {@link LockHandle} returned by {@link acquireLock}.
 */
export async function releaseLock(lock: LockHandle): Promise<void> {
  try {
    // Node.js fallback: fs.promises.rm(lock.path, { recursive: true })
    await Deno.remove(lock.path, { recursive: true });
  } catch {
    // Lock may already have been released or cleaned up
  }
}

// ---------------------------------------------------------------------------
// CAS status update
// ---------------------------------------------------------------------------

/**
 * Read a JSON file, apply a mutation via `updater`, and write back
 * atomically while holding a file lock.
 *
 * Implements the Compare-And-Swap pattern from design-decisions.md
 * section 4.1.
 *
 * @param path    - Path to the JSON file.
 * @param updater - Pure function that receives the current value and
 *                  returns the new value to persist.
 */
export async function updateStatusAtomic(
  path: string,
  updater: (current: unknown) => unknown,
): Promise<void> {
  const lockPath = `${path}.lock`;
  const lock = await acquireLock(lockPath, 5_000);
  try {
    // Node.js fallback: fs.promises.readFile
    const raw = await Deno.readTextFile(path);
    const current = JSON.parse(raw);
    const updated = updater(current);
    await atomicWriteJSON(path, updated);
  } finally {
    await releaseLock(lock);
  }
}

// ---------------------------------------------------------------------------
// Atomic request-ID allocation
// ---------------------------------------------------------------------------

/**
 * Allocate the next sequential request ID using a counter file.
 *
 * Reads `{basePath}/counter.json`, increments `last_id`, persists it
 * atomically, and creates the corresponding request directory.
 *
 * If `counter.json` does not exist, the function scans existing REQ-
 * directories to initialize the counter before allocation.
 *
 * @param basePath - Root requests directory (e.g. `.gran-maestro/requests`).
 * @returns The allocated ID string (e.g. `"REQ-007"` or `"REQ-1000"`).
 */
export async function allocateRequestId(basePath: string): Promise<string> {
  const counterPath = `${basePath}/counter.json`;
  const lockPath = `${counterPath}.lock`;

  const lock = await acquireLock(lockPath, 5_000);
  try {
    let lastId = 0;

    try {
      const raw = await Deno.readTextFile(counterPath);
      const data = JSON.parse(raw) as { last_id?: number };
      lastId = typeof data.last_id === 'number' ? data.last_id : 0;
    } catch {
      lastId = await scanMaxReqId(basePath);
    }

    const nextId = lastId + 1;
    await writeCounterId(counterPath, nextId);

    const reqId = formatRequestId(nextId);
    // Node.js fallback: fs.promises.mkdir(path, { recursive: false })
    await Deno.mkdir(`${basePath}/${reqId}`, { recursive: false });
    return reqId;
  } finally {
    await releaseLock(lock);
  }
}

/**
 * Persist `last_id` to a counter file, creating parent directory if needed.
 *
 * @param counterPath - Counter JSON file path.
 * @param nextId - Next request id number.
 */
async function writeCounterId(counterPath: string, nextId: number): Promise<void> {
  const counterDir = counterPath.replace(/[/\\][^/\\]*$/, '');
  await Deno.mkdir(counterDir, { recursive: true });
  await atomicWriteJSON(counterPath, { last_id: nextId });
}

/**
 * Find the maximum existing REQ number from `basePath` directories.
 *
 * @param basePath - Root requests directory.
 * @returns Maximum request number already used, or 0 if none.
 */
async function scanMaxReqId(basePath: string): Promise<number> {
  let max = 0;

  try {
    for await (const entry of Deno.readDir(basePath)) {
      if (!entry.isDirectory) continue;

      const match = entry.name.match(/^REQ-(\d+)$/);
      if (!match) continue;

      const parsed = Number.parseInt(match[1], 10);
      if (!Number.isNaN(parsed)) {
        max = Math.max(max, parsed);
      }
    }
  } catch {
    // ignore; caller will initialize from zero
  }

  return max;
}

/**
 * Convert numeric request id into REQ identifier.
 *
 * - 1000 미만: 3자리 zero-pad (`REQ-001`)
 * - 1000 이상: 그대로 (`REQ-1000`)
 *
 * @param id - Numeric request id.
 */
function formatRequestId(id: number): string {
  if (id < 1000) {
    return `REQ-${String(id).padStart(3, '0')}`;
  }
  return `REQ-${id}`;
}

// ---------------------------------------------------------------------------
// Task queue
// ---------------------------------------------------------------------------

/**
 * Bounded FIFO task queue that respects `max_parallel_tasks`.
 *
 * Tasks are enqueued and only dispatched when a slot becomes available.
 * The caller provides an `executor` callback that runs the actual task.
 */
export class TaskQueue {
  private active = 0;
  private queue: Array<{ id: string; run: () => Promise<void> }> = [];

  constructor(private readonly config: ConcurrencyConfig = DEFAULT_CONCURRENCY_CONFIG) {}

  /**
   * Add a task to the queue.
   *
   * If a slot is available the task starts immediately; otherwise it is
   * queued and will be started when {@link onTaskComplete} frees a slot.
   *
   * @param id  - Task identifier (for diagnostics).
   * @param run - Async function that performs the work.
   */
  async enqueue(id: string, run: () => Promise<void>): Promise<void> {
    if (this.active < this.config.max_parallel_tasks) {
      this.active++;
      this.executeAndRelease(id, run);
    } else {
      this.queue.push({ id, run });
    }
  }

  /**
   * Signal that a task has completed, freeing a slot for the next queued task.
   *
   * This is called automatically by the internal runner, but can also be
   * invoked externally when a task completes outside of the queue's control.
   */
  onTaskComplete(): void {
    this.active = Math.max(0, this.active - 1);
    this.drainQueue();
  }

  /** Number of tasks currently executing. */
  getActiveCount(): number {
    return this.active;
  }

  /** Number of tasks waiting in the queue. */
  getQueueLength(): number {
    return this.queue.length;
  }

  // -- Internal helpers --

  private async executeAndRelease(_id: string, run: () => Promise<void>): Promise<void> {
    try {
      await run();
    } finally {
      this.active = Math.max(0, this.active - 1);
      this.drainQueue();
    }
  }

  private drainQueue(): void {
    while (this.active < this.config.max_parallel_tasks && this.queue.length > 0) {
      const next = this.queue.shift()!;
      this.active++;
      this.executeAndRelease(next.id, next.run);
    }
  }
}
