import { AlertTriangle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { StatusBadge } from '@/components/shared/StatusBadge';
import type { AgileSprint } from './types';
import { formatSprintPeriod, phaseBadgeClass, resolveSprintPhase } from './utils';

interface SprintTimelineProps {
  sprints: AgileSprint[];
  currentSprintId?: string | null;
  selectedSprintId?: string | null;
  onSprintSelect: (sprintId: string) => void;
}

function sprintKindLabel(kind: AgileSprint['sprint_kind']): string {
  return kind === 'foundational' ? 'Foundational' : 'User Observable';
}

function sprintKindClass(kind: AgileSprint['sprint_kind']): string {
  return kind === 'foundational'
    ? 'border-zinc-200 bg-zinc-100 text-zinc-700'
    : 'border-sky-200 bg-sky-50 text-sky-700';
}

export function SprintTimeline({
  sprints,
  currentSprintId,
  selectedSprintId,
  onSprintSelect,
}: SprintTimelineProps) {
  return (
    <section className="rounded-md border border-zinc-200 bg-white p-6">
      <div className="mb-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Execution Timeline</p>
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-zinc-950">user_observable_change 중심 타임라인</h2>
      </div>

      {sprints.length === 0 ? (
        <p className="text-sm text-zinc-500">표시할 스프린트가 없습니다.</p>
      ) : (
        <div className="space-y-4">
          {sprints.map((sprint, index) => {
            const isCurrent = sprint.sprint_id === currentSprintId;
            const isSelected = sprint.sprint_id === selectedSprintId;
            const mainMessage = sprint.user_observable_change?.trim()
              || sprint.summary?.trim()
              || sprint.sprint_purpose?.trim()
              || '요약이 없습니다.';

            return (
              <div key={sprint.sprint_id} className="relative">
                {index > 0 ? <div className="absolute -top-4 left-4 h-4 border-l border-zinc-200" aria-hidden="true" /> : null}
                <button
                  type="button"
                  onClick={() => onSprintSelect(sprint.sprint_id)}
                  className={`flex w-full gap-4 rounded-md border p-5 text-left transition-colors ${
                    isSelected ? 'border-zinc-950 bg-zinc-50' : 'border-zinc-200 bg-white hover:bg-zinc-50'
                  }`}
                >
                  <div className="pt-1">
                    <span className={`block h-2.5 w-2.5 rounded-full ${isCurrent ? 'bg-zinc-950' : 'bg-zinc-300'}`} aria-hidden="true" />
                  </div>

                  <div className="min-w-0 flex-1 space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-zinc-950">{sprint.sprint_id}</span>
                        {isCurrent ? (
                          <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">Current</Badge>
                        ) : null}
                        <Badge variant="outline" className={sprintKindClass(sprint.sprint_kind)}>
                          {sprintKindLabel(sprint.sprint_kind)}
                        </Badge>
                        <Badge variant="outline" className={phaseBadgeClass(resolveSprintPhase(sprint.status))}>
                          {resolveSprintPhase(sprint.status)}
                        </Badge>
                        <StatusBadge status={sprint.status ?? 'unknown'} />
                      </div>

                      {sprint.integrationReview?.force_wire_recommended ? (
                        <span
                          className="inline-flex items-center gap-1 text-xs font-semibold text-red-600"
                          title={`force_wire_recommended · ${(sprint.integrationReview?.ratios?.new_island ?? 0).toFixed(2)}`}
                        >
                          <AlertTriangle className="h-4 w-4" />
                          wire 권고
                        </span>
                      ) : null}
                    </div>

                    <div className="max-w-4xl">
                      <p className="text-base font-semibold leading-7 text-zinc-950">{mainMessage}</p>
                      <p className="mt-2 text-sm leading-6 text-zinc-500">{formatSprintPeriod(sprint)}</p>
                    </div>
                  </div>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
