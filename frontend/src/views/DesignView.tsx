import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAppContext } from '@/context/AppContext';
import { apiFetch } from '@/hooks/useApi';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent } from '@/components/ui/card';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer';
import { EmptyState } from '@/components/shared/EmptyState';
import { SessionCard } from '@/components/shared/SessionCard';
import { RefreshButton } from '@/components/shared/RefreshButton';
import { ListFilter, type FilterOption } from '@/components/shared/ListFilter';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ExternalLink, Palette, FileText, ChevronDown, ChevronRight, Pencil, GitBranch, Send, Undo2, Maximize2, Clipboard, Check, RefreshCw } from 'lucide-react';
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { parseDesignSections } from '@/shared/designUtils';

interface DesignScreen {
  id: string;
  slug?: string;
  stitch_screen_id?: string;
  title?: string;
  url?: string;
  image_url?: string | null;
  html_file?: string | null;
  html?: string | null;
  image?: string | null;
  purpose?: string | null;
  meta?: string | null;
  style?: string | null;
  created_at?: string;
  status?: string;
  parent_screen_id?: string | null;
}

interface DesignStyle {
  name: string;
  slug: string;
  screens: string[];
}

interface DesignSession {
  id: string;
  title?: string;
  status: string;
  created_at?: string;
  linked_plan?: string | null;
  linked_req?: string | null;
  screens?: DesignScreen[];
  styles?: DesignStyle[];
  screen_files?: string[];
  has_styles?: boolean;
  style_dirs?: string[];
  source?: 'plan_design';
  plan_design?: boolean;
  design_content?: string | null;
  stitch_project_id?: string | null;
  stitch_project_url?: string | null;
}

interface ScreenContent {
  exists: boolean;
  content: string | null;
}

interface ScreenFilesResponse {
  screen_files: string[];
}

type InlineEditMode = 'edit' | 'alt';
type CopyFeedbackState = 'copied' | 'failed';
type AltCreativeRange = 'REFINE' | 'EXPLORE' | 'REIMAGINE';

const ALT_DEFAULT_PROMPT = '대체 디자인 생성';

interface DesignEditResponse {
  job_id: string;
  status: string;
}

interface DesignRefreshResponse {
  ok?: boolean;
  job_id?: string;
  error?: string;
}

interface DesignEditStatusEventData {
  status?: 'started' | 'completed' | 'failed' | string;
  job_id?: string;
  mode?: InlineEditMode | 'refresh' | string;
  screen_ids?: string[];
  error?: string;
}

function parseScreenContent(content: string) {
  const titleMatch = content.match(/^##\s+(.+)$/m);
  const imageMatch = content.match(/!\[[^\]]*\]\(([^)]+)\)/);
  const linkMatch = content.match(/\[([^\]]+)\]\((https:\/\/stitch\.[^)]+)\)/);
  const description = content
    .replace(/^##\s+.+$/m, '')
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
    .replace(/\[[^\]]+\]\([^)]+\)/g, '')
    .trim();

  return {
    title: titleMatch?.[1] ?? '',
    imageUrl: imageMatch?.[1] ?? null,
    stitchUrl: linkMatch?.[2] ?? null,
    stitchLabel: linkMatch?.[1] ?? 'Stitch에서 보기',
    description,
  };
}

function getStyleNames(session: DesignSession | null): string[] {
  if (!session) {
    return [];
  }

  if (Array.isArray(session.style_dirs) && session.style_dirs.length > 0) {
    return session.style_dirs;
  }

  if (!Array.isArray(session.styles) || session.styles.length === 0) {
    return [];
  }

  return session.styles
    .map((style) => style.slug || style.name)
    .filter((name): name is string => Boolean(name));
}

export function normalizeScreenId(screenId: unknown): string {
  if (typeof screenId !== 'string') {
    return '';
  }
  return screenId.trim().replace(/\.(md|html)$/, '').trim();
}

function getScreenFileNameFromPath(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }

  const normalized = value.trim();
  if (!normalized.endsWith('.html')) {
    return null;
  }

  const fileName = normalized.split('/').pop()?.trim() ?? '';
  return fileName.length > 0 ? fileName : null;
}

function getScreenIdentity(screen: DesignScreen): string {
  return normalizeScreenId(screen.id || screen.slug || screen.html_file || screen.html || '');
}

function getScreenFile(screen: DesignScreen): string | null {
  const htmlFile = getScreenFileNameFromPath(screen.html_file) ?? getScreenFileNameFromPath(screen.html);
  if (htmlFile) {
    return htmlFile;
  }

  const screenId = getScreenIdentity(screen);
  return screenId ? `${screenId}.md` : null;
}

function getSessionScreenFiles(session: DesignSession | null, hasStyles: boolean, styleScreenFiles: string[]): string[] {
  if (!session) {
    return [];
  }

  if (hasStyles) {
    return styleScreenFiles;
  }

  const files = Array.isArray(session.screen_files) ? [...session.screen_files] : [];
  const seen = new Set(files);
  for (const screen of session.screens ?? []) {
    const file = getScreenFile(screen);
    if (file && !seen.has(file)) {
      seen.add(file);
      files.push(file);
    }
  }
  return files;
}

function extractSessionNumberToken(session: DesignSession | null): string {
  if (!session) {
    return '000';
  }

  const preferred = [session.id, session.linked_plan ?? ''];
  for (const candidate of preferred) {
    const desMatch = candidate.match(/^DES-(\d+)$/i);
    if (desMatch) {
      return desMatch[1].padStart(3, '0');
    }
  }

  for (const candidate of preferred) {
    const idMatch = candidate.match(/^(?:DES|PLN)-(\d+)$/i);
    if (idMatch) {
      return idMatch[1].padStart(3, '0');
    }
  }

  return '000';
}

export function DesignView() {
  const { projectId, lastSseEvent, navigateTo } = useAppContext();
  const { designId } = useParams();
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<DesignSession[]>([]);
  const [selectedSession, setSelectedSession] = useState<DesignSession | null>(null);
  const [selectedStyle, setSelectedStyle] = useState<string | null>(null);
  const [styleScreenFiles, setStyleScreenFiles] = useState<string[]>([]);
  const [selectedScreenFile, setSelectedScreenFile] = useState<string | null>(null);
  const [screenContent, setScreenContent] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'image' | 'html'>('html');
  const [planDesignSections, setPlanDesignSections] = useState<ReturnType<typeof parseDesignSections>>([]);
  const [selectedPlanSection, setSelectedPlanSection] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [designSystem, setDesignSystem] = useState<{ exists: boolean; content: string | null } | null>(null);
  const [isDesignSystemOpen, setIsDesignSystemOpen] = useState(true);

  const [searchValue, setSearchValue] = useState('');
  const [filterValue, setFilterValue] = useState('all');
  const [sortValue, setSortValue] = useState('newest');
  const [inlineEditMode, setInlineEditMode] = useState<InlineEditMode | null>(null);
  const [editPrompt, setEditPrompt] = useState('');
  const [isEditSubmitting, setIsEditSubmitting] = useState(false);
  const [activeEditJobId, setActiveEditJobId] = useState<string | null>(null);
  const [activeEditJobMode, setActiveEditJobMode] = useState<InlineEditMode | null>(null);
  const [editStatusMessage, setEditStatusMessage] = useState<string | null>(null);
  const [editErrorMessage, setEditErrorMessage] = useState<string | null>(null);
  const [altVariantCount, setAltVariantCount] = useState<2 | 3 | 4>(2);
  const [altCreativeRange, setAltCreativeRange] = useState<AltCreativeRange>('EXPLORE');
  const [pendingAutoSelectScreenId, setPendingAutoSelectScreenId] = useState<string | null>(null);
  const [altCandidateScreenIds, setAltCandidateScreenIds] = useState<string[]>([]);
  const [copyFeedback, setCopyFeedback] = useState<Record<string, CopyFeedbackState>>({});
  const copyFeedbackTimeoutsRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const [altBaseScreenFile, setAltBaseScreenFile] = useState<string | null>(null);
  const [isStitchRefreshing, setIsStitchRefreshing] = useState(false);
  const [activeRefreshJobId, setActiveRefreshJobId] = useState<string | null>(null);
  const [refreshStatusMessage, setRefreshStatusMessage] = useState<string | null>(null);
  const [refreshErrorMessage, setRefreshErrorMessage] = useState<string | null>(null);
  const [selectedSessionRefreshKey, setSelectedSessionRefreshKey] = useState(0);

  const statusFilterOptions: FilterOption[] = [
    { value: 'all', label: 'All Status' },
    { value: 'draft', label: 'Draft' },
    { value: 'done', label: 'Done' },
    { value: 'in_progress', label: 'In Progress' },
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
          s.title?.toLowerCase().includes(query)
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

  const isPlanDesign = selectedSession?.source === 'plan_design';
  const hasStyles = Boolean(selectedSession?.has_styles) && !isPlanDesign;
  const styleNames = useMemo(() => getStyleNames(selectedSession), [selectedSession]);
  const activeStyle = hasStyles ? (selectedStyle ?? styleNames[0] ?? null) : null;
  const screenFiles = useMemo(
    () => getSessionScreenFiles(selectedSession, hasStyles, styleScreenFiles),
    [hasStyles, styleScreenFiles, selectedSession]
  );
  const selectedScreen = useMemo(() => {
    const selectedScreenId = selectedScreenFile ? normalizeScreenId(selectedScreenFile) : null;
    return selectedSession?.screens?.find((screen) => {
      const screenId = getScreenIdentity(screen);
      if (!screenId) {
        return false;
      }
      if (screenId !== selectedScreenId) {
        return false;
      }
      if (!hasStyles || !activeStyle) {
        return true;
      }
      return screen.style === activeStyle;
    }) ?? selectedSession?.screens?.find((screen) =>
      Boolean(getScreenIdentity(screen)) &&
      getScreenIdentity(screen) === selectedScreenId &&
      (!hasStyles || !activeStyle || !screen.style)
    );
  }, [selectedSession?.screens, selectedScreenFile, hasStyles, activeStyle]);
  const screenMap = useMemo(() => {
    const map = new Map<string, DesignScreen>();
    for (const screen of selectedSession?.screens ?? []) {
      const screenId = getScreenIdentity(screen);
      if (!screenId) {
        continue;
      }
      if (!map.has(screenId)) {
        map.set(screenId, screen);
      }
      if (hasStyles && activeStyle && screen.style === activeStyle) {
        map.set(screenId, screen);
      }
    }
    return map;
  }, [selectedSession?.screens, hasStyles, activeStyle]);
  const historyChain = useMemo(() => {
    if (!selectedScreen?.parent_screen_id) {
      return [] as DesignScreen[];
    }

    const chain: DesignScreen[] = [];
    const visited = new Set<string>();
    let cursor: string | null = normalizeScreenId(selectedScreen.parent_screen_id);

    while (cursor && !visited.has(cursor) && chain.length < 20) {
      visited.add(cursor);
      const parent = screenMap.get(cursor);
      if (!parent) {
        break;
      }
      chain.push(parent);
      cursor = parent.parent_screen_id ? normalizeScreenId(parent.parent_screen_id) : null;
    }

    return chain;
  }, [selectedScreen, screenMap]);
  const altComparisonTabs = useMemo(() => {
    if (!altBaseScreenFile || altCandidateScreenIds.length === 0) {
      return [] as Array<{ value: string; label: string }>;
    }

    const candidates = [...new Set(altCandidateScreenIds.map((id) => normalizeScreenId(id)))]
      .filter((id) => id.length > 0)
      .slice(0, 4);

    return [
      { value: altBaseScreenFile, label: '기존' },
      ...candidates.map((id, index) => ({
        value: `${id}.md`,
        label: `대체시안${String.fromCharCode(65 + index)}`,
      })),
    ];
  }, [altBaseScreenFile, altCandidateScreenIds]);
  const activeAltComparisonTab = useMemo(() => {
    if (!altBaseScreenFile || altComparisonTabs.length === 0) {
      return null;
    }

    if (selectedScreenFile && altComparisonTabs.some((tab) => tab.value === selectedScreenFile)) {
      return selectedScreenFile;
    }

    return altBaseScreenFile;
  }, [altBaseScreenFile, altComparisonTabs, selectedScreenFile]);

  useEffect(() => {
    if (altComparisonTabs.length === 0) {
      return;
    }

    const isInAltComparisonTabs = Boolean(
      selectedScreenFile && altComparisonTabs.some((tab) => tab.value === selectedScreenFile)
    );
    if (isInAltComparisonTabs) {
      return;
    }

    setAltCandidateScreenIds([]);
    setAltBaseScreenFile(null);
  }, [altComparisonTabs, selectedScreenFile]);
  const isDesSession = Boolean(selectedSession && /^DES-\d+$/.test(selectedSession.id));
  const hasLinkedStitchProject = Boolean(
    typeof selectedSession?.stitch_project_id === 'string' && selectedSession.stitch_project_id.trim().length > 0
  );
  const canEditSelectedScreen = Boolean(isDesSession && selectedScreenFile);
  const canRefreshFromStitch = canEditSelectedScreen && hasLinkedStitchProject;
  const canOpenStitchProject = canRefreshFromStitch && Boolean(
    typeof selectedSession?.stitch_project_url === 'string' && selectedSession.stitch_project_url.trim().length > 0
  );
  const canPreview = useMemo(
    () =>
      Boolean(selectedScreen?.html_file) ||
      Boolean(selectedScreen?.html) ||
      Boolean(selectedScreenFile?.endsWith('.html')) ||
      Boolean(hasStyles && activeStyle && selectedScreenFile && projectId && selectedSession),
    [selectedScreen?.html_file, selectedScreen?.html, hasStyles, activeStyle, selectedScreenFile, projectId, selectedSession]
  );
  const htmlPreviewSrc = useMemo(() => {
    if (!projectId || !selectedSession || !selectedScreenFile) {
      return null;
    }

    if (hasStyles && activeStyle) {
      return `/api/projects/${projectId}/designs/${selectedSession.id}/styles/${encodeURIComponent(activeStyle)}/screens/${selectedScreenFile}/html`;
    }

    return `/api/projects/${projectId}/designs/${selectedSession.id}/screens/${selectedScreenFile}/html`;
  }, [projectId, selectedSession, selectedScreenFile, hasStyles, activeStyle]);
  const sessionNumberToken = useMemo(
    () => extractSessionNumberToken(selectedSession),
    [selectedSession?.id, selectedSession?.linked_plan]
  );
  const buildScreenScrId = useCallback(
    (order: number) => `SCR-${sessionNumberToken}-${String(order).padStart(3, '0')}`,
    [sessionNumberToken]
  );

  const fetchSessions = useCallback(async () => {
    try {
      const data = await apiFetch<DesignSession[]>('/api/designs', projectId);
      setSessions(data);
      setSelectedSession(prev =>
        prev ? (data.find((session) => session.id === prev.id) ?? data[0] ?? null) : (data[0] ?? null)
      );
    } catch {
      setSessions([]);
      setSelectedSession(null);
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (sessions.length === 0) return;
    if (designId) {
      const target = sessions.find((d: any) => d.id === designId);
      setSelectedSession(target || sessions[0]);
    } else {
      setSelectedSession(sessions[0]);
    }
  }, [designId, sessions]);

  useEffect(() => {
    if (!projectId) {
      setDesignSystem(null);
      return;
    }
    apiFetch<{ exists: boolean; content: string | null }>('/api/designs/design-system', projectId)
      .then(setDesignSystem)
      .catch(() => setDesignSystem({ exists: false, content: null }));
  }, [projectId]);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      setSessions([]);
      setSelectedSession(null);
      return;
    }

    setLoading(true);
    fetchSessions();
  }, [projectId, fetchSessions]);

  useEffect(() => {
    if (lastSseEvent?.type === 'design_update' || lastSseEvent?.type === 'refresh') {
      fetchSessions();
    }
  }, [lastSseEvent, fetchSessions]);

  useEffect(() => {
    return () => {
      Object.values(copyFeedbackTimeoutsRef.current).forEach((timeoutId) => clearTimeout(timeoutId));
    };
  }, []);

  useEffect(() => {
    if (lastSseEvent?.type !== 'design_edit_status' || !selectedSession || !projectId) {
      return;
    }

    const eventDesignId = typeof (lastSseEvent as { designId?: unknown }).designId === 'string'
      ? (lastSseEvent as { designId: string }).designId
      : null;
    if (eventDesignId && eventDesignId !== selectedSession.id) {
      return;
    }

    const eventData = (lastSseEvent as { data?: DesignEditStatusEventData }).data;
    if (!eventData?.status) {
      return;
    }

    const eventJobId = typeof eventData.job_id === 'string' ? eventData.job_id : null;
    const eventMode = eventData.mode;

    if (eventMode === 'refresh') {
      if (activeRefreshJobId && eventJobId && activeRefreshJobId !== eventJobId) {
        return;
      }

      if (eventData.status === 'started') {
        setIsStitchRefreshing(true);
        setRefreshErrorMessage(null);
        setRefreshStatusMessage('새로고침 중...');
        return;
      }

      if (eventData.status === 'failed') {
        setIsStitchRefreshing(false);
        setActiveRefreshJobId(null);
        setRefreshStatusMessage(null);
        setRefreshErrorMessage(
          typeof eventData.error === 'string' && eventData.error.length > 0
            ? eventData.error
            : '새로고침 요청이 실패했습니다'
        );
        return;
      }

      if (eventData.status === 'completed') {
        setIsStitchRefreshing(false);
        setActiveRefreshJobId(null);
        setRefreshErrorMessage(null);
        setRefreshStatusMessage('새로고침 완료');
        setSelectedSessionRefreshKey((value) => value + 1);
        void fetchSessions();
      }
      return;
    }

    if (activeEditJobId && eventJobId && activeEditJobId !== eventJobId) {
      return;
    }

    if (eventData.status === 'started') {
      setEditStatusMessage('편집 중...');
      setEditErrorMessage(null);
      return;
    }

    if (eventData.status === 'failed') {
      setActiveEditJobId(null);
      setActiveEditJobMode(null);
      setEditStatusMessage(null);
      setEditErrorMessage(
        typeof eventData.error === 'string' && eventData.error.length > 0
          ? eventData.error
          : '편집 요청이 실패했습니다'
      );
      return;
    }

    if (eventData.status === 'completed') {
      const completedMode = eventData.mode === 'alt' || eventData.mode === 'edit'
        ? eventData.mode
        : activeEditJobMode;
      const screenIds = [...new Set(Array.isArray(eventData.screen_ids)
        ? eventData.screen_ids
          .filter((value): value is string => typeof value === 'string')
          .map((value) => normalizeScreenId(value))
          .filter((value) => value.length > 0)
        : [])];

      setActiveEditJobId(null);
      setActiveEditJobMode(null);
      setEditErrorMessage(null);
      setEditStatusMessage('완료');
      setSelectedSessionRefreshKey((value) => value + 1);
      void fetchSessions();

      if (completedMode === 'alt') {
        setAltCandidateScreenIds(screenIds.slice(0, 4));
      } else {
        setAltCandidateScreenIds([]);
        setPendingAutoSelectScreenId(screenIds[0] ?? null);
        setInlineEditMode(null);
      }
    }
  }, [lastSseEvent, selectedSession, activeEditJobId, activeEditJobMode, activeRefreshJobId, fetchSessions, projectId]);

  useEffect(() => {
    setViewMode('html');

    if (!selectedSession || !projectId) {
      setSelectedStyle(null);
      setStyleScreenFiles([]);
      setSelectedScreenFile(null);
      setScreenContent(null);
      setPlanDesignSections([]);
      return;
    }

    apiFetch<DesignSession>(`/api/designs/${selectedSession.id}`, projectId)
      .then((data) => {
        setSelectedSession(prev => {
          if (!prev) return data;
          return { ...prev, ...data };
        });

        if (data.plan_design && data.design_content) {
          const sections = parseDesignSections(data.design_content);
          setPlanDesignSections(sections);
          setSelectedPlanSection(0);
          setSelectedStyle(null);
          setStyleScreenFiles([]);
          setSelectedScreenFile(null);
        } else {
          setPlanDesignSections([]);

          if (data.has_styles) {
            const styleNames = getStyleNames(data);
            setSelectedStyle((prev) =>
              prev && styleNames.includes(prev) ? prev : (styleNames[0] ?? null)
            );
            setStyleScreenFiles([]);
            setSelectedScreenFile(null);
          } else {
            setSelectedStyle(null);
            setStyleScreenFiles([]);
            const files = getSessionScreenFiles(data, false, []);
            setSelectedScreenFile((prev) =>
              prev && files.includes(prev) ? prev : (files.length > 0 ? files[0] : null)
            );
          }
        }
      })
      .catch(() => {
        setSelectedStyle(null);
        setStyleScreenFiles([]);
        setSelectedScreenFile(null);
        setScreenContent(null);
        setPlanDesignSections([]);
      });
  }, [selectedSession?.id, projectId, selectedSessionRefreshKey]);

  useEffect(() => {
    setViewMode(canPreview ? 'html' : 'image');
  }, [canPreview]);

  useEffect(() => {
    if (viewMode !== 'html' || !htmlPreviewSrc) {
      return;
    }

    const abortController = new AbortController();

    fetch(htmlPreviewSrc, { method: 'HEAD', signal: abortController.signal })
      .then((response) => {
        if (!response.ok) {
          setViewMode('image');
        }
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === 'AbortError') {
          return;
        }
        setViewMode('image');
      });

    return () => {
      abortController.abort();
    };
  }, [viewMode, htmlPreviewSrc]);

  useEffect(() => {
    if (
      !selectedSession ||
      !projectId ||
      selectedSession.source === 'plan_design' ||
      !selectedSession.has_styles
    ) {
      setStyleScreenFiles([]);
      return;
    }

    const styleName = selectedStyle ?? styleNames[0] ?? null;
    if (!styleName) {
      setStyleScreenFiles([]);
      setSelectedScreenFile(null);
      setScreenContent(null);
      return;
    }

    if (selectedStyle !== styleName) {
      setSelectedStyle(styleName);
      return;
    }

    setStyleScreenFiles([]);
    setSelectedScreenFile(null);
    setScreenContent(null);
    apiFetch<ScreenFilesResponse>(
      `/api/designs/${selectedSession.id}/styles/${encodeURIComponent(styleName)}/screens`,
      projectId
    )
      .then((data) => {
        const files = data.screen_files ?? [];
        setStyleScreenFiles(files);
        setSelectedScreenFile(files.length > 0 ? files[0] : null);
      })
      .catch(() => {
        setStyleScreenFiles([]);
        setSelectedScreenFile(null);
        setScreenContent(null);
      });
  }, [
    selectedSession?.id,
    selectedSession?.has_styles,
    selectedSession?.source,
    selectedStyle,
    styleNames,
    projectId,
  ]);

  useEffect(() => {
    if (!selectedSession || !selectedScreenFile || !projectId) {
      setScreenContent(null);
      return;
    }

    const isStyleSession = selectedSession.source !== 'plan_design' && Boolean(selectedSession.has_styles);
    const styleName = selectedStyle ?? styleNames[0] ?? null;

    if (isStyleSession && !styleName) {
      setScreenContent(null);
      return;
    }

    const screenPath = isStyleSession
      ? `/api/designs/${selectedSession.id}/styles/${encodeURIComponent(styleName!)}/screens/${selectedScreenFile}`
      : `/api/designs/${selectedSession.id}/screens/${selectedScreenFile}`;

    apiFetch<ScreenContent>(
      screenPath,
      projectId
    )
      .then((data) => setScreenContent(data.exists ? data.content : null))
      .catch(() => setScreenContent(null));
  }, [
    selectedSession?.id,
    selectedSession?.has_styles,
    selectedSession?.source,
    selectedScreenFile,
    selectedStyle,
    styleNames,
    projectId,
  ]);

  useEffect(() => {
    if (!pendingAutoSelectScreenId) {
      return;
    }

    const targetScreenId = normalizeScreenId(pendingAutoSelectScreenId);
    if (!targetScreenId) {
      setPendingAutoSelectScreenId(null);
      return;
    }
    const targetScreenFile = screenFiles.find((file) => normalizeScreenId(file) === targetScreenId) ?? `${targetScreenId}.md`;
    if (screenFiles.includes(targetScreenFile)) {
      setSelectedScreenFile(targetScreenFile);
      setPendingAutoSelectScreenId(null);
      setEditStatusMessage(null);
    }
  }, [pendingAutoSelectScreenId, screenFiles]);

  useEffect(() => {
    Object.values(copyFeedbackTimeoutsRef.current).forEach((timeoutId) => clearTimeout(timeoutId));
    copyFeedbackTimeoutsRef.current = {};
    setCopyFeedback({});
    setInlineEditMode(null);
    setEditPrompt('');
    setSelectedScreenFile(null);
    setScreenContent(null);
    setIsEditSubmitting(false);
    setActiveEditJobId(null);
    setActiveEditJobMode(null);
    setEditStatusMessage(null);
    setEditErrorMessage(null);
    setAltVariantCount(2);
    setAltCreativeRange('EXPLORE');
    setPendingAutoSelectScreenId(null);
    setAltCandidateScreenIds([]);
    setAltBaseScreenFile(null);
    setIsStitchRefreshing(false);
    setActiveRefreshJobId(null);
    setRefreshStatusMessage(null);
    setRefreshErrorMessage(null);
  }, [selectedSession?.id]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    fetchSessions();
  };

  const selectScreenById = useCallback((screenId: string) => {
    const normalized = normalizeScreenId(screenId);
    if (!normalized) {
      return;
    }
    const existingFile = screenFiles.find((file) => normalizeScreenId(file) === normalized);
    setSelectedScreenFile(existingFile ?? `${normalized}.md`);
  }, [screenFiles]);

  const handleOpenInlineEditor = useCallback((mode: InlineEditMode) => {
    setInlineEditMode(mode);
    setEditErrorMessage(null);
    setEditStatusMessage(null);
    if (mode === 'alt') {
      setEditPrompt((prev) => (prev.trim().length > 0 ? prev : ALT_DEFAULT_PROMPT));
    } else {
      setEditPrompt('');
      setAltCandidateScreenIds([]);
      setAltBaseScreenFile(null);
    }
  }, []);

  const handleSendEdit = useCallback(async () => {
    if (!projectId || !selectedSession || !selectedScreenFile || !inlineEditMode) {
      return;
    }

    const prompt = editPrompt.trim();
    if (!prompt) {
      return;
    }

    const targetScreenId = normalizeScreenId(selectedScreen?.id ?? selectedScreenFile);
    if (!targetScreenId) {
      return;
    }

    const payload: Record<string, unknown> = {
      prompt,
      mode: inlineEditMode,
      screen_id: targetScreenId,
    };
    if (inlineEditMode === 'alt') {
      payload.variant_options = {
        count: altVariantCount,
        creative_range: altCreativeRange,
      };
    }

    setIsEditSubmitting(true);
    setEditErrorMessage(null);
    setEditStatusMessage('편집 요청 중...');
    setPendingAutoSelectScreenId(null);
    if (inlineEditMode === 'alt') {
      setAltBaseScreenFile(selectedScreenFile);
      setAltCandidateScreenIds([]);
    } else {
      setAltCandidateScreenIds([]);
      setAltBaseScreenFile(null);
    }

    try {
      const response = await apiFetch<DesignEditResponse>(
        `/api/designs/${selectedSession.id}/edit`,
        projectId,
        {
          method: 'POST',
          body: JSON.stringify(payload),
        }
      );
      setActiveEditJobId(response.job_id);
      setActiveEditJobMode(inlineEditMode);
      setEditStatusMessage('편집 중...');
      if (inlineEditMode === 'edit') {
        setEditPrompt('');
      }
    } catch {
      setEditStatusMessage(null);
      setEditErrorMessage('편집 요청 전송에 실패했습니다');
    } finally {
      setIsEditSubmitting(false);
    }
  }, [projectId, selectedSession, selectedScreen, selectedScreenFile, inlineEditMode, editPrompt, altVariantCount, altCreativeRange]);

  const handleUndo = useCallback(() => {
    const previousScreen = historyChain[0];
    if (!previousScreen) {
      return;
    }
    selectScreenById(previousScreen.id);
  }, [historyChain, selectScreenById]);

  const handleRefreshFromStitch = useCallback(async () => {
    if (!projectId || !selectedSession || !canRefreshFromStitch) {
      return;
    }

    setIsStitchRefreshing(true);
    setRefreshErrorMessage(null);
    setRefreshStatusMessage('새로고침 요청 중...');

    try {
      const response = await apiFetch<DesignRefreshResponse>(
        `/api/designs/${selectedSession.id}/refresh`,
        projectId
      );

      if (response.ok === false) {
        throw new Error(response.error || '새로고침 요청이 실패했습니다');
      }

      setActiveRefreshJobId(response.job_id ?? null);
      setRefreshStatusMessage('새로고침 중...');
    } catch (error) {
      setIsStitchRefreshing(false);
      setActiveRefreshJobId(null);
      setRefreshStatusMessage(null);
      setRefreshErrorMessage(
        error instanceof Error && error.message.length > 0
          ? error.message
          : '새로고침 요청 전송에 실패했습니다'
      );
    }
  }, [projectId, selectedSession, canRefreshFromStitch]);

  const handleOpenStitchProject = useCallback(() => {
    if (!canOpenStitchProject || !selectedSession?.stitch_project_url) {
      return;
    }
    window.open(selectedSession.stitch_project_url, '_blank', 'noopener,noreferrer');
  }, [canOpenStitchProject, selectedSession?.stitch_project_url]);

  const handleCopyScreenId = useCallback(async (screenId: string) => {
    if (copyFeedbackTimeoutsRef.current[screenId]) {
      clearTimeout(copyFeedbackTimeoutsRef.current[screenId]);
    }

    let success = false;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(screenId);
        success = true;
      } catch {
        success = false;
      }
    }

    if (!success) {
      try {
        const textarea = document.createElement('textarea');
        textarea.value = screenId;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        success = document.execCommand('copy');
        document.body.removeChild(textarea);
      } catch {
        success = false;
      }
    }

    setCopyFeedback((prev) => ({ ...prev, [screenId]: success ? 'copied' : 'failed' }));

    copyFeedbackTimeoutsRef.current[screenId] = setTimeout(() => {
      setCopyFeedback((prev) => {
        const next = { ...prev };
        delete next[screenId];
        return next;
      });
    }, 2000);
  }, []);

  if (!projectId) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        프로젝트를 선택하세요
      </div>
    );
  }

  if (loading) {
    return (
      <div className="grid grid-cols-12 gap-6 h-full p-6">
        <div className="col-span-4 space-y-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
        </div>
        <div className="col-span-8">
          <Skeleton className="h-full w-full" />
        </div>
      </div>
    );
  }

  const parsedScreen = screenContent ? parseScreenContent(screenContent) : null;
  const parsedScreenTitle = parsedScreen?.title || selectedScreen?.title || selectedScreen?.slug || 'Design 화면';
  const hasHtmlPreview = canPreview;

  const renderScreenTabs = (files: string[], emptyDescription: string) => {
    if (files.length === 0) {
      return (
        <EmptyState
          icon={<Palette className="h-8 w-8" />}
          title="스크린 없음"
          description={emptyDescription}
        />
      );
    }

    return (
      <Tabs
        value={selectedScreenFile ?? ''}
        onValueChange={setSelectedScreenFile}
        className="flex-1 flex flex-col overflow-hidden"
      >
        <div className="px-4 border-b">
          <TabsList className="bg-transparent h-10 p-0 gap-3 overflow-x-auto">
            {files.map((file, index) => {
              const scrId = buildScreenScrId(index + 1);
              const feedback = copyFeedback[scrId];
              return (
                <div key={file} className="flex items-center gap-1">
                  <TabsTrigger
                    value={file}
                    className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-1 gap-1"
                  >
                    <span className="font-mono text-[11px] text-muted-foreground">{scrId}</span>
                    <span>{file}</span>
                  </TabsTrigger>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className={`h-5 w-5 shrink-0 p-0 ${feedback === 'failed' ? 'text-destructive' : 'text-muted-foreground hover:text-foreground'}`}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      void handleCopyScreenId(scrId);
                    }}
                    title={feedback === 'copied' ? '복사됨' : feedback === 'failed' ? '복사 실패' : `${scrId} 복사`}
                    aria-label={`${scrId} 복사`}
                  >
                    {feedback === 'copied' ? (
                      <Check className="h-3 w-3" />
                    ) : (
                      <Clipboard className="h-3 w-3" />
                    )}
                  </Button>
                </div>
              );
            })}
          </TabsList>
        </div>
        {files.map((file) => (
          <TabsContent key={file} value={file} className="flex-1 m-0 p-0">
            <ScrollArea className="h-full">
              <div className="p-8">
                {file === selectedScreenFile ? (
                  <>
                    <h3 className="text-lg font-semibold mb-3">{parsedScreenTitle}</h3>
                    <div className="flex flex-wrap gap-1 mb-3">
                      {hasHtmlPreview && (
                        <>
                          <Button
                            type="button"
                            variant={viewMode === 'image' ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => setViewMode('image')}
                          >
                            이미지
                          </Button>
                          <Button
                            type="button"
                            variant={viewMode === 'html' ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => setViewMode('html')}
                          >
                            HTML 미리보기
                          </Button>
                          {viewMode === 'html' && htmlPreviewSrc && (
                            <Dialog>
                              <DialogTrigger asChild>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  title="전체화면"
                                >
                                  <Maximize2 className="h-3.5 w-3.5" />
                                </Button>
                              </DialogTrigger>
                              <DialogContent className="max-w-[100vw] w-[100vw] h-[100vh] max-h-[100vh] m-0 p-0 border-none rounded-none flex flex-col">
                                <DialogTitle className="sr-only">HTML 전체화면 미리보기</DialogTitle>
                                <DialogDescription className="sr-only">선택된 디자인 화면의 HTML 전체화면 미리보기입니다.</DialogDescription>
                                <iframe
                                  title={`${selectedSession?.id ?? 'design'}-${file}-html-fullscreen`}
                                  src={htmlPreviewSrc}
                                  className="w-full h-full flex-1 border-none"
                                  sandbox="allow-scripts"
                                />
                              </DialogContent>
                            </Dialog>
                          )}
                        </>
                      )}
                      {canEditSelectedScreen && (
                        <>
                          <Button
                            type="button"
                            variant={inlineEditMode === 'edit' ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => handleOpenInlineEditor('edit')}
                            disabled={Boolean(activeEditJobId)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                            Edit
                          </Button>
                          <Button
                            type="button"
                            variant={inlineEditMode === 'alt' ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => handleOpenInlineEditor('alt')}
                            disabled={Boolean(activeEditJobId)}
                          >
                            <GitBranch className="h-3.5 w-3.5" />
                            Alt
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={handleUndo}
                            disabled={historyChain.length === 0 || Boolean(activeEditJobId)}
                          >
                            <Undo2 className="h-3.5 w-3.5" />
                            Undo
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              void handleRefreshFromStitch();
                            }}
                            disabled={!canRefreshFromStitch || isStitchRefreshing || Boolean(activeEditJobId)}
                          >
                            <RefreshCw className={`h-3.5 w-3.5 ${isStitchRefreshing ? 'animate-spin' : ''}`} />
                            Refresh
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={handleOpenStitchProject}
                            disabled={!canOpenStitchProject || isStitchRefreshing}
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                            Stitch열기
                          </Button>
                        </>
                      )}
                    </div>
                    {canEditSelectedScreen && refreshStatusMessage && (
                      <p className="text-xs text-muted-foreground mb-3">{refreshStatusMessage}</p>
                    )}
                    {canEditSelectedScreen && refreshErrorMessage && (
                      <p className="text-xs text-destructive mb-3">{refreshErrorMessage}</p>
                    )}
                    {hasHtmlPreview && viewMode === 'html' && htmlPreviewSrc ? (
                      <iframe
                        title={`${selectedSession?.id ?? 'design'}-${file}-html-preview`}
                        src={htmlPreviewSrc}
                        className="w-full border rounded"
                        style={{ minHeight: 'calc(100vh - 250px)' }}
                        sandbox="allow-scripts"
                        onError={() => setViewMode('image')}
                      />
                    ) : (
                      <>
                        {parsedScreen?.imageUrl && (
                          <Card className="mb-4 overflow-hidden">
                            <a
                              href={parsedScreen.stitchUrl ?? parsedScreen.imageUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              <img
                                src={parsedScreen.imageUrl}
                                alt={parsedScreen.title}
                                className="max-w-[85%] block mx-auto"
                              />
                            </a>
                            <CardContent className="p-3 pt-2">
                              {parsedScreen.stitchUrl && (
                                <a
                                  href={parsedScreen.stitchUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                                >
                                  <ExternalLink className="h-3 w-3" /> {parsedScreen.stitchLabel}
                                </a>
                              )}
                            </CardContent>
                          </Card>
                        )}
                        {parsedScreen?.description ? (
                          <MarkdownRenderer content={parsedScreen.description} />
                        ) : (
                          <div className="text-sm text-muted-foreground">디자인 상세가 없습니다</div>
                        )}
                      </>
                    )}
                    {canEditSelectedScreen && inlineEditMode && (
                      <Card className="mt-4">
                        <CardContent className="p-3 space-y-3">
                          <div className="text-sm font-medium">
                            {inlineEditMode === 'edit' ? 'Edit 프롬프트' : 'Alt 프롬프트'}
                          </div>
                          {inlineEditMode === 'alt' && (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                              <div className="space-y-1">
                                <p className="text-xs text-muted-foreground">개수</p>
                                <Select
                                  value={String(altVariantCount)}
                                  onValueChange={(value) => {
                                    if (value === '2' || value === '3' || value === '4') {
                                      setAltVariantCount(Number(value) as 2 | 3 | 4);
                                    }
                                  }}
                                  disabled={isEditSubmitting || Boolean(activeEditJobId)}
                                >
                                  <SelectTrigger className="h-8 text-xs" aria-label="Alt 시안 개수">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="2">2</SelectItem>
                                    <SelectItem value="3">3</SelectItem>
                                    <SelectItem value="4">4</SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                              <div className="space-y-1">
                                <p className="text-xs text-muted-foreground">Creative Range</p>
                                <Select
                                  value={altCreativeRange}
                                  onValueChange={(value) => {
                                    if (value === 'REFINE' || value === 'EXPLORE' || value === 'REIMAGINE') {
                                      setAltCreativeRange(value);
                                    }
                                  }}
                                  disabled={isEditSubmitting || Boolean(activeEditJobId)}
                                >
                                  <SelectTrigger className="h-8 text-xs" aria-label="Alt Creative Range">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="REFINE">REFINE</SelectItem>
                                    <SelectItem value="EXPLORE">EXPLORE</SelectItem>
                                    <SelectItem value="REIMAGINE">REIMAGINE</SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                            </div>
                          )}
                          <div className="flex gap-2">
                            <Input
                              value={editPrompt}
                              onChange={(event) => setEditPrompt(event.target.value)}
                              placeholder={inlineEditMode === 'edit' ? '예: 사이드바 추가' : ALT_DEFAULT_PROMPT}
                              disabled={isEditSubmitting || Boolean(activeEditJobId)}
                              onKeyDown={(event) => {
                                if (event.key === 'Enter') {
                                  event.preventDefault();
                                  void handleSendEdit();
                                }
                              }}
                            />
                            <Button
                              type="button"
                              size="sm"
                              onClick={() => {
                                void handleSendEdit();
                              }}
                              disabled={isEditSubmitting || Boolean(activeEditJobId) || editPrompt.trim().length === 0}
                            >
                              <Send className="h-3.5 w-3.5" />
                              Send
                            </Button>
                          </div>
                          {editStatusMessage && (
                            <p className="text-xs text-muted-foreground">{editStatusMessage}</p>
                          )}
                          {editErrorMessage && (
                            <p className="text-xs text-destructive">{editErrorMessage}</p>
                          )}
                        </CardContent>
                      </Card>
                    )}
                    {altComparisonTabs.length > 0 && (
                      <Card className="mt-4">
                        <CardContent className="p-3 space-y-2">
                          <p className="text-sm font-medium">Alt 결과 비교</p>
                          <Tabs
                            value={activeAltComparisonTab ?? altComparisonTabs[0]?.value ?? ''}
                            onValueChange={setSelectedScreenFile}
                          >
                            <TabsList className="w-full justify-start overflow-x-auto">
                              {altComparisonTabs.map((tab) => (
                                <TabsTrigger key={tab.value} value={tab.value}>
                                  {tab.label}
                                </TabsTrigger>
                              ))}
                            </TabsList>
                          </Tabs>
                        </CardContent>
                      </Card>
                    )}
                    {canEditSelectedScreen && historyChain.length > 0 && (
                      <Card className="mt-4">
                        <CardContent className="p-3">
                          <div className="flex items-center justify-between mb-2">
                            <p className="text-sm font-medium">편집 히스토리</p>
                            <span className="text-xs text-muted-foreground">{historyChain.length} / 20</span>
                          </div>
                          <ScrollArea className="max-h-44 pr-3">
                            <div className="space-y-1">
                              {historyChain.map((historyScreen) => (
                                <button
                                  key={`${historyScreen.id}-${historyScreen.created_at ?? ''}`}
                                  type="button"
                                  onClick={() => selectScreenById(historyScreen.id)}
                                  className="w-full text-left rounded border px-2 py-1.5 hover:bg-muted/40"
                                >
                                  <p className="text-xs font-medium">
                                    {historyScreen.title ?? normalizeScreenId(historyScreen.id)}
                                  </p>
                                  <p className="text-[11px] text-muted-foreground">
                                    {normalizeScreenId(historyScreen.id)}
                                  </p>
                                </button>
                              ))}
                            </div>
                          </ScrollArea>
                        </CardContent>
                      </Card>
                    )}
                  </>
                ) : (
                  <div className="text-sm text-muted-foreground">선택한 화면을 불러오는 중입니다</div>
                )}
              </div>
            </ScrollArea>
          </TabsContent>
        ))}
      </Tabs>
    );
  };

  return (
    <div className="grid grid-cols-12 gap-0 h-full overflow-hidden">
      <div className="col-span-4 border-r flex flex-col min-h-0">
        <div className="p-4 border-b bg-muted/30 flex justify-between items-center">
          <h2 className="font-semibold">Designs ({sessions.length})</h2>
          <RefreshButton onClick={handleRefresh} isRefreshing={isRefreshing} />
        </div>
        <div className="border-b">
          <Collapsible open={isDesignSystemOpen} onOpenChange={setIsDesignSystemOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center justify-between w-full p-3 hover:bg-muted/20 transition-colors text-sm font-medium">
                <span className="flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  DESIGN.md (디자인 시스템)
                </span>
                {isDesignSystemOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="p-4 max-h-[300px] overflow-y-auto text-sm border-t">
                {designSystem ? (
                  designSystem.exists && designSystem.content ? (
                    <MarkdownRenderer content={designSystem.content} />
                  ) : (
                    <p className="text-muted-foreground text-center py-4">DESIGN.md가 없습니다</p>
                  )
                ) : (
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-3/4" />
                  </div>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
        <ListFilter
          searchValue={searchValue}
          onSearchChange={setSearchValue}
          searchPlaceholder="Search designs..."
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
            {filteredSessions.length === 0 ? (
              <EmptyState
                icon={<Palette className="h-8 w-8" />}
                title="시안 없음"
                description="/mst:stitch로 Stitch 화면을 생성하면 여기에 표시됩니다"
              />
            ) : (
              filteredSessions.map((session) => (
                <div key={session.id} className="relative">
                  <SessionCard
                    id={session.id}
                    title={session.title || session.id}
                    status={session.status}
                    createdAt={session.created_at}
                    extraBadge={
                      session.source === 'plan_design'
                        ? `PLN ${session.linked_plan ?? session.id.replace('PLN-', '')}`
                        : session.linked_plan
                          ? `PLN ${session.linked_plan}`
                          : undefined
                    }
                    isSelected={selectedSession?.id === session.id}
                    onClick={() => navigate('/designs/' + session.id)}
                  />
                  {session.linked_req && (
                    <div className="absolute bottom-2 right-2">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); navigateTo('workflow', session.linked_req!); }}
                        className="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-600 hover:bg-blue-100 hover:underline font-mono"
                      >
                        {session.linked_req} →
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </div>

      <div className="col-span-8 flex flex-col bg-card min-h-0">
        {selectedSession ? (
          <>
            <div className="p-4 border-b flex justify-between items-center bg-muted/10">
              <div>
                <h2 className="font-bold text-lg">{selectedSession.title || selectedSession.id}</h2>
                <p className="text-xs text-muted-foreground">{selectedSession.created_at?.slice(0, 10)}</p>
              </div>
              <div className="flex items-center gap-2">
                {selectedSession.stitch_project_url && (
                  <a
                    href={selectedSession.stitch_project_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" /> Stitch 프로젝트
                  </a>
                )}
                <StatusBadge status={selectedSession.status} />
              </div>
            </div>

            {isPlanDesign ? (
              planDesignSections.length > 0 ? (
                <Tabs
                  value={String(selectedPlanSection)}
                  onValueChange={(v) => setSelectedPlanSection(Number(v))}
                  className="flex-1 flex flex-col overflow-hidden"
                >
                  <div className="px-4 border-b">
                    <TabsList className="bg-transparent h-10 p-0 gap-3 overflow-x-auto">
                      {planDesignSections.map((section, index) => {
                        const scrId = buildScreenScrId(index + 1);
                        const feedback = copyFeedback[scrId];
                        return (
                          <div key={index} className="flex items-center gap-1">
                            <TabsTrigger
                              value={String(index)}
                              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-1 gap-1"
                            >
                              <span className="font-mono text-[11px] text-muted-foreground">{scrId}</span>
                              <span>{section.title || `섹션 ${index + 1}`}</span>
                            </TabsTrigger>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className={`h-5 w-5 shrink-0 p-0 ${feedback === 'failed' ? 'text-destructive' : 'text-muted-foreground hover:text-foreground'}`}
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                void handleCopyScreenId(scrId);
                              }}
                              title={
                                feedback === 'copied'
                                  ? '복사됨'
                                  : feedback === 'failed'
                                    ? '복사 실패'
                                    : `${scrId} 복사`
                              }
                              aria-label={`${scrId} 복사`}
                            >
                              {feedback === 'copied' ? (
                                <Check className="h-3 w-3" />
                              ) : (
                                <Clipboard className="h-3 w-3" />
                              )}
                            </Button>
                          </div>
                        );
                      })}
                    </TabsList>
                  </div>
                  {planDesignSections.map((section, index) => (
                    <TabsContent key={index} value={String(index)} className="flex-1 m-0 p-0">
                      <ScrollArea className="h-full">
                        <div className="p-8">
                          <h3 className="text-lg font-semibold mb-3">{section.title || `섹션 ${index + 1}`}</h3>
                          {section.imageUrl && (
                            <Card className="mb-4 overflow-hidden">
                              <a
                                href={section.stitchUrl ?? section.imageUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                <img
                                  src={section.imageUrl}
                                  alt={section.title}
                                  className="max-w-[85%] block mx-auto"
                                />
                              </a>
                              <CardContent className="p-3 pt-2">
                                {section.stitchUrl && (
                                  <a
                                    href={section.stitchUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                                  >
                                    <ExternalLink className="h-3 w-3" /> {section.stitchLabel}
                                  </a>
                                )}
                              </CardContent>
                            </Card>
                          )}
                          {section.description ? (
                            <MarkdownRenderer content={section.description} />
                          ) : (
                            <div className="text-sm text-muted-foreground">디자인 상세가 없습니다</div>
                          )}
                        </div>
                      </ScrollArea>
                    </TabsContent>
                  ))}
                </Tabs>
              ) : (
                <EmptyState
                  icon={<Palette className="h-8 w-8" />}
                  title="섹션 없음"
                  description="design.md에 --- 구분 섹션이 없습니다"
                />
              )
            ) : hasStyles ? (
              styleNames.length > 0 && activeStyle ? (
                <Tabs
                  value={activeStyle}
                  onValueChange={setSelectedStyle}
                  className="flex-1 flex flex-col overflow-hidden"
                >
                  <div className="px-4 border-b">
                    <TabsList className="bg-transparent h-10 p-0 gap-4 overflow-x-auto">
                      {styleNames.map((styleName) => (
                        <TabsTrigger
                          key={styleName}
                          value={styleName}
                          className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-1"
                        >
                          {styleName}
                        </TabsTrigger>
                      ))}
                    </TabsList>
                  </div>
                  {styleNames.map((styleName) => (
                    <TabsContent key={styleName} value={styleName} className="flex-1 m-0 p-0">
                      {styleName === activeStyle
                        ? renderScreenTabs(styleScreenFiles, '선택한 스타일에 화면 파일이 아직 없습니다')
                        : null}
                    </TabsContent>
                  ))}
                </Tabs>
              ) : (
                <EmptyState
                  icon={<Palette className="h-8 w-8" />}
                  title="스타일 없음"
                  description="현재 선택한 세션에 표시할 스타일 폴더가 없습니다"
                />
              )
            ) : (
              renderScreenTabs(screenFiles, '현재 선택한 세션에 화면 파일이 아직 없습니다')
            )}
          </>
        ) : (
          <EmptyState
            icon={<Palette className="h-8 w-8" />}
            title="시안을 선택하세요"
            description="왼쪽 목록에서 디자인 세션을 클릭하세요"
          />
        )}
      </div>
    </div>
  );
}
