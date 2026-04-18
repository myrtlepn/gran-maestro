import { Badge } from '@/components/ui/badge';
import type { AgileSprint, ObjectiveParsedDod } from './types';
import { extractDodIds, isDodDoneStatus } from './utils';

interface AlignmentViewProps {
  dods: ObjectiveParsedDod[];
  sprints: AgileSprint[];
  onSelectSprint?: (sprintId: string) => void;
}

function verdictTone(verdict: AgileSprint['alignmentCheck'] extends infer T ? T extends { verdict: infer V } ? V : never : never) {
  switch (verdict) {
    case 'aligned':
      return { dot: 'bg-emerald-500', text: '정합', tint: 'bg-emerald-50' };
    case 'drift_warning':
      return { dot: 'bg-amber-500', text: 'Drift', tint: 'bg-amber-50' };
    case 'objective_stale':
      return { dot: 'bg-red-500', text: 'Stale', tint: 'bg-red-50' };
    default:
      return { dot: 'bg-zinc-300', text: 'Unknown', tint: 'bg-white' };
  }
}

export function AlignmentView({ dods, sprints, onSelectSprint }: AlignmentViewProps) {
  if (dods.length === 0) {
    return (
      <section className="rounded-md border border-zinc-200 bg-white p-6">
        <h2 className="text-lg font-semibold tracking-tight text-zinc-950">Alignment View</h2>
        <p className="mt-3 text-sm text-zinc-500">Objective DoD를 찾지 못해 alignment matrix를 표시할 수 없습니다.</p>
      </section>
    );
  }

  return (
    <section className="rounded-md border border-zinc-200 bg-white p-6">
      <div className="mb-5 flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Alignment View</p>
          <h2 className="mt-1 text-lg font-semibold tracking-tight text-zinc-950">DoD x alignment-check</h2>
        </div>
        <p className="text-xs text-zinc-500">각 셀에 마우스를 올리면 verdict와 원문 일부를 볼 수 있습니다.</p>
      </div>

      <div className="overflow-x-auto rounded-md border border-zinc-200">
        <table className="min-w-full border-collapse text-left">
          <thead className="bg-zinc-50">
            <tr>
              <th className="w-[280px] border-b border-zinc-200 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">DoD Item</th>
              {sprints.map((sprint) => (
                <th key={sprint.sprint_id} className="border-b border-l border-zinc-200 px-4 py-3 text-center text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
                  {sprint.sprint_id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dods.map((dod) => (
              <tr key={dod.dod} className="border-b border-zinc-100 last:border-b-0">
                <td className="px-4 py-4 align-top">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-zinc-950">{dod.dod}</span>
                      <Badge variant="outline" className={isDodDoneStatus(dod.status) ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-zinc-200 bg-zinc-50 text-zinc-600'}>
                        {dod.status}
                      </Badge>
                    </div>
                    <p className="text-sm leading-6 text-zinc-600">{(dod.contentText ?? dod.anchorText ?? '').trim() || '설명 없음'}</p>
                  </div>
                </td>

                {sprints.map((sprint) => {
                  const targetsDod = extractDodIds(sprint.target_dod).includes(dod.dod)
                    || extractDodIds(sprint.target_dod_text).includes(dod.dod);
                  const verdict = targetsDod ? sprint.alignmentCheck?.verdict ?? 'unknown' : 'unknown';
                  const tone = verdictTone(verdict);
                  const tooltip = targetsDod
                    ? `${verdict} · ${(sprint.alignmentCheck?.raw_excerpt ?? 'alignment-check 없음').slice(0, 200)}`
                    : `${sprint.sprint_id}에서 이 DoD를 직접 다루지 않았습니다.`;

                  return (
                    <td key={`${dod.dod}-${sprint.sprint_id}`} className={`border-l border-zinc-200 px-4 py-4 text-center ${targetsDod ? tone.tint : 'bg-white'}`}>
                      <button
                        type="button"
                        title={tooltip}
                        className="mx-auto flex min-w-[56px] items-center justify-center"
                        onClick={() => onSelectSprint?.(sprint.sprint_id)}
                      >
                        <span className={`h-2.5 w-2.5 rounded-full ${tone.dot}`} aria-label={`${dod.dod}-${sprint.sprint_id}-${verdict}`} />
                      </button>
                      <div className="mt-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-500">{tone.text}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
