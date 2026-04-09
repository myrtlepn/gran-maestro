import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useDispatchStream } from '@/hooks/useDispatchStream';

type DispatchPanelProps = {
  projectId: string;
  staleThresholdSec?: number;
};

function formatHeartbeatAge(ageSec: number): string {
  if (!Number.isFinite(ageSec) || ageSec < 0) return '0s';
  if (ageSec < 60) return `${ageSec}s`;
  return `${Math.floor(ageSec / 60)}m`;
}

function formatAsOf(value: string): string {
  if (!value) return '연결 대기 중';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString(undefined, { hour12: false });
}

export function DispatchPanel({ projectId, staleThresholdSec = 60 }: DispatchPanelProps) {
  const { status, items, asOf } = useDispatchStream(projectId, staleThresholdSec);
  const isInitialLoading = status === 'connecting' && items.length === 0;

  return (
    <Card className="bg-white dark:bg-card">
      <CardHeader className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-base">Dispatch Runs</CardTitle>
          <span className="text-xs text-muted-foreground">
            {items.length} active · {status}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          stale threshold {staleThresholdSec}s · updated {formatAsOf(asOf)}
        </p>
      </CardHeader>
      <CardContent>
        {isInitialLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500 dark:border-border dark:text-muted-foreground">
            진행 중인 dispatch가 없습니다.
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((item) => (
              <div
                key={item.task_id}
                className={`rounded-xl border p-4 ${
                  item.stale
                    ? 'border-red-300 bg-red-50/40 dark:border-red-900/50 dark:bg-red-950/20'
                    : 'border-slate-200 dark:border-border'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-900 dark:text-foreground">{item.task_id}</p>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 font-medium text-blue-700 dark:border-blue-900/50 dark:bg-blue-900/30 dark:text-blue-200">
                      {item.provider}
                    </span>
                    {item.stale && (
                      <span className="inline-flex items-center rounded-full border border-red-200 bg-red-50 px-2 py-0.5 font-medium text-red-700 dark:border-red-900/50 dark:bg-red-900/30 dark:text-red-200">
                        stale
                      </span>
                    )}
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <span>phase: {item.phase}</span>
                  <span>heartbeat: {formatHeartbeatAge(item.heartbeat_age_sec)}</span>
                  {item.model && <span>model: {item.model}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
