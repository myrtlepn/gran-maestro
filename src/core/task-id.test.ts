import { parseTaskId, RecoveryError } from './task-id.ts';

let serial = Promise.resolve();

function runSerialTest(name: string, fn: () => void) {
  Deno.test(name, async () => {
    const prev = serial;
    let release = () => {};
    serial = new Promise<void>((resolve) => {
      release = resolve;
    });

    await prev;
    try {
      fn();
    } finally {
      release();
    }
  });
}

runSerialTest('parseTaskId: REQ-001-01 splits to REQ-001 + 01', () => {
  const result = parseTaskId('REQ-001-01');
  assertEquals(result, { requestId: 'REQ-001', taskSegment: '01' });
});

runSerialTest('parseTaskId: REQ-100-T01 splits to REQ-100 + T01', () => {
  const result = parseTaskId('REQ-100-T01');
  assertEquals(result, { requestId: 'REQ-100', taskSegment: 'T01' });
});

runSerialTest('parseTaskId: REQ-100-T01-X preserves the multi-segment tail', () => {
  const result = parseTaskId('REQ-100-T01-X');
  assertEquals(result, { requestId: 'REQ-100', taskSegment: 'T01-X' });
});

runSerialTest('parseTaskId: rejects lowercase prefix req-001-01', () => {
  assertThrowsRecoveryError(() => parseTaskId('req-001-01'), 'req-001-01');
});

runSerialTest('parseTaskId: rejects empty string', () => {
  assertThrowsRecoveryError(() => parseTaskId(''), '');
});

runSerialTest('parseTaskId: rejects bare request id REQ-001 (no task segment)', () => {
  assertThrowsRecoveryError(() => parseTaskId('REQ-001'), 'REQ-001');
});

runSerialTest('parseTaskId: rejects REQ- with no digits', () => {
  assertThrowsRecoveryError(() => parseTaskId('REQ-'), 'REQ-');
});

runSerialTest('parseTaskId: rejects non-numeric request id REQ-abc-01', () => {
  assertThrowsRecoveryError(() => parseTaskId('REQ-abc-01'), 'REQ-abc-01');
});

runSerialTest('parseTaskId: rejects empty trailing segment REQ-001-', () => {
  assertThrowsRecoveryError(() => parseTaskId('REQ-001-'), 'REQ-001-');
});

function assertEquals(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Assertion failed: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}

function assertThrowsRecoveryError(fn: () => void, expectedIdInMessage: string): void {
  let caught: unknown = null;
  try {
    fn();
  } catch (e) {
    caught = e;
  }
  if (!(caught instanceof RecoveryError)) {
    throw new Error(
      `Expected RecoveryError, got ${caught === null ? 'no throw' : String(caught)}`,
    );
  }
  if (!caught.message.includes('invalid task id:')) {
    throw new Error(`RecoveryError message missing 'invalid task id:' — got: ${caught.message}`);
  }
  if (!caught.message.includes(expectedIdInMessage)) {
    throw new Error(
      `RecoveryError message missing the offending id '${expectedIdInMessage}' — got: ${caught.message}`,
    );
  }
}
