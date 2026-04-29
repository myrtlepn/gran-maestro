import { apiFetch } from '@/hooks/useApi';

export type PolicyEvent = {
  type?: string;
  timestamp?: string;
  rule_id?: string;
  tool?: string;
  tool_name?: string;
  reason?: string;
  message?: string;
};

export type PolicyTimelineRow = {
  event?: PolicyEvent;
  timestamp?: string;
  session_id?: string;
  seq?: number;
};

export type PolicyAllowlistEntry = {
  id?: string;
  tool?: string;
  args_pattern?: string;
  expires_at?: string | null;
  created_at?: string;
  added_by_tty?: boolean;
};

export async function fetchTimeline(session?: string, limit = 100, projectId?: string) {
  const params = new URLSearchParams();
  if (session) params.set('session', session);
  params.set('limit', String(limit));
  return apiFetch<PolicyTimelineRow[]>(`/api/policy/timeline?${params.toString()}`, projectId);
}

export async function fetchRules(projectId?: string) {
  return apiFetch<Record<string, number>>('/api/policy/rules', projectId);
}

export async function fetchAllowlist(projectId?: string) {
  return apiFetch<PolicyAllowlistEntry[]>('/api/policy/allowlist', projectId);
}
