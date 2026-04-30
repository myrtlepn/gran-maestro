/// <reference lib="deno.ns" />

import {
  isGranMaestroRoot,
  normalizeGranMaestroBasePath,
  Paths,
  resolveBasePath,
} from './paths.ts';

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

const BASE = '/x/.gran-maestro';

runSerialTest('Paths.requestRoot joins requests/<reqId>', () => {
  const p = new Paths(BASE);
  assertEquals(p.requestRoot('REQ-001'), '/x/.gran-maestro/requests/REQ-001');
});

runSerialTest('Paths.taskRoot joins requests/<reqId>/tasks/<seg>', () => {
  const p = new Paths(BASE);
  assertEquals(p.taskRoot('REQ-001', '01'), '/x/.gran-maestro/requests/REQ-001/tasks/01');
});

runSerialTest('Paths.statusJson appends status.json under task root', () => {
  const p = new Paths(BASE);
  assertEquals(
    p.statusJson('REQ-001', '01'),
    '/x/.gran-maestro/requests/REQ-001/tasks/01/status.json',
  );
});

runSerialTest('Paths.worktreeMeta joins worktrees/<taskId>.meta.json', () => {
  const p = new Paths(BASE);
  assertEquals(
    p.worktreeMeta('REQ-001-01'),
    '/x/.gran-maestro/worktrees/REQ-001-01.meta.json',
  );
});

runSerialTest('Paths.pendingNdjson joins state/skill/pending.ndjson', () => {
  const p = new Paths(BASE);
  assertEquals(
    p.pendingNdjson(),
    '/x/.gran-maestro/state/skill/pending.ndjson',
  );
});

runSerialTest('Paths.hooksLedger joins hooks-ledger.ndjson', () => {
  const p = new Paths(BASE);
  assertEquals(p.hooksLedger(), '/x/.gran-maestro/hooks-ledger.ndjson');
});

runSerialTest('Paths.hooksOverflow joins hooks-ledger.overflow.ndjson', () => {
  const p = new Paths(BASE);
  assertEquals(p.hooksOverflow(), '/x/.gran-maestro/hooks-ledger.overflow.ndjson');
});

runSerialTest('Paths.archiveDir joins archive', () => {
  const p = new Paths(BASE);
  assertEquals(p.archiveDir(), '/x/.gran-maestro/archive');
});

runSerialTest('Paths.stateSnapshot joins state/snapshots/<ppid>.json', () => {
  const p = new Paths(BASE);
  assertEquals(
    p.stateSnapshot('12345'),
    '/x/.gran-maestro/state/snapshots/12345.json',
  );
});

runSerialTest('Paths.root returns the basePath unchanged', () => {
  const p = new Paths(BASE);
  assertEquals(p.root, BASE);
});

runSerialTest('isGranMaestroRoot detects normalized and trailing-slash roots', () => {
  assertEquals(isGranMaestroRoot('/repo/.gran-maestro'), true);
  assertEquals(isGranMaestroRoot('/repo/.gran-maestro/'), true);
  assertEquals(isGranMaestroRoot('/repo'), false);
});

runSerialTest('normalizeGranMaestroBasePath appends root directory once', () => {
  assertEquals(normalizeGranMaestroBasePath('/repo'), '/repo/.gran-maestro');
  assertEquals(normalizeGranMaestroBasePath('/repo/.gran-maestro'), '/repo/.gran-maestro');
  assertEquals(normalizeGranMaestroBasePath('/repo/.gran-maestro/'), '/repo/.gran-maestro');
});

runSerialTest('resolveBasePath honours MST_BASE_PATH when set', () => {
  const previous = Deno.env.get('MST_BASE_PATH');
  try {
    Deno.env.set('MST_BASE_PATH', '/tmp/override');
    assertEquals(resolveBasePath(), '/tmp/override');
  } finally {
    if (previous === undefined) {
      Deno.env.delete('MST_BASE_PATH');
    } else {
      Deno.env.set('MST_BASE_PATH', previous);
    }
  }
});

runSerialTest('resolveBasePath trims whitespace around MST_BASE_PATH', () => {
  const previous = Deno.env.get('MST_BASE_PATH');
  try {
    Deno.env.set('MST_BASE_PATH', '  /tmp/spaced  ');
    assertEquals(resolveBasePath(), '/tmp/spaced');
  } finally {
    if (previous === undefined) {
      Deno.env.delete('MST_BASE_PATH');
    } else {
      Deno.env.set('MST_BASE_PATH', previous);
    }
  }
});

runSerialTest('resolveBasePath falls back to a path ending in .gran-maestro', () => {
  const previous = Deno.env.get('MST_BASE_PATH');
  try {
    Deno.env.delete('MST_BASE_PATH');
    const result = resolveBasePath();
    if (!result.endsWith('/.gran-maestro')) {
      throw new Error(`expected fallback path to end with /.gran-maestro, got ${result}`);
    }
  } finally {
    if (previous !== undefined) {
      Deno.env.set('MST_BASE_PATH', previous);
    }
  }
});

function assertEquals(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Assertion failed: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}
