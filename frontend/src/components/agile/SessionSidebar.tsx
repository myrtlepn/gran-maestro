import { ScrollArea } from '@/components/ui/scroll-area';
import { RefreshButton } from '@/components/shared/RefreshButton';
import { StatusBadge } from '@/components/shared/StatusBadge';
import type { AgileSessionSummary } from './types';
import { formatTime, toSprintId } from './utils';

interface SessionSidebarProps {
  sessions: AgileSessionSummary[];
  selectedSessionId: string | null;
  sessionsError: string | null;
  isRefreshing: boolean;
  onRefresh: () => void;
  onSelectSession: (sessionId: string) => void;
}

export function SessionSidebar({
  sessions,
  selectedSessionId,
  sessionsError,
  isRefreshing,
  onRefresh,
  onSelectSession,
}: SessionSidebarProps) {
  return (
    <div className="flex min-h-0 flex-col border-r border-zinc-200 bg-zinc-50">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-zinc-900">Sessions</h2>
          <p className="mt-1 text-xs text-zinc-500">Agile Precision</p>
        </div>
        <RefreshButton onClick={onRefresh} isRefreshing={isRefreshing} />
      </div>

      {sessionsError ? (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">{sessionsError}</div>
      ) : null}

      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-2 p-3">
          {sessions.map((session) => {
            const isSelected = selectedSessionId === session.id;
            return (
              <button
                key={session.id}
                type="button"
                onClick={() => onSelectSession(session.id)}
                className={`w-full rounded-md border px-3 py-3 text-left transition-colors ${
                  isSelected ? 'border-zinc-950 bg-white' : 'border-zinc-200 bg-transparent hover:bg-white'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold text-zinc-900">{session.id}</span>
                  <StatusBadge status={session.status} />
                </div>
                <p className="mt-2 text-xs text-zinc-500">
                  current sprint: {toSprintId(session.current_sprint) ?? `S${String(session.current_sprint ?? 0).padStart(2, '0')}`}
                </p>
                <p className="mt-1 text-[11px] text-zinc-400">
                  updated: {formatTime(session.updated_at ?? session.created_at)}
                </p>
              </button>
            );
          })}

          {sessions.length === 0 ? <p className="px-1 py-2 text-xs text-zinc-500">세션이 없습니다.</p> : null}
        </div>
      </ScrollArea>
    </div>
  );
}
