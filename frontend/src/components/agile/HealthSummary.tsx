import { AlertTriangle, TrendingUp } from 'lucide-react';

interface HealthSummaryProps {
  dodProgress: number;
  openIssuesCount: number;
  newIslandRatio: number;
}

function ratioTone(ratio: number): string {
  if (ratio >= 0.2) return 'border-red-200 bg-red-50 text-red-700';
  if (ratio >= 0.1) return 'border-amber-200 bg-amber-50 text-amber-700';
  return 'border-emerald-200 bg-emerald-50 text-emerald-700';
}

export function HealthSummary({ dodProgress, openIssuesCount, newIslandRatio }: HealthSummaryProps) {
  const progressWidth = `${Math.max(0, Math.min(100, dodProgress))}%`;

  return (
    <section className="rounded-md border border-zinc-200 bg-white p-6">
      <div className="mb-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Health Summary</p>
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-zinc-950">프로젝트 건강도</h2>
      </div>

      <div className="space-y-7">
        <div>
          <div className="mb-2 flex items-end justify-between gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">DoD Progress</span>
            <span className="text-2xl font-black tracking-tight text-zinc-950">{dodProgress}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-zinc-200">
            <div className="h-full bg-zinc-950 transition-all" style={{ width: progressWidth }} />
          </div>
        </div>

        <div>
          <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">미해결 이슈</span>
          <div className="mt-2 text-4xl font-black tracking-tight text-zinc-950">{openIssuesCount}</div>
        </div>

        <div className="border-t border-zinc-200 pt-4">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">new_island_ratio</span>
            <span className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold ${ratioTone(newIslandRatio)}`}>
              {newIslandRatio >= 0.2 ? <AlertTriangle className="h-3.5 w-3.5" /> : <TrendingUp className="h-3.5 w-3.5" />}
              {newIslandRatio.toFixed(2)}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
