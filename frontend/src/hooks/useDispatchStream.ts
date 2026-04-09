import { useCallback, useEffect, useRef, useState } from 'react';

const RECONNECT_DELAY_MS = 3_000;

export type DispatchStreamStatus = 'connected' | 'disconnected' | 'connecting';

export type DispatchStreamItem = {
  task_id: string;
  phase: string;
  provider: string;
  model: string;
  heartbeat_age_sec: number;
  stale: boolean;
};

type DispatchSnapshotEvent = {
  event: 'snapshot';
  items: DispatchStreamItem[];
  stale_threshold_sec: number;
  as_of: string;
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

function normalizeItem(value: unknown): DispatchStreamItem | null {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const row = value as Record<string, unknown>;
  return {
    task_id: asString(row.task_id, ''),
    phase: asString(row.phase, 'running'),
    provider: asString(row.provider, 'unknown'),
    model: asString(row.model, ''),
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
    as_of: asString(row.as_of, ''),
  };
}

export function useDispatchStream(projectId: string, staleThresholdSec = 60) {
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

    const url = `/api/projects/${encodeURIComponent(projectId)}/dispatch/stream?stale_threshold_sec=${encodeURIComponent(
      String(staleThresholdSec),
    )}`;
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
  }, [disconnect, projectId, staleThresholdSec]);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { status, items, asOf };
}
