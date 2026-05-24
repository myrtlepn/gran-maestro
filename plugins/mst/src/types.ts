/**
 * Gran Maestro Dashboard Types
 */

export interface GranMaestroConfig {
  dashboard_port?: number;
  [key: string]: unknown;
}

export interface ConfigResponse {
  merged: GranMaestroConfig;
  overrides: GranMaestroConfig;
  defaults: GranMaestroConfig;
}

export interface ReviewSummary {
  iteration: number;
  status: "reviewing" | "gap_fixing" | "passed" | "limit_reached";
}

export interface RequestMeta {
  id: string;
  title?: string;
  status?: string;
  phase?: number;
  blockedBy?: string[];
  createdAt?: string;
  linked_plan?: string | null;
  review_summary?: ReviewSummary | null;
  [key: string]: unknown;
}

export interface PlanMeta {
  id: string;
  title?: string;
  status?: string;
  created_at?: string;
  linked_requests?: string[];
  content?: string | null;
  [key: string]: unknown;
}

export interface DebugMeta {
  id: string;
  issue?: string;
  focus?: string;
  status?: string;
  created_at?: string;
  content?: string | null;
  [key: string]: unknown;
}

export interface ExploreMeta {
  id: string;
  goal?: string;
  focus?: string;
  status?: string;
  created_at?: string;
  content?: string | null;
  [key: string]: unknown;
}

export interface SessionParticipant {
  key: string;
  role?: string;
  perspective?: string;
  type?: string;
  status?: string;
  provider?: string;
}

export interface TaskMeta {
  id: string;
  requestId: string;
  status?: string;
  duration?: number | null;
  started_at?: string;
  completed_at?: string;
  agent?: string;
  [key: string]: unknown;
}

export interface SSEEvent {
  type: string;
  requestId?: string;
  taskId?: string;
  sessionId?: string;
  planId?: string;
  projectId?: string;
  designId?: string;
  captureId?: string;
  data: unknown;
}

export interface CaptureMeta {
  id: string;
  status: "pending" | "selected" | "consumed" | "done" | "cancelled" | "archived";
  created_at: string;
  url: string;
  selector: string | null;
  rect:
    | {
      x: number;
      y: number;
      width: number;
      height: number;
    }
    | null;
  screenshot_path: string | null;
  memo: string;
  tags: string[];
  html_snapshot: string | null;
  css_path: string | null;
  component_name: string | null;
  source_path: string | null;
  linked_plan: string | null;
  linked_request: string | null;
  ttl_expires_at: string | null;
  ttl_warned_at: string | null;
  consumed_at: string | null;
  mode: "immediate" | "batch";
  [key: string]: unknown;
}

export interface CaptureCreatePayload {
  url: string;
  selector: string;
  rect: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  screenshot_data: string | null;
  memo: string;
  tags: string[];
  css_path: string;
  html_snapshot: string | null;
  mode: "immediate" | "batch";
  component_name: string | null;
  source_path: string | null;
}

export interface CaptureUpdatePayload {
  status: "pending" | "selected" | "consumed" | "done" | "cancelled";
}

export interface IntentMeta {
  id: string;
  feature?: string;
  situation?: string;
  motivation?: string;
  goal?: string;
  linked_req?: string | null;
  linked_plan?: string | null;
  related_intent?: string[];
  tags?: string[];
  files?: string[];
  created_at?: string;
  body?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface IdeationSession {
  id: string;
  topic: string;
  focus?: string;
  status: string;
  created_at?: string;
  opinions?: Record<string, { status: string }>;
  participants?: SessionParticipant[];
  roles?: Record<
    string,
    { perspective: string; type: string; status: string; provider?: string }
  >;
  participant_config?: Record<string, number>;
  critics?: Record<string, { status: string; provider?: string }>;
  critic_count?: number;
  [key: string]: unknown;
}

export interface DiscussionSession {
  id: string;
  topic: string;
  source_ideation?: string;
  focus?: string;
  status: string;
  max_rounds: number;
  current_round: number;
  created_at?: string;
  participants?: SessionParticipant[];
  roles?: Record<
    string,
    { perspective: string; type: string; status: string; provider?: string }
  >;
  rounds?: Array<{
    round: number;
    divergences_before: number;
    divergences_after: number;
    status: string;
    responses?: Record<string, string | null>;
    critiques?: Record<string, string | null>;
  }>;
  critics?: Record<string, { status: string; provider?: string }>;
  [key: string]: unknown;
}

export interface Project {
  id: string;
  name: string;
  path: string;
  registered_at: string;
}

export interface Registry {
  projects: Project[];
}

export interface DesignStyle {
  name: string;
  slug: string;
  screens: string[];
}

export interface DesignScreen {
  id: string;
  stitch_screen_id?: string;
  parent_screen_id?: string | null;
  title?: string;
  url?: string;
  image_url?: string | null;
  html_file?: string | null;
  style?: string | null;
  created_at?: string;
  status?: string;
  [key: string]: unknown;
}

export interface DesignSession {
  id: string;
  title?: string;
  status: string;
  created_at?: string;
  linked_plan?: string | null;
  linked_req?: string | null;
  stitch_project_id?: string | null;
  revision?: number;
  editing_by?: string | null;
  editing_at?: string | null;
  screens?: DesignScreen[];
  styles?: DesignStyle[];
  [key: string]: unknown;
}

export interface PresetMeta {
  id: string;
  name: string;
  description?: string;
  category?: string;
  wizardCategory?: "claude" | "claude-codex" | "claude-gemini" | "full-team";
  tier?: "performance" | "efficient" | "budget";
  providers?: string[];
  file?: string;
}

export interface PresetListResponse {
  builtin: PresetMeta[];
  user: PresetMeta[];
  categories: Record<string, { label: string; description: string }>;
  tiers: Record<string, { label: string; description: string }>;
}

export interface PresetDiffChange {
  path: string;
  from: unknown;
  to: unknown;
}
