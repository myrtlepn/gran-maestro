import { describe, expect, it } from 'vitest';
import { __flowViewTestData } from '@/views/FlowView';

describe('FlowView session graph helpers', () => {
  it('prefers canonical mst_session_id over raw legacy session_id', () => {
    expect(__flowViewTestData.eventSessionId({ mst_session_id: 'MST-AGI-038', session_id: 'legacy-session' })).toBe('MST-AGI-038');
    expect(__flowViewTestData.eventSessionId({ session_id: 'legacy-session' })).toBe('legacy-session');
  });

  it('formats graph labels and active status for deterministic rendering', () => {
    expect(__flowViewTestData.nodeId({ id: 'mst:request.step-2', label: 'Spec ready' })).toBe('mst:request.step-2');
    expect(__flowViewTestData.nodeLabel({ id: 'mst:request.step-2', label: 'Spec ready' })).toBe('Spec ready');
    expect(__flowViewTestData.statusTone('blocked')).toContain('red');
    expect(__flowViewTestData.statusTone('active')).toContain('blue');
    expect(__flowViewTestData.statusTone('merged')).toContain('green');
  });

  it('formats timeline events without exposing raw JSON by default', () => {
    expect(__flowViewTestData.eventTime({ timestamp: '2026-05-15T00:00:00Z' })).toBe('2026-05-15T00:00:00Z');
    expect(__flowViewTestData.eventName({ event_type: 'request.created' })).toBe('request.created');
    expect(__flowViewTestData.asText(undefined)).toBe('—');
  });

  it('formats graph consistency diagnostics deterministically', () => {
    expect(__flowViewTestData.graphConsistencyStatus({ status: 'consistent' })).toBe('consistent');
    expect(__flowViewTestData.graphConsistencySummary({ status: 'degraded', joined_event_count: 2, event_count: 5 })).toBe('degraded · joined 2/5 canonical events');
    expect(__flowViewTestData.statusTone('degraded')).toContain('amber');
    expect(__flowViewTestData.statusTone('mismatch')).toContain('red');
    expect(__flowViewTestData.statusTone('consistent')).toContain('green');
  });

  it('labels mismatch diagnostics without requiring raw JSON', () => {
    expect(__flowViewTestData.diagnosticLabel({
      code: 'legacy_session_id_mismatch',
      detail: 'event legacy session_id differs from canonical mst_session_id',
      mst_session_id: 'MST-AGI-038',
      legacy_session_id: 'legacy-session',
    })).toBe('legacy_session_id_mismatch: event legacy session_id differs from canonical mst_session_id · MST-AGI-038 · legacy=legacy-session');
  });
});
