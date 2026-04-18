import type {
  AgileSessionMeta,
  AgileSessionSummary,
  AgileSprint,
  ObjectiveParsedDod,
  SprintGoal,
  SprintGoalDiff,
  SprintGoalTestResults,
  SprintWhyItem,
} from './types';

export type MainTabValue = 'overview' | 'sprint-detail' | 'objective';
export type SprintPhaseLabel = 'Plan' | 'Execute' | 'Review' | 'Done';

export interface ActionCardData {
  id: string;
  tone: 'neutral' | 'warning' | 'danger';
  eyebrow: string;
  title: string;
  description: string;
  count?: number;
}

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
    .replace(/(\bPLN-\d+\b)/g, (match, _p1, offset, source) => {
      if (source.slice(Math.max(0, offset - 2), offset).includes('[')) return match;
      if (source.slice(Math.max(0, offset - 7), offset).includes('/plans/')) return match;
      return `[${match}](/plans/${match})`;
    })
    .replace(/(\bREQ-\d+\b)/g, (match, _p1, offset, source) => {
      if (source.slice(Math.max(0, offset - 2), offset).includes('[')) return match;
      if (source.slice(Math.max(0, offset - 10), offset).includes('/workflow/')) return match;
      return `[${match}](/workflow/${match})`;
    });
}

const LOCAL_MARKDOWN_IMAGE_PATTERN = /!\[([^\]]*)\]\((\.{1,2}\/[^)\s]+)\)/g;

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

export function resolveObjectiveMarkdownPath(href: string, currentFile: string): string | null {
  const trimmedHref = href.trim();
  if (!trimmedHref || trimmedHref.startsWith('#') || trimmedHref.startsWith('?')) {
    return null;
  }

  try {
    const currentUrl = new URL(currentFile, 'https://objective.local/');
    const resolvedUrl = new URL(trimmedHref, currentUrl);
    if (resolvedUrl.origin !== 'https://objective.local') return null;

    const normalizedPath = decodeURIComponent(resolvedUrl.pathname.replace(/^\/+/, ''));
    return normalizedPath.toLowerCase().endsWith('.md') ? normalizedPath : null;
  } catch {
    return null;
  }
}

export function toArray<T>(value: T[] | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

export function extractDodIds(value: string | undefined): string[] {
  if (!value) return [];
  const matches = value.toUpperCase().match(/DOD-\d+/g);
  return matches ? [...new Set(matches)] : [];
}

export function isDodDoneStatus(status: string): boolean {
  return status.trim().toLowerCase() === 'done';
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
    if (/^S\d+$/i.test(trimmed)) return `S${trimmed.slice(1).padStart(2, '0')}`;
    const parsed = Number.parseInt(trimmed, 10);
    if (Number.isFinite(parsed)) {
      return `S${String(Math.max(0, parsed)).padStart(2, '0')}`;
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
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

export function formatRate(rate: number | undefined): string {
  return typeof rate === 'number' && Number.isFinite(rate) ? `${Math.round(rate * 100)}%` : '-';
}

export function resolveSprintPhase(status: string | undefined): SprintPhaseLabel {
  const normalized = (status ?? '').trim().toLowerCase();
  if (['done', 'completed', 'success'].includes(normalized)) return 'Done';
  if (['review', 'phase3_review', 'qa', 'verify', 'verifying'].includes(normalized)) return 'Review';
  if (['active', 'running', 'processing', 'executing', 'execute', 'in_progress', 'in-progress', 'progress', 'ongoing'].includes(normalized)) {
    return 'Execute';
  }
  return 'Plan';
}

export function phaseBadgeClass(phase: SprintPhaseLabel): string {
  switch (phase) {
    case 'Done':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    case 'Review':
      return 'border-amber-200 bg-amber-50 text-amber-700';
    case 'Execute':
      return 'border-sky-200 bg-sky-50 text-sky-700';
    default:
      return 'border-zinc-200 bg-zinc-50 text-zinc-600';
  }
}

export function formatSprintPeriod(sprint: AgileSprint): string {
  if (typeof sprint.period === 'string' && sprint.period.trim().length > 0) return sprint.period;
  const start = sprint.started_at ?? sprint.start_date;
  const end = sprint.ended_at ?? sprint.end_date;
  return start || end ? `${formatTime(start)} ~ ${formatTime(end)}` : formatTime(sprint.timestamp);
}

export function getSprintStories(sprint: AgileSprint): string[] {
  const directStories = toArray(sprint.stories).filter(Boolean);
  return directStories.length > 0 ? directStories : [...new Set([...toArray(sprint.planned), ...toArray(sprint.completed)])];
}

export function buildFallbackResultMarkdown(sprint: AgileSprint): string {
  return [
    `# ${sprint.sprint_id} Result`,
    '',
    `- status: ${sprint.status ?? 'unknown'}`,
    `- planned: ${toArray(sprint.planned).join(', ') || '-'}`,
    `- completed: ${toArray(sprint.completed).join(', ') || '-'}`,
    `- generated PLN: ${toArray(sprint.generated?.pln).join(', ') || '-'}`,
    `- generated REQ: ${toArray(sprint.generated?.req).join(', ') || '-'}`,
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
  return toArray(sprint.sprint_goals).filter((goal): goal is SprintGoal => {
    return typeof goal?.goal === 'string' && typeof goal?.status === 'string' && typeof goal?.change_summary === 'string';
  });
}

export function getSprintWhyItems(sprint: AgileSprint | null): SprintWhyItem[] {
  if (!sprint) return [];

  return [
    ['Sprint 목적', sprint.sprint_purpose],
    ['선택 근거', sprint.selection_reason],
    ['대상 DoD', sprint.target_dod_text],
    ['직전 회고 방향', sprint.previous_direction],
  ]
    .map(([label, value]) => ({ label, value: (value ?? '').trim() }))
    .filter((item): item is SprintWhyItem => item.value.length > 0);
}

export function formatGoalDiff(diff: SprintGoalDiff | undefined): string {
  if (!diff) return '증빙 미첨부';
  const commits = toArray(diff.commits).filter((commit) => typeof commit === 'string' && commit.trim().length > 0);
  return `files ${diff.files_changed ?? 0} · +${diff.insertions ?? 0} / -${diff.deletions ?? 0} · commits: ${commits.join(', ') || '-'}`;
}

export function formatGoalTestResults(testResults: SprintGoalTestResults | undefined): string {
  if (!testResults) return '증빙 미첨부';
  const summary = typeof testResults.summary === 'string' && testResults.summary.trim().length > 0 ? ` · ${testResults.summary}` : '';
  return `pass ${testResults.passed ?? 0} / fail ${testResults.failed ?? 0}${summary}`;
}

export function computeDodProgress(dods: ObjectiveParsedDod[]): number {
  if (dods.length === 0) return 0;
  const completed = dods.filter((dod) => isDodDoneStatus(dod.status)).length;
  return Math.round((completed / dods.length) * 100);
}

export function computeOpenKnownIssues(sprints: AgileSprint[], currentRetrospectiveFailures: number): number {
  const sprintSignals = sprints.filter((sprint) => {
    return sprint.integrationReview?.force_wire_recommended
      || sprint.alignmentCheck?.verdict === 'drift_warning'
      || sprint.alignmentCheck?.verdict === 'objective_stale';
  }).length;
  return sprintSignals + currentRetrospectiveFailures;
}

export function getLatestNewIslandRatio(sprints: AgileSprint[], preferredSprintId?: string | null): number {
  const ordered = preferredSprintId
    ? [...sprints.filter((sprint) => sprint.sprint_id === preferredSprintId), ...sprints.filter((sprint) => sprint.sprint_id !== preferredSprintId)]
    : [...sprints].reverse();

  for (const sprint of ordered) {
    const ratio = sprint.integrationReview?.ratios?.new_island;
    if (typeof ratio === 'number' && Number.isFinite(ratio)) return ratio;
  }
  return 0;
}

export function buildActionCards(session: AgileSessionMeta | null, sprints: AgileSprint[], currentSprintId?: string | null): ActionCardData[] {
  const cards: ActionCardData[] = [];
  const deferredDodCount = session?.deferred_dod_count ?? 0;
  if (deferredDodCount >= 1) {
    cards.push({
      id: 'approvals',
      tone: 'neutral',
      eyebrow: '승인 대기',
      title: `승인 대기 ${deferredDodCount}건`,
      description: 'proposed_done 상태 DoD 검토가 필요합니다.',
      count: deferredDodCount,
    });
  }

  const steeringSprint = sprints.find((sprint) => {
    return sprint.alignmentCheck?.verdict === 'drift_warning' || sprint.alignmentCheck?.verdict === 'objective_stale';
  });
  if (steeringSprint) {
    cards.push({
      id: 'steering',
      tone: 'warning',
      eyebrow: 'Steering Trigger',
      title: steeringSprint.alignmentCheck?.verdict === 'objective_stale' ? 'Objective 갱신 필요' : '기획-구현 Drift 감지',
      description: `${steeringSprint.sprint_id} · ${(steeringSprint.alignmentCheck?.raw_excerpt ?? 'alignment-check 원문 확인').slice(0, 96)}`,
    });
  }

  const escalationSprint = sprints.find((sprint) => {
    const ratio = sprint.integrationReview?.ratios?.new_island ?? 0;
    return sprint.integrationReview?.force_wire_recommended || ratio >= 0.2;
  }) ?? sprints.find((sprint) => sprint.sprint_id === currentSprintId);

  if (escalationSprint && (escalationSprint.integrationReview?.force_wire_recommended || (escalationSprint.integrationReview?.ratios?.new_island ?? 0) >= 0.2)) {
    const ratio = escalationSprint.integrationReview?.ratios?.new_island ?? 0;
    cards.push({
      id: 'escalation',
      tone: 'danger',
      eyebrow: 'Escalation',
      title: escalationSprint.integrationReview?.force_wire_recommended ? '강제 wire 검토 필요' : '통합 부채 임계치 초과',
      description: `${escalationSprint.sprint_id} · new_island_ratio ${ratio.toFixed(2)}`,
    });
  }

  return cards;
}
