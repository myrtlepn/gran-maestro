import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

type FlowEvent = {
  ts?: string;
  event?: string;
  session_id?: string;
  [key: string]: unknown;
};

function formatValue(value: unknown): string {
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatLine(event: FlowEvent): string {
  const ts = event.ts ?? '';
  const ev = event.event ?? '';
  const sid = (event.session_id ?? '').toString().slice(0, 8);
  const extra = Object.entries(event)
    .filter(([key]) => !['ts', 'event', 'session_id'].includes(key))
    .map(([key, value]) => `${key}=${formatValue(value)}`)
    .join(' ');

  return `${ts}  ${ev.padEnd(20)} ${sid}  ${extra}`;
}

export function FlowView() {
  const { agiId } = useParams<{ agiId: string }>();
  const [events, setEvents] = useState<FlowEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agiId) return;

    let cancelled = false;

    fetch(`/api/agile/${agiId}/flow`)
      .then((response) => response.json())
      .then((data: FlowEvent[]) => {
        if (!cancelled) {
          setEvents(Array.isArray(data) ? data : []);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(String(err));
        }
      });

    const es = new EventSource(`/api/agile/${agiId}/flow/stream`);
    es.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as FlowEvent;
        setEvents((prev) => [...prev, event]);
      } catch {
        // Ignore malformed stream payloads and keep the text dump live.
      }
    };
    es.onerror = () => {
      // Native EventSource handles reconnect attempts.
    };

    return () => {
      cancelled = true;
      es.close();
    };
  }, [agiId]);

  return (
    <div style={{ padding: '1rem', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
      <h2>Flow - {agiId}</h2>
      {error && <div style={{ color: 'red' }}>error: {error}</div>}
      <div style={{ marginTop: '1rem' }}>
        {events.length === 0 ? <div>(no events yet)</div> : events.map((event, index) => <div key={index}>{formatLine(event)}</div>)}
      </div>
    </div>
  );
}
