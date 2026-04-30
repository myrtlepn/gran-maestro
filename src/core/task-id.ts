// AD-006: regex-based task ID parsing.
//
// Replace heuristic `parts[parts.length - 1]` taskNum extraction with an
// explicit regex so non-standard task IDs surface a clear `RecoveryError`
// instead of silently mapping to a wrong status.json path.

const TASK_ID_PATTERN = /^(REQ-\d+)(?:-(.+))?$/;
const TASK_SEGMENT_PATTERN = /^\w+(-\w+)*$/;

export class RecoveryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RecoveryError';
  }
}

export interface ParsedTaskId {
  requestId: string;
  taskSegment: string;
}

/**
 * Parse a task ID like `REQ-001-01` or `REQ-100-T01-X` into its
 * `requestId` and `taskSegment` components.
 *
 * Throws {@link RecoveryError} when the input does not match
 * `^REQ-\d+(-\w+)*$` -- including bare request IDs (`REQ-001`) which are
 * not task identifiers.
 */
export function parseTaskId(rawId: string): ParsedTaskId {
  if (typeof rawId !== 'string') {
    throw new RecoveryError(`invalid task id: ${String(rawId)}`);
  }
  const match = rawId.match(TASK_ID_PATTERN);
  if (!match || !match[2]) {
    throw new RecoveryError(`invalid task id: ${rawId}`);
  }
  const segment = match[2];
  if (!TASK_SEGMENT_PATTERN.test(segment)) {
    throw new RecoveryError(`invalid task id: ${rawId}`);
  }
  return { requestId: match[1], taskSegment: segment };
}
