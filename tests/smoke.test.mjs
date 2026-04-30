import test from 'node:test';
import assert from 'node:assert/strict';

test('smoke test runner executes deterministically', () => {
  assert.equal(1 + 1, 2);
});
