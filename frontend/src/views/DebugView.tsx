import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAppContext } from '@/context/AppContext';
import { apiFetch } from '@/hooks/useApi';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer';
import { EmptyState } from '@/components/shared/EmptyState';
import { Bug, ClipboardList, ArrowRight } from 'lucide-react';
import { SessionCard } from '@/components/shared/SessionCard';
import { RefreshButton } from '@/components/shared/RefreshButton';
import { EditModeToolbar } from '@/components/EditModeToolbar';
import { useResizableSidebar } from '@/hooks/useResizableSidebar';
import { ResizableHandle } from '@/components/shared/ResizableHandle';
import { ListFilter, type FilterOption } from '@/components/shared/ListFilter';

export const SESSION_DEBUG_SUMMARY_CARD_IDS = [
  'identity',
  'current_work',
  'prompt',
  'writers',
  'integrity',
  'projection',
] as const;

export const SESSION_DEBUG_PANEL_REGISTRY = [
  { id: 'summary', label: 'Summary' },
  { id: 'identity', label: 'Identity Mapping' },
  { id: 'prompt_timeline', label: 'Prompt Timeline' },
  { id: 'current_work', label: 'Current Work' },
  { id: 'execution_flow', label: 'Execution Flow' },
  { id: 'writer_coverage', label: 'Writer Coverage' },
  { id: 'integrity_freshness', label: 'Integrity & Freshness' },
  { id: 'policy_block', label: 'Policy/Block' },
] as const;

type SessionDebugSummaryCardId = (typeof SESSION_DEBUG_SUMMARY_CARD_IDS)[number];
type SessionDebugPanelId = (typeof SESSION_DEBUG_PANEL_REGISTRY)[number]['id'];

interface DebugMeta {
  id: string;
  issue?: string;
  focus?: string;
  status?: string;
  created_at?: string;
  logs?: string;
  linked_plan?: string;
}

interface DebugDetail {
  content?: string;
  logs?: string;
  session_debug?: SessionDebugPayload;
  session_debug_dashboard?: SessionDebugPayload;
  debug_dashboard?: SessionDebugPayload;
  summary?: unknown;
  panels?: unknown;
  selected_detail?: unknown;
  evidence_paths?: unknown;
  mst_session_id?: unknown;
  generated_at?: unknown;
}

interface SessionDebugPanelRow {
  id: SessionDebugPanelId;
  label: string;
  status: string;
}

interface SessionDebugPayload {
  schema_version?: number;
  generated_at?: string;
  mst_session_id?: string;
  summary?: Partial<Record<SessionDebugSummaryCardId, Record<string, unknown>>>;
  panels?: SessionDebugPanelRow[];
  selected_detail?: Record<string, unknown>;
  panel_details?: Partial<Record<SessionDebugPanelId, Record<string, unknown>>>;
  evidence_paths?: string[];
}

const SESSION_DEBUG_CARD_LABELS: Record<SessionDebugSummaryCardId, string> = {
  identity: 'Identity',
  current_work: 'Current Work',
  prompt: 'Prompt',
  writers: 'Writers',
  integrity: 'Integrity',
  projection: 'Projection',
};

const SESSION_DEBUG_CARD_PANEL: Record<SessionDebugSummaryCardId, SessionDebugPanelId> = {
  identity: 'identity',
  current_work: 'current_work',
  prompt: 'prompt_timeline',
  writers: 'writer_coverage',
  integrity: 'integrity_freshness',
  projection: 'summary',
};

const FORBIDDEN_SESSION_DEBUG_KEYS = new Set([
  'raw_ledger',
  'raw_ledger_rows',
  'ledger_rows',
  'raw_history',
  'raw_history_rows',
  'history_rows',
  'full_history',
  'full_history_events',
  'full_history_payload',
  'full_history_event_payload',
  'raw_prompt',
  'raw_prompt_text',
  'full_prompt',
  'full_prompt_text',
  'prompt_text',
  'raw_transcript',
  'raw_transcript_content',
  'transcript_text',
  'llm_summary',
  'semantic_summary',
  'generated_summary',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function safeString(value: unknown, fallback = 'unknown'): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function safeStatus(value: unknown, fallback = 'unknown'): string {
  return safeString(value, fallback).toLowerCase();
}

function truncateText(value: string, maxLength = 180): string {
  return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
}

function isSessionDebugPayload(value: unknown): value is SessionDebugPayload {
  if (!isRecord(value)) return false;
  return isRecord(value.summary) || Array.isArray(value.panels) || isRecord(value.selected_detail);
}

function normalizeSessionDebugPayload(value: unknown): SessionDebugPayload | null {
  if (!isSessionDebugPayload(value)) return null;

  let summary: SessionDebugPayload['summary'];
  if (isRecord(value.summary)) {
    const normalizedSummary: Partial<Record<SessionDebugSummaryCardId, Record<string, unknown>>> = {};
    SESSION_DEBUG_SUMMARY_CARD_IDS.forEach((cardId) => {
      const card = value.summary?.[cardId];
      if (isRecord(card)) normalizedSummary[cardId] = card;
    });
    summary = normalizedSummary;
  }

  const rawPanels = Array.isArray(value.panels) ? value.panels : [];
  const panels = SESSION_DEBUG_PANEL_REGISTRY.map((registered) => {
    const source = rawPanels.find((panel) => isRecord(panel) && panel.id === registered.id);
    return {
      id: registered.id,
      label: registered.label,
      status: isRecord(source) ? safeStatus(source.status) : 'unknown',
    };
  });

  const panelDetails: Partial<Record<SessionDebugPanelId, Record<string, unknown>>> = {};
  if (isRecord(value.panel_details)) {
    SESSION_DEBUG_PANEL_REGISTRY.forEach((panel) => {
      const detail = value.panel_details?.[panel.id];
      if (isRecord(detail)) panelDetails[panel.id] = detail;
    });
  }

  return {
    schema_version: typeof value.schema_version === 'number' ? value.schema_version : undefined,
    generated_at: typeof value.generated_at === 'string' ? value.generated_at : undefined,
    mst_session_id: typeof value.mst_session_id === 'string' ? value.mst_session_id : undefined,
    summary,
    panels,
    selected_detail: isRecord(value.selected_detail) ? value.selected_detail : undefined,
    panel_details: panelDetails,
    evidence_paths: asStringList(value.evidence_paths),
  };
}

function getSessionDebugPayload(detail: DebugDetail | null): SessionDebugPayload | null {
  if (!detail) return null;
  return (
    normalizeSessionDebugPayload(detail.session_debug) ??
    normalizeSessionDebugPayload(detail.session_debug_dashboard) ??
    normalizeSessionDebugPayload(detail.debug_dashboard) ??
    normalizeSessionDebugPayload(detail)
  );
}

function createFallbackSessionDebugPayload(
  session: DebugMeta,
  detail: DebugDetail | null
): SessionDebugPayload {
  const generatedAt = session.created_at || undefined;
  const reportAvailable = Boolean(detail?.content?.trim());
  const logAvailable = Boolean((detail?.logs || session.logs)?.trim());
  const evidencePaths = session.linked_plan ? [session.linked_plan] : [];

  return {
    schema_version: 1,
    generated_at: generatedAt,
    mst_session_id: session.id,
    evidence_paths: evidencePaths,
    summary: {
      identity: {
        status: 'unknown',
        canonical_mst_session_id: session.id,
      },
      current_work: {
        status: session.status || 'unknown',
        next_action_type: session.focus || 'unknown',
      },
      prompt: {
        status: 'unknown',
        latest_prompt_digest: 'not_available',
      },
      writers: {
        status: 'unknown',
        total: 0,
      },
      integrity: {
        status: 'unknown',
        reason: 'projection_not_available',
      },
      projection: {
        status: reportAvailable || logAvailable ? 'unknown' : 'no_history',
        generated_at: generatedAt || 'not_available',
      },
    },
    panels: SESSION_DEBUG_PANEL_REGISTRY.map((panel) => ({
      id: panel.id,
      label: panel.label,
      status: panel.id === 'summary' && (reportAvailable || logAvailable) ? 'unknown' : 'empty',
    })),
    selected_detail: {
      panel_id: 'summary',
      empty_state: !reportAvailable && !logAvailable,
      reason: reportAvailable || logAvailable
        ? 'Session Debug projection was not returned by the debug endpoint.'
        : 'No bounded Session Debug projection data is available yet.',
      evidence_paths: evidencePaths,
    },
  };
}

function getPanelLabel(panelId: SessionDebugPanelId): string {
  return SESSION_DEBUG_PANEL_REGISTRY.find((panel) => panel.id === panelId)?.label ?? panelId;
}

function getPanelRows(payload: SessionDebugPayload): SessionDebugPanelRow[] {
  const payloadPanels = Array.isArray(payload.panels) ? payload.panels : [];
  return SESSION_DEBUG_PANEL_REGISTRY.map((registered) => {
    const source = payloadPanels.find((panel) => panel.id === registered.id);
    return {
      id: registered.id,
      label: registered.label,
      status: source?.status || 'unknown',
    };
  });
}

function getSummaryCard(payload: SessionDebugPayload, cardId: SessionDebugSummaryCardId): Record<string, unknown> {
  const card = payload.summary?.[cardId];
  return isRecord(card) ? card : { status: 'unknown' };
}

function getSummaryCardPrimary(cardId: SessionDebugSummaryCardId, card: Record<string, unknown>): string {
  if (cardId === 'identity') return safeString(card.canonical_mst_session_id, 'No canonical session');
  if (cardId === 'current_work') return safeString(card.next_action_type, 'No active action');
  if (cardId === 'prompt') return safeString(card.latest_prompt_digest, 'No prompt anchor');
  if (cardId === 'writers') return `${typeof card.total === 'number' ? card.total : 0} writers`;
  if (cardId === 'integrity') return safeString(card.reason, 'No verifier result');
  return safeString(card.generated_at, 'No projection timestamp');
}

function selectedDetailForPanel(payload: SessionDebugPayload, panelId: SessionDebugPanelId): Record<string, unknown> {
  const panelDetail = payload.panel_details?.[panelId];
  if (isRecord(panelDetail)) {
    return panelDetail;
  }

  if (panelId === 'summary') {
    return {
      panel_id: 'summary',
      summary: payload.summary ?? {},
      evidence_paths: payload.evidence_paths ?? [],
    };
  }

  const detail = payload.selected_detail;
  if (isRecord(detail) && detail.panel_id === panelId) {
    return detail;
  }

  return {
    panel_id: panelId,
    empty_state: true,
    reason: `${getPanelLabel(panelId)} projection data is not available in this debug response.`,
    evidence_paths: payload.evidence_paths ?? [],
  };
}

function sanitizeDetailValue(value: unknown, depth = 0): unknown {
  if (depth > 3) return '[bounded]';
  if (Array.isArray(value)) return value.slice(0, 8).map((item) => sanitizeDetailValue(item, depth + 1));
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !FORBIDDEN_SESSION_DEBUG_KEYS.has(key))
        .slice(0, 12)
        .map(([key, item]) => [key, sanitizeDetailValue(item, depth + 1)])
    );
  }
  if (typeof value === 'string') return truncateText(value);
  return value;
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return truncateText(value);
  return '';
}

function BoundedValue({ value }: { value: unknown }) {
  const sanitized = sanitizeDetailValue(value);

  if (Array.isArray(sanitized)) {
    if (sanitized.length === 0) {
      return <span className="text-muted-foreground">None</span>;
    }
    return (
      <div className="space-y-2">
        {sanitized.map((item, index) => (
          <div key={index} className="rounded-md border bg-muted/20 p-2">
            <BoundedValue value={item} />
          </div>
        ))}
      </div>
    );
  }

  if (isRecord(sanitized)) {
    const entries = Object.entries(sanitized).filter(([key]) => !FORBIDDEN_SESSION_DEBUG_KEYS.has(key));
    if (entries.length === 0) {
      return <span className="text-muted-foreground">No bounded fields</span>;
    }
    return (
      <dl className="grid gap-2 sm:grid-cols-2">
        {entries.map(([key, item]) => (
          <div key={key} className="rounded-md border bg-muted/20 p-2">
            <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">{key}</dt>
            <dd className="mt-1 break-words text-xs">
              {isRecord(item) || Array.isArray(item) ? <BoundedValue value={item} /> : formatScalar(item)}
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  return <span>{formatScalar(sanitized)}</span>;
}

function SessionDebugDashboard({
  payload,
  selectedPanelId,
  onPanelChange,
}: {
  payload: SessionDebugPayload;
  selectedPanelId: SessionDebugPanelId;
  onPanelChange: (panelId: SessionDebugPanelId) => void;
}) {
  const panels = getPanelRows(payload);
  const selectedDetail = selectedDetailForPanel(payload, selectedPanelId);
  const detailEvidencePaths = asStringList(selectedDetail.evidence_paths);
  const evidencePaths = detailEvidencePaths.length > 0
    ? detailEvidencePaths
    : asStringList(payload.evidence_paths);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground">Session Debug</h3>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <div className="font-mono">{payload.mst_session_id || 'unknown-session'}</div>
          <div>{payload.generated_at || 'projection time unavailable'}</div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {SESSION_DEBUG_SUMMARY_CARD_IDS.map((cardId) => {
          const card = getSummaryCard(payload, cardId);
          const panelId = SESSION_DEBUG_CARD_PANEL[cardId];
          const status = safeStatus(card.status);
          return (
            <button
              key={cardId}
              type="button"
              onClick={() => onPanelChange(panelId)}
              className={`rounded-lg border p-3 text-left transition-colors hover:bg-accent/60 ${
                selectedPanelId === panelId ? 'border-primary bg-accent/40' : 'bg-background'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {SESSION_DEBUG_CARD_LABELS[cardId]}
                </span>
                <StatusBadge status={status} className="text-[10px]" />
              </div>
              <div className="mt-3 truncate font-mono text-xs text-foreground">
                {getSummaryCardPrimary(cardId, card)}
              </div>
            </button>
          );
        })}
      </div>

      <div className="rounded-lg border bg-background">
        <div className="flex gap-1 overflow-x-auto border-b p-2">
          {panels.map((panel) => (
            <button
              key={panel.id}
              type="button"
              onClick={() => onPanelChange(panel.id)}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 text-xs transition-colors ${
                selectedPanelId === panel.id
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              }`}
            >
              {panel.label}
            </button>
          ))}
        </div>
        <div className="space-y-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h4 className="font-semibold">{getPanelLabel(selectedPanelId)}</h4>
              <p className="text-xs text-muted-foreground">
                {safeString(selectedDetail.reason, 'Panel detail')}
              </p>
            </div>
            <StatusBadge
              status={panels.find((panel) => panel.id === selectedPanelId)?.status || 'unknown'}
              className="text-[10px]"
            />
          </div>

          {selectedDetail.empty_state === true ? (
            <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              {safeString(selectedDetail.reason, 'No bounded projection data is available for this panel.')}
            </div>
          ) : (
            <BoundedValue value={selectedDetail} />
          )}

          {evidencePaths.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Evidence Paths
              </div>
              <div className="flex flex-wrap gap-2">
                {evidencePaths.slice(0, 6).map((path) => (
                  <span key={path} className="rounded-md bg-muted px-2 py-1 font-mono text-[10px] text-muted-foreground">
                    {truncateText(path, 96)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export function DebugView() {
  const { projectId, lastSseEvent, navigateTo } = useAppContext();
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<DebugMeta[]>([]);
  const [selectedSession, setSelectedSession] = useState<DebugMeta | null>(null);
  const [debugDetail, setDebugDetail] = useState<DebugDetail | null>(null);
  const [reportContent, setReportContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [isBackingUp, setIsBackingUp] = useState(false);
  const [selectedDebugPanelId, setSelectedDebugPanelId] = useState<SessionDebugPanelId>('summary');

  const { sidebarWidth, isResizing, startResizing, sidebarRef } = useResizableSidebar({
    defaultWidth: 300,
    minWidth: 250,
    maxWidth: 600,
    storageKey: 'debug-sidebar-width',
  });

  const [searchValue, setSearchValue] = useState('');
  const [filterValue, setFilterValue] = useState('all');
  const [sortValue, setSortValue] = useState('newest');

  const statusFilterOptions: FilterOption[] = [
    { value: 'all', label: 'All Status' },
    { value: 'open', label: 'Open' },
    { value: 'in_progress', label: 'In Progress' },
    { value: 'done', label: 'Done' },
  ];

  const sortOptions: FilterOption[] = [
    { value: 'newest', label: 'Newest First' },
    { value: 'oldest', label: 'Oldest First' },
  ];

  const filteredSessions = useMemo(() => {
    let result = [...sessions];

    // text search
    if (searchValue.trim()) {
      const query = searchValue.trim().toLowerCase();
      result = result.filter(
        (s) =>
          s.id?.toLowerCase().includes(query) ||
          s.issue?.toLowerCase().includes(query) ||
          s.focus?.toLowerCase().includes(query)
      );
    }

    // status filter
    if (filterValue && filterValue !== 'all') {
      result = result.filter((s) => s.status === filterValue);
    }

    // sort
    if (sortValue === 'oldest') {
      result.sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''));
    } else {
      result.sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
    }

    return result;
  }, [sessions, searchValue, filterValue, sortValue]);

  const fetchData = useCallback(async () => {
    try {
      const data = await apiFetch<DebugMeta[]>('/api/debug', projectId);
      setSessions(data);
      setSelectedSession(prev =>
        prev ? (data.find(session => session.id === prev.id) ?? data[0] ?? null) : (data[0] ?? null)
      );
    } catch (err) {
      console.error('Failed to fetch debug data:', err);
    }
  }, [projectId]);

  useEffect(() => {
    if (sessions.length === 0) return;
    if (sessionId) {
      const target = sessions.find((s: any) => s.id === sessionId);
      setSelectedSession(target || sessions[0]);
    } else {
      setSelectedSession(sessions[0]);
    }
  }, [sessionId, sessions]);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchData().finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => {
    if (!lastSseEvent || !projectId) return;
    if (lastSseEvent.type !== 'debug_update') return;

    apiFetch<DebugMeta[]>('/api/debug', projectId)
      .then(data => {
        setSessions(data);
        if (selectedSession) {
          const updated = data.find(session => session.id === selectedSession.id);
          if (updated) {
            setSelectedSession(updated);
          }
        }
      })
      .catch(err => console.error('SSE re-fetch debug failed:', err));

    if (selectedSession) {
      const eventSessionId =
        (lastSseEvent as { sessionId?: string }).sessionId ??
        (lastSseEvent as { session_id?: string }).session_id;
      if (!eventSessionId || eventSessionId === selectedSession.id) {
        apiFetch<DebugDetail>(`/api/debug/${selectedSession.id}`, projectId)
          .then(data => {
            setDebugDetail(data);
            setReportContent(data.content || null);
          })
          .catch(() => {
            setDebugDetail(null);
            setReportContent(null);
          });
      }
    }
  }, [lastSseEvent, projectId, selectedSession?.id]);

  useEffect(() => {
    if (!selectedSession || !projectId) {
      setDebugDetail(null);
      setReportContent(null);
      return;
    }
    setSelectedDebugPanelId('summary');
    apiFetch<DebugDetail>(`/api/debug/${selectedSession.id}`, projectId)
      .then(data => {
        setDebugDetail(data);
        setReportContent(data.content || null);
      })
      .catch(() => {
        setDebugDetail(null);
        setReportContent(null);
      });
  }, [selectedSession?.id, projectId]);

  const sessionDebugPayload = useMemo(() => {
    if (!selectedSession) return null;
    return getSessionDebugPayload(debugDetail) ?? createFallbackSessionDebugPayload(selectedSession, debugDetail);
  }, [debugDetail, selectedSession]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await fetchData();
      if (selectedSession && projectId) {
        const data = await apiFetch<DebugDetail>(`/api/debug/${selectedSession.id}`, projectId);
        setDebugDetail(data);
        setReportContent(data.content || null);
      }
    } catch (err) {
      console.error('Failed to refresh debug sessions:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleStatusChange = async (targetStatus: string) => {
    try {
      const resolvedPath = projectId
        ? `/api/projects/${projectId}/manage/status`
        : '/api/manage/status';
      const response = await fetch(resolvedPath, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: selectedIds, targetStatus }),
      });
      const result = await response.json() as {
        succeeded: string[];
        skipped: string[];
        errors: string[];
      };

      if (!response.ok) {
        throw new Error(`상태 변경 실패: ${response.status}`);
      }

      if (result.errors.length > 0) {
        alert(`상태 변경 실패: ${result.errors.join(', ')}`);
      }

      setIsEditMode(false);
      setSelectedIds([]);
      await fetchData();
    } catch (err) {
      console.error('상태 변경 실패:', err);
    }
  };

  const handleBackup = async () => {
    if (isBackingUp) return;
    setIsBackingUp(true);
    try {
      const resolvedPath = projectId
        ? `/api/projects/${projectId}/manage/backup`
        : '/api/manage/backup';
      const response = await fetch(resolvedPath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: selectedIds }),
      });
      if (!response.ok) {
        let errorMessage = `백업 실패: ${response.status}`;
        try {
          const errorBody = await response.json() as { error?: string; detail?: string };
          if (errorBody.error) {
            errorMessage = errorBody.detail
              ? `백업 실패: ${errorBody.error} (${errorBody.detail})`
              : `백업 실패: ${errorBody.error}`;
          }
        } catch {
          // ignore non-JSON error body
        }
        throw new Error(errorMessage);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `gran-maestro-backup-${Date.now()}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('백업 실패:', err);
      alert(err instanceof Error ? err.message : '백업 실패');
    } finally {
      setIsBackingUp(false);
    }
  };

  if (!projectId) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        프로젝트를 선택하세요
      </div>
    );
  }

  if (loading) {
    return <div className="p-6"><Skeleton className="h-full w-full" /></div>;
  }

  return (
    <div className="flex h-full overflow-hidden">
      <div ref={sidebarRef} style={{ width: sidebarWidth }} className="border-r flex flex-col min-h-0 shrink-0">
        <div className="p-4 border-b bg-muted/30 flex justify-between items-center">
          <h2 className="font-semibold">Debug Sessions ({sessions.length})</h2>
          <div className="flex items-center gap-2">
            <EditModeToolbar
              isEditMode={isEditMode}
              selectedIds={selectedIds}
              itemType="session"
              onToggleEditMode={() => { setIsEditMode(v => !v); setSelectedIds([]); }}
              onStatusChange={handleStatusChange}
              isBackingUp={isBackingUp}
              onBackup={handleBackup}
              onCancel={() => { setIsEditMode(false); setSelectedIds([]); }}
            />
            <RefreshButton onClick={handleRefresh} isRefreshing={isRefreshing} />
          </div>
        </div>
        <ListFilter
          searchValue={searchValue}
          onSearchChange={setSearchValue}
          searchPlaceholder="Search by issue or ID..."
          filterOptions={statusFilterOptions}
          filterValue={filterValue}
          onFilterChange={setFilterValue}
          filterPlaceholder="Status"
          sortOptions={sortOptions}
          sortValue={sortValue}
          onSortChange={setSortValue}
          sortPlaceholder="Sort"
        />
        <ScrollArea className="flex-1">
          <div className="p-3 space-y-1.5">
            {filteredSessions.map((s) => (
              <div key={s.id} className="flex items-center">
                {isEditMode && (
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(s.id)}
                    onChange={(e) => {
                      setSelectedIds(prev =>
                        e.target.checked ? [...prev, s.id] : prev.filter(id => id !== s.id)
                      );
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="mr-2 h-4 w-4"
                  />
                )}
                <div className="flex-1">
                  <SessionCard
                    id={s.id}
                    title={s.issue || s.id}
                    status={s.status ?? ''}
                    createdAt={s.created_at}
                    icon={<Bug className="h-3 w-3 text-red-500" />}
                    extraBadge={s.focus}
                    isSelected={selectedSession?.id === s.id}
                    onClick={() => navigate('/debug/' + s.id)}
                  />
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </div>

      <ResizableHandle isResizing={isResizing} onMouseDown={startResizing} />

      <div className="flex-1 flex flex-col bg-card min-h-0 overflow-hidden">
        {selectedSession ? (
          <>
            <div className="p-4 border-b flex justify-between items-center bg-muted/10">
              <div className="flex items-center gap-3">
                <div>
                  <h2 className="font-bold text-lg">{selectedSession.issue || selectedSession.id}</h2>
                  <p className="text-xs text-muted-foreground">{selectedSession.created_at?.slice(0, 10)}</p>
                </div>
                {selectedSession.linked_plan && (
                  <button
                    type="button"
                    onClick={() => navigateTo('plans', selectedSession.linked_plan)}
                    className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-muted hover:bg-accent transition-colors font-mono"
                  >
                    <ClipboardList className="h-3 w-3" />
                    {selectedSession.linked_plan}
                    <ArrowRight className="h-3 w-3" />
                  </button>
                )}
              </div>
              <StatusBadge status={selectedSession.status ?? ''} />
            </div>

            <ScrollArea className="flex-1">
              <div className="p-8">
                <div className="space-y-10">
                  {sessionDebugPayload && (
                    <SessionDebugDashboard
                      payload={sessionDebugPayload}
                      selectedPanelId={selectedDebugPanelId}
                      onPanelChange={setSelectedDebugPanelId}
                    />
                  )}

                  <section>
                    <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground mb-4">Report</h3>
                    <MarkdownRenderer content={reportContent || '# No report yet'} />
                  </section>

                  {selectedSession.logs && (
                    <section>
                      <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground mb-4">Relevant Logs</h3>
                      <pre className="p-4 rounded-lg bg-zinc-100 dark:bg-zinc-950 text-zinc-800 dark:text-zinc-300 font-mono text-[10px] overflow-x-auto">
                        {selectedSession.logs}
                      </pre>
                    </section>
                  )}
                </div>
              </div>
            </ScrollArea>
          </>
        ) : (
          <EmptyState
            icon={<Bug className="h-8 w-8" />}
            title="디버그 세션을 선택하세요"
            description="왼쪽 목록에서 디버그 세션을 클릭하면 리포트를 볼 수 있어요"
          />
        )}
      </div>
    </div>
  );
}
