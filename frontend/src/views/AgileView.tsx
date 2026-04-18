import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { useMatch, useNavigate, useParams } from 'react-router-dom';
import { GitBranch } from 'lucide-react';
import { useAppContext } from '@/context/AppContext';
import { ApiFetchError, apiFetch } from '@/hooks/useApi';
import { useResizableSidebar } from '@/hooks/useResizableSidebar';
import { ResizableHandle } from '@/components/shared/ResizableHandle';
import { EmptyState } from '@/components/shared/EmptyState';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ActionBoard } from '@/components/agile/ActionBoard';
import { AlignmentView } from '@/components/agile/AlignmentView';
import { DeepDivePanel } from '@/components/agile/DeepDivePanel';
import { HealthSummary } from '@/components/agile/HealthSummary';
import { ObjectiveWorkspace } from '@/components/agile/ObjectiveWorkspace';
import { SessionSidebar } from '@/components/agile/SessionSidebar';
import { SprintDetailView } from '@/components/agile/SprintDetailView';
import { SprintTimeline } from '@/components/agile/SprintTimeline';
import type {
  AgileRetrospective,
  AgileSessionDetail,
  AgileSessionSummary,
  ObjectiveParsedContent,
  ObjectiveResponsePayload,
} from '@/components/agile/types';
import {
  buildActionCards,
  buildFallbackResultMarkdown,
  computeDodProgress,
  computeOpenKnownIssues,
  getLatestNewIslandRatio,
  getSprintGoals,
  getSprintWhyItems,
  linkify,
  parseDodMarkers,
  resolveAgileMainTab,
  resolveAgileSelectedSessionId,
  resolveDefaultSprintId,
  resolveObjectiveMarkdownPath,
  rewriteLocalMarkdownImagePaths,
  sortSprints,
  toArray,
  toSprintId,
  type MainTabValue,
} from '@/components/agile/utils';

export { resolveAgileMainTab, resolveAgileSelectedSessionId };

export function AgileView() {
  const navigate = useNavigate();
  const { agiId } = useParams();
  const isObjectiveRoute = Boolean(useMatch('/agile/:agiId/objective'));
  const { projectId, lastSseEvent } = useAppContext();

  const [sessions, setSessions] = useState<AgileSessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionDetail, setSessionDetail] = useState<AgileSessionDetail | null>(null);
  const [selectedSprintId, setSelectedSprintId] = useState<string | null | undefined>(undefined);
  const [resultMarkdown, setResultMarkdown] = useState<string | null>(null);
  const [retrospective, setRetrospective] = useState<AgileRetrospective | null>(null);
  const [retrospectiveMd, setRetrospectiveMd] = useState<string | null>(null);
  const [resultDetailFiles, setResultDetailFiles] = useState<string[]>([]);
  const [selectedResultDetailFile, setSelectedResultDetailFile] = useState<string | null>(null);
  const [resultDetailContent, setResultDetailContent] = useState<string | null>(null);
  const [resultDetailFilesLoading, setResultDetailFilesLoading] = useState(false);
  const [resultDetailLoading, setResultDetailLoading] = useState(false);
  const [resultDetailError, setResultDetailError] = useState<string | null>(null);
  const [isResultCompareMode, setIsResultCompareMode] = useState(false);
  const [isDeepDiveOpen, setIsDeepDiveOpen] = useState(false);

  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);

  const [objectiveContent, setObjectiveContent] = useState<string | null>(null);
  const [objectiveParsed, setObjectiveParsed] = useState<ObjectiveParsedContent | null>(null);
  const [objectiveLoading, setObjectiveLoading] = useState(false);
  const [objectiveError, setObjectiveError] = useState<string | null>(null);
  const [isObjectiveEditMode, setIsObjectiveEditMode] = useState(false);
  const [objectiveEditValue, setObjectiveEditValue] = useState('');
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [objectiveFiles, setObjectiveFiles] = useState<string[]>([]);
  const [selectedObjectiveFile, setSelectedObjectiveFile] = useState('objective.md');
  const [isObjectiveTreeCollapsed, setIsObjectiveTreeCollapsed] = useState(false);
  const [objectiveDetailContent, setObjectiveDetailContent] = useState<string | null>(null);
  const [objectiveDetailLoading, setObjectiveDetailLoading] = useState(false);
  const [objectiveDetailError, setObjectiveDetailError] = useState<string | null>(null);
  const [objectiveEtag, setObjectiveEtag] = useState<string | null>(null);
  const [activeMainTab, setActiveMainTab] = useState<MainTabValue>('overview');
  const [isObjectiveCommentsCollapsed, setIsObjectiveCommentsCollapsed] = useState(
    () => localStorage.getItem('agile-objective-comments-collapsed') === 'true',
  );

  const statusTimeoutRef = useRef<number | null>(null);

  const {
    sidebarWidth,
    isResizing,
    startResizing,
    sidebarRef,
  } = useResizableSidebar({ defaultWidth: 320, minWidth: 280, maxWidth: 560, storageKey: 'agile-sidebar-width' });
  const {
    sidebarWidth: objectiveTreeWidth,
    isResizing: isObjectiveTreeResizing,
    startResizing: startObjectiveTreeResizing,
    sidebarRef: objectiveTreeRef,
  } = useResizableSidebar({ defaultWidth: 160, minWidth: 120, maxWidth: 280, storageKey: 'agile-objective-tree-width' });
  const {
    sidebarWidth: deepDiveWidth,
    isResizing: isDeepDiveResizing,
    startResizing: startDeepDiveResizing,
    sidebarRef: deepDiveRef,
  } = useResizableSidebar({ defaultWidth: 420, minWidth: 340, maxWidth: 620, storageKey: 'agile-deep-dive-width' });

  useEffect(() => {
    localStorage.setItem('agile-objective-comments-collapsed', String(isObjectiveCommentsCollapsed));
  }, [isObjectiveCommentsCollapsed]);

  useEffect(() => {
    setActiveMainTab(resolveAgileMainTab(isObjectiveRoute));
  }, [isObjectiveRoute]);

  useEffect(() => {
    return () => {
      if (statusTimeoutRef.current) window.clearTimeout(statusTimeoutRef.current);
    };
  }, []);

  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) ?? null,
    [sessions, selectedSessionId],
  );
  const selectedSprint = useMemo(
    () => sessionDetail?.sprints.find((sprint) => sprint.sprint_id === selectedSprintId) ?? null,
    [sessionDetail, selectedSprintId],
  );
  const currentSprintId = useMemo(
    () => toSprintId(sessionDetail?.session.current_sprint ?? selectedSession?.current_sprint),
    [sessionDetail?.session.current_sprint, selectedSession?.current_sprint],
  );
  const selectedSprintIndex = useMemo(
    () => sessionDetail?.sprints.findIndex((sprint) => sprint.sprint_id === selectedSprintId) ?? -1,
    [sessionDetail, selectedSprintId],
  );
  const previousSprint = useMemo(
    () => (selectedSprintIndex > 0 && sessionDetail ? sessionDetail.sprints[selectedSprintIndex - 1] ?? null : null),
    [selectedSprintIndex, sessionDetail],
  );
  const selectedSprintGoals = useMemo(() => getSprintGoals(selectedSprint), [selectedSprint]);
  const previousSprintGoals = useMemo(() => getSprintGoals(previousSprint), [previousSprint]);
  const selectedSprintWhyItems = useMemo(() => getSprintWhyItems(selectedSprint), [selectedSprint]);
  const previousSprintWhyItems = useMemo(() => getSprintWhyItems(previousSprint), [previousSprint]);
  const canCompareResult = Boolean(previousSprint);
  const objectiveDodItems = useMemo(() => {
    if (objectiveParsed?.dods?.length) return objectiveParsed.dods;
    return objectiveContent ? parseDodMarkers(objectiveContent) : [];
  }, [objectiveContent, objectiveParsed]);
  const objectiveSections = useMemo(() => objectiveParsed?.sections ?? [], [objectiveParsed]);
  const dodProgress = useMemo(() => computeDodProgress(objectiveDodItems), [objectiveDodItems]);
  const openKnownIssues = useMemo(
    () => computeOpenKnownIssues(sessionDetail?.sprints ?? [], toArray(retrospective?.failed).length),
    [retrospective?.failed, sessionDetail?.sprints],
  );
  const latestNewIslandRatio = useMemo(
    () => getLatestNewIslandRatio(sessionDetail?.sprints ?? [], currentSprintId),
    [currentSprintId, sessionDetail?.sprints],
  );
  const actionCards = useMemo(
    () => buildActionCards(sessionDetail?.session ?? null, sessionDetail?.sprints ?? [], currentSprintId),
    [currentSprintId, sessionDetail?.session, sessionDetail?.sprints],
  );

  const rewriteMarkdown = useCallback(
    (content: string) => rewriteLocalMarkdownImagePaths(content, selectedSessionId),
    [selectedSessionId],
  );
  const rewriteLinkedMarkdown = useCallback(
    (content: string) => rewriteMarkdown(linkify(content)),
    [rewriteMarkdown],
  );

  const handleResultClick = useCallback((event: MouseEvent) => {
    const target = event.target as HTMLElement;
    const anchor = target.closest('a');
    const href = anchor?.getAttribute('href');
    if (href?.startsWith('/')) {
      event.preventDefault();
      navigate(href);
    }
  }, [navigate]);

  const handleObjectiveMarkdownLinkClick = useCallback((event: MouseEvent<HTMLAnchorElement>, href: string) => {
    const nextFile = resolveObjectiveMarkdownPath(href, selectedObjectiveFile);
    if (!nextFile) return;

    const canNavigate = nextFile === 'objective.md' || objectiveFiles.includes(nextFile);
    if (!canNavigate) return;

    event.preventDefault();
    setSelectedObjectiveFile(nextFile);
  }, [objectiveFiles, selectedObjectiveFile]);

  const resetResultDetailState = useCallback(() => {
    setResultDetailFiles([]);
    setSelectedResultDetailFile(null);
    setResultDetailContent(null);
    setResultDetailError(null);
    setResultDetailFilesLoading(false);
    setResultDetailLoading(false);
  }, []);

  const resetSprintState = useCallback(() => {
    setSelectedSprintId(undefined);
    setResultMarkdown(null);
    setRetrospective(null);
    setRetrospectiveMd(null);
    setReportError(null);
    setReportLoading(false);
    setIsResultCompareMode(false);
    resetResultDetailState();
  }, [resetResultDetailState]);

  const resetObjectiveState = useCallback(() => {
    setObjectiveContent(null);
    setObjectiveParsed(null);
    setObjectiveError(null);
    setObjectiveLoading(false);
    setIsObjectiveEditMode(false);
    setObjectiveEditValue('');
    setObjectiveFiles([]);
    setSelectedObjectiveFile('objective.md');
    setObjectiveDetailContent(null);
    setObjectiveDetailError(null);
    setObjectiveDetailLoading(false);
    setObjectiveEtag(null);
    setStatusMessage(null);
  }, []);

  const requestSessions = useCallback(async (): Promise<AgileSessionSummary[]> => {
    const data = await apiFetch<AgileSessionSummary[]>('/api/agile/sessions', projectId);
    return Array.isArray(data) ? data : [];
  }, [projectId]);

  const requestSessionDetail = useCallback(async (sessionId: string): Promise<AgileSessionDetail> => {
    const data = await apiFetch<AgileSessionDetail>(`/api/agile/sessions/${sessionId}`, projectId);
    return { ...data, sprints: sortSprints(Array.isArray(data.sprints) ? data.sprints : []) };
  }, [projectId]);

  const requestResultMarkdown = useCallback(async (sessionId: string, sprint: NonNullable<typeof selectedSprint>): Promise<string> => {
    if (typeof sprint.result_md === 'string' && sprint.result_md.trim().length > 0) return sprint.result_md;

    try {
      const data = await apiFetch<{ content: string }>(
        `/api/file?path=${encodeURIComponent(`agile/${sessionId}/sprints/${sprint.sprint_id}/result.md`)}`,
        projectId,
      );
      return data.content;
    } catch (error) {
      if (error instanceof ApiFetchError && error.status === 404) {
        return buildFallbackResultMarkdown(sprint);
      }
      throw error;
    }
  }, [projectId]);

  const requestRetrospective = useCallback(async (sessionId: string, sprintId: string): Promise<AgileRetrospective | null> => {
    try {
      return await apiFetch<AgileRetrospective>(`/api/agile/sessions/${sessionId}/sprints/${sprintId}/retrospective`, projectId);
    } catch (error) {
      if (error instanceof ApiFetchError && error.status === 404) return null;
      throw error;
    }
  }, [projectId]);

  const requestRetrospectiveMd = useCallback(async (sessionId: string, sprintId: string): Promise<string | null> => {
    try {
      return await apiFetch<string>(
        `/api/agile/sessions/${sessionId}/sprints/${sprintId}/retrospective-md`,
        projectId,
        { parseAs: 'text' },
      );
    } catch (error) {
      if (error instanceof ApiFetchError && error.status === 404) return null;
      throw error;
    }
  }, [projectId]);

  const requestResultDetailFiles = useCallback(async (sessionId: string, sprintId: string): Promise<string[]> => {
    try {
      const data = await apiFetch<{ files?: Array<{ name?: string }> }>(
        `/api/agile/sessions/${sessionId}/sprints/${sprintId}/result-details/files`,
        projectId,
      );
      return toArray(data.files)
        .map((item) => (typeof item?.name === 'string' ? item.name : null))
        .filter((name): name is string => Boolean(name && name.trim().length > 0));
    } catch (error) {
      if (error instanceof ApiFetchError && error.status === 404) return [];
      throw error;
    }
  }, [projectId]);

  const requestResultDetail = useCallback(async (sessionId: string, sprintId: string, filename: string): Promise<string | null> => {
    try {
      const data = await apiFetch<{ content?: string }>(
        `/api/agile/sessions/${sessionId}/sprints/${sprintId}/result-details/${encodeURIComponent(filename)}`,
        projectId,
      );
      return typeof data.content === 'string' ? data.content : null;
    } catch (error) {
      if (error instanceof ApiFetchError && error.status === 404) return null;
      throw error;
    }
  }, [projectId]);

  const requestObjectiveFiles = useCallback(async (sessionId: string): Promise<string[]> => {
    try {
      const data = await apiFetch<{ files?: Array<{ name?: string; path?: string }> }>(
        `/api/agile/sessions/${sessionId}/objective/files`,
        projectId,
      );
      return toArray(data.files)
        .map((item) => (typeof item?.name === 'string' ? item.name : typeof item?.path === 'string' ? item.path : null))
        .filter((name): name is string => Boolean(name && name.trim().length > 0));
    } catch (error) {
      if (error instanceof ApiFetchError && error.status === 404) return [];
      throw error;
    }
  }, [projectId]);

  const requestObjectiveDetail = useCallback(async (sessionId: string, filename: string): Promise<string | null> => {
    const data = await apiFetch<{ content?: string }>(
      `/api/agile/sessions/${sessionId}/objective/details/${encodeURIComponent(filename)}`,
      projectId,
    );
    return typeof data.content === 'string' ? data.content : null;
  }, [projectId]);

  const requestObjective = useCallback(async (sessionId: string): Promise<ObjectiveResponsePayload | null> => {
    try {
      const response = await apiFetch<Response>(`/api/agile/${sessionId}/objective`, projectId, { parseAs: 'response' });
      setObjectiveEtag(response.headers.get('ETag'));
      const data = await response.json() as ObjectiveResponsePayload;
      const normalizedDods = Array.isArray(data.parsed?.dods)
        ? data.parsed.dods.map((dod) => ({
          dod: dod.dod?.toUpperCase?.() ?? '',
          status: dod.status ?? 'todo',
          priority: dod.priority ?? 'must',
          anchorText: dod.anchorText ?? null,
          contentText: dod.contentText ?? null,
        })).filter((dod) => dod.dod.length > 0)
        : [];
      return {
        ...data,
        parsed: {
          dods: normalizedDods,
          sections: Array.isArray(data.parsed?.sections) ? data.parsed.sections : [],
        },
      };
    } catch (error) {
      if (error instanceof ApiFetchError && error.status === 404) return null;
      throw error;
    }
  }, [projectId]);

  useEffect(() => {
    if (sessions.length === 0) {
      setSelectedSessionId(null);
      return;
    }
    setSelectedSessionId((previous) => resolveAgileSelectedSessionId(sessions, previous, agiId));
  }, [agiId, sessions]);

  useEffect(() => {
    if (!canCompareResult) setIsResultCompareMode(false);
  }, [canCompareResult]);

  useEffect(() => {
    if (!projectId) {
      setSessions([]);
      setSelectedSessionId(null);
      setSessionDetail(null);
      setDetailLoading(false);
      setSessionsLoading(false);
      setDetailError(null);
      setSessionsError(null);
      resetSprintState();
      resetObjectiveState();
      return;
    }

    let cancelled = false;
    setSessionsLoading(true);
    requestSessions()
      .then((data) => {
        if (cancelled) return;
        setSessions(data);
        setSessionsError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        setSessions([]);
        setSessionsError(error instanceof Error ? error.message : '세션 목록을 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setSessionsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, requestSessions, resetObjectiveState, resetSprintState]);

  useEffect(() => {
    if (!projectId || !selectedSessionId) {
      setSessionDetail(null);
      setDetailLoading(false);
      setDetailError(null);
      resetSprintState();
      resetObjectiveState();
      return;
    }

    let cancelled = false;
    setDetailLoading(true);
    setObjectiveLoading(true);
    resetSprintState();
    setObjectiveFiles([]);
    setSelectedObjectiveFile('objective.md');
    setObjectiveDetailContent(null);
    setObjectiveDetailError(null);
    setIsObjectiveEditMode(false);
    setStatusMessage(null);

    requestObjective(selectedSessionId)
      .then((objective) => {
        if (cancelled) return;
        setObjectiveContent(objective?.content ?? null);
        setObjectiveParsed(objective?.parsed ?? null);
        setObjectiveError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        setObjectiveContent(null);
        setObjectiveParsed(null);
        setObjectiveError(error instanceof Error ? error.message : 'Objective를 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setObjectiveLoading(false);
      });

    requestObjectiveFiles(selectedSessionId)
      .then((files) => {
        if (cancelled) return;
        setObjectiveFiles(files);
      })
      .catch((error) => {
        if (!cancelled) {
          setObjectiveError(error instanceof Error ? error.message : 'Objective 파일 목록을 불러오지 못했습니다.');
        }
      });

    requestSessionDetail(selectedSessionId)
      .then((data) => {
        if (cancelled) return;
        setSessionDetail(data);
        setDetailError(null);
        setSelectedSprintId(resolveDefaultSprintId(data.sprints, data.session.current_sprint, null));
      })
      .catch((error) => {
        if (cancelled) return;
        setSessionDetail(null);
        setSelectedSprintId(null);
        setDetailError(error instanceof Error ? error.message : '세션 상세를 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, requestObjective, requestObjectiveFiles, requestSessionDetail, resetObjectiveState, resetSprintState, selectedSessionId]);

  useEffect(() => {
    if (!projectId || !selectedSessionId || !selectedObjectiveFile || selectedObjectiveFile === 'objective.md') {
      setObjectiveDetailContent(null);
      setObjectiveDetailError(null);
      setObjectiveDetailLoading(false);
      return;
    }

    let cancelled = false;
    setObjectiveDetailLoading(true);
    setObjectiveDetailError(null);
    requestObjectiveDetail(selectedSessionId, selectedObjectiveFile)
      .then((content) => {
        if (!cancelled) setObjectiveDetailContent(content);
      })
      .catch((error) => {
        if (!cancelled) setObjectiveDetailError(error instanceof Error ? error.message : '문서 내용을 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setObjectiveDetailLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, requestObjectiveDetail, selectedObjectiveFile, selectedSessionId]);

  useEffect(() => {
    if (!projectId || !selectedSessionId || !selectedSprintId || !selectedSprint) {
      resetResultDetailState();
      return;
    }

    let cancelled = false;
    setResultDetailFilesLoading(true);
    setResultDetailError(null);
    requestResultDetailFiles(selectedSessionId, selectedSprintId)
      .then((files) => {
        if (cancelled) return;
        setResultDetailFiles(files);
        setSelectedResultDetailFile((previous) => {
          if (files.length === 0) return null;
          return previous && files.includes(previous) ? previous : files[0];
        });
      })
      .catch((error) => {
        if (!cancelled) setResultDetailError(error instanceof Error ? error.message : '상세 파일 목록을 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setResultDetailFilesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, requestResultDetailFiles, resetResultDetailState, selectedSessionId, selectedSprint, selectedSprintId]);

  useEffect(() => {
    if (!projectId || !selectedSessionId || !selectedSprintId || !selectedResultDetailFile) {
      setResultDetailContent(null);
      setResultDetailError(null);
      setResultDetailLoading(false);
      return;
    }

    let cancelled = false;
    setResultDetailLoading(true);
    setResultDetailError(null);
    requestResultDetail(selectedSessionId, selectedSprintId, selectedResultDetailFile)
      .then((content) => {
        if (!cancelled) setResultDetailContent(content);
      })
      .catch((error) => {
        if (!cancelled) setResultDetailError(error instanceof Error ? error.message : '상세 내용을 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setResultDetailLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, requestResultDetail, selectedResultDetailFile, selectedSessionId, selectedSprintId]);

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
      .catch((error) => {
        if (cancelled) return;
        setResultMarkdown(buildFallbackResultMarkdown(selectedSprint));
        setRetrospective(null);
        setRetrospectiveMd(null);
        setReportError(error instanceof Error ? error.message : '스프린트 보고서를 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setReportLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, requestResultMarkdown, requestRetrospective, requestRetrospectiveMd, selectedSessionId, selectedSprint, selectedSprintId]);

  useEffect(() => {
    if (!projectId || !lastSseEvent) return;

    if (lastSseEvent.type === 'objective_changed') {
      const eventSessionId = lastSseEvent.sessionId ?? lastSseEvent.session_id ?? lastSseEvent.data?.agiId;
      if (selectedSessionId && (!eventSessionId || eventSessionId === selectedSessionId)) {
        requestObjective(selectedSessionId)
          .then((objective) => {
            setObjectiveContent(objective?.content ?? null);
            setObjectiveParsed(objective?.parsed ?? null);
            setObjectiveError(null);
          })
          .catch(() => undefined);
      }
      return;
    }

    if (lastSseEvent.type !== 'agile_update') return;

    requestSessions()
      .then((nextSessions) => {
        setSessions(nextSessions);
        setSessionsError(null);
        setSelectedSessionId((previous) => resolveAgileSelectedSessionId(nextSessions, previous, agiId));
      })
      .catch(() => undefined);

    const eventSessionId = lastSseEvent.sessionId ?? lastSseEvent.session_id ?? lastSseEvent.data?.agiId;
    if (selectedSessionId && (!eventSessionId || eventSessionId === selectedSessionId)) {
      requestSessionDetail(selectedSessionId)
        .then((data) => {
          setSessionDetail(data);
          setSelectedSprintId((previous) => (previous === null ? null : resolveDefaultSprintId(data.sprints, data.session.current_sprint, previous)));
        })
        .catch(() => undefined);
    }
  }, [agiId, lastSseEvent, projectId, requestObjective, requestSessionDetail, requestSessions, selectedSessionId]);

  const navigateForSession = useCallback((sessionId: string, nextTab: MainTabValue = activeMainTab) => {
    if (nextTab === 'objective') {
      navigate(`/agile/${sessionId}/objective`);
      return;
    }
    navigate(`/agile/${sessionId}`);
  }, [activeMainTab, navigate]);

  const handleSelectSession = useCallback((sessionId: string) => {
    setSelectedSessionId(sessionId);
    navigateForSession(sessionId, activeMainTab);
  }, [activeMainTab, navigateForSession]);

  const handleMainTabChange = useCallback((value: string) => {
    if (value !== 'overview' && value !== 'sprint-detail' && value !== 'objective') return;
    setActiveMainTab(value);
    if (selectedSessionId) {
      navigateForSession(selectedSessionId, value);
    } else if (value !== 'objective') {
      navigate('/agile');
    }
  }, [navigate, navigateForSession, selectedSessionId]);

  const handleSelectSprint = useCallback((sprintId: string, tab: MainTabValue = 'sprint-detail') => {
    setSelectedSprintId(sprintId);
    setActiveMainTab(tab);
    if (selectedSessionId && tab !== 'objective') {
      navigate(`/agile/${selectedSessionId}`);
    }
  }, [navigate, selectedSessionId]);

  const handleRefresh = useCallback(async () => {
    if (!projectId) return;
    setIsRefreshing(true);
    try {
      const nextSessions = await requestSessions();
      setSessions(nextSessions);
      setSessionsError(null);
      const resolvedSessionId = resolveAgileSelectedSessionId(nextSessions, selectedSessionId, agiId);
      setSelectedSessionId(resolvedSessionId);

      if (!resolvedSessionId) {
        setSessionDetail(null);
        resetSprintState();
        resetObjectiveState();
        return;
      }

      const [detail, objective] = await Promise.all([
        requestSessionDetail(resolvedSessionId),
        requestObjective(resolvedSessionId),
      ]);
      setSessionDetail(detail);
      setDetailError(null);
      setObjectiveContent(objective?.content ?? null);
      setObjectiveParsed(objective?.parsed ?? null);
      setObjectiveError(null);
      const nextSprintId = resolveDefaultSprintId(detail.sprints, detail.session.current_sprint, selectedSprintId ?? null);
      setSelectedSprintId(nextSprintId);
    } catch (error) {
      setSessionsError(error instanceof Error ? error.message : 'Agile 데이터를 새로고침하지 못했습니다.');
    } finally {
      setIsRefreshing(false);
    }
  }, [agiId, projectId, requestObjective, requestSessionDetail, requestSessions, resetObjectiveState, resetSprintState, selectedSessionId, selectedSprintId]);

  const handleSaveObjective = useCallback(async () => {
    if (!projectId || !selectedSessionId) return;

    try {
      setStatusMessage(null);
      await apiFetch<Response>(`/api/agile/${selectedSessionId}/objective`, projectId, {
        method: 'PATCH',
        headers: objectiveEtag ? { 'If-Match': objectiveEtag } : undefined,
        body: JSON.stringify({ content: objectiveEditValue }),
        parseAs: 'response',
      });
      const objective = await requestObjective(selectedSessionId);
      setObjectiveContent(objective?.content ?? objectiveEditValue);
      setObjectiveParsed(objective?.parsed ?? null);
      setIsObjectiveEditMode(false);
      setStatusMessage({ type: 'success', text: '저장 완료' });
    } catch (error) {
      const message = error instanceof ApiFetchError && error.status === 409
        ? '다른 프로세스에 의해 Objective가 수정되었습니다. (충돌 발생)'
        : error instanceof Error ? error.message : '저장 실패';
      setStatusMessage({ type: 'error', text: message });
    } finally {
      if (statusTimeoutRef.current) window.clearTimeout(statusTimeoutRef.current);
      statusTimeoutRef.current = window.setTimeout(() => setStatusMessage(null), 3000);
    }
  }, [objectiveEditValue, objectiveEtag, projectId, requestObjective, selectedSessionId]);

  const handleObjectiveModeChange = useCallback((mode: 'preview' | 'edit') => {
    if (mode === 'edit') {
      setObjectiveEditValue(objectiveContent ?? '');
      setIsObjectiveEditMode(true);
    } else {
      setIsObjectiveEditMode(false);
    }
    setStatusMessage(null);
  }, [objectiveContent]);

  if (!projectId) {
    return <div className="flex flex-1 items-center justify-center text-muted-foreground">프로젝트를 선택하세요</div>;
  }

  if (sessionsLoading && sessions.length === 0) {
    return (
      <div className="grid h-full grid-cols-12 gap-6 p-6">
        <div className="col-span-4 space-y-4">{[1, 2, 3].map((item) => <Skeleton key={item} className="h-24 w-full" />)}</div>
        <div className="col-span-8"><Skeleton className="h-full w-full" /></div>
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden bg-white">
      <div ref={sidebarRef} style={{ width: sidebarWidth }} className="min-h-0 shrink-0">
        <SessionSidebar
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          sessionsError={sessionsError}
          isRefreshing={isRefreshing}
          onRefresh={handleRefresh}
          onSelectSession={handleSelectSession}
        />
      </div>
      <ResizableHandle isResizing={isResizing} onMouseDown={startResizing} />

      {!selectedSession ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyState
            icon={<GitBranch className="h-8 w-8" />}
            title="Agile 세션을 선택하세요"
            description="왼쪽 목록에서 세션을 선택하면 승인 대기, alignment, 스프린트 흐름을 볼 수 있습니다."
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="border-b border-zinc-200 bg-white px-6 py-5">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Conductor&apos;s Dashboard</p>
                  <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-950">{selectedSession.id}</h1>
                  <div className="mt-2 flex flex-wrap gap-4 text-sm text-zinc-500">
                    <span>current sprint: {toSprintId(selectedSession.current_sprint) ?? '-'}</span>
                    <span>steering_every: {sessionDetail?.session.steering_every ?? 0}</span>
                    <span>queue: {sessionDetail?.session.queue?.length ?? 0}</span>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setIsDeepDiveOpen((previous) => !previous)}
                    className="rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100"
                  >
                    {isDeepDiveOpen ? 'Deep Dive 닫기' : 'Deep Dive 열기'}
                  </button>
                </div>
              </div>
            </div>

            <Tabs value={activeMainTab} onValueChange={handleMainTabChange} className="flex min-h-0 flex-1 flex-col">
              <div className="border-b border-zinc-200 px-6 pt-3">
                <TabsList>
                  <TabsTrigger value="overview">대시보드</TabsTrigger>
                  <TabsTrigger value="sprint-detail">스프린트</TabsTrigger>
                  <TabsTrigger value="objective">Objective</TabsTrigger>
                </TabsList>
              </div>

              <ScrollArea className="min-h-0 flex-1">
                <div className="space-y-6 p-6">
                  <TabsContent value="overview" className="mt-0 outline-none">
                    <div className="space-y-6">
                      {detailError ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{detailError}</div> : null}
                      <div className="grid gap-6 xl:grid-cols-12">
                        <div className="xl:col-span-8">
                          <ActionBoard cards={actionCards} />
                        </div>
                        <div className="xl:col-span-4">
                          <HealthSummary
                            dodProgress={dodProgress}
                            openIssuesCount={openKnownIssues}
                            newIslandRatio={latestNewIslandRatio}
                          />
                        </div>
                      </div>

                      <AlignmentView
                        dods={objectiveDodItems}
                        sprints={sessionDetail?.sprints ?? []}
                        onSelectSprint={(sprintId) => handleSelectSprint(sprintId)}
                      />

                      <SprintTimeline
                        sprints={sessionDetail?.sprints ?? []}
                        currentSprintId={currentSprintId}
                        selectedSprintId={selectedSprintId ?? null}
                        onSprintSelect={(sprintId) => handleSelectSprint(sprintId)}
                      />
                    </div>
                  </TabsContent>

                  <TabsContent value="sprint-detail" className="mt-0 outline-none">
                    <SprintDetailView
                      currentSprintId={currentSprintId}
                      selectedSprint={selectedSprint}
                      previousSprint={previousSprint}
                      selectedSprintGoals={selectedSprintGoals}
                      previousSprintGoals={previousSprintGoals}
                      selectedSprintWhyItems={selectedSprintWhyItems}
                      previousSprintWhyItems={previousSprintWhyItems}
                      reportLoading={reportLoading}
                      reportError={reportError}
                      isResultCompareMode={isResultCompareMode}
                      canCompareResult={canCompareResult}
                      onToggleCompare={() => setIsResultCompareMode((previous) => !previous)}
                      onOpenDeepDive={() => setIsDeepDiveOpen(true)}
                      rewriteLinkedMarkdown={rewriteLinkedMarkdown}
                      onResultClick={handleResultClick}
                    />
                  </TabsContent>

                  <TabsContent value="objective" className="mt-0 outline-none">
                    <ObjectiveWorkspace
                      selectedSessionId={selectedSessionId}
                      objectiveLoading={objectiveLoading}
                      objectiveError={objectiveError}
                      objectiveContent={objectiveContent}
                      objectiveSections={objectiveSections}
                      isObjectiveEditMode={isObjectiveEditMode}
                      objectiveEditValue={objectiveEditValue}
                      statusMessage={statusMessage}
                      selectedObjectiveFile={selectedObjectiveFile}
                      objectiveFiles={objectiveFiles}
                      objectiveDetailContent={objectiveDetailContent}
                      objectiveDetailLoading={objectiveDetailLoading}
                      objectiveDetailError={objectiveDetailError}
                      isObjectiveTreeCollapsed={isObjectiveTreeCollapsed}
                      setIsObjectiveTreeCollapsed={setIsObjectiveTreeCollapsed}
                      objectiveTreeWidth={objectiveTreeWidth}
                      objectiveTreeRef={objectiveTreeRef}
                      isObjectiveTreeResizing={isObjectiveTreeResizing}
                      startObjectiveTreeResizing={startObjectiveTreeResizing}
                      isObjectiveCommentsCollapsed={isObjectiveCommentsCollapsed}
                      setIsObjectiveCommentsCollapsed={setIsObjectiveCommentsCollapsed}
                      setSelectedObjectiveFile={setSelectedObjectiveFile}
                      setObjectiveEditValue={setObjectiveEditValue}
                      onObjectiveModeChange={handleObjectiveModeChange}
                      onSaveObjective={handleSaveObjective}
                      rewriteMarkdown={rewriteMarkdown}
                      onObjectiveMarkdownLinkClick={handleObjectiveMarkdownLinkClick}
                    />
                  </TabsContent>
                </div>
              </ScrollArea>
            </Tabs>
          </div>

          {isDeepDiveOpen ? (
            <>
              <ResizableHandle isResizing={isDeepDiveResizing} onMouseDown={startDeepDiveResizing} />
              <div ref={deepDiveRef} style={{ width: deepDiveWidth }} className="min-h-0 shrink-0 border-l border-zinc-200">
                <DeepDivePanel
                  sprint={selectedSprint}
                  retrospective={retrospective}
                  resultMarkdown={resultMarkdown}
                  retrospectiveMd={retrospectiveMd}
                  objectiveContent={objectiveContent}
                  resultDetailFiles={resultDetailFiles}
                  selectedResultDetailFile={selectedResultDetailFile}
                  resultDetailContent={resultDetailContent}
                  resultDetailLoading={resultDetailLoading || resultDetailFilesLoading}
                  resultDetailError={resultDetailError}
                  rewriteLinkedMarkdown={rewriteLinkedMarkdown}
                  onResultClick={handleResultClick}
                  onResultDetailFileChange={setSelectedResultDetailFile}
                  onClose={() => setIsDeepDiveOpen(false)}
                />
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
