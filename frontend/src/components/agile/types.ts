export interface AgileSessionSummary {
  id: string;
  status: string;
  current_sprint: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AgileSessionMeta {
  id?: string;
  status?: string;
  current_sprint?: number | string;
  created_at?: string;
  updated_at?: string;
  steering_every?: number;
  queue?: string[];
  refs?: string[];
  deferred_dod_count?: number;
}

export interface SprintGoalTestResults {
  passed?: number;
  failed?: number;
  summary?: string;
  test_intent?: string;
  test_strategy?: string;
  test_flow?: string[];
}

export interface SprintGoalDiff {
  files_changed?: number;
  insertions?: number;
  deletions?: number;
  commits?: string[];
}

export interface SprintGoalEvidence {
  screenshots?: string[];
  test_results?: SprintGoalTestResults;
  diff?: SprintGoalDiff;
}

export interface SprintGoal {
  goal: string;
  status: string;
  change_summary: string;
  evidence?: SprintGoalEvidence;
}

export interface IntegrationReviewVerdict {
  new_island_threshold?: number;
  exceeded?: boolean;
  force_wire_recommended?: boolean;
  escape_hatch_used?: boolean;
  escape_reason?: string | null;
}

export interface IntegrationReview {
  verdict?: IntegrationReviewVerdict | string | null;
  ratios?: {
    new_island?: number;
  };
  files?: {
    new_island?: number | string[];
  };
  force_wire_recommended?: boolean;
}

export interface AlignmentCheck {
  verdict: 'aligned' | 'drift_warning' | 'objective_stale' | 'unknown';
  raw_excerpt?: string;
}

export interface AgileSprint {
  sprint_id: string;
  status?: string;
  sprint_kind?: 'foundational' | 'user_observable' | string;
  user_observable_change?: string | null;
  stories?: string[];
  period?: string;
  started_at?: string;
  ended_at?: string;
  start_date?: string;
  end_date?: string;
  planned?: string[];
  completed?: string[];
  generated?: {
    pln?: string[];
    req?: string[];
  };
  timestamp?: string;
  summary?: string;
  outcome?: string;
  sprint_purpose?: string;
  selection_reason?: string;
  target_dod?: string;
  target_dod_text?: string;
  previous_direction?: string;
  result_md?: string;
  sprint_goals?: SprintGoal[];
  integrationReview?: IntegrationReview | null;
  alignmentCheck?: AlignmentCheck | null;
}

export interface AgileSessionDetail {
  session: AgileSessionMeta;
  sprints: AgileSprint[];
}

export interface RetrospectiveFailedItem {
  item?: string;
  tried_approach?: string;
  failure_reason?: string;
}

export interface AgileRetrospective {
  sprint_id?: string;
  status?: string;
  succeeded?: string[];
  failed?: RetrospectiveFailedItem[];
  velocity?: {
    planned?: number;
    completed?: number;
    rate?: number;
  };
  known_limitations?: string;
  lessons_learned?: string;
  direction?: string;
  timestamp?: string;
}

export interface ObjectiveParsedDod {
  dod: string;
  status: string;
  priority: string;
  anchorText?: string | null;
  contentText?: string | null;
}

export interface ObjectiveParsedSection {
  key: string;
  title: string;
  content: string;
}

export interface ObjectiveParsedContent {
  dods: ObjectiveParsedDod[];
  sections: ObjectiveParsedSection[];
}

export interface ObjectiveResponsePayload {
  content: string | null;
  path: string;
  revision?: string | null;
  parsed?: ObjectiveParsedContent | null;
}

export interface ResultDetailFile {
  name: string;
}

export interface SprintWhyItem {
  label: string;
  value: string;
}

export type MainTabValue = 'overview' | 'sprint-detail' | 'objective';
