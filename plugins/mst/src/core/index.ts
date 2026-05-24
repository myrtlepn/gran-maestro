/**
 * Core module barrel export for Gran Maestro.
 *
 * Re-exports every public type, interface, constant, class, and function
 * from the core subsystem so consumers can import from a single path:
 *
 * ```typescript
 * import { CLIAdapter, TaskStatus, WorktreeManager } from './core/index.ts';
 * ```
 *
 * @module core
 */

// CLI Adapter (design-decisions.md section 1)
export type { CLIResult, CLIOptions, CLIAdapter } from './cli-adapter.ts';
export { CodexAdapter, GeminiAdapter, createAdapter, runWithTimeout } from './cli-adapter.ts';

// Task FSM (design-decisions.md section 2)
export type { TaskStatus, RequestPhase, TaskTransition, TaskState } from './task-fsm.ts';
export {
  VALID_TRANSITIONS,
  canTransition,
  transitionTask,
  computeRequestPhase,
} from './task-fsm.ts';

// Error Model (design-decisions.md section 3)
export type {
  ErrorCategory,
  ErrorSeverity,
  ErrorResolution,
  ExecutionError,
  TimeoutConfig,
  RetryPolicy,
} from './error-model.ts';
export {
  DEFAULT_TIMEOUTS,
  DEFAULT_RETRY_POLICY,
  classifyError,
  resolveError,
} from './error-model.ts';

// Concurrency (design-decisions.md section 4)
export type { LockHandle, ConcurrencyConfig } from './concurrency.ts';
export {
  DEFAULT_CONCURRENCY_CONFIG,
  atomicWriteJSON,
  acquireLock,
  releaseLock,
  updateStatusAtomic,
  allocateRequestId,
  TaskQueue,
} from './concurrency.ts';

// Worktree Manager (design-decisions.md section 5)
export type { WorktreeState, WorktreeConfig, WorktreeInfo, MergeResult } from './worktree-manager.ts';
export { DEFAULT_WORKTREE_CONFIG, WorktreeManager } from './worktree-manager.ts';

// Session Recovery (design-decisions.md section 9)
export type { RecoverableTask, RecoveryAction } from './session-recovery.ts';
export {
  scanForRecoverableTasks,
  determineRecoveryAction,
  recoverTask,
} from './session-recovery.ts';
