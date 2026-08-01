import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useDispatchStream, type DispatchStreamItem } from '@/hooks/useDispatchStream';

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

export function formatDispatchExitCode(exitCode: number | null): string {
  return exitCode === null ? 'N/A' : String(exitCode);
}

function recordText(value: Record<string, unknown> | null, key: string): string {
  const field = value?.[key];
  if (typeof field === 'string' && field.trim()) return field;
  if (typeof field === 'number' && Number.isFinite(field)) return String(field);
  return '';
}

function formatFallbackLink(item: DispatchStreamItem): string {
  if (item.fallback_from) {
    return `${item.fallback_from} → ${item.fallback_to || item.attempt_id || 'current'}`;
  }
  if (item.fallback_to) {
    return `${item.attempt_id || 'current'} → ${item.fallback_to}`;
  }
  return '';
}

function formatReconciliationAction(action: Record<string, unknown> | null): string {
  if (!action) return '';
  const identity = recordText(action, 'action_id') || recordText(action, 'kind') || recordText(action, 'lookup_key');
  const status = recordText(action, 'status');
  return [identity, status].filter(Boolean).join(' · ') || 'pending';
}

export function DispatchRunCard({ item }: { item: DispatchStreamItem }) {
  const fallbackLink = formatFallbackLink(item);
  const reconciliation = formatReconciliationAction(item.reconciliation_action);

  return (
    <div
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
          <span className="inline-flex items-center rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 font-medium text-violet-700 dark:border-violet-900/50 dark:bg-violet-900/30 dark:text-violet-200">
            {item.execution_transport}
          </span>
          {item.requested_launch_surface === 'orca' && (
            <span className="inline-flex items-center rounded-full border border-cyan-200 bg-cyan-50 px-2 py-0.5 font-medium text-cyan-700 dark:border-cyan-900/50 dark:bg-cyan-900/30 dark:text-cyan-200">
              orca · {item.launch_surface === 'orca'
                ? item.orca_launch_status || item.launch_surface_status
                : `fallback · ${item.launch_surface_status}`}
            </span>
          )}
          {item.stale && (
            <span className="inline-flex items-center rounded-full border border-red-200 bg-red-50 px-2 py-0.5 font-medium text-red-700 dark:border-red-900/50 dark:bg-red-900/30 dark:text-red-200">
              stale
            </span>
          )}
          {item.reconciliation_invariant_gap && (
            <span className="inline-flex items-center rounded-full border border-red-200 bg-red-50 px-2 py-0.5 font-medium text-red-700 dark:border-red-900/50 dark:bg-red-900/30 dark:text-red-200">
              reconciliation invariant gap
            </span>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>phase: {item.phase}</span>
        <span>heartbeat: {formatHeartbeatAge(item.heartbeat_age_sec)}</span>
        {item.model && <span>model: {item.model}</span>}
        <span>exit: {formatDispatchExitCode(item.exit_code)}</span>
        <span>completion: {item.completion_signal || 'N/A'}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 break-all text-[11px] text-muted-foreground">
        {item.attempt_id && <span>attempt: {item.attempt_id}</span>}
        <span>route: {item.route_reason || 'N/A'}</span>
        <span>provider task: {item.provider_task_id || 'N/A'}</span>
        {fallbackLink && <span>fallback: {fallbackLink}</span>}
        {reconciliation && <span>reconcile: {reconciliation}</span>}
      </div>
    </div>
  );
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
              <DispatchRunCard key={`${item.task_id}:${item.attempt_id}`} item={item} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
