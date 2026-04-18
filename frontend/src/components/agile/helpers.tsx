import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react';
import { useAppContext } from '@/context/AppContext';
import { useMatch, useNavigate, useParams } from 'react-router-dom';
import { ApiFetchError, apiFetch } from '@/hooks/useApi';
import { useResizableSidebar } from '@/hooks/useResizableSidebar';
import { ResizableHandle } from '@/components/shared/ResizableHandle';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { RefreshButton } from '@/components/shared/RefreshButton';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer';
import { MilkdownEditor } from '@/components/shared/MilkdownEditor';
import { ObjectiveCommentsPanel } from '@/views/ObjectiveCommentsPanel';
import { ArrowDown, ChevronLeft, ChevronRight, FileText, GitBranch, ListChecks } from 'lucide-react';

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
  test_intent?: string;
  test_strategy?: string;
  test_flow?: string[];
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
  sprint_purpose?: string;
  selection_reason?: string;
  target_dod?: string;
  target_dod_text?: string;
  previous_direction?: string;
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

interface ObjectiveParsedDod {
  dod: string;
  status: string;
  priority: string;
  anchorText?: string | null;
  contentText?: string | null;
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

interface ResultDetailFile {
  name: string;
}

interface SprintWhyItem {
  label: string;
  value: string;
}

type MainTabValue = 'overview' | 'sprint-detail' | 'objective';


export function resolveAgileMainTab(isObjectiveRoute: boolean): MainTabValue {
  return isObjectiveRoute ? 'objective' : 'overview';
}

export function resolveAgileSelectedSessionId(
  nextSessions: Array<Pick<AgileSessionSummary, 'id'>>,
  previousSessionId: string | null,
  agiId: string | undefined,
): string | null {
  if (agiId) {
    const target = nextSessions.find((session) => session.id === agiId);
    return target?.id ?? nextSessions[0]?.id ?? null;
  }

  if (previousSessionId && nextSessions.some((session) => session.id === previousSessionId)) {
    return previousSessionId;
  }

  return nextSessions[0]?.id ?? null;
}


export function linkify(text: string): string {
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

export const LOCAL_MARKDOWN_IMAGE_PATTERN = /!\[([^\]]*)\]\((\.{1,2}\/[^)\s]+)\)/g;

export function rewriteLocalMarkdownImagePaths(content: string, agiId: string | null): string {
  if (!agiId || content.length === 0) return content;

  return content.replace(LOCAL_MARKDOWN_IMAGE_PATTERN, (fullMatch, altText: string, rawPath: string) => {
    if (!rawPath.startsWith('./') && !rawPath.startsWith('../')) {
      return fullMatch;
    }

    const normalizedPath = rawPath.startsWith('./') ? rawPath.slice(2) : rawPath;
    const url = `/api/agile/sessions/${encodeURIComponent(agiId)}/file?path=${encodeURIComponent(normalizedPath)}`;
    return `![${altText}](${url})`;
  });
}

export function parseDodMarkers(content: string): ObjectiveParsedDod[] {
  const regex = /<!--\s*dod:\s*([a-z0-9_-]+)\s+status:\s*([a-z0-9_-]+)\s+priority:\s*([a-z0-9_-]+)\s*-->/gi;
  const markers: ObjectiveParsedDod[] = [];
  let match: RegExpExecArray | null;
  while ((match = regex.exec(content)) !== null) {
    markers.push({
      dod: match[1].toUpperCase(),
      status: match[2].toLowerCase(),
      priority: match[3].toLowerCase(),
      anchorText: null,
      contentText: null,
    });
  }
  return markers;
}

export function priorityBadgeClass(priority: string): string {
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

export const DOD_PRIORITY_DISPLAY_ORDER = ['must', 'should', 'could'] as const;

export function isDodDoneStatus(status: string): boolean {
  return status.trim().toLowerCase() === 'done';
}

export function extractDodIds(value: string | undefined): string[] {
  if (!value) return [];
  const matches = value.toUpperCase().match(/DOD-\d+/g);
  return matches ? [...new Set(matches)] : [];
}

export function buildDodCompletionSprintMap(sprints: AgileSprint[]): Record<string, string> {
  const completionSprintByDod: Record<string, string> = {};
  for (const sprint of sprints) {
    const dodIds = [
      ...extractDodIds(typeof sprint.target_dod === 'string' ? sprint.target_dod : undefined),
      ...extractDodIds(typeof sprint.target_dod_text === 'string' ? sprint.target_dod_text : undefined),
    ];

    for (const dodId of dodIds) {
      completionSprintByDod[dodId] = sprint.sprint_id;
    }
  }
  return completionSprintByDod;
}

export function renderDodStatus(
  dods: ObjectiveParsedDod[],
  options?: {
    completionSprintByDod?: Record<string, string>;
    rewriteMarkdown?: (content: string) => string;
    onLinkClick?: (e: MouseEvent<HTMLAnchorElement>, href: string) => void;
  },
) {
  if (dods.length === 0) return null;

  const completionSprintByDod = options?.completionSprintByDod ?? {};
  const rewriteMarkdown = options?.rewriteMarkdown;
  const onLinkClick = options?.onLinkClick;

  const grouped = new Map<string, ObjectiveParsedDod[]>();
  for (const dod of dods) {
    const key = dod.priority.toLowerCase();
    const items = grouped.get(key) ?? [];
    items.push(dod);
    grouped.set(key, items);
  }

  const fallbackPriorityKeys = [...grouped.keys()]
    .filter((key) => !DOD_PRIORITY_DISPLAY_ORDER.includes(key as typeof DOD_PRIORITY_DISPLAY_ORDER[number]))
    .sort((a, b) => a.localeCompare(b));

  const orderedPriorityKeys = [
    ...DOD_PRIORITY_DISPLAY_ORDER.filter((key) => grouped.has(key)),
    ...fallbackPriorityKeys,
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <ListChecks className="h-4 w-4" /> Project DoD Status
        </CardTitle>
        <CardDescription>
          프로젝트 완료 기준(DoD) 상태와 우선순위
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {orderedPriorityKeys.map((priorityKey) => {
            const items = [...(grouped.get(priorityKey) ?? [])].sort((a, b) => {
              const doneRankGap = Number(isDodDoneStatus(b.status)) - Number(isDodDoneStatus(a.status));
              if (doneRankGap !== 0) return doneRankGap;
              return a.dod.localeCompare(b.dod);
            });

            return (
              <div key={priorityKey} className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {priorityKey}
                </h3>
                <div className="space-y-2">
                  {items.map((dod, idx) => {
                    const dodText = (dod.contentText ?? dod.anchorText ?? '').trim();
                    const isDone = isDodDoneStatus(dod.status);
                    const completionSprintId = isDone ? completionSprintByDod[dod.dod] : null;

                    return (
                      <div key={`${priorityKey}-${dod.dod}-${idx}`} className="flex items-center justify-between border rounded-md p-3 text-sm bg-muted/5 gap-3">
                        <div className="min-w-0">
                          <div className="font-mono text-xs text-muted-foreground">{dod.dod}</div>
                          {dodText.length > 0 && (
                            <div className="text-sm mt-1 min-w-0 [&_p]:my-0">
                              <MarkdownRenderer
                                content={rewriteMarkdown ? rewriteMarkdown(dodText) : dodText}
                                onLinkClick={onLinkClick}
                              />
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {isDone && (
                            <Badge variant="secondary" className="font-mono text-[11px]">
                              sprint:{completionSprintId ?? '-'}
                            </Badge>
                          )}
                          <Badge variant="outline" className={priorityBadgeClass(dod.priority)}>
                            priority:{dod.priority}
                          </Badge>
                          <StatusBadge status={dod.status} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

export function renderObjectiveSections(
  sections: ObjectiveParsedSection[],
  rewriteMarkdown: (content: string) => string,
  onLinkClick?: (e: MouseEvent<HTMLAnchorElement>, href: string) => void,
) {
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
              <MarkdownRenderer content={rewriteMarkdown(section.content)} onLinkClick={onLinkClick} />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function resolveObjectiveMarkdownPath(href: string, currentFile: string): string | null {
  const trimmedHref = href.trim();
  if (!trimmedHref || trimmedHref.startsWith('#') || trimmedHref.startsWith('?')) {
    return null;
  }

  try {
    const currentUrl = new URL(currentFile, 'https://objective.local/');
    const resolvedUrl = new URL(trimmedHref, currentUrl);
    if (resolvedUrl.origin !== 'https://objective.local') {
      return null;
    }

    const normalizedPath = decodeURIComponent(resolvedUrl.pathname.replace(/^\/+/, ''));
    if (!normalizedPath.toLowerCase().endsWith('.md')) {
      return null;
    }

    return normalizedPath;
  } catch {
    return null;
  }
}

export function toArray<T>(value: T[] | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

export function parseSprintNumber(sprintId: string): number {
  const match = /^S(\d+)$/i.exec(sprintId);
  return match ? Number.parseInt(match[1], 10) : Number.POSITIVE_INFINITY;
}

export function sortSprints(sprints: AgileSprint[]): AgileSprint[] {
  return [...sprints].sort((a, b) => parseSprintNumber(a.sprint_id) - parseSprintNumber(b.sprint_id));
}

export function toSprintId(value: number | string | undefined): string | null {
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

export function resolveDefaultSprintId(
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

export function formatTime(value: string | null | undefined): string {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

export function formatRate(rate: number | undefined): string {
  if (typeof rate !== 'number' || !Number.isFinite(rate)) return '-';
  return `${Math.round(rate * 100)}%`;
}

type SprintPhaseLabel = 'Plan' | 'Execute' | 'Review' | 'Done';

export function resolveSprintPhase(status: string | undefined): SprintPhaseLabel {
  const normalized = (status ?? '').trim().toLowerCase();
  if (normalized.length === 0) return 'Plan';

  if (['done', 'completed', 'success'].includes(normalized)) {
    return 'Done';
  }

  if (['review', 'phase3_review', 'qa', 'verify', 'verifying'].includes(normalized)) {
    return 'Review';
  }

  if ([
    'active',
    'running',
    'processing',
    'executing',
    'execute',
    'in_progress',
    'in-progress',
    'progress',
    'ongoing',
  ].includes(normalized)) {
    return 'Execute';
  }

  return 'Plan';
}

export function phaseBadgeClass(phase: SprintPhaseLabel): string {
  switch (phase) {
    case 'Done':
      return 'border-green-300 text-green-700 bg-green-50';
    case 'Review':
      return 'border-purple-300 text-purple-700 bg-purple-50';
    case 'Execute':
      return 'border-blue-300 text-blue-700 bg-blue-50';
    case 'Plan':
    default:
      return 'border-amber-300 text-amber-700 bg-amber-50';
  }
}

export function formatSprintPeriod(sprint: AgileSprint): string {
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

export function getSprintStories(sprint: AgileSprint): string[] {
  const directStories = toArray(sprint.stories).filter(Boolean);
  if (directStories.length > 0) {
    return directStories;
  }

  return [...new Set([...toArray(sprint.planned), ...toArray(sprint.completed)])];
}

export function buildFallbackResultMarkdown(sprint: AgileSprint): string {
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

export function isGoalAchieved(status: string | undefined): boolean {
  return (status ?? '').trim().toLowerCase() === 'achieved';
}

export function getSprintGoals(sprint: AgileSprint | null): SprintGoal[] {
  if (!sprint) return [];

  return toArray(sprint.sprint_goals).filter(
    (goal): goal is SprintGoal => (
      typeof goal?.goal === 'string'
      && typeof goal?.status === 'string'
      && typeof goal?.change_summary === 'string'
    ),
  );
}

export function getSprintWhyItems(sprint: AgileSprint | null): SprintWhyItem[] {
  if (!sprint) return [];

  const items: SprintWhyItem[] = [];
  const purpose = typeof sprint.sprint_purpose === 'string' ? sprint.sprint_purpose.trim() : '';
  const selectionReason = typeof sprint.selection_reason === 'string' ? sprint.selection_reason.trim() : '';
  const targetDodText = typeof sprint.target_dod_text === 'string' ? sprint.target_dod_text.trim() : '';
  const previousDirection = typeof sprint.previous_direction === 'string' ? sprint.previous_direction.trim() : '';

  if (purpose.length > 0) {
    items.push({ label: 'Sprint 목적', value: purpose });
  }
  if (selectionReason.length > 0) {
    items.push({ label: '선택 근거', value: selectionReason });
  }
  if (targetDodText.length > 0) {
    items.push({ label: '대상 DoD', value: targetDodText });
  }
  if (previousDirection.length > 0) {
    items.push({ label: '직전 회고 방향', value: previousDirection });
  }

  return items;
}

export function formatGoalTestResults(testResults: SprintGoalTestResults | undefined): string {
  if (!testResults) return '증빙 미첨부';

  const passed = typeof testResults.passed === 'number' ? testResults.passed : 0;
  const failed = typeof testResults.failed === 'number' ? testResults.failed : 0;
  const summary = typeof testResults.summary === 'string' && testResults.summary.trim().length > 0
    ? ` · ${testResults.summary}`
    : '';
  return `pass ${passed} / fail ${failed}${summary}`;
}

export function renderGoalTestSection(testResults: SprintGoalTestResults | undefined) {
  const testIntent = typeof testResults?.test_intent === 'string' ? testResults.test_intent.trim() : '';
  if (testIntent.length === 0) {
    return (
      <>
        <div className="text-xs font-semibold text-muted-foreground mb-1">테스트 결과</div>
        <div>{formatGoalTestResults(testResults)}</div>
      </>
    );
  }

  const testStrategy = typeof testResults?.test_strategy === 'string' && testResults.test_strategy.trim().length > 0
    ? testResults.test_strategy.trim()
    : '-';
  const testFlow = toArray(testResults?.test_flow)
    .map((step) => (typeof step === 'string' ? step.trim() : ''))
    .filter((step) => step.length > 0);

  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold text-muted-foreground">테스트 검증</div>
      <div className="rounded-md border bg-background p-3 space-y-2">
        <div>
          <div className="text-[11px] font-semibold text-muted-foreground">의도</div>
          <div className="text-sm">{testIntent}</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold text-muted-foreground">전략</div>
          <div className="text-sm">{testStrategy}</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold text-muted-foreground">흐름</div>
          {testFlow.length > 0 ? (
            <ol className="mt-1 list-decimal list-inside text-sm space-y-1">
              {testFlow.map((step, index) => (
                <li key={`test-flow-${index}`}>{step}</li>
              ))}
            </ol>
          ) : (
            <div className="text-sm">-</div>
          )}
        </div>
        <div>
          <div className="text-[11px] font-semibold text-muted-foreground">결과</div>
          <div className="text-sm">{formatGoalTestResults(testResults)}</div>
        </div>
      </div>
    </div>
  );
}

export function formatGoalDiff(diff: SprintGoalDiff | undefined): string {
  if (!diff) return '증빙 미첨부';

  const filesChanged = typeof diff.files_changed === 'number' ? diff.files_changed : 0;
  const insertions = typeof diff.insertions === 'number' ? diff.insertions : 0;
  const deletions = typeof diff.deletions === 'number' ? diff.deletions : 0;
  const commits = toArray(diff.commits).filter((commit) => typeof commit === 'string' && commit.trim().length > 0);
  const commitText = commits.length > 0 ? commits.join(', ') : '-';
  return `files ${filesChanged} · +${insertions} / -${deletions} · commits: ${commitText}`;
}

export function sprintGoalLine(sprint: AgileSprint): string | null {
  const targetDod = typeof sprint.target_dod === 'string' && sprint.target_dod.trim().length > 0
    ? sprint.target_dod.trim()
    : (typeof sprint.target_dod_text === 'string' && sprint.target_dod_text.trim().length > 0 ? sprint.target_dod_text.trim() : null);
  const purpose = typeof sprint.sprint_purpose === 'string' && sprint.sprint_purpose.trim().length > 0
    ? sprint.sprint_purpose.trim()
    : null;
  const line = [targetDod, purpose].filter((value): value is string => Boolean(value)).join(' · ');
  return line.length > 0 ? line : null;
}

export function toResultDetailTabLabel(filename: string): string {
  const withoutExtension = filename.replace(/\.md$/i, '').trim();
  return withoutExtension.length > 0 ? withoutExtension : filename;
}

