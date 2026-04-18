import type { MouseEvent } from 'react';
import { AlertTriangle, FileText } from 'lucide-react';
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { AgileSprint, SprintGoal, SprintWhyItem } from './types';
import {
  formatSprintPeriod,
  getSprintStories,
  isGoalAchieved,
  phaseBadgeClass,
  resolveSprintPhase,
  toArray,
} from './utils';

interface SprintDetailViewProps {
  currentSprintId: string | null;
  selectedSprint: AgileSprint | null;
  previousSprint: AgileSprint | null;
  selectedSprintGoals: SprintGoal[];
  previousSprintGoals: SprintGoal[];
  selectedSprintWhyItems: SprintWhyItem[];
  previousSprintWhyItems: SprintWhyItem[];
  reportLoading: boolean;
  reportError: string | null;
  isResultCompareMode: boolean;
  canCompareResult: boolean;
  onToggleCompare: () => void;
  onOpenDeepDive: () => void;
  rewriteLinkedMarkdown: (content: string) => string;
  onResultClick: (event: MouseEvent) => void;
}

function SprintWhatTable({
  goals,
  sprint,
  rewriteLinkedMarkdown,
  onResultClick,
}: {
  goals: SprintGoal[];
  sprint: AgileSprint;
  rewriteLinkedMarkdown: (content: string) => string;
  onResultClick: (event: MouseEvent) => void;
}) {
  if (goals.length === 0) {
    return (
      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-4">
        <div className="grid gap-3 text-sm md:grid-cols-2">
          <div>Planned: {toArray(sprint.planned).join(', ') || '-'}</div>
          <div>Completed: {toArray(sprint.completed).join(', ') || '-'}</div>
          <div className="md:col-span-2">Summary: {sprint.summary?.trim() || '-'}</div>
          <div className="md:col-span-2">Stories: {getSprintStories(sprint).join(', ') || '-'}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-md border border-zinc-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-zinc-50 text-zinc-500">
          <tr>
            <th className="w-[28%] border-b border-zinc-200 px-4 py-3 font-medium">목표</th>
            <th className="w-24 border-b border-zinc-200 px-4 py-3 text-center font-medium">상태</th>
            <th className="border-b border-zinc-200 px-4 py-3 font-medium">변화 요약</th>
          </tr>
        </thead>
        <tbody>
          {goals.map((goal, index) => (
            <tr key={`${goal.goal}-${index}`} className="border-b border-zinc-100 last:border-b-0">
              <td className="px-4 py-3 font-medium text-zinc-950">{goal.goal}</td>
              <td className="px-4 py-3 text-center">{isGoalAchieved(goal.status) ? '✅' : '❌'}</td>
              <td className="px-4 py-3 text-zinc-600" onClick={onResultClick}>
                <MarkdownRenderer content={rewriteLinkedMarkdown(goal.change_summary)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SprintWhyGrid({ items }: { items: SprintWhyItem[] }) {
  if (items.length === 0) return <div className="rounded-md border border-zinc-200 bg-zinc-50 p-4 text-sm text-zinc-500">WHY 데이터 없음</div>;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {items.map((item, index) => (
        <div key={`${item.label}-${index}`} className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">{item.label}</div>
          <div className="mt-2 text-sm leading-6 text-zinc-800">{item.value}</div>
        </div>
      ))}
    </div>
  );
}

export function SprintDetailView({
  currentSprintId,
  selectedSprint,
  previousSprint,
  selectedSprintGoals,
  previousSprintGoals,
  selectedSprintWhyItems,
  previousSprintWhyItems,
  reportLoading,
  reportError,
  isResultCompareMode,
  canCompareResult,
  onToggleCompare,
  onOpenDeepDive,
  rewriteLinkedMarkdown,
  onResultClick,
}: SprintDetailViewProps) {
  return (
    <Card className="border-zinc-200 shadow-none">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileText className="h-4 w-4" /> Sprint Detail
            </CardTitle>
            <CardDescription>{selectedSprint ? `${selectedSprint.sprint_id} 결과 보고서와 비교 뷰` : '스프린트를 선택하세요'}</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={onOpenDeepDive} disabled={!selectedSprint} className="rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400">
              Deep Dive
            </button>
            <button type="button" onClick={onToggleCompare} disabled={!canCompareResult} aria-pressed={isResultCompareMode} className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
              isResultCompareMode ? 'border-zinc-950 bg-zinc-950 text-white' : 'border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-100'
            } disabled:cursor-not-allowed disabled:border-zinc-200 disabled:text-zinc-400`}>
              비교
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {reportLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-8 w-56" />
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : !selectedSprint ? (
          <div className="rounded-md border border-dashed border-zinc-300 bg-zinc-50 px-4 py-10 text-center text-sm text-zinc-500">Overview에서 Sprint를 선택하세요.</div>
        ) : (
          <>
            {reportError ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{reportError}</div> : null}

            {isResultCompareMode && previousSprint ? (
              <div className="grid gap-4 xl:grid-cols-2">
                {[
                  { label: '이전 Sprint', sprint: previousSprint, whyItems: previousSprintWhyItems, goals: previousSprintGoals },
                  { label: '현재 Sprint', sprint: selectedSprint, whyItems: selectedSprintWhyItems, goals: selectedSprintGoals },
                ].map((item) => (
                  <div key={`${item.label}-${item.sprint.sprint_id}`} className="space-y-4 rounded-md border border-zinc-200 bg-zinc-50 p-4">
                    <div className="flex items-center justify-between">
                      <h3 className="font-mono text-sm font-semibold text-zinc-950">{item.sprint.sprint_id}</h3>
                      <span className="rounded-full border border-zinc-200 bg-white px-2 py-1 text-[11px] font-medium text-zinc-500">{item.label}</span>
                    </div>
                    <SprintWhyGrid items={item.whyItems} />
                    <SprintWhatTable goals={item.goals} sprint={item.sprint} rewriteLinkedMarkdown={rewriteLinkedMarkdown} onResultClick={onResultClick} />
                  </div>
                ))}
              </div>
            ) : (
              <>
                <div className="rounded-md border border-zinc-200 bg-zinc-50 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-zinc-950">{selectedSprint.sprint_id}</span>
                      <Badge variant="outline" className={phaseBadgeClass(resolveSprintPhase(selectedSprint.status))}>{resolveSprintPhase(selectedSprint.status)}</Badge>
                      {currentSprintId === selectedSprint.sprint_id ? <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">Current</Badge> : null}
                      <StatusBadge status={selectedSprint.status ?? 'unknown'} />
                    </div>
                    {selectedSprint.integrationReview?.force_wire_recommended ? (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600" title={`force_wire_recommended · ${(selectedSprint.integrationReview?.ratios?.new_island ?? 0).toFixed(2)}`}>
                        <AlertTriangle className="h-4 w-4" /> integration 경고
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-2 text-xs text-zinc-500">기간: {formatSprintPeriod(selectedSprint)}</div>
                </div>

                <div className="rounded-md border border-zinc-200 bg-zinc-950 px-6 py-8 text-white">
                  <div className="max-w-3xl">
                    <p className="text-sm uppercase tracking-[0.18em] text-zinc-300">user_observable_change</p>
                    <p className="mt-4 text-2xl font-semibold leading-[1.4]">
                      {selectedSprint.user_observable_change?.trim() || selectedSprint.summary?.trim() || '사용자 체감 변화가 기록되지 않았습니다.'}
                    </p>
                  </div>
                </div>

                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-zinc-950">이 스프린트를 왜 했는가</h3>
                  <SprintWhyGrid items={selectedSprintWhyItems} />
                </div>

                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-zinc-950">무엇을 달성했는가</h3>
                  <SprintWhatTable goals={selectedSprintGoals} sprint={selectedSprint} rewriteLinkedMarkdown={rewriteLinkedMarkdown} onResultClick={onResultClick} />
                </div>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
