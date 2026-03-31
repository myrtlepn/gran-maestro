import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAppContext } from '@/context/AppContext';
import { useNavigate } from 'react-router-dom';
import { ApiFetchError, apiFetch } from '@/hooks/useApi';
import { useResizableSidebar } from '@/hooks/useResizableSidebar';
import { ResizableHandle } from '@/components/shared/ResizableHandle';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { RefreshButton } from '@/components/shared/RefreshButton';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer';
import { MilkdownEditor } from '@/components/shared/MilkdownEditor';
import { ObjectiveCommentsPanel } from '@/views/ObjectiveCommentsPanel';
import { ArrowRight, ChevronLeft, ChevronRight, FileText, GitBranch, ListChecks } from 'lucide-react';

interface AgileSessionSummary {
  id: string;
  status: string;
  current_sprint: number;
  created_at?: string | null;
  updated_at?: string | null;
}

interface AgileSessionMeta {
  id?: string;
  status?: string;
  current_sprint?: number | string;
  created_at?: string;
  updated_at?: string;
  steering_every?: number;
  queue?: string[];
  refs?: string[];
}

interface SprintGoalTestResults {
  passed?: number;
  failed?: number;
  summary?: string;
}

interface SprintGoalDiff {
  files_changed?: number;
  insertions?: number;
  deletions?: number;
  commits?: string[];
}

interface SprintGoalEvidence {
  screenshots?: string[];
  test_results?: SprintGoalTestResults;
  diff?: SprintGoalDiff;
}

interface SprintGoal {
  goal: string;
  status: string;
  change_summary: string;
  evidence?: SprintGoalEvidence;
}

interface AgileSprint {
  sprint_id: string;
  status?: string;
  stories?: string[];
  period?: string;
  started_at?: string;
  ended_at?: string;
  start_date?: string;
  end_date?: string;
  planned?: string[];
  completed?: string[];
  generated?: {
    pln?: string[];
    req?: string[];
  };
  timestamp?: string;
  summary?: string;
  outcome?: string;
  result_md?: string;
  sprint_goals?: SprintGoal[];
}

interface AgileSessionDetail {
  session: AgileSessionMeta;
  sprints: AgileSprint[];
}

interface RetrospectiveFailedItem {
  item?: string;
  tried_approach?: string;
  failure_reason?: string;
}

interface AgileRetrospective {
  sprint_id?: string;
  status?: string;
  succeeded?: string[];
  failed?: RetrospectiveFailedItem[];
  velocity?: {
    planned?: number;
    completed?: number;
    rate?: number;
  };
  known_limitations?: string;
  lessons_learned?: string;
  direction?: string;
  timestamp?: string;
}

type FlowStatus = 'done' | 'in_progress' | 'not_started';

interface ObjectiveParsedDod {
  dod: string;
  status: string;
  priority: string;
  anchorText?: string | null;
}

interface ObjectiveParsedSection {
  key: string;
  title: string;
  content: string;
}

interface ObjectiveParsedContent {
  dods: ObjectiveParsedDod[];
  sections: ObjectiveParsedSection[];
}

interface ObjectiveResponsePayload {
  content: string | null;
  path: string;
  revision?: string | null;
  parsed?: ObjectiveParsedContent | null;
}


function linkify(text: string): string {
  return text
    .replace(/(\bPLN-\d+\b)/g, (match, p1, offset, string) => {
      if (string.slice(Math.max(0, offset - 2), offset).includes('[')) return match;
      if (string.slice(Math.max(0, offset - 7), offset).includes('/plans/')) return match;
      return `[${match}](/plans/${match})`;
    })
    .replace(/(\bREQ-\d+\b)/g, (match, p1, offset, string) => {
      if (string.slice(Math.max(0, offset - 2), offset).includes('[')) return match;
      if (string.slice(Math.max(0, offset - 10), offset).includes('/workflow/')) return match;
      return `[${match}](/workflow/${match})`;
    });
}

function parseDodMarkers(content: string): ObjectiveParsedDod[] {
  const regex = /<!--\s*dod:\s*([a-z0-9_-]+)\s+status:\s*([a-z0-9_-]+)\s+priority:\s*([a-z0-9_-]+)\s*-->/gi;
  const markers: ObjectiveParsedDod[] = [];
  let match: RegExpExecArray | null;
  while ((match = regex.exec(content)) !== null) {
    markers.push({
      dod: match[1].toUpperCase(),
      status: match[2].toLowerCase(),
      priority: match[3].toLowerCase(),
      anchorText: null,
    });
  }
  return markers;
}

function priorityBadgeClass(priority: string): string {
  switch (priority.toLowerCase()) {
    case 'must':
      return 'text-red-600 border-red-300';
    case 'should':
      return 'text-amber-700 border-amber-300';
    case 'could':
      return 'text-blue-700 border-blue-300';
    case "won't":
    case 'wont':
      return 'text-slate-600 border-slate-300';
    default:
      return 'text-muted-foreground border-border';
  }
}

function renderDodStatus(dods: ObjectiveParsedDod[]) {
  if (dods.length === 0) return null;

  return (
    <Card className="mt-4">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <ListChecks className="h-4 w-4" /> Project DoD Status
        </CardTitle>
        <CardDescription>
          프로젝트 완료 기준(DoD) 상태와 우선순위
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {dods.map((dod, idx) => (
            <div key={`${dod.dod}-${idx}`} className="flex items-center justify-between border rounded-md p-3 text-sm bg-muted/5 gap-3">
              <div className="min-w-0">
                <div className="font-mono text-xs text-muted-foreground">{dod.dod}</div>
                {dod.anchorText && (
                  <p className="text-sm mt-1 truncate">{dod.anchorText}</p>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge variant="outline" className={priorityBadgeClass(dod.priority)}>
                  priority:{dod.priority}
                </Badge>
                <StatusBadge status={dod.status} />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function renderObjectiveSections(sections: ObjectiveParsedSection[]) {
  if (sections.length === 0) return null;

  return (
    <Card className="mt-4">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <FileText className="h-4 w-4" /> Objective Sections
        </CardTitle>
        <CardDescription>
          설계/제약/NFR/리스크/레퍼런스 요약 섹션
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {sections.map((section, index) => (
            <div key={`${section.key}-${index}`} className="rounded-md border p-3 bg-muted/5">
              <h4 className="text-sm font-semibold mb-2">{section.title}</h4>
              <MarkdownRenderer content={section.content} />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function toArray<T>(value: T[] | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function parseSprintNumber(sprintId: string): number {
  const match = /^S(\d+)$/i.exec(sprintId);
  return match ? Number.parseInt(match[1], 10) : Number.POSITIVE_INFINITY;
}

function sortSprints(sprints: AgileSprint[]): AgileSprint[] {
  return [...sprints].sort((a, b) => parseSprintNumber(a.sprint_id) - parseSprintNumber(b.sprint_id));
}

function toSprintId(value: number | string | undefined): string | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return `S${String(Math.max(0, value)).padStart(2, '0')}`;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return null;
    if (/^S\d+$/i.test(trimmed)) {
      const num = Number.parseInt(trimmed.slice(1), 10);
      return Number.isFinite(num) ? `S${String(Math.max(0, num)).padStart(2, '0')}` : null;
    }
    const num = Number.parseInt(trimmed, 10);
    if (Number.isFinite(num)) {
      return `S${String(Math.max(0, num)).padStart(2, '0')}`;
    }
  }
  return null;
}

function resolveDefaultSprintId(
  sprints: AgileSprint[],
  currentSprint: number | string | undefined,
  preferredSprintId?: string | null,
): string | null {
  if (preferredSprintId && sprints.some((sprint) => sprint.sprint_id === preferredSprintId)) {
    return preferredSprintId;
  }

  const currentSprintId = toSprintId(currentSprint);
  if (currentSprintId && sprints.some((sprint) => sprint.sprint_id === currentSprintId)) {
    return currentSprintId;
  }

  return sprints[sprints.length - 1]?.sprint_id ?? null;
}

function toFlowStatus(raw: string | undefined): FlowStatus {
  const normalized = (raw ?? '').toLowerCase().replace(/[\s_-]+/g, '');

  if (normalized === 'done' || normalized === 'completed' || normalized === 'success') {
    return 'done';
  }
  if (
    normalized === 'inprogress'
    || normalized === 'running'
    || normalized === 'active'
    || normalized === 'processing'
    || normalized === 'executing'
  ) {
    return 'in_progress';
  }

  return 'not_started';
}

function getPlanStatus(sprint: AgileSprint): FlowStatus {
  const plannedCount = toArray(sprint.planned).length;
  const completedCount = toArray(sprint.completed).length;

  if (plannedCount > 0 && completedCount >= plannedCount) {
    return 'done';
  }
  if (completedCount > 0) {
    return 'in_progress';
  }

  const sprintStatus = toFlowStatus(sprint.status);
  if (sprintStatus === 'done' && plannedCount > 0) {
    return 'in_progress';
  }
  return sprintStatus;
}

function getResultStatus(sprint: AgileSprint): FlowStatus {
  const sprintStatus = toFlowStatus(sprint.status);
  if (sprintStatus !== 'not_started') {
    return sprintStatus;
  }

  const hasGenerated = toArray(sprint.generated?.pln).length > 0 || toArray(sprint.generated?.req).length > 0;
  if (hasGenerated || sprint.summary || sprint.outcome) {
    return 'in_progress';
  }

  return 'not_started';
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

function formatRate(rate: number | undefined): string {
  if (typeof rate !== 'number' || !Number.isFinite(rate)) return '-';
  return `${Math.round(rate * 100)}%`;
}

function formatSprintPeriod(sprint: AgileSprint): string {
  if (typeof sprint.period === 'string' && sprint.period.trim().length > 0) {
    return sprint.period;
  }

  const start = sprint.started_at ?? sprint.start_date;
  const end = sprint.ended_at ?? sprint.end_date;
  if (start || end) {
    return `${formatTime(start)} ~ ${formatTime(end)}`;
  }

  return formatTime(sprint.timestamp);
}

function getSprintStories(sprint: AgileSprint): string[] {
  const directStories = toArray(sprint.stories).filter(Boolean);
  if (directStories.length > 0) {
    return directStories;
  }

  return [...new Set([...toArray(sprint.planned), ...toArray(sprint.completed)])];
}

function buildFallbackResultMarkdown(sprint: AgileSprint): string {
  const planned = toArray(sprint.planned);
  const completed = toArray(sprint.completed);
  const generatedPln = toArray(sprint.generated?.pln);
  const generatedReq = toArray(sprint.generated?.req);

  return [
    `# ${sprint.sprint_id} Result`,
    '',
    `- status: ${sprint.status ?? 'unknown'}`,
    `- planned: ${planned.length > 0 ? planned.join(', ') : '-'}`,
    `- completed: ${completed.length > 0 ? completed.join(', ') : '-'}`,
    `- generated PLN: ${generatedPln.length > 0 ? generatedPln.join(', ') : '-'}`,
    `- generated REQ: ${generatedReq.length > 0 ? generatedReq.join(', ') : '-'}`,
    `- summary: ${sprint.summary ?? '-'}`,
    `- outcome: ${sprint.outcome ?? '-'}`,
    `- timestamp: ${sprint.timestamp ?? '-'}`,
  ].join('\n');
}

function isGoalAchieved(status: string | undefined): boolean {
  return (status ?? '').trim().toLowerCase() === 'achieved';
}

function formatGoalTestResults(testResults: SprintGoalTestResults | undefined): string {
  if (!testResults) return '증빙 미첨부';

  const passed = typeof testResults.passed === 'number' ? testResults.passed : 0;
  const failed = typeof testResults.failed === 'number' ? testResults.failed : 0;
  const summary = typeof testResults.summary === 'string' && testResults.summary.trim().length > 0
    ? ` · ${testResults.summary}`
    : '';
  return `pass ${passed} / fail ${failed}${summary}`;
}

function formatGoalDiff(diff: SprintGoalDiff | undefined): string {
  if (!diff) return '증빙 미첨부';

  const filesChanged = typeof diff.files_changed === 'number' ? diff.files_changed : 0;
  const insertions = typeof diff.insertions === 'number' ? diff.insertions : 0;
  const deletions = typeof diff.deletions === 'number' ? diff.deletions : 0;
  const commits = toArray(diff.commits).filter((commit) => typeof commit === 'string' && commit.trim().length > 0);
  const commitText = commits.length > 0 ? commits.join(', ') : '-';
  return `files ${filesChanged} · +${insertions} / -${deletions} · commits: ${commitText}`;
}

function nodeClassName(status: FlowStatus): string {
  if (status === 'done') {
    return 'border-green-300 bg-green-50 text-green-700';
  }
  if (status === 'in_progress') {
    return 'border-blue-300 bg-blue-50 text-blue-700';
  }
  return 'border-slate-300 bg-slate-100 text-slate-600';
}

function statusText(status: FlowStatus): string {
  if (status === 'done') return '완료';
  if (status === 'in_progress') return '진행중';
  return '미시작';
}

function TimelineNode({
  title,
  subtitle,
  status,
}: {
  title: string;
  subtitle?: string;
  status: FlowStatus;
}) {
  return (
    <div className={`rounded-md border px-3 py-2 min-w-[132px] ${nodeClassName(status)}`}>
      <div className="text-sm font-semibold">{title}</div>
      {subtitle && <div className="text-xs opacity-90 mt-0.5">{subtitle}</div>}
      <div className="text-[11px] mt-1 font-medium">{statusText(status)}</div>
    </div>
  );
}

export function AgileView() {
  const navigate = useNavigate();

  const handleResultClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    const a = target.closest('a');
    if (a) {
      const href = a.getAttribute('href');
      if (href?.startsWith('/')) {
        e.preventDefault();
        navigate(href);
      }
    }
  }, [navigate]);
  const { projectId, lastSseEvent } = useAppContext();
  const [sessions, setSessions] = useState<AgileSessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionDetail, setSessionDetail] = useState<AgileSessionDetail | null>(null);
  const [selectedSprintId, setSelectedSprintId] = useState<string | null | undefined>(undefined);
  const [resultMarkdown, setResultMarkdown] = useState<string | null>(null);
  const [retrospective, setRetrospective] = useState<AgileRetrospective | null>(null);
  const [retrospectiveMd, setRetrospectiveMd] = useState<string | null>(null);

  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);

  // Objective state
  const [objectiveContent, setObjectiveContent] = useState<string | null>(null);
  const [objectiveParsed, setObjectiveParsed] = useState<ObjectiveParsedContent | null>(null);
  const [objectiveLoading, setObjectiveLoading] = useState(false);
  const [objectiveError, setObjectiveError] = useState<string | null>(null);
  const [isObjectiveEditMode, setIsObjectiveEditMode] = useState(false);
  const [objectiveEditValue, setObjectiveEditValue] = useState('');
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const { sidebarWidth, isResizing, startResizing, sidebarRef } = useResizableSidebar({
    defaultWidth: 320,
    minWidth: 280,
    maxWidth: 560,
    storageKey: 'agile-sidebar-width',
  });
  const {
    sidebarWidth: sprintPanelWidth,
    isResizing: isSprintPanelResizing,
    startResizing: startSprintPanelResizing,
    sidebarRef: sprintPanelRef,
  } = useResizableSidebar({
    defaultWidth: 340,
    minWidth: 280,
    maxWidth: 560,
    storageKey: 'agile-sprint-panel-width',
  });
  const [isSprintPanelCollapsed, setIsSprintPanelCollapsed] = useState(false);

  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) ?? null,
    [sessions, selectedSessionId],
  );

  const selectedSprint = useMemo(
    () => sessionDetail?.sprints.find((sprint) => sprint.sprint_id === selectedSprintId) ?? null,
    [sessionDetail, selectedSprintId],
  );
  const selectedSprintStories = useMemo(
    () => (selectedSprint ? getSprintStories(selectedSprint) : []),
    [selectedSprint],
  );
  const selectedSprintGoals = useMemo(
    () => (selectedSprint
      ? toArray(selectedSprint.sprint_goals).filter(
        (goal): goal is SprintGoal => (
          typeof goal?.goal === 'string'
          && typeof goal?.status === 'string'
          && typeof goal?.change_summary === 'string'
        ),
      )
      : []),
    [selectedSprint],
  );
  const objectiveDodItems = useMemo(() => {
    if (objectiveParsed?.dods && objectiveParsed.dods.length > 0) {
      return objectiveParsed.dods;
    }
    return objectiveContent ? parseDodMarkers(objectiveContent) : [];
  }, [objectiveContent, objectiveParsed]);
  const objectiveSections = useMemo(
    () => objectiveParsed?.sections ?? [],
    [objectiveParsed],
  );

  const requestSessions = useCallback(async (): Promise<AgileSessionSummary[]> => {
    const data = await apiFetch<AgileSessionSummary[]>('/api/agile/sessions', projectId);
    return Array.isArray(data) ? data : [];
  }, [projectId]);

  const requestSessionDetail = useCallback(async (agiId: string): Promise<AgileSessionDetail> => {
    const data = await apiFetch<AgileSessionDetail>(`/api/agile/sessions/${agiId}`, projectId);
    return {
      ...data,
      sprints: sortSprints(Array.isArray(data.sprints) ? data.sprints : []),
    };
  }, [projectId]);

  const requestResultMarkdown = useCallback(async (agiId: string, sprint: AgileSprint): Promise<string> => {
    if (typeof sprint.result_md === 'string' && sprint.result_md.trim().length > 0) {
      return sprint.result_md;
    }

    const filePath = `agile/${agiId}/sprints/${sprint.sprint_id}/result.md`;
    try {
      const data = await apiFetch<{ path: string; content: string }>(
        `/api/file?path=${encodeURIComponent(filePath)}`,
        projectId,
      );
      return data.content;
    } catch (err) {
      if (err instanceof ApiFetchError && err.status === 404) {
        return buildFallbackResultMarkdown(sprint);
      }
      throw err;
    }
  }, [projectId]);

  const requestRetrospective = useCallback(async (agiId: string, sprintId: string): Promise<AgileRetrospective | null> => {
    try {
      return await apiFetch<AgileRetrospective>(
        `/api/agile/sessions/${agiId}/sprints/${sprintId}/retrospective`,
        projectId,
      );
    } catch (err) {
      if (err instanceof ApiFetchError && err.status === 404) {
        return null;
      }
      throw err;
    }
  }, [projectId]);

  const requestRetrospectiveMd = useCallback(async (agiId: string, sprintId: string): Promise<string | null> => {
    try {
      const resolvedPath = projectId 
        ? `/api/projects/${projectId}/agile/sessions/${agiId}/sprints/${sprintId}/retrospective-md`
        : `/api/agile/sessions/${agiId}/sprints/${sprintId}/retrospective-md`;

      const response = await fetch(resolvedPath);
      if (!response.ok) {
        if (response.status === 404) return null;
        throw new Error(`API failed: ${response.status}`);
      }
      
      return await response.text();
    } catch (err) {
      console.error('Failed to fetch retrospective markdown:', err);
      return null;
    }
  }, [projectId]);

  const [objectiveEtag, setObjectiveEtag] = useState<string | null>(null);

  const requestObjective = useCallback(async (agiId: string): Promise<ObjectiveResponsePayload | null> => {
    try {
      const resolvedPath = projectId 
        ? `/api/projects/${projectId}/agile/sessions/${agiId}/objective`
        : `/api/agile/sessions/${agiId}/objective`;

      const response = await fetch(resolvedPath);
      if (!response.ok) {
        if (response.status === 404) return null;
        throw new Error(`API failed: ${response.status}`);
      }
      
      const etag = response.headers.get('ETag');
      setObjectiveEtag(etag);

      const data = await response.json() as ObjectiveResponsePayload;
      const parsed = data.parsed;
      const normalizedDods = Array.isArray(parsed?.dods)
        ? parsed.dods.map((dod) => ({
          dod: dod.dod?.toUpperCase?.() ?? '',
          status: dod.status ?? 'todo',
          priority: dod.priority ?? 'must',
          anchorText: dod.anchorText ?? null,
        })).filter((dod) => dod.dod.length > 0)
        : [];
      const normalizedSections = Array.isArray(parsed?.sections) ? parsed.sections : [];
      return {
        ...data,
        parsed: {
          dods: normalizedDods,
          sections: normalizedSections,
        },
      };
    } catch (err) {
      if (err instanceof ApiFetchError && err.status === 404) {
        return null;
      }
      throw err;
    }
  }, [projectId]);

  useEffect(() => {
    if (!projectId) {
      setSessions([]);
      setSelectedSessionId(null);
      setSessionDetail(null);
      setSelectedSprintId(undefined);
      setResultMarkdown(null);
      setRetrospective(null);
      setRetrospectiveMd(null);
      setObjectiveParsed(null);
      setSessionsError(null);
      setDetailError(null);
      setReportError(null);
      setSessionsLoading(false);
      return;
    }

    let cancelled = false;
    setSessionsLoading(true);

    requestSessions()
      .then((data) => {
        if (cancelled) return;
        setSessions(data);
        setSessionsError(null);
        setSelectedSessionId((prev) => {
          if (prev && data.some((session) => session.id === prev)) return prev;
          return data[0]?.id ?? null;
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setSessions([]);
        setSelectedSessionId(null);
        setSessionsError(err instanceof Error ? err.message : '세션 목록을 불러오지 못했습니다');
      })
      .finally(() => {
        if (!cancelled) setSessionsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, requestSessions]);

  useEffect(() => {
    if (!projectId || !selectedSessionId) {
      setSessionDetail(null);
      setSelectedSprintId(undefined);
      setResultMarkdown(null);
      setRetrospective(null);
      setRetrospectiveMd(null);
      setDetailLoading(false);

      setObjectiveContent(null);
      setObjectiveParsed(null);
      setIsObjectiveEditMode(false);
      setStatusMessage(null);
      return;
    }

    let cancelled = false;
    setDetailLoading(true);
    setObjectiveLoading(true);

    // Fetch objective separately
    requestObjective(selectedSessionId)
      .then((objective) => {
        if (cancelled) return;
        setObjectiveContent(objective?.content ?? null);
        setObjectiveParsed(objective?.parsed ?? null);
        setObjectiveError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setObjectiveContent(null);
        setObjectiveParsed(null);
        setObjectiveError(err instanceof Error ? err.message : 'Objective를 불러오지 못했습니다');
      })
      .finally(() => {
        if (!cancelled) setObjectiveLoading(false);
      });

    requestSessionDetail(selectedSessionId)
      .then((data) => {
        if (cancelled) return;
        setSessionDetail(data);
        setDetailError(null);
        setSelectedSprintId(resolveDefaultSprintId(data.sprints, data.session?.current_sprint, null));
      })
      .catch((err) => {
        if (cancelled) return;
        setSessionDetail(null);
        setSelectedSprintId(null);
        setResultMarkdown(null);
        setRetrospective(null);
        setDetailError(err instanceof Error ? err.message : '세션 상세를 불러오지 못했습니다');
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, selectedSessionId, requestSessionDetail, requestObjective]);

  useEffect(() => {
    if (!projectId || !selectedSessionId || !selectedSprint || !selectedSprintId) {
      setResultMarkdown(null);
      setRetrospective(null);
      setRetrospectiveMd(null);
      setReportError(null);
      setReportLoading(false);
      return;
    }

    let cancelled = false;
    setReportLoading(true);

    Promise.all([
      requestResultMarkdown(selectedSessionId, selectedSprint),
      requestRetrospective(selectedSessionId, selectedSprintId),
      requestRetrospectiveMd(selectedSessionId, selectedSprintId),
    ])
      .then(([markdown, retro, retroMd]) => {
        if (cancelled) return;
        setResultMarkdown(markdown);
        setRetrospective(retro);
        setRetrospectiveMd(retroMd);
        setReportError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setResultMarkdown(buildFallbackResultMarkdown(selectedSprint));
        setRetrospective(null);
        setRetrospectiveMd(null);
        setReportError(err instanceof Error ? err.message : '스프린트 보고서를 불러오지 못했습니다');
      })
      .finally(() => {
        if (!cancelled) setReportLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, selectedSessionId, selectedSprint, selectedSprintId, requestResultMarkdown, requestRetrospective, requestRetrospectiveMd]);

  useEffect(() => {
    if (!projectId || !lastSseEvent) return;

    if (lastSseEvent.type === 'objective_changed') {
      const eventSessionId =
        (lastSseEvent as { sessionId?: string }).sessionId
        ?? (lastSseEvent as { session_id?: string }).session_id
        ?? (lastSseEvent as { data?: { agiId?: string } }).data?.agiId;

      if (selectedSessionId && (!eventSessionId || eventSessionId === selectedSessionId)) {
        requestObjective(selectedSessionId)
          .then((objective) => {
            setObjectiveContent(objective?.content ?? null);
            setObjectiveParsed(objective?.parsed ?? null);
            setObjectiveError(null);
          })
          .catch((err) => {
            console.error('SSE re-fetch objective failed:', err);
          });
      }
      return;
    }

    if (lastSseEvent.type !== 'agile_update') return;

    requestSessions()
      .then((data) => {
        setSessions(data);
        setSessionsError(null);
        setSelectedSessionId((prev) => {
          if (prev && data.some((session) => session.id === prev)) return prev;
          return data[0]?.id ?? null;
        });
      })
      .catch((err) => {
        console.error('SSE re-fetch agile sessions failed:', err);
      });

    const eventSessionId =
      (lastSseEvent as { sessionId?: string }).sessionId
      ?? (lastSseEvent as { session_id?: string }).session_id
      ?? (lastSseEvent as { data?: { agiId?: string } }).data?.agiId;

    if (selectedSessionId && (!eventSessionId || eventSessionId === selectedSessionId)) {
      requestSessionDetail(selectedSessionId)
        .then((data) => {
          setSessionDetail(data);
          setDetailError(null);
          setSelectedSprintId((prev) => (
            prev === null
              ? null
              : resolveDefaultSprintId(data.sprints, data.session?.current_sprint, prev)
          ));
        })
        .catch((err) => {
          console.error('SSE re-fetch agile session detail failed:', err);
        });
    }
  }, [lastSseEvent, projectId, selectedSessionId, requestSessions, requestSessionDetail]);

  const handleRefresh = async () => {
    if (!projectId) return;

    setIsRefreshing(true);
    try {
      const nextSessions = await requestSessions();
      setSessions(nextSessions);
      setSessionsError(null);

      const resolvedSessionId = selectedSessionId && nextSessions.some((session) => session.id === selectedSessionId)
        ? selectedSessionId
        : (nextSessions[0]?.id ?? null);

      setSelectedSessionId(resolvedSessionId);

      if (!resolvedSessionId) {
        setSessionDetail(null);
        setSelectedSprintId(undefined);
        setResultMarkdown(null);
        setRetrospective(null);
        setObjectiveContent(null);
        setObjectiveParsed(null);
        return;
      }

      const detail = await requestSessionDetail(resolvedSessionId);
      setSessionDetail(detail);
      setDetailError(null);

      requestObjective(resolvedSessionId)
        .then((objective) => {
          setObjectiveContent(objective?.content ?? null);
          setObjectiveParsed(objective?.parsed ?? null);
        })
        .catch(err => setObjectiveError(err instanceof Error ? err.message : 'Objective 새로고침 실패'));

      const nextSprintId = selectedSprintId === null
        ? null
        : resolveDefaultSprintId(detail.sprints, detail.session?.current_sprint, selectedSprintId);
      setSelectedSprintId(nextSprintId);

      if (!nextSprintId) {
        setResultMarkdown(null);
        setRetrospective(null);
        return;
      }

      const sprint = detail.sprints.find((item) => item.sprint_id === nextSprintId);
      if (!sprint) {
        setResultMarkdown(null);
        setRetrospective(null);
        return;
      }

      const [markdown, retro, retroMd] = await Promise.all([
        requestResultMarkdown(resolvedSessionId, sprint),
        requestRetrospective(resolvedSessionId, nextSprintId),
        requestRetrospectiveMd(resolvedSessionId, nextSprintId),
      ]);

      setResultMarkdown(markdown);
      setRetrospective(retro);
      setRetrospectiveMd(retroMd);
      setReportError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Agile 데이터를 새로고침하지 못했습니다';
      setSessionsError(message);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleSaveObjective = async () => {
    if (!projectId || !selectedSessionId) return;
    try {
      setStatusMessage(null);
      const resolvedPath = projectId 
        ? `/api/projects/${projectId}/agile/${selectedSessionId}/objective`
        : `/api/agile/${selectedSessionId}/objective`;

      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (objectiveEtag) {
        headers['If-Match'] = objectiveEtag;
      }

      const response = await fetch(resolvedPath, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ content: objectiveEditValue }),
      });
      
      if (!response.ok) {
        if (response.status === 409) {
          throw new Error('다른 프로세스에 의해 Objective가 수정되었습니다. (충돌 발생)');
        }
        throw new Error(`저장 실패: ${response.status}`);
      }

      // Re-fetch objective to get the new ETag
      const objective = await requestObjective(selectedSessionId);
      setObjectiveContent(objective?.content ?? objectiveEditValue);
      setObjectiveParsed(objective?.parsed ?? null);
      setIsObjectiveEditMode(false);
      setStatusMessage({ type: 'success', text: '저장 완료' });
      setTimeout(() => setStatusMessage(null), 3000);
    } catch (err) {
      setStatusMessage({ type: 'error', text: err instanceof Error ? err.message : '저장 실패' });
    }
  };

  const handleObjectiveModeChange = useCallback((mode: 'preview' | 'edit') => {
    if (mode === 'edit') {
      setObjectiveEditValue(objectiveContent ?? '');
      setIsObjectiveEditMode(true);
      setStatusMessage(null);
      return;
    }

    setIsObjectiveEditMode(false);
    setStatusMessage(null);
  }, [objectiveContent]);

  if (!projectId) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        프로젝트를 선택하세요
      </div>
    );
  }

  if (sessionsLoading && sessions.length === 0) {
    return (
      <div className="grid grid-cols-12 gap-6 h-full p-6">
        <div className="col-span-4 space-y-4">
          {[1, 2, 3].map((item) => <Skeleton key={item} className="h-24 w-full" />)}
        </div>
        <div className="col-span-8">
          <Skeleton className="h-full w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      <div ref={sidebarRef} style={{ width: sidebarWidth }} className="border-r flex flex-col min-h-0 shrink-0">
        <div className="p-4 border-b bg-muted/30 flex items-center justify-between">
          <h2 className="font-semibold">Agile ({sessions.length})</h2>
          <RefreshButton onClick={handleRefresh} isRefreshing={isRefreshing} />
        </div>
        {sessionsError && (
          <div className="px-4 py-2 text-xs text-red-600 border-b border-red-200 bg-red-50">
            {sessionsError}
          </div>
        )}
        <div className="p-3 border-b bg-muted/10 text-xs font-medium text-muted-foreground">세션</div>
        <ScrollArea className="flex-1 min-h-0">
          <div className="p-3 space-y-2">
            {sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => {
                  setSelectedSessionId(session.id);
                  setSelectedSprintId(null);
                  setResultMarkdown(null);
                  setRetrospective(null);
                  setRetrospectiveMd(null);
                }}
                className={`w-full text-left rounded-md border p-3 transition-colors ${
                  selectedSessionId === session.id
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:bg-accent/40'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs">{session.id}</span>
                  <StatusBadge status={session.status} />
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  current sprint: {toSprintId(session.current_sprint) ?? `S${String(session.current_sprint ?? 0).padStart(2, '0')}`}
                </p>
                <p className="text-[11px] text-muted-foreground mt-1">
                  updated: {formatTime(session.updated_at ?? session.created_at)}
                </p>
              </button>
            ))}
            {sessions.length === 0 && (
              <p className="text-xs text-muted-foreground px-1 py-2">세션이 없습니다.</p>
            )}
          </div>
        </ScrollArea>
      </div>
      <ResizableHandle isResizing={isResizing} onMouseDown={startResizing} />
      {isSprintPanelCollapsed ? (
        <div className="w-11 border-r bg-muted/10 shrink-0 flex items-start justify-center pt-3">
          <button
            type="button"
            onClick={() => setIsSprintPanelCollapsed(false)}
            className="h-7 w-7 rounded-md border bg-background hover:bg-accent/40 text-muted-foreground flex items-center justify-center"
            aria-label="스프린트 패널 펼치기"
            title="스프린트 패널 펼치기"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <>
          <div
            ref={sprintPanelRef}
            style={{ width: sprintPanelWidth }}
            className="border-r flex flex-col min-h-0 shrink-0"
          >
            <div className="p-3 border-b bg-muted/10 flex items-center justify-between gap-2">
              <h3 className="text-xs font-medium text-muted-foreground">스프린트</h3>
              <button
                type="button"
                onClick={() => setIsSprintPanelCollapsed(true)}
                className="h-7 w-7 rounded-md border bg-background hover:bg-accent/40 text-muted-foreground flex items-center justify-center"
                aria-label="스프린트 패널 접기"
                title="스프린트 패널 접기"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            </div>

            {detailError && (
              <div className="px-3 py-2 text-xs text-red-600 border-b border-red-200 bg-red-50">
                {detailError}
              </div>
            )}

            <div className="p-3 border-b bg-muted/10 text-xs font-medium text-muted-foreground">목록</div>
            <ScrollArea className="h-56 border-b">
              <div className="p-3 space-y-2">
                {detailLoading && (
                  <div className="space-y-2">
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                  </div>
                )}
                {!detailLoading && sessionDetail?.sprints.map((sprint) => (
                  <button
                    key={sprint.sprint_id}
                    type="button"
                    onClick={() => setSelectedSprintId(sprint.sprint_id)}
                    className={`w-full text-left rounded-md border p-3 transition-colors ${
                      selectedSprintId === sprint.sprint_id
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:bg-accent/40'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs">{sprint.sprint_id}</span>
                      <StatusBadge status={sprint.status ?? 'unknown'} />
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-1.5">
                      planned {toArray(sprint.planned).length} · completed {toArray(sprint.completed).length}
                    </p>
                  </button>
                ))}
                {!detailLoading && (!sessionDetail || sessionDetail.sprints.length === 0) && (
                  <p className="text-xs text-muted-foreground px-1 py-2">스프린트가 없습니다.</p>
                )}
              </div>
            </ScrollArea>

            <div className="p-3 border-b bg-muted/10 text-xs font-medium text-muted-foreground">세부 정보</div>
            <ScrollArea className="flex-1 min-h-0">
              <div className="p-3 space-y-3">
                {!selectedSession && (
                  <p className="text-sm text-muted-foreground">먼저 세션을 선택하세요.</p>
                )}
                {selectedSession && detailLoading && (
                  <div className="space-y-2">
                    <Skeleton className="h-20 w-full" />
                    <Skeleton className="h-24 w-full" />
                  </div>
                )}
                {selectedSession && !detailLoading && !selectedSprint && (
                  <p className="text-sm text-muted-foreground">스프린트를 선택하세요.</p>
                )}
                {selectedSession && !detailLoading && selectedSprint && (
                  <>
                    <div className="rounded-md border p-3 space-y-2 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs">{selectedSprint.sprint_id}</span>
                        <StatusBadge status={selectedSprint.status ?? 'unknown'} />
                      </div>
                      <p className="text-xs text-muted-foreground">이름: {selectedSprint.sprint_id}</p>
                      <p className="text-xs text-muted-foreground">기간: {formatSprintPeriod(selectedSprint)}</p>
                    </div>

                    <div className="rounded-md border p-3">
                      <div className="text-xs font-semibold text-muted-foreground mb-2">스토리 목록</div>
                      {selectedSprintStories.length > 0 ? (
                        <ul className="list-disc pl-5 text-sm space-y-1">
                          {selectedSprintStories.map((story, index) => (
                            <li key={`${story}-${index}`}>{story}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-muted-foreground">스토리 정보가 없습니다.</p>
                      )}
                    </div>
                  </>
                )}
              </div>
            </ScrollArea>
          </div>
          <ResizableHandle isResizing={isSprintPanelResizing} onMouseDown={startSprintPanelResizing} />
        </>
      )}
      <div className="flex-1 min-h-0 flex flex-col bg-card overflow-hidden">
        {!selectedSession ? (
          <EmptyState
            icon={<GitBranch className="h-8 w-8" />}
            title="Agile 세션을 선택하세요"
            description="왼쪽 목록에서 세션을 선택하면 스프린트 타임라인과 결과 보고서를 볼 수 있습니다."
          />
        ) : (
          <>
            <div className="p-4 border-b bg-muted/10 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{selectedSession.id}</h2>
                <div className="flex gap-4 items-center mt-1">
                  <p className="text-xs text-muted-foreground">
                    current sprint: {toSprintId(selectedSession.current_sprint) ?? `S${String(selectedSession.current_sprint ?? 0).padStart(2, '0')}`}
                  </p>
                  {sessionDetail && (
                    <>
                      <p className="text-xs text-muted-foreground">
                        steering_every: {sessionDetail.session.steering_every ?? 0}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        queue: {sessionDetail.session.queue?.length ?? 0}
                      </p>
                      <p className="text-xs text-muted-foreground truncate max-w-[200px]">
                        refs: {sessionDetail.session.refs && sessionDetail.session.refs.length > 0 ? sessionDetail.session.refs.join(', ') : '없음'}
                      </p>
                    </>
                  )}
                </div>
              </div>
              <StatusBadge status={selectedSession.status} />
            </div>

            <Tabs defaultValue="timeline" className="flex-1 flex flex-col min-h-0">
              <div className="px-4 pt-3 border-b">
                <TabsList>
                  <TabsTrigger value="objective">Objective</TabsTrigger>
                  <TabsTrigger value="timeline">Timeline</TabsTrigger>
                  <TabsTrigger value="result">Result</TabsTrigger>
                </TabsList>
              </div>

              <ScrollArea className="flex-1 min-h-0">
                <div className="p-4 space-y-4">
                  <TabsContent value="objective" className="mt-0 outline-none">
                    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 h-full items-start">
                      <div className="xl:col-span-2 space-y-4">
                        <Card>
                          <CardHeader className="pb-3 flex flex-row items-center justify-between">
                            <div>
                              <CardTitle className="text-base flex items-center gap-2">
                                <FileText className="h-4 w-4" /> Objective
                                <span className="text-xs text-muted-foreground font-normal">세션 전체 목표</span>
                              </CardTitle>
                              <CardDescription>
                                세션의 목표와 요구사항
                              </CardDescription>
                            </div>
                            {objectiveContent !== null && (
                              <div className="inline-flex items-center rounded-md border border-input p-0.5 bg-muted/20">
                                <button
                                  type="button"
                                  onClick={() => handleObjectiveModeChange('preview')}
                                  className={`inline-flex h-8 items-center justify-center rounded-sm px-3 text-sm font-medium transition-colors ${
                                    !isObjectiveEditMode
                                      ? 'bg-background shadow-sm'
                                      : 'text-muted-foreground hover:bg-accent/40'
                                  }`}
                                >
                                  Preview
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleObjectiveModeChange('edit')}
                                  className={`inline-flex h-8 items-center justify-center rounded-sm px-3 text-sm font-medium transition-colors ${
                                    isObjectiveEditMode
                                      ? 'bg-background shadow-sm'
                                      : 'text-muted-foreground hover:bg-accent/40'
                                  }`}
                                >
                                  Edit
                                </button>
                              </div>
                            )}
                          </CardHeader>
                          <CardContent>
                            {statusMessage && (
                              <div className={`mb-4 px-3 py-2 text-sm rounded-md ${
                                statusMessage.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'
                              }`}>
                                {statusMessage.text}
                              </div>
                            )}
                            
                            {objectiveLoading ? (
                              <Skeleton className="h-40 w-full" />
                            ) : objectiveError ? (
                              <div className="text-sm text-red-600 p-3 bg-red-50 rounded-md">
                                {objectiveError}
                              </div>
                            ) : isObjectiveEditMode ? (
                              <div className="space-y-4">
                                <MilkdownEditor
                                  defaultValue={objectiveEditValue}
                                  onChange={setObjectiveEditValue}
                                  className="min-h-[300px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring prose prose-sm max-w-none"
                                />
                                <div className="flex gap-2">
                                  <button
                                    type="button"
                                    onClick={handleSaveObjective}
                                    className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-4 py-2"
                                  >
                                    Save
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => handleObjectiveModeChange('preview')}
                                    className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors border border-input bg-background hover:bg-accent hover:text-accent-foreground h-9 px-4 py-2"
                                  >
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            ) : objectiveContent !== null ? (
                              <>
                                <div className="rounded-md border p-4 bg-background">
                                  <MarkdownRenderer content={objectiveContent} />
                                </div>
                                {renderDodStatus(objectiveDodItems)}
                                {renderObjectiveSections(objectiveSections)}
                              </>
                            ) : (
                              <div className="text-sm text-muted-foreground py-8 text-center border rounded-md bg-muted/10">
                                objective.md가 없습니다
                              </div>
                            )}
                          </CardContent>
                        </Card>
                      </div>
                      <div className="xl:col-span-1 h-[600px] xl:h-[calc(100vh-250px)] sticky top-0">
                        {selectedSessionId ? (
                          <ObjectiveCommentsPanel agiId={selectedSessionId} />
                        ) : (
                          <Card className="h-full flex items-center justify-center text-sm text-muted-foreground bg-muted/5">
                            세션을 선택하세요
                          </Card>
                        )}
                      </div>
                    </div>
                  </TabsContent>

                  <TabsContent value="timeline" className="mt-0 outline-none">
                    <Card>
                      <CardHeader className="pb-3">
                        <CardTitle className="text-base flex items-center gap-2">
                          <GitBranch className="h-4 w-4" /> Sprint Timeline
                        </CardTitle>
                        <CardDescription>
                          Sprint - Plan - Result 흐름과 상태를 가로 타임라인으로 표시합니다.
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        {detailLoading ? (
                          <Skeleton className="h-28 w-full" />
                        ) : sessionDetail && sessionDetail.sprints.length > 0 ? (
                          <div className="overflow-x-auto pb-2">
                            <div className="inline-flex min-w-max gap-3">
                              {(selectedSprintId ? sessionDetail.sprints.filter(s => s.sprint_id === selectedSprintId) : sessionDetail.sprints).map((sprint) => {
                                const sprintStatus = toFlowStatus(sprint.status);
                                const planStatus = getPlanStatus(sprint);
                                const resultStatus = getResultStatus(sprint);

                                return (
                                  <button
                                    key={sprint.sprint_id}
                                    type="button"
                                    onClick={() => setSelectedSprintId(sprint.sprint_id)}
                                    className={`rounded-lg border p-3 cursor-pointer transition-colors text-left flex-shrink-0 ${
                                      selectedSprintId === sprint.sprint_id
                                        ? 'border-primary/60 bg-primary/5 hover:bg-primary/10'
                                        : 'border-border bg-background hover:bg-accent/40'
                                    }`}
                                  >
                                    <div className="inline-flex items-center gap-2">
                                      <TimelineNode title={sprint.sprint_id} subtitle="Sprint" status={sprintStatus} />
                                      <ArrowRight className="h-4 w-4 text-muted-foreground" />
                                      <TimelineNode
                                        title="Plan"
                                        subtitle={`${toArray(sprint.completed).length}/${toArray(sprint.planned).length}`}
                                        status={planStatus}
                                      />
                                      <ArrowRight className="h-4 w-4 text-muted-foreground" />
                                      <TimelineNode
                                        title="Result"
                                        subtitle={`PLN ${toArray(sprint.generated?.pln).length} · REQ ${toArray(sprint.generated?.req).length}`}
                                        status={resultStatus}
                                      />
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        ) : (
                          <div className="text-sm text-muted-foreground">타임라인 데이터가 없습니다.</div>
                        )}
                      </CardContent>
                    </Card>
                  </TabsContent>

                  <TabsContent value="result" className="mt-0 outline-none">
                    <Card>
                      <CardHeader className="pb-3">
                        <CardTitle className="text-base flex items-center gap-2">
                          <FileText className="h-4 w-4" /> Sprint Result Report
                        </CardTitle>
                        <CardDescription>
                          {selectedSprintId ? `${selectedSprintId} 결과 보고서와 회고` : '스프린트를 선택하세요'}
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        {reportLoading ? (
                          <div className="space-y-3">
                            <Skeleton className="h-6 w-44" />
                            <Skeleton className="h-28 w-full" />
                            <Skeleton className="h-24 w-full" />
                          </div>
                        ) : selectedSprintId && selectedSprint ? (
                          <>
                            {reportError && (
                              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
                                {reportError}
                              </div>
                            )}

                            {selectedSprintGoals.length > 0 ? (
                              <>
                                <div className="rounded-md border p-4 space-y-3">
                                  <div className="text-sm font-semibold">목표 달성 현황</div>
                                  {selectedSprintGoals.map((goal, index) => {
                                    const achieved = isGoalAchieved(goal.status);
                                    const evidence = goal.evidence;
                                    const screenshots = toArray(evidence?.screenshots)
                                      .filter((item) => typeof item === 'string' && item.trim().length > 0);
                                    const screenshotLinks = screenshots.length > 0
                                      ? screenshots.map((shot, shotIndex) => `[screenshot ${shotIndex + 1}](${shot})`).join(', ')
                                      : '증빙 미첨부';

                                    return (
                                      <div key={`${goal.goal}-${index}`} className="rounded-md border bg-muted/10 p-3 space-y-2">
                                        <div className="text-sm font-medium">
                                          {achieved ? '✅' : '❌'} {goal.goal}
                                        </div>
                                        <div className="text-xs text-muted-foreground">
                                          status: {goal.status}
                                        </div>
                                        <div className="text-sm" onClick={handleResultClick}>
                                          <MarkdownRenderer content={linkify(goal.change_summary)} />
                                        </div>
                                        <div className="space-y-1 text-sm">
                                          <div className="text-xs text-muted-foreground">증빙</div>
                                          <div onClick={handleResultClick}>
                                            <span className="text-xs text-muted-foreground">스크린샷: </span>
                                            <MarkdownRenderer content={linkify(screenshotLinks)} />
                                          </div>
                                          <div>
                                            <span className="text-xs text-muted-foreground">테스트: </span>
                                            {formatGoalTestResults(evidence?.test_results)}
                                          </div>
                                          <div>
                                            <span className="text-xs text-muted-foreground">diff: </span>
                                            {formatGoalDiff(evidence?.diff)}
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>

                                <details className="rounded-md border p-4">
                                  <summary className="cursor-pointer text-sm font-semibold">스프린트 메타데이터</summary>
                                  <div className="mt-3 space-y-4">
                                    <div>
                                      <div className="text-xs font-semibold text-muted-foreground mb-2">result.md</div>
                                      <div onClick={handleResultClick}>
                                        <MarkdownRenderer content={linkify(resultMarkdown ?? buildFallbackResultMarkdown(selectedSprint))} />
                                      </div>
                                    </div>
                                    {retrospectiveMd && (
                                      <div>
                                        <div className="text-xs font-semibold text-muted-foreground mb-2">retrospective.md</div>
                                        <div onClick={handleResultClick}>
                                          <MarkdownRenderer content={linkify(retrospectiveMd)} />
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                </details>
                              </>
                            ) : (
                              <>
                                <div className="rounded-md border p-4">
                                  <div className="text-sm font-semibold mb-3">result.md</div>
                                  <div onClick={handleResultClick}>
                                    <MarkdownRenderer content={linkify(resultMarkdown ?? buildFallbackResultMarkdown(selectedSprint))} />
                                  </div>
                                </div>
                                {retrospectiveMd && (
                                  <div className="rounded-md border p-4">
                                    <div className="text-sm font-semibold mb-3">retrospective.md</div>
                                    <div onClick={handleResultClick}>
                                      <MarkdownRenderer content={linkify(retrospectiveMd)} />
                                    </div>
                                  </div>
                                )}
                              </>
                            )}

                            <details className="rounded-md border p-4">
                              <summary className="cursor-pointer text-sm font-semibold flex items-center gap-2">
                                <ListChecks className="h-4 w-4" /> 스프린트 회고
                              </summary>

                              <div className="mt-4 space-y-4">
                                {retrospective ? (
                                  <>
                                    <div className="space-y-2">
                                      <h4 className="text-xs font-semibold text-muted-foreground">succeeded</h4>
                                      {toArray(retrospective.succeeded).length > 0 ? (
                                        <ul className="list-disc pl-5 text-sm space-y-1">
                                          {toArray(retrospective.succeeded).map((item, index) => (
                                            <li key={`${item}-${index}`}>{item}</li>
                                          ))}
                                        </ul>
                                      ) : (
                                        <p className="text-sm text-muted-foreground">기록 없음</p>
                                      )}
                                    </div>

                                    <div className="space-y-2">
                                      <h4 className="text-xs font-semibold text-muted-foreground">failed</h4>
                                      {toArray(retrospective.failed).length > 0 ? (
                                        <div className="space-y-2">
                                          {toArray(retrospective.failed).map((item, index) => (
                                            <div key={`${item.item ?? 'failed'}-${index}`} className="rounded-md border bg-muted/20 p-3 text-sm">
                                              <div className="font-medium">{item.item ?? `Failure ${index + 1}`}</div>
                                              <div className="text-xs text-muted-foreground mt-1">
                                                tried_approach: {item.tried_approach ?? '-'}
                                              </div>
                                              <div className="text-xs text-muted-foreground mt-1">
                                                failure_reason: {item.failure_reason ?? '-'}
                                              </div>
                                            </div>
                                          ))}
                                        </div>
                                      ) : (
                                        <p className="text-sm text-muted-foreground">기록 없음</p>
                                      )}
                                    </div>

                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm">
                                      <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground">velocity planned</div>
                                        <div className="font-semibold">{retrospective.velocity?.planned ?? '-'}</div>
                                      </div>
                                      <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground">velocity completed</div>
                                        <div className="font-semibold">{retrospective.velocity?.completed ?? '-'}</div>
                                      </div>
                                      <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground">velocity rate</div>
                                        <div className="font-semibold">{formatRate(retrospective.velocity?.rate)}</div>
                                      </div>
                                    </div>

                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
                                      <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground mb-1">known_limitations</div>
                                        <div>{retrospective.known_limitations || '-'}</div>
                                      </div>
                                      <div className="rounded-md border p-3">
                                        <div className="text-xs text-muted-foreground mb-1">lessons_learned</div>
                                        <div>{retrospective.lessons_learned || '-'}</div>
                                      </div>
                                    </div>

                                    <div className="rounded-md border p-3 text-sm">
                                      <div className="text-xs text-muted-foreground mb-1">direction</div>
                                      <div>{retrospective.direction || '-'}</div>
                                    </div>
                                  </>
                                ) : (
                                  <p className="text-sm text-muted-foreground">retrospective.json이 아직 없습니다.</p>
                                )}
                              </div>
                            </details>
                          </>
                        ) : (
                          <div className="text-sm text-muted-foreground">왼쪽에서 스프린트를 선택하세요.</div>
                        )}
                      </CardContent>
                    </Card>
                  </TabsContent>
                </div>
              </ScrollArea>
            </Tabs>
          </>
        )}
      </div>
    </div>
  );
}
