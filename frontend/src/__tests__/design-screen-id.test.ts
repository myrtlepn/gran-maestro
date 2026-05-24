import { describe, expect, it } from 'vitest';
import { normalizeScreenId } from '@/views/DesignView';

describe('design screen id normalization', () => {
  it('normalizes markdown screen filenames', () => {
    expect(normalizeScreenId('screen-001.md')).toBe('screen-001');
    expect(normalizeScreenId(' screen-002.md ')).toBe('screen-002');
    expect(normalizeScreenId('recovery-journal-today.html')).toBe('recovery-journal-today');
  });

  it('does not throw when malformed design data omits screen ids', () => {
    expect(normalizeScreenId(undefined)).toBe('');
    expect(normalizeScreenId(null)).toBe('');
    expect(normalizeScreenId({})).toBe('');
  });
});
