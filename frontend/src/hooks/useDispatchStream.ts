import { useCallback, useEffect, useRef, useState } from 'react';

const RECONNECT_DELAY_MS = 3_000;

export type DispatchStreamStatus = 'connected' | 'disconnected' | 'connecting';
export type DispatchQueryMode = 'active' | 'history' | 'all';

export type DispatchStreamItem = {
  task_id: string;
  attempt_id: string;
  phase: string;
  provider: string;
  model: string;
  execution_transport: string;
  requested_launch_surface: string;
  launch_surface: string;
  launch_surface_status: string;
  orca_launch_status: string | null;
  route_reason: string;
  provider_task_id: string | null;
  completion_signal: string | null;
  exit_code: number | null;
  fallback_from: string | null;
  fallback_to: string | null;
  provider_reconciliation_required: boolean;
  reconciliation_required: boolean;
  reconciliation_invariant_gap: boolean;
  reconciliation_action: Record<string, unknown> | null;
  mst_session_id: string | null;
  root_mst_id: string | null;
  parent_session_id: string | null;
  running_log_path: string | null;
  trace_path: string | null;
  output_path: string | null;
  terminal: boolean;
  heartbeat_age_sec: number;
  stale: boolean;
};

type DispatchSnapshotEvent = {
  event: 'snapshot';
  items: DispatchStreamItem[];
  stale_threshold_sec: number;
  mode: DispatchQueryMode;
  limit: number | null;
  as_of: string;
};

export type DispatchStreamOptions = {
  mode?: DispatchQueryMode;
  limit?: number;
};

function asString(value: unknown, fallback: string): string {
  if (typeof value === 'string' && value.trim().length > 0) {
    return value;
  }
  return fallback;
}

function asNumber(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  return fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  if (typeof value === 'boolean') {
    return value;
  }
  return fallback;
}

function asNullableString(value: unknown): string | null {
  if (typeof value === 'string' && value.trim().length > 0) {
    return value;
  }
  return null;
}

function asNullableNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return { ...(value as Record<string, unknown>) };
}

function normalizeItem(value: unknown): DispatchStreamItem | null {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const row = value as Record<string, unknown>;
  return {
    task_id: asString(row.task_id, ''),
    attempt_id: asString(row.attempt_id, ''),
    phase: asString(row.phase, 'running'),
    provider: asString(row.provider, 'unknown'),
    model: asString(row.model, ''),
    execution_transport: asString(row.execution_transport, 'external').toLowerCase(),
    requested_launch_surface: asString(
      row.requested_launch_surface,
      row.launch_surface === 'orca' ? 'orca' : 'direct',
    ).toLowerCase(),
    launch_surface: asString(row.launch_surface, 'direct').toLowerCase(),
    launch_surface_status: asString(row.launch_surface_status, 'disabled').toLowerCase(),
    orca_launch_status: asNullableString(row.orca_launch_status),
    route_reason: asString(row.route_reason, ''),
    provider_task_id: asNullableString(row.provider_task_id),
    completion_signal: asNullableString(row.completion_signal),
    exit_code: asNullableNumber(row.exit_code),
    fallback_from: asNullableString(row.fallback_from),
    fallback_to: asNullableString(row.fallback_to),
    provider_reconciliation_required: asBoolean(
      row.provider_reconciliation_required,
      false,
    ),
    reconciliation_required: asBoolean(row.reconciliation_required, false),
    reconciliation_invariant_gap: asBoolean(row.reconciliation_invariant_gap, false),
    reconciliation_action: asRecord(row.reconciliation_action),
    mst_session_id: asNullableString(row.mst_session_id),
    root_mst_id: asNullableString(row.root_mst_id),
    parent_session_id: asNullableString(row.parent_session_id),
    running_log_path: asNullableString(row.running_log_path),
    trace_path: asNullableString(row.trace_path),
    output_path: asNullableString(row.output_path),
    terminal: asBoolean(row.terminal, false),
    heartbeat_age_sec: Math.max(0, asNumber(row.heartbeat_age_sec, 0)),
    stale: asBoolean(row.stale, false),
  };
}

function normalizeSnapshotEvent(value: unknown): DispatchSnapshotEvent | null {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const row = value as Record<string, unknown>;
  if (row.event !== 'snapshot') {
    return null;
  }

  const items: DispatchStreamItem[] = Array.isArray(row.items)
    ? row.items
      .map((item) => normalizeItem(item))
      .filter((item): item is DispatchStreamItem => item !== null)
    : [];

  return {
    event: 'snapshot',
    items,
    stale_threshold_sec: Math.max(1, asNumber(row.stale_threshold_sec, 60)),
    mode: row.mode === 'history' || row.mode === 'all' ? row.mode : 'active',
    limit: asNullableNumber(row.limit),
    as_of: asString(row.as_of, ''),
  };
}

export function useDispatchStream(
  projectId: string,
  staleThresholdSec = 60,
  options: DispatchStreamOptions = {},
) {
  const queryMode = options.mode ?? 'active';
  const historyLimit = Math.max(1, Math.min(options.limit ?? 50, 200));
  const [status, setStatus] = useState<DispatchStreamStatus>('disconnected');
  const [items, setItems] = useState<DispatchStreamItem[]>([]);
  const [asOf, setAsOf] = useState<string>('');
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!projectId) {
      disconnect();
      setItems([]);
      setAsOf('');
      setStatus('disconnected');
      return;
    }

    disconnect();
    setStatus('connecting');

    const params = new URLSearchParams({
      stale_threshold_sec: String(staleThresholdSec),
      mode: queryMode,
    });
    if (queryMode !== 'active') {
      params.set('limit', String(historyLimit));
    }
    const url = `/api/projects/${encodeURIComponent(projectId)}/dispatch/stream?${params.toString()}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      setStatus('connected');
    };

    es.onmessage = (evt) => {
      try {
        const snapshot = normalizeSnapshotEvent(JSON.parse(evt.data));
        if (!snapshot) return;
        setItems(snapshot.items);
        setAsOf(snapshot.as_of);
      } catch (err) {
        console.error('Failed to parse dispatch SSE payload:', err);
      }
    };

    es.onerror = () => {
      if (esRef.current !== es) return;
      setStatus('disconnected');
      es.close();
      esRef.current = null;

      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, RECONNECT_DELAY_MS);
    };
  }, [disconnect, historyLimit, projectId, queryMode, staleThresholdSec]);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { status, items, asOf };
}
