import { useCallback, useEffect, useMemo, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { useAppContext } from '@/context/AppContext';
import { fetchAllowlist, fetchRules, fetchTimeline, type PolicyAllowlistEntry, type PolicyEvent, type PolicyTimelineRow } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';

type AllowlistStatus = 'active' | 'expiring' | 'expired' | 'never';

function eventOf(row: PolicyTimelineRow): PolicyEvent {
  return row.event ?? row;
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' });
}

function eventTimestamp(row: PolicyTimelineRow): string {
  return eventOf(row).timestamp ?? row.timestamp ?? '';
}

function eventRule(row: PolicyTimelineRow): string {
  const event = eventOf(row);
  return event.rule_id || event.tool || event.tool_name || 'unknown';
}

function eventNote(row: PolicyTimelineRow): string {
  const event = eventOf(row);
  return event.reason || event.message || '-';
}

function allowlistStatus(entry: PolicyAllowlistEntry): AllowlistStatus {
  if (!entry.expires_at) return 'never';

  const expiresAt = new Date(entry.expires_at).getTime();
  if (Number.isNaN(expiresAt)) return 'active';

  const remainingMs = expiresAt - Date.now();
  if (remainingMs <= 0) return 'expired';
  return remainingMs <= 24 * 60 * 60 * 1000 ? 'expiring' : 'active';
}

function statusLabel(status: AllowlistStatus): string {
  switch (status) {
    case 'expired':
      return '만료';
    case 'expiring':
      return '만료 임박';
    case 'never':
      return '무기한';
    case 'active':
    default:
      return '활성';
  }
}

function statusBadgeVariant(status: AllowlistStatus): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'expired') return 'destructive';
  if (status === 'expiring') return 'outline';
  if (status === 'never') return 'secondary';
  return 'default';
}

export function PolicyView() {
  const { projectId } = useAppContext();
  const [timeline, setTimeline] = useState<PolicyTimelineRow[]>([]);
  const [rules, setRules] = useState<Record<string, number>>({});
  const [allowlist, setAllowlist] = useState<PolicyAllowlistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sortedRules = useMemo(
    () => Object.entries(rules).sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0])),
    [rules],
  );

  const loadPolicy = useCallback(async (isRefresh = false) => {
    if (!projectId) return;
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    try {
      const [timelineData, rulesData, allowlistData] = await Promise.all([
        fetchTimeline(undefined, 100, projectId),
        fetchRules(projectId),
        fetchAllowlist(projectId),
      ]);
      setTimeline(Array.isArray(timelineData) ? timelineData : []);
      setRules(rulesData && typeof rulesData === 'object' ? rulesData : {});
      setAllowlist(Array.isArray(allowlistData) ? allowlistData : []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Policy 데이터를 불러오지 못했습니다');
      setTimeline([]);
      setRules({});
      setAllowlist([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadPolicy();
  }, [loadPolicy]);

  return (
    <div className="h-full flex flex-col bg-muted/20">
      <div className="border-b bg-background px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="h-10 w-10 rounded-md bg-primary/10 text-primary flex items-center justify-center shrink-0">
            <ShieldAlert className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight">Policy</h1>
            <p className="text-sm text-muted-foreground">차단 타임라인, 룰별 히트 빈도, 만료형 allowlist</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => loadPolicy(true)} disabled={refreshing}>
          {refreshing ? '새로고침 중' : '새로고침'}
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-6 space-y-6">
          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-lg">차단 타임라인</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className="h-40 w-full" />
              ) : timeline.length === 0 ? (
                <div className="text-sm text-muted-foreground py-8 text-center">차단 이벤트가 없습니다.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-2 pr-4 font-medium">시간</th>
                        <th className="py-2 pr-4 font-medium">세션</th>
                        <th className="py-2 pr-4 font-medium">이벤트</th>
                        <th className="py-2 pr-4 font-medium">룰</th>
                        <th className="py-2 font-medium">비고</th>
                      </tr>
                    </thead>
                    <tbody>
                      {timeline.map((row, index) => {
                        const event = eventOf(row);
                        return (
                          <tr key={`${row.session_id ?? 'session'}-${row.seq ?? index}`} className="border-b last:border-0">
                            <td className="py-2 pr-4 whitespace-nowrap">{formatDateTime(eventTimestamp(row))}</td>
                            <td className="py-2 pr-4 font-mono text-xs">{row.session_id ?? '-'}</td>
                            <td className="py-2 pr-4">
                              <Badge variant={event.type === 'core_block' ? 'destructive' : 'secondary'}>
                                {event.type ?? 'policy_block'}
                              </Badge>
                            </td>
                            <td className="py-2 pr-4 font-mono text-xs">{eventRule(row)}</td>
                            <td className="py-2 text-muted-foreground">{eventNote(row)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-lg">룰별 히트 빈도</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className="h-32 w-full" />
              ) : sortedRules.length === 0 ? (
                <div className="text-sm text-muted-foreground py-8 text-center">집계된 룰 히트가 없습니다.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-2 pr-4 font-medium">룰</th>
                        <th className="py-2 font-medium text-right">히트</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedRules.map(([ruleId, count]) => (
                        <tr key={ruleId} className="border-b last:border-0">
                          <td className="py-2 pr-4 font-mono text-xs">{ruleId}</td>
                          <td className="py-2 text-right font-semibold">{count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-lg">만료형 Allowlist</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className="h-32 w-full" />
              ) : allowlist.length === 0 ? (
                <div className="text-sm text-muted-foreground py-8 text-center">등록된 allowlist 항목이 없습니다.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-2 pr-4 font-medium">ID</th>
                        <th className="py-2 pr-4 font-medium">Tool</th>
                        <th className="py-2 pr-4 font-medium">Args Pattern</th>
                        <th className="py-2 pr-4 font-medium">만료 시간</th>
                        <th className="py-2 font-medium">상태</th>
                      </tr>
                    </thead>
                    <tbody>
                      {allowlist.map((entry, index) => {
                        const status = allowlistStatus(entry);
                        return (
                          <tr
                            key={entry.id ?? `${entry.tool ?? 'tool'}-${index}`}
                            className={cn(
                              'border-b last:border-0',
                              status === 'expiring' && 'bg-amber-500/10',
                              status === 'expired' && 'opacity-60',
                            )}
                          >
                            <td className="py-2 pr-4 font-mono text-xs">{entry.id ?? '-'}</td>
                            <td className="py-2 pr-4">{entry.tool ?? '-'}</td>
                            <td className="py-2 pr-4 font-mono text-xs">{entry.args_pattern ?? '*'}</td>
                            <td className="py-2 pr-4 whitespace-nowrap">{formatDateTime(entry.expires_at)}</td>
                            <td className="py-2">
                              <Badge variant={statusBadgeVariant(status)}>{statusLabel(status)}</Badge>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
    </div>
  );
}
