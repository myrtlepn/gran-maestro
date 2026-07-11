import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

// 1. Mock React for renderHook
let hookState: any[] = [];
let hookCursor = 0;
let effectCb: (() => (() => void) | void) | null = null;
let cleanupCb: (() => void) | void = undefined;

vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>();
  return {
    ...actual,
    useState: (initial: any) => {
      const cursor = hookCursor++;
      if (hookState.length === cursor) {
        hookState.push(typeof initial === 'function' ? initial() : initial);
      }
      const setState = (val: any) => {
        hookState[cursor] = typeof val === 'function' ? val(hookState[cursor]) : val;
      };
      return [hookState[cursor], setState];
    },
    useRef: (initial: any) => {
      const cursor = hookCursor++;
      if (hookState.length === cursor) {
        hookState.push({ current: initial });
      }
      return hookState[cursor];
    },
    useCallback: (cb: any) => cb,
    useEffect: (cb: any) => {
      // For this specific hook, we capture the effect to run on mount
      if (!effectCb) {
        effectCb = cb;
      }
    }
  };
});

function renderHook<T>(hookFn: () => T) {
  hookCursor = 0;
  effectCb = null;
  const result = { current: hookFn() };
  
  if (effectCb) {
    cleanupCb = (effectCb as any)();
  }
  
  return {
    result,
    rerender: () => {
      hookCursor = 0;
      result.current = hookFn();
    },
    unmount: () => {
      if (typeof cleanupCb === 'function') {
        cleanupCb();
      }
      hookState = [];
      hookCursor = 0;
      effectCb = null;
      cleanupCb = undefined;
    }
  };
}

// 2. Mock EventSource
class MockEventSource {
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((evt: any) => void) | null = null;
  onerror: (() => void) | null = null;
  
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
    // simulate async open
    setTimeout(() => {
      if (this.onopen) this.onopen();
    }, 1);
  }
  
  close() {
    MockEventSource.instances = MockEventSource.instances.filter(i => i !== this);
  }

  static instances: MockEventSource[] = [];
  
  static triggerMessage(data: any) {
    MockEventSource.instances.forEach(inst => {
      if (inst.onmessage) {
        inst.onmessage({ data: typeof data === 'string' ? data : JSON.stringify(data) });
      }
    });
  }
  
  static triggerError() {
    MockEventSource.instances.forEach(inst => {
      if (inst.onerror) inst.onerror();
    });
  }
  
  static clear() {
    MockEventSource.instances = [];
  }
}

vi.stubGlobal('EventSource', MockEventSource);

// Import hook after mocks
import { useDispatchStream } from '../hooks/useDispatchStream';

describe('useDispatchStream', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockEventSource.clear();
    hookState = [];
    hookCursor = 0;
    effectCb = null;
    cleanupCb = undefined;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('AC-001: snapshot 이벤트 수신 시 items 상태 업데이트', () => {
    const hook = renderHook(() => useDispatchStream('PROJ-1', 60));
    
    // initially disconnected before effect updates are reflected
    expect(hook.result.current.status).toBe('disconnected');
    expect(hook.result.current.items).toEqual([]);

    // reflect mount effect (connect)
    hook.rerender();
    expect(hook.result.current.status).toBe('connecting');

    // simulate open
    vi.advanceTimersByTime(2);
    hook.rerender();
    expect(hook.result.current.status).toBe('connected');

    const snapshotPayload = {
      event: 'snapshot',
      items: [
        {
          task_id: 'TASK-1',
          phase: 'running',
          provider: 'anthropic',
          model: 'claude-3-opus',
          heartbeat_age_sec: 10,
          stale: false
        }
      ],
      stale_threshold_sec: 60,
      as_of: '2026-04-10T10:00:00Z'
    };

    MockEventSource.triggerMessage(snapshotPayload);
    hook.rerender();

    expect(hook.result.current.items).toHaveLength(1);
    expect(hook.result.current.items[0].task_id).toBe('TASK-1');
    expect(hook.result.current.asOf).toBe('2026-04-10T10:00:00Z');
    
    hook.unmount();
  });

  it('AC-002: 서버 stale 플래그가 items에 정확히 반영', () => {
    const hook = renderHook(() => useDispatchStream('PROJ-1', 60));
    
    const snapshotPayload = {
      event: 'snapshot',
      items: [
        {
          task_id: 'TASK-1',
          stale: true
        },
        {
          task_id: 'TASK-2',
          stale: false
        }
      ],
      stale_threshold_sec: 60,
      as_of: '2026-04-10T10:00:00Z'
    };

    MockEventSource.triggerMessage(snapshotPayload);
    hook.rerender();

    expect(hook.result.current.items).toHaveLength(2);
    
    const item1 = hook.result.current.items.find((i: any) => i.task_id === 'TASK-1');
    const item2 = hook.result.current.items.find((i: any) => i.task_id === 'TASK-2');
    
    expect(item1?.stale).toBe(true);
    expect(item2?.stale).toBe(false);

    hook.unmount();
  });

  it('AC-003: malformed/필드 누락 SSE payload error handling', () => {
    const hook = renderHook(() => useDispatchStream('PROJ-1', 60));
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    // (a) JSON 파싱 실패 문자열
    MockEventSource.triggerMessage("invalid-json{");
    hook.rerender();
    expect(consoleErrorSpy).toHaveBeenCalled();
    expect(hook.result.current.items).toEqual([]); // no crash, items unchanged

    consoleErrorSpy.mockClear();

    // (b) event !== 'snapshot'인 객체
    MockEventSource.triggerMessage({ event: 'other', items: [{ task_id: 'T1' }] });
    hook.rerender();
    expect(consoleErrorSpy).not.toHaveBeenCalled();
    expect(hook.result.current.items).toEqual([]); // ignored

    // (c) items 필드가 배열 아님
    MockEventSource.triggerMessage({ event: 'snapshot', items: "not-an-array" });
    hook.rerender();
    expect(hook.result.current.items).toEqual([]); // normalized to []

    // (d) item 객체에 일부 필드 누락
    MockEventSource.triggerMessage({
      event: 'snapshot',
      items: [
        {
          // missing task_id, phase, provider, model, heartbeat_age_sec, stale
        }
      ]
    });
    hook.rerender();
    expect(hook.result.current.items).toHaveLength(1);
    expect(hook.result.current.items[0]).toEqual({
      task_id: '',
      attempt_id: '',
      phase: 'running',
      provider: 'unknown',
      model: '',
      execution_transport: 'external',
      route_reason: '',
      provider_task_id: null,
      completion_signal: null,
      exit_code: null,
      fallback_from: null,
      fallback_to: null,
      provider_reconciliation_required: false,
      reconciliation_required: false,
      reconciliation_invariant_gap: false,
      reconciliation_action: null,
      mst_session_id: null,
      root_mst_id: null,
      parent_session_id: null,
      running_log_path: null,
      trace_path: null,
      output_path: null,
      terminal: false,
      heartbeat_age_sec: 0,
      stale: false
    });

    hook.unmount();
  });

  it('AC-004: native/external lifecycle evidence and nullable exit codes survive normalization', () => {
    const hook = renderHook(() => useDispatchStream('PROJ-1', 60));

    MockEventSource.triggerMessage({
      event: 'snapshot',
      items: [
        {
          task_id: 'TASK-NATIVE',
          attempt_id: 'native-a1',
          phase: 'reconciling',
          provider: 'codex',
          model: 'gpt-5',
          execution_transport: 'native',
          route_reason: 'same_host_native_capable',
          provider_task_id: 'provider-native-1',
          completion_signal: null,
          exit_code: null,
          fallback_from: null,
          fallback_to: null,
          provider_reconciliation_required: true,
          reconciliation_required: true,
          reconciliation_invariant_gap: false,
          reconciliation_action: {
            action_id: 'provider-reconcile:abc',
            status: 'pending',
            lookup_key: 'provider-native-1',
          },
          heartbeat_age_sec: 12,
          stale: false,
        },
        {
          task_id: 'TASK-EXTERNAL',
          attempt_id: 'external-a2',
          phase: 'reconciling',
          provider: 'claude',
          execution_transport: 'external',
          route_reason: 'external_fallback_after_definitive_not_created',
          provider_task_id: null,
          completion_signal: null,
          exit_code: null,
          fallback_from: 'native-a1',
          fallback_to: null,
          provider_reconciliation_required: true,
          reconciliation_required: true,
          reconciliation_invariant_gap: false,
          reconciliation_action: {
            kind: 'provider_reconcile',
            action_id: 'provider-reconcile:external',
            status: 'pending',
            lookup_key: 'attempt:external-a2',
            next_operation: 'reconcile_external_provider_group',
          },
          heartbeat_age_sec: 3,
          stale: false,
        },
        {
          task_id: 'TASK-RESOLVED',
          attempt_id: 'external-a3',
          phase: 'terminated',
          provider: 'claude',
          execution_transport: 'external',
          completion_signal: 'process_cancelled',
          exit_code: 143,
          provider_reconciliation_required: false,
          reconciliation_required: false,
          reconciliation_invariant_gap: false,
          reconciliation_action: {
            kind: 'provider_reconcile',
            action_id: 'provider-reconcile:resolved',
            status: 'resolved',
            completion_accepted: true,
            resolved_at: '2026-07-11T10:00:00Z',
            result: { provider_state: 'cancelled' },
          },
          terminal: true,
          heartbeat_age_sec: 1,
          stale: false,
        },
        {
          task_id: 'TASK-CORRUPT',
          attempt_id: 'native-a4',
          phase: 'done',
          provider: 'codex',
          execution_transport: 'native',
          completion_signal: 'completed',
          provider_reconciliation_required: true,
          reconciliation_required: false,
          reconciliation_invariant_gap: true,
          reconciliation_action: {
            action_id: 'provider-reconcile:corrupt',
            status: 'pending',
            completion_accepted: false,
          },
          terminal: true,
          heartbeat_age_sec: 1,
          stale: false,
        },
      ],
      stale_threshold_sec: 60,
      as_of: '2026-07-11T10:00:00Z',
    });
    hook.rerender();

    const native = hook.result.current.items.find((item) => item.task_id === 'TASK-NATIVE');
    const external = hook.result.current.items.find((item) => item.task_id === 'TASK-EXTERNAL');
    const resolved = hook.result.current.items.find((item) => item.task_id === 'TASK-RESOLVED');
    const corrupt = hook.result.current.items.find((item) => item.task_id === 'TASK-CORRUPT');

    expect(native).toMatchObject({
      attempt_id: 'native-a1',
      execution_transport: 'native',
      route_reason: 'same_host_native_capable',
      provider_task_id: 'provider-native-1',
      completion_signal: null,
      exit_code: null,
      provider_reconciliation_required: true,
      reconciliation_required: true,
      reconciliation_invariant_gap: false,
      reconciliation_action: {
        action_id: 'provider-reconcile:abc',
        status: 'pending',
        lookup_key: 'provider-native-1',
      },
    });
    expect(external).toMatchObject({
      attempt_id: 'external-a2',
      execution_transport: 'external',
      route_reason: 'external_fallback_after_definitive_not_created',
      exit_code: null,
      fallback_from: 'native-a1',
      provider_reconciliation_required: true,
      reconciliation_required: true,
      reconciliation_invariant_gap: false,
      reconciliation_action: {
        kind: 'provider_reconcile',
        action_id: 'provider-reconcile:external',
        status: 'pending',
        lookup_key: 'attempt:external-a2',
        next_operation: 'reconcile_external_provider_group',
      },
    });
    expect(resolved).toMatchObject({
      phase: 'terminated',
      terminal: true,
      provider_reconciliation_required: false,
      reconciliation_required: false,
      reconciliation_invariant_gap: false,
      reconciliation_action: {
        action_id: 'provider-reconcile:resolved',
        status: 'resolved',
        completion_accepted: true,
      },
    });
    expect(corrupt).toMatchObject({
      phase: 'done',
      terminal: true,
      provider_reconciliation_required: true,
      reconciliation_required: false,
      reconciliation_invariant_gap: true,
      reconciliation_action: {
        action_id: 'provider-reconcile:corrupt',
        status: 'pending',
        completion_accepted: false,
      },
    });
    expect(native?.exit_code).not.toBe(0);

    hook.unmount();
  });

  it('Reconnects on error after delay', () => {
    const hook = renderHook(() => useDispatchStream('PROJ-1', 60));
    vi.advanceTimersByTime(2); // open
    hook.rerender();
    expect(hook.result.current.status).toBe('connected');

    MockEventSource.triggerError();
    hook.rerender();
    expect(hook.result.current.status).toBe('disconnected');

    // After 3 seconds (RECONNECT_DELAY_MS), it should reconnect
    vi.advanceTimersByTime(3000);
    hook.rerender();
    expect(hook.result.current.status).toBe('connecting');
    
    hook.unmount();
  });
});
