import type { MouseEvent } from 'react';
import { X } from 'lucide-react';
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { AgileRetrospective, AgileSprint } from './types';
import { formatGoalDiff, formatGoalTestResults, getSprintGoals, toArray } from './utils';

interface DeepDivePanelProps {
  sprint: AgileSprint | null;
  retrospective: AgileRetrospective | null;
  resultMarkdown: string | null;
  retrospectiveMd: string | null;
  objectiveContent: string | null;
  resultDetailFiles: string[];
  selectedResultDetailFile: string | null;
  resultDetailContent: string | null;
  resultDetailLoading: boolean;
  resultDetailError: string | null;
  rewriteLinkedMarkdown: (content: string) => string;
  onResultClick: (event: MouseEvent) => void;
  onResultDetailFileChange: (value: string) => void;
  onClose: () => void;
}

export function DeepDivePanel({
  sprint,
  retrospective,
  resultMarkdown,
  retrospectiveMd,
  objectiveContent,
  resultDetailFiles,
  selectedResultDetailFile,
  resultDetailContent,
  resultDetailLoading,
  resultDetailError,
  rewriteLinkedMarkdown,
  onResultClick,
  onResultDetailFileChange,
  onClose,
}: DeepDivePanelProps) {
  const goals = getSprintGoals(sprint);

  return (
    <aside className="flex h-full min-h-0 flex-col bg-zinc-50">
      <div className="flex items-start justify-between gap-3 border-b border-zinc-200 bg-white px-4 py-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Deep Dive</p>
          <h2 className="mt-1 text-base font-semibold tracking-tight text-zinc-950">
            {sprint ? `${sprint.sprint_id} 상세 원문` : '선택된 Sprint 없음'}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-100"
          aria-label="Deep Dive 닫기"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!sprint ? (
          <div className="rounded-md border border-dashed border-zinc-300 bg-white px-4 py-10 text-center text-sm text-zinc-500">
            Overview나 Sprint Detail에서 스프린트를 선택하면 evidence, retrospective, raw metadata를 확인할 수 있습니다.
          </div>
        ) : (
          <Tabs defaultValue="evidence" className="space-y-4">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="evidence">증빙</TabsTrigger>
              <TabsTrigger value="retro">회고</TabsTrigger>
              <TabsTrigger value="raw">Raw</TabsTrigger>
              <TabsTrigger value="objective">Objective</TabsTrigger>
            </TabsList>

            <TabsContent value="evidence" className="space-y-4">
              {goals.length > 0 ? (
                goals.map((goal, index) => (
                  <div key={`${goal.goal}-${index}`} className="rounded-md border border-zinc-200 bg-white p-4">
                    <div className="space-y-1">
                      <p className="text-sm font-semibold text-zinc-950">{goal.goal}</p>
                      <p className="text-sm leading-6 text-zinc-600">{goal.change_summary}</p>
                    </div>
                    <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
                      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">Test</div>
                        <div className="mt-2 text-zinc-700">{formatGoalTestResults(goal.evidence?.test_results)}</div>
                      </div>
                      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">Diff</div>
                        <div className="mt-2 text-zinc-700">{formatGoalDiff(goal.evidence?.diff)}</div>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-md border border-zinc-200 bg-white p-4 text-sm text-zinc-500">
                  구조화된 sprint evidence가 없습니다.
                </div>
              )}

              {resultDetailFiles.length > 0 ? (
                <div className="rounded-md border border-zinc-200 bg-white p-4">
                  <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">result-details</div>
                  <Tabs value={selectedResultDetailFile ?? resultDetailFiles[0]} onValueChange={onResultDetailFileChange} className="space-y-3">
                    <div className="overflow-x-auto">
                      <TabsList className="inline-flex h-auto w-max flex-wrap gap-1 bg-zinc-100 p-1">
                        {resultDetailFiles.map((file) => (
                          <TabsTrigger key={file} value={file}>
                            {file.replace(/\.md$/i, '')}
                          </TabsTrigger>
                        ))}
                      </TabsList>
                    </div>
                  </Tabs>

                  {resultDetailLoading ? <Skeleton className="h-28 w-full" /> : null}
                  {resultDetailError ? <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{resultDetailError}</div> : null}
                  {!resultDetailLoading && !resultDetailError && resultDetailContent ? (
                    <div className="prose prose-sm mt-3 max-w-none rounded-md border border-zinc-200 bg-zinc-50 p-4" onClick={onResultClick}>
                      <MarkdownRenderer content={rewriteLinkedMarkdown(resultDetailContent)} />
                    </div>
                  ) : null}
                </div>
              ) : null}
            </TabsContent>

            <TabsContent value="retro" className="space-y-4">
              <div className="rounded-md border border-zinc-200 bg-white p-4">
                {retrospective ? (
                  <div className="space-y-4 text-sm">
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">succeeded</div>
                      <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-700">
                        {toArray(retrospective.succeeded).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
                      </ul>
                    </div>
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">failed</div>
                      <div className="mt-2 space-y-2">
                        {toArray(retrospective.failed).map((item, index) => (
                          <div key={`${item.item ?? 'failed'}-${index}`} className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
                            <div className="font-medium text-zinc-950">{item.item ?? `Failure ${index + 1}`}</div>
                            <div className="mt-1 text-zinc-600">tried_approach: {item.tried_approach ?? '-'}</div>
                            <div className="mt-1 text-zinc-600">failure_reason: {item.failure_reason ?? '-'}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-3">
                      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">planned: {retrospective.velocity?.planned ?? '-'}</div>
                      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">completed: {retrospective.velocity?.completed ?? '-'}</div>
                      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">rate: {retrospective.velocity?.rate ?? '-'}</div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">{retrospective.known_limitations || '-'}</div>
                      <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">{retrospective.lessons_learned || '-'}</div>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-zinc-500">retrospective.json이 아직 없습니다.</p>
                )}
              </div>
            </TabsContent>

            <TabsContent value="raw" className="space-y-4">
              <div className="rounded-md border border-zinc-200 bg-white p-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">result.md</div>
                <div className="prose prose-sm mt-3 max-w-none rounded-md border border-zinc-200 bg-zinc-50 p-4" onClick={onResultClick}>
                  <MarkdownRenderer content={rewriteLinkedMarkdown(resultMarkdown ?? '결과 문서가 없습니다.')} />
                </div>
              </div>
              {retrospectiveMd ? (
                <div className="rounded-md border border-zinc-200 bg-white p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">retrospective.md</div>
                  <div className="prose prose-sm mt-3 max-w-none rounded-md border border-zinc-200 bg-zinc-50 p-4" onClick={onResultClick}>
                    <MarkdownRenderer content={rewriteLinkedMarkdown(retrospectiveMd)} />
                  </div>
                </div>
              ) : null}
            </TabsContent>

            <TabsContent value="objective">
              <div className="rounded-md border border-zinc-200 bg-white p-4">
                {objectiveContent ? (
                  <div className="prose prose-sm max-w-none rounded-md border border-zinc-200 bg-zinc-50 p-4" onClick={onResultClick}>
                    <MarkdownRenderer content={rewriteLinkedMarkdown(objectiveContent)} />
                  </div>
                ) : (
                  <p className="text-sm text-zinc-500">objective.md가 없습니다.</p>
                )}
              </div>
            </TabsContent>
          </Tabs>
        )}
      </div>
    </aside>
  );
}
