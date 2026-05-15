import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';

type FlowEvent = {
  ts?: string;
  timestamp?: string;
  event?: string;
  event_type?: string;
  session_id?: string;
  mst_session_id?: string;
  [key: string]: unknown;
};

type FlowNode = {
  id?: string;
  label?: string;
  status?: string;
  kind?: string;
  [key: string]: unknown;
};

type FlowEdge = {
  from?: string;
  to?: string;
  transition?: string;
  label?: string;
  [key: string]: unknown;
};

type WorktreeState = {
  id?: string;
  path?: string;
  branch?: string;
  state?: string;
  merge_target?: string;
  [key: string]: unknown;
};

type GraphConsistencyDiagnostic = {
  code?: string;
  severity?: 'info' | 'warning' | 'error' | string;
  detail?: string;
  mst_session_id?: string;
  legacy_session_id?: string;
  field?: string;
  [key: string]: unknown;
};

type GraphConsistency = {
  status?: string;
  diagnostics?: GraphConsistencyDiagnostic[];
  event_count?: number;
  joined_event_count?: number;
  orphan_event_count?: number;
  [key: string]: unknown;
};

type SessionGraph = {
  mst_session_id: string;
  status?: string;
  nodes?: FlowNode[];
  edges?: FlowEdge[];
  events?: FlowEvent[];
  current_node?: string;
  last_transition?: unknown;
  next_action?: unknown;
  blocker?: unknown;
  coverage?: Record<string, unknown>;
  worktrees?: {
    session?: WorktreeState | null;
    children?: WorktreeState[];
  };
  recovery_action?: unknown;
  projection_status?: Record<string, unknown>;
  graph_consistency?: GraphConsistency;
  display_only?: boolean;
  next_action_authority?: boolean;
  transition_authority?: string;
  [key: string]: unknown;
};

type FlowViewResponse = {
  events?: FlowEvent[];
  session_graphs?: SessionGraph[];
  display_only?: boolean;
  next_action_authority?: boolean;
  transition_authority?: string;
};

function asText(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

function eventSessionId(event: FlowEvent): string | undefined {
  return event.mst_session_id ?? event.session_id;
}

function eventTime(event: FlowEvent): string {
  return asText(event.ts ?? event.timestamp, 'no timestamp');
}

function eventName(event: FlowEvent): string {
  return asText(event.event ?? event.event_type, 'event');
}

function nodeLabel(node: FlowNode): string {
  return asText(node.label ?? node.id ?? node.kind, 'node');
}

function nodeId(node: FlowNode): string {
  return asText(node.id ?? node.label ?? node.kind, 'node');
}

function statusTone(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized.includes('block') || normalized.includes('fail') || normalized.includes('dirty') || normalized.includes('conflict') || normalized.includes('mismatch')) {
    return 'border-red-200 bg-red-50 text-red-800';
  }
  if (normalized.includes('warn') || normalized.includes('degraded') || normalized.includes('legacy') || normalized.includes('orphan')) {
    return 'border-amber-200 bg-amber-50 text-amber-800';
  }
  if (normalized.includes('active') || normalized.includes('current') || normalized.includes('ready')) {
    return 'border-blue-200 bg-blue-50 text-blue-800';
  }
  if (normalized.includes('done') || normalized.includes('merged') || normalized.includes('removed') || normalized.includes('clean') || normalized.includes('consistent')) {
    return 'border-green-200 bg-green-50 text-green-800';
  }
  return 'border-slate-200 bg-slate-50 text-slate-700';
}

function graphConsistencyStatus(consistency?: GraphConsistency): string {
  return asText(consistency?.status, 'unknown');
}

function graphConsistencySummary(consistency?: GraphConsistency): string {
  const status = graphConsistencyStatus(consistency);
  const joined = asText(consistency?.joined_event_count, '0');
  const total = asText(consistency?.event_count, '0');
  return `${status} · joined ${joined}/${total} canonical events`;
}

function diagnosticLabel(diagnostic: GraphConsistencyDiagnostic): string {
  const code = asText(diagnostic.code, 'diagnostic');
  const detail = asText(diagnostic.detail, 'No detail');
  const session = diagnostic.mst_session_id ? ` · ${diagnostic.mst_session_id}` : '';
  const legacy = diagnostic.legacy_session_id ? ` · legacy=${diagnostic.legacy_session_id}` : '';
  return `${code}: ${detail}${session}${legacy}`;
}

function DetailCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="mt-3 text-sm text-slate-900">{children}</div>
    </section>
  );
}

function EmptyState({ agiId }: { agiId?: string }) {
  return (
    <div className="p-6">
      <h2 className="text-xl font-semibold">Flow - {agiId}</h2>
      <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-600">
        No session graphs yet. The dashboard will populate after `execution-flow.json` projections are available for a canonical MST session.
      </div>
    </div>
  );
}

export const __flowViewTestData = {
  asText,
  eventSessionId,
  eventName,
  eventTime,
  nodeLabel,
  nodeId,
  statusTone,
  graphConsistencyStatus,
  graphConsistencySummary,
  diagnosticLabel,
};

export function FlowView() {
  const { agiId } = useParams<{ agiId: string }>();
  const [response, setResponse] = useState<FlowViewResponse | null>(null);
  const [liveEvents, setLiveEvents] = useState<FlowEvent[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agiId) return;

    let cancelled = false;
    setError(null);
    setLiveEvents([]);

    fetch(`/api/agile/${agiId}/flow/view`)
      .then((fetchResponse) => {
        if (!fetchResponse.ok) throw new Error(`flow view request failed: ${fetchResponse.status}`);
        return fetchResponse.json();
      })
      .then((data: FlowViewResponse) => {
        if (cancelled) return;
        const sessionGraphs = Array.isArray(data.session_graphs) ? data.session_graphs : [];
        setResponse({
          ...data,
          events: Array.isArray(data.events) ? data.events : [],
          session_graphs: sessionGraphs,
        });
        setSelectedSessionId((current) => current || sessionGraphs[0]?.mst_session_id || '');
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(String(err));
      });

    const es = new EventSource(`/api/agile/${agiId}/flow/stream`);
    es.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as FlowEvent;
        setLiveEvents((prev) => [...prev, event]);
      } catch {
        // Native stream may include non-data frames; malformed data should not break the dashboard.
      }
    };
    es.onerror = () => {
      // Native EventSource reconnects automatically.
    };

    return () => {
      cancelled = true;
      es.close();
    };
  }, [agiId]);

  const sessionGraphs = response?.session_graphs ?? [];
  const selectedGraph = useMemo(() => {
    return sessionGraphs.find((graph) => graph.mst_session_id === selectedSessionId) ?? sessionGraphs[0];
  }, [selectedSessionId, sessionGraphs]);

  const selectedEvents = useMemo(() => {
    if (!selectedGraph) return [];
    const persisted = Array.isArray(selectedGraph.events) ? selectedGraph.events : [];
    const live = liveEvents.filter((event) => eventSessionId(event) === selectedGraph.mst_session_id);
    return [...persisted, ...live].sort((a, b) => eventTime(a).localeCompare(eventTime(b)));
  }, [liveEvents, selectedGraph]);

  if (!selectedGraph && !error) return <EmptyState agiId={agiId} />;

  const nodes = selectedGraph?.nodes ?? [];
  const edges = selectedGraph?.edges ?? [];
  const childWorktrees = selectedGraph?.worktrees?.children ?? [];
  const sessionWorktree = selectedGraph?.worktrees?.session;
  const currentNode = selectedGraph?.current_node ?? '';

  return (
    <div className="h-full overflow-auto bg-slate-50 p-6 text-slate-900">
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Agile / {agiId} / Sessions</div>
          <h2 className="mt-1 text-2xl font-bold">Session Graph</h2>
          <p className="mt-1 text-sm text-slate-600">Display-only progress graph joined by canonical MST_SESSION_ID.</p>
        </div>
        <label className="text-sm font-medium text-slate-700">
          Session Selector
          <select
            className="mt-1 block min-w-80 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-sm shadow-sm"
            value={selectedGraph?.mst_session_id ?? selectedSessionId}
            onChange={(event) => setSelectedSessionId(event.target.value)}
          >
            {sessionGraphs.map((graph) => (
              <option key={graph.mst_session_id} value={graph.mst_session_id}>{graph.mst_session_id}</option>
            ))}
          </select>
        </label>
      </div>

      {error && <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">error: {error}</div>}

      {selectedGraph && (
        <div className="grid gap-4 xl:grid-cols-[1fr_1.4fr_1fr]">
          <DetailCard title="Summary">
            <dl className="space-y-2">
              <div><dt className="text-xs text-slate-500">Canonical session</dt><dd className="break-all font-mono">{selectedGraph.mst_session_id}</dd></div>
              <div><dt className="text-xs text-slate-500">Status</dt><dd><span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${statusTone(asText(selectedGraph.status, 'unknown'))}`}>{asText(selectedGraph.status, 'unknown')}</span></dd></div>
              <div><dt className="text-xs text-slate-500">Current node</dt><dd className="font-mono">{asText(selectedGraph.current_node)}</dd></div>
              <div><dt className="text-xs text-slate-500">Last transition</dt><dd>{asText(selectedGraph.last_transition)}</dd></div>
              <div><dt className="text-xs text-slate-500">Authority</dt><dd>{selectedGraph.display_only ? 'display-only' : 'unknown'} · next_action_authority={String(selectedGraph.next_action_authority)}</dd></div>
            </dl>
          </DetailCard>

          <DetailCard title="Progress Graph">
            <div className="space-y-3" role="list" aria-label="Session progress graph nodes">
              {nodes.length === 0 ? <div className="text-slate-500">No graph nodes.</div> : nodes.map((node) => {
                const id = nodeId(node);
                const active = id === currentNode;
                return (
                  <div key={id} role="listitem" className={`rounded-md border p-3 ${active ? 'border-blue-400 bg-blue-50' : 'border-slate-200 bg-white'}`} aria-current={active ? 'step' : undefined}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-mono text-sm">{nodeLabel(node)}</span>
                      <span className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(asText(node.status ?? (active ? 'active' : 'observed')))}`}>{active ? 'current' : asText(node.status, 'observed')}</span>
                    </div>
                    {active && <div className="mt-1 text-xs font-semibold text-blue-700">Current node</div>}
                  </div>
                );
              })}
            </div>
            <div className="mt-4 border-t border-slate-200 pt-3">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Observed transitions</h4>
              <ul className="mt-2 space-y-1 text-xs text-slate-600">
                {edges.length === 0 ? <li>No observed edges.</li> : edges.map((edge, index) => (
                  <li key={`${asText(edge.from)}-${asText(edge.to)}-${index}`} className="font-mono">
                    {asText(edge.from)} → {asText(edge.to)} <span className="text-slate-400">{asText(edge.transition ?? edge.label, '')}</span>
                  </li>
                ))}
              </ul>
            </div>
          </DetailCard>

          <div className="space-y-4">
            <DetailCard title="Next Action">
              <pre className="whitespace-pre-wrap break-words rounded-md bg-slate-100 p-3 text-xs">{asText(selectedGraph.next_action, 'No next action')}</pre>
            </DetailCard>
            <DetailCard title="Blocker">
              <pre className="whitespace-pre-wrap break-words rounded-md bg-slate-100 p-3 text-xs">{asText(selectedGraph.blocker, 'No blocker')}</pre>
            </DetailCard>
            <DetailCard title="Recovery & Cleanup Diagnostics">
              <div className="space-y-2">
                <div><span className="text-xs text-slate-500">Recovery action</span><div className="font-mono">{asText(selectedGraph.recovery_action, 'diagnostic_only')}</div></div>
                <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">Diagnostic display only. This dashboard does not run cleanup, final merge, or recovery retry commands.</div>
              </div>
            </DetailCard>
            <DetailCard title="Graph Consistency">
              <div className="space-y-3">
                <div>
                  <span className="text-xs text-slate-500">Source status</span>
                  <div className={`mt-1 inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${statusTone(graphConsistencyStatus(selectedGraph.graph_consistency))}`}>{graphConsistencySummary(selectedGraph.graph_consistency)}</div>
                </div>
                <div className="space-y-2">
                  {(selectedGraph.graph_consistency?.diagnostics ?? []).length === 0 ? (
                    <div className="text-xs text-slate-500">No graph source mismatches.</div>
                  ) : selectedGraph.graph_consistency?.diagnostics?.map((diagnostic, index) => (
                    <div key={`${asText(diagnostic.code, 'diagnostic')}-${index}`} className={`rounded-md border p-2 text-xs ${statusTone(asText(diagnostic.severity ?? diagnostic.code, 'warning'))}`}>
                      {diagnosticLabel(diagnostic)}
                    </div>
                  ))}
                </div>
              </div>
            </DetailCard>
          </div>

          <DetailCard title="Worktree Lifecycle">
            <div className="space-y-3">
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold text-slate-500">Session worktree</div>
                {sessionWorktree ? (
                  <div className="mt-1 space-y-1 font-mono text-xs">
                    <div>state={asText(sessionWorktree.state)}</div>
                    <div>branch={asText(sessionWorktree.branch)}</div>
                    <div className="break-all">path={asText(sessionWorktree.path)}</div>
                  </div>
                ) : <div className="mt-1 text-sm text-slate-500">No session worktree evidence.</div>}
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-500">Child worktrees</div>
                <div className="mt-2 space-y-2">
                  {childWorktrees.length === 0 ? <div className="text-sm text-slate-500">No child worktrees.</div> : childWorktrees.map((child, index) => (
                    <div key={`${asText(child.id, 'child')}-${index}`} className="rounded-md border border-slate-200 bg-white p-3 text-xs">
                      <div className="font-semibold">{asText(child.id, `child-${index + 1}`)}</div>
                      <div className="mt-1 font-mono">state={asText(child.state)} · merge_target={asText(child.merge_target)}</div>
                      <div className="break-all font-mono text-slate-500">{asText(child.path)}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </DetailCard>

          <DetailCard title="Timeline & Evidence">
            <div className="max-h-80 overflow-auto">
              {selectedEvents.length === 0 ? <div className="text-slate-500">No timeline events.</div> : (
                <ol className="space-y-2">
                  {selectedEvents.map((event, index) => (
                    <li key={`${eventTime(event)}-${eventName(event)}-${index}`} className="rounded-md border border-slate-200 bg-white p-3 text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-slate-500">{eventTime(event)}</span>
                        <span className="font-semibold">{eventName(event)}</span>
                        <span className="font-mono text-slate-400">{asText(eventSessionId(event), '')}</span>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </DetailCard>

          <DetailCard title="Coverage">
            <pre className="whitespace-pre-wrap break-words rounded-md bg-slate-100 p-3 text-xs">{asText(selectedGraph.coverage, 'No coverage')}</pre>
          </DetailCard>
        </div>
      )}
    </div>
  );
}
