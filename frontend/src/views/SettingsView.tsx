import React, { useEffect, useState } from 'react';
import { useAppContext } from '@/context/AppContext';
import { apiFetch } from '@/hooks/useApi';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent } from '@/components/ui/card';
import { FoldVertical, Globe, RefreshCcw, Replace, Save, UnfoldVertical, Wand2, Bookmark } from 'lucide-react';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import type { PresetDiffChange } from '../../../src/types';
import { SETTING_DESCRIPTIONS, getDescription, getOptions } from '@/config/settingDescriptions';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SettingsFindReplace } from '@/components/shared/SettingsFindReplace';
import { TagInput } from '@/components/shared/TagInput';
import { SetupWizardModal } from '@/components/shared/SetupWizardModal';
import { PresetManagerModal } from '@/components/shared/PresetManagerModal';
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from '@/components/ui/accordion';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

const HIDDEN_FIELDS = ['version', 'plugin_name', 'branding'];
const BEHAVIOR_SECTIONS = ['workflow', 'auto_mode', 'concurrency', 'review', 'plan_review'];
const AGENT_PROVIDERS = ['codex', 'gemini', 'claude'] as const;

type AgentProvider = typeof AGENT_PROVIDERS[number];
type AgentTier = 'premium' | 'economy';

type WorkflowNodeKind = 'agent-matrix' | 'role-summary' | 'info';

type WorkflowNode = {
  id: string;
  label: string;
  description: string;
  kind: WorkflowNodeKind;
  agentsPath?: string[];
  rolesPath?: string[];
  enabledPath?: string[];
  configPath?: string[];
};

type WorkflowPhase = {
  id: string;
  title: string;
  subtitle: string;
  nodes: WorkflowNode[];
};

type WorkflowAgentRow = {
  provider: AgentProvider;
  count: number;
  tier: AgentTier;
  editable: boolean;
  mixedTier?: boolean;
};

type WorkflowRoleDetailRow = {
  name: string;
  enabled: boolean;
  agent: string;
  tier: string;
  tierPath: string[];
  agentPath: string[];
};

type WorkflowInfoFieldRow = {
  key: string;
  fullPath: string[];
  value: any;
  description?: string;
  options?: string[];
};

type WorkflowModelProviderRow = {
  provider: string;
  premium: string;
  economy: string;
  defaultTier: string;
};

type WorkflowModelRoleAssignmentRow = {
  role: string;
  provider: string;
  tier: string;
  tierPath: string[];
  providerPath: string[];
};

const MODEL_ROLE_DISPLAY_ORDER = ['pm_conductor', 'architect', 'developer', 'reviewer', 'developer_claude'] as const;
const ADVERSARIAL_ATTACK_SURFACE_OPTIONS = [
  'auth_permissions',
  'data_integrity',
  'rollback_safety',
  'race_conditions',
  'null_timeout',
  'version_skew',
  'observability',
] as const;

const WORKFLOW_INFO_FOCUS_FIELDS: Partial<Record<WorkflowNode['id'], string[]>> = {
  stitch: ['enabled', 'auto_detect', 'auto_trigger', 'project_id', 'model_id', 'failure_policy'],
  code_review: ['enabled', 'agents', 'agent_roster', 'parallel', 'use_native_review', 'native_review_prompt'],
  collaborative_debug: ['finding_char_limit', 'merge_wait_ms', 'auto_trigger_from_request'],
  'workflow.feedback': ['max_feedback_rounds'],
  'models.providers': ['codex', 'gemini', 'claude'],
  'models.roles': ['pm_conductor', 'architect', 'developer', 'reviewer', 'developer_claude'],
  auto_mode: ['plan', 'request', 'review', 'confidence_threshold', 'max_review_iterations'],
  intent_fidelity: ['enabled', 'mode', 'exclude_dirs'],
  plan_qa_presets: ['test_strategy', 'loop_exit', 'loop_exit_n'],
  agile: [
    'steering_every',
    'drift_threshold',
    'drift_count_trigger',
    'no_diff_count_trigger',
    'convergence_threshold_abs',
    'convergence_threshold_trend',
    'soft_limit_small',
    'soft_limit_large',
    'round_history_max_summary_lines',
  ],
  reference: ['cache_ttl_days', 'cutoff_threshold_months', 'auto_search', 'max_searches_per_step'],
  test_enforcement: ['enabled', 'backend_tdd', 'web_execution_test', 'exempt_patterns', 'require_exemption_reason'],
};

const WORKFLOW_PHASES: WorkflowPhase[] = [
  {
    id: 'phase-0',
    title: 'Models',
    subtitle: '모델/역할',
    nodes: [
      {
        id: 'models.providers',
        label: 'models.providers',
        description: 'Provider별 premium/economy 모델 및 기본 tier',
        kind: 'info',
        configPath: ['models', 'providers'],
      },
      {
        id: 'models.roles',
        label: 'models.roles',
        description: 'Role별 provider/tier 매핑',
        kind: 'info',
        configPath: ['models', 'roles'],
      },
      {
        id: 'auto_mode',
        label: 'auto_mode',
        description: '자동 실행 모드 설정',
        kind: 'info',
        configPath: ['auto_mode'],
      },
    ],
  },
  {
    id: 'phase-1',
    title: 'Phase 1',
    subtitle: '분석/계획',
    nodes: [
      {
        id: 'exploration',
        label: 'exploration',
        description: '탐색 단계 에이전트 구성',
        kind: 'agent-matrix',
        agentsPath: ['explore', 'agents'],
      },
      {
        id: 'ideation',
        label: 'ideation',
        description: '아이디어 수렴 단계 에이전트 구성',
        kind: 'agent-matrix',
        agentsPath: ['ideation', 'agents'],
      },
      {
        id: 'discussion',
        label: 'discussion',
        description: '토론 단계 에이전트 구성',
        kind: 'agent-matrix',
        agentsPath: ['discussion', 'agents'],
      },
      {
        id: 'phase1_exploration',
        label: 'phase1_exploration',
        description: '탐색 역할별 agent/tier 배정',
        kind: 'role-summary',
        rolesPath: ['phase1_exploration', 'roles'],
      },
      {
        id: 'intent_fidelity',
        label: 'intent_fidelity',
        description: '요청 의도 충실도 검증 설정',
        kind: 'info',
        enabledPath: ['intent_fidelity', 'enabled'],
        configPath: ['intent_fidelity'],
      },
      {
        id: 'plan_qa_presets',
        label: 'plan_qa_presets',
        description: 'Plan Q&A 자동화 프리셋',
        kind: 'info',
        configPath: ['plan_qa_presets'],
      },
      {
        id: 'agile',
        label: 'agile',
        description: 'Agile 실행/플래닝 파라미터',
        kind: 'info',
        configPath: ['agile'],
      },
      {
        id: 'reference',
        label: 'reference',
        description: '외부 참조 검색/캐싱 설정',
        kind: 'info',
        configPath: ['reference'],
      },
      {
        id: 'test_enforcement',
        label: 'test_enforcement',
        description: '테스트 강제화 설정 (request/review 단계에서 사용)',
        kind: 'info',
        enabledPath: ['test_enforcement', 'enabled'],
        configPath: ['test_enforcement'],
      },
      {
        id: 'prereview',
        label: 'prereview',
        description: '사전 검토 단계 에이전트 구성',
        kind: 'agent-matrix',
        agentsPath: ['prereview', 'agents'],
      },
    ],
  },
  {
    id: 'phase-2',
    title: 'Phase 2',
    subtitle: '구현',
    nodes: [
      {
        id: 'agent_assignments',
        label: 'agent_assignments',
        description: '도메인별 담당 에이전트 매핑',
        kind: 'info',
        configPath: ['agent_assignments'],
      },
      {
        id: 'stitch',
        label: 'stitch',
        description: 'UI 설계 자동화 기능',
        kind: 'info',
        enabledPath: ['stitch', 'enabled'],
        configPath: ['stitch'],
      },
    ],
  },
  {
    id: 'phase-3',
    title: 'Phase 3',
    subtitle: '리뷰',
    nodes: [
      {
        id: 'review.roles',
        label: 'review.roles',
        description: '리뷰 역할별 agent/tier 배정',
        kind: 'role-summary',
        rolesPath: ['review', 'roles'],
      },
      {
        id: 'code_review',
        label: 'code_review',
        description: '코드 리뷰 자동화 기능',
        kind: 'info',
        enabledPath: ['code_review', 'enabled'],
        configPath: ['code_review'],
      },
      {
        id: 'plan_review.roles',
        label: 'plan_review.roles',
        description: '계획 리뷰 역할별 agent/tier 배정',
        kind: 'role-summary',
        rolesPath: ['plan_review', 'roles'],
        enabledPath: ['plan_review', 'enabled'],
      },
    ],
  },
  {
    id: 'phase-4',
    title: 'Phase 4',
    subtitle: '피드백',
    nodes: [
      {
        id: 'debug',
        label: 'debug',
        description: '디버깅 단계 에이전트 구성',
        kind: 'agent-matrix',
        enabledPath: ['debug', 'enabled'],
        agentsPath: ['debug', 'agents'],
      },
      {
        id: 'collaborative_debug',
        label: 'collaborative_debug',
        description: '협업 디버그 운영 설정',
        kind: 'info',
        configPath: ['collaborative_debug'],
      },
      {
        id: 'workflow.feedback',
        label: 'workflow.max_feedback_rounds',
        description: '피드백 라운드 제어',
        kind: 'info',
        configPath: ['workflow'],
      },
    ],
  },
];

const WORKFLOW_NODE_MAP: Record<string, WorkflowNode> = WORKFLOW_PHASES
  .flatMap((phase) => phase.nodes)
  .reduce<Record<string, WorkflowNode>>((acc, node) => {
    acc[node.id] = node;
    return acc;
  }, {});

type FieldCardProps = {
  fieldKey: string;
  fullPath: string[];
  value: any;
  indent: number;
  description?: string;
  options?: string[];
  fieldStatus: 'modified' | 'custom' | null;
  onResetField: (path: string[]) => void;
  onDeleteField: (path: string[]) => void;
  onValueChange: (path: string[], value: any) => void;
};

const FieldCard = React.memo(function FieldCard({
  fieldKey,
  fullPath,
  value,
  indent,
  description,
  options,
  fieldStatus,
  onResetField,
  onDeleteField,
  onValueChange,
}: FieldCardProps) {
  const isInvalidOption = options && options.length > 0 && typeof value === 'string' && !options.includes(value);

  return (
    <Card style={{ marginLeft: indent }}>
      <CardContent className="p-4 flex items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="text-sm font-semibold font-mono">{fieldKey}</div>
          {description && <div className="text-xs text-muted-foreground">{description}</div>}
        </div>
        <div className="flex-1 max-w-md flex flex-wrap justify-end items-center gap-2">
          {fieldStatus === 'modified' && (
            <Badge variant="outline" className="text-[10px] text-blue-600 border-blue-400 dark:text-blue-400 dark:border-blue-500">
              Modified
            </Badge>
          )}
          {fieldStatus === 'custom' && (
            <Badge variant="outline" className="text-[10px] text-orange-600 border-orange-400 dark:text-orange-400 dark:border-orange-500">
              Custom
            </Badge>
          )}
          {isInvalidOption && (
            <Badge variant="outline" className="text-[10px] text-red-600 border-red-400 dark:text-red-400 dark:border-red-500">
              Invalid
            </Badge>
          )}
          {fieldStatus === 'modified' && (
            <Button variant="outline" size="sm" onClick={() => onResetField(fullPath)}>
              Reset to default
            </Button>
          )}
          {fieldStatus === 'custom' && (
            <Button variant="outline" size="sm" onClick={() => onDeleteField(fullPath)}>
              Delete
            </Button>
          )}
          {Array.isArray(value) ? (
            value.every((entry) => !isObject(entry) && !Array.isArray(entry)) ? (
              <TagInput
                tags={value.map(String)}
                onChange={(tags) => onValueChange(fullPath, tags)}
              />
            ) : (
              <Input value={JSON.stringify(value)} readOnly className="text-left font-mono" />
            )
          ) : value === null ? (
            <Input
              value=""
              placeholder="null"
              className="text-left font-mono"
              onChange={(e) => {
                const val = e.target.value === '' ? null : e.target.value;
                onValueChange(fullPath, val);
              }}
            />
          ) : typeof value === 'boolean' ? (
            <Switch checked={value} onCheckedChange={(checked) => onValueChange(fullPath, checked)} />
          ) : options && options.length > 0 && typeof value === 'string' && value !== '' ? (
            <Select value={value} onValueChange={(val) => onValueChange(fullPath, val)}>
              <SelectTrigger className="w-[180px] h-9 font-mono text-left">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {isInvalidOption && (
                  <SelectItem value={value} className="text-red-500 font-mono">
                    {value} (invalid)
                  </SelectItem>
                )}
                {options.map((opt) => (
                  <SelectItem key={opt} value={opt} className="font-mono">
                    {opt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              value={value}
              type={typeof value === 'number' ? 'number' : 'text'}
              className="text-left font-mono"
              onChange={(e) => {
                const val = typeof value === 'number' ? Number(e.target.value) : e.target.value;
                onValueChange(fullPath, val);
              }}
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
});

function formatReadonlyValue(value: any): string {
  if (value === null) return 'null';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

const ReadonlyFieldCard = React.memo(function ReadonlyFieldCard({
  fieldKey,
  value,
  description,
  options,
  onValueChange,
  fullPath,
}: {
  fieldKey: string;
  value: any;
  description?: string;
  options?: string[];
  onValueChange?: (path: string[], value: any) => void;
  fullPath?: string[];
}) {
  const isInvalidOption = options && options.length > 0 && typeof value === 'string' && !options.includes(value);

  return (
    <Card>
      <CardContent className="p-4 flex items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="text-sm font-semibold font-mono">{fieldKey}</div>
          {description && <div className="text-xs text-muted-foreground">{description}</div>}
        </div>
        <div className="flex-1 max-w-md flex justify-end items-center">
          {Array.isArray(value) && onValueChange && fullPath ? (
            value.every((entry) => !isObject(entry) && !Array.isArray(entry)) ? (
              <TagInput
                tags={value.map(String)}
                onChange={(tags) => onValueChange(fullPath, tags)}
              />
            ) : (
              <Input value={JSON.stringify(value)} readOnly className="text-left font-mono" />
            )
          ) : value === null && onValueChange && fullPath ? (
            <Input
              value=""
              placeholder="null"
              className="text-left font-mono"
              onChange={(e) => {
                const val = e.target.value === '' ? null : e.target.value;
                onValueChange(fullPath, val);
              }}
            />
          ) : typeof value === 'boolean' && onValueChange && fullPath ? (
            <Switch checked={value} onCheckedChange={(checked) => onValueChange(fullPath, checked)} />
          ) : options && options.length > 0 && typeof value === 'string' && value !== '' && onValueChange && fullPath ? (
            <Select value={value} onValueChange={(val) => onValueChange(fullPath, val)}>
              <SelectTrigger className="w-[180px] h-9 font-mono text-left">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {isInvalidOption && (
                  <SelectItem value={value} className="text-red-500 font-mono">
                    {value} (invalid)
                  </SelectItem>
                )}
                {options.map((opt) => (
                  <SelectItem key={opt} value={opt} className="font-mono">
                    {opt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (typeof value === 'number' || typeof value === 'string') && onValueChange && fullPath ? (
            <Input
              value={value}
              type={typeof value === 'number' ? 'number' : 'text'}
              className="text-left font-mono"
              onChange={(e) => {
                const val = typeof value === 'number' ? Number(e.target.value) : e.target.value;
                onValueChange(fullPath, val);
              }}
            />
          ) : isObject(value) ? (
            <Input value={JSON.stringify(value)} readOnly className="text-left font-mono" />
          ) : (
            <Input value={formatReadonlyValue(value)} readOnly className="text-left font-mono" />
          )}
        </div>
      </CardContent>
    </Card>
  );
});

function isObject(v: any) {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isNumericIndex(key: string) {
  return /^\d+$/.test(key);
}

function isTier(value: unknown): value is AgentTier {
  return value === 'premium' || value === 'economy';
}

function getNestedValueWithArrays(obj: any, path: string[]): any {
  let current = obj;

  for (const key of path) {
    if (current === undefined || current === null) {
      return undefined;
    }

    if (Array.isArray(current)) {
      const index = Number(key);
      if (!Number.isInteger(index) || index < 0 || index >= current.length) {
        return undefined;
      }
      current = current[index];
      continue;
    }

    if (typeof current !== 'object' || !(key in current)) {
      return undefined;
    }

    current = current[key];
  }

  return current;
}

function deepSetWithArrays(obj: any, path: string[], value: any): any {
  if (path.length === 0) return value;

  const [head, ...rest] = path;

  if (Array.isArray(obj)) {
    const index = Number(head);
    if (!Number.isInteger(index) || index < 0) return obj;

    const clone = [...obj];
    clone[index] = deepSetWithArrays(clone[index], rest, value);
    return clone;
  }

  if (obj && typeof obj === 'object') {
    return {
      ...obj,
      [head]: deepSetWithArrays(obj[head], rest, value),
    };
  }

  if (isNumericIndex(head)) {
    const index = Number(head);
    const clone: any[] = [];
    clone[index] = deepSetWithArrays(undefined, rest, value);
    return clone;
  }

  return {
    [head]: deepSetWithArrays(undefined, rest, value),
  };
}

function deepRemoveWithArrays(obj: any, path: string[]): any {
  if (!obj || typeof obj !== 'object' || path.length === 0) {
    return obj;
  }

  const [head, ...rest] = path;

  if (Array.isArray(obj)) {
    const index = Number(head);
    if (!Number.isInteger(index) || index < 0 || index >= obj.length) {
      return obj;
    }

    const clone = [...obj];
    if (rest.length === 0) {
      clone.splice(index, 1);
      return clone;
    }

    clone[index] = deepRemoveWithArrays(clone[index], rest);
    if (isObject(clone[index]) && Object.keys(clone[index]).length === 0) {
      clone.splice(index, 1);
    }
    return clone;
  }

  if (!(head in obj)) {
    return obj;
  }

  const clone = { ...obj };
  if (rest.length === 0) {
    delete clone[head];
    return clone;
  }

  clone[head] = deepRemoveWithArrays(obj[head], rest);
  if (isObject(clone[head]) && Object.keys(clone[head]).length === 0) {
    delete clone[head];
  }

  return clone;
}

function getRoleSlotLabel(index: number) {
  if (index === 0) return 'primary';
  if (index === 1) return 'fallback';
  return `slot_${index + 1}`;
}

function formatRoleDisplayName(roleName: string) {
  return roleName
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function resolveDefaultTier(config: any, provider: AgentProvider): AgentTier {
  const defaultTier = getNestedValueWithArrays(config, ['models', 'providers', provider, 'default_tier']);
  return isTier(defaultTier) ? defaultTier : 'premium';
}

function normalizeAgentEntry(entry: any, defaultTier: AgentTier): { count: number; tier: AgentTier } {
  if (typeof entry === 'number') {
    return {
      count: Number.isFinite(entry) ? Math.max(0, Math.trunc(entry)) : 0,
      tier: defaultTier,
    };
  }

  if (isObject(entry)) {
    const rawCount = typeof entry.count === 'number' ? entry.count : 0;
    const rawTier = isTier(entry.tier) ? entry.tier : defaultTier;
    return {
      count: Number.isFinite(rawCount) ? Math.max(0, Math.trunc(rawCount)) : 0,
      tier: rawTier,
    };
  }

  return { count: 0, tier: defaultTier };
}

function buildRowsFromAgentsPath(config: any, path: string[]): WorkflowAgentRow[] {
  const source = getNestedValueWithArrays(config, path);
  return AGENT_PROVIDERS.map((provider) => {
    const fallbackTier = resolveDefaultTier(config, provider);
    const normalized = normalizeAgentEntry(source?.[provider], fallbackTier);
    return {
      provider,
      count: normalized.count,
      tier: normalized.tier,
      editable: true,
    };
  });
}

function buildRowsFromRolePath(config: any, path: string[]): WorkflowAgentRow[] {
  const source = getNestedValueWithArrays(config, path);
  const rows = AGENT_PROVIDERS.map((provider) => {
    const fallbackTier = resolveDefaultTier(config, provider);
    return {
      provider,
      count: 0,
      tier: fallbackTier,
      editable: false,
      mixedTier: false,
    };
  });

  if (!isObject(source)) {
    return rows;
  }

  for (const rv of Object.values(source)) {
    const roleValue = rv as Record<string, unknown>;
    if (!isObject(roleValue)) continue;
    if (roleValue.enabled === false) continue;

    const roleAgent = roleValue.agent as string;
    if (!AGENT_PROVIDERS.includes(roleAgent as AgentProvider)) continue;

    const row = rows.find((item) => item.provider === roleAgent);
    if (!row) continue;

    row.count += 1;
    if (isTier(roleValue.tier as string)) {
      if (row.count === 1) {
        row.tier = roleValue.tier as AgentTier;
      } else if (row.tier !== roleValue.tier) {
        row.mixedTier = true;
      }
    }
  }

  return rows;
}

function buildRoleDetailsFromRolePath(config: any, path: string[]): WorkflowRoleDetailRow[] {
  const source = getNestedValueWithArrays(config, path);
  if (!isObject(source)) {
    return [];
  }

  return Object.entries(source).map(([name, rv]) => {
    const roleValue = rv as Record<string, unknown>;
    if (!isObject(roleValue)) {
      return {
        name,
        enabled: false,
        agent: '-',
        tier: '-',
        tierPath: [...path, name, 'tier'],
        agentPath: [...path, name, 'agent'],
      };
    }

    return {
      name,
      enabled: roleValue.enabled !== false,
      agent: typeof roleValue.agent === 'string' ? roleValue.agent : '-',
      tier: typeof roleValue.tier === 'string' ? roleValue.tier : '-',
      tierPath: [...path, name, 'tier'],
      agentPath: [...path, name, 'agent'],
    };
  });
}

function buildModelProviderRows(config: any): WorkflowModelProviderRow[] {
  const source = getNestedValueWithArrays(config, ['models', 'providers']);
  return AGENT_PROVIDERS.map((provider) => {
    const providerConfig = isObject(source?.[provider]) ? source[provider] as Record<string, unknown> : {};
    return {
      provider,
      premium: typeof providerConfig.premium === 'string' ? providerConfig.premium : '-',
      economy: typeof providerConfig.economy === 'string' ? providerConfig.economy : '-',
      defaultTier: typeof providerConfig.default_tier === 'string' ? providerConfig.default_tier : '-',
    };
  });
}

function buildModelRoleAssignmentRows(config: any): WorkflowModelRoleAssignmentRow[] {
  const source = getNestedValueWithArrays(config, ['models', 'roles']);
  if (!isObject(source)) {
    return [];
  }

  const orderedRoleNames = [
    ...MODEL_ROLE_DISPLAY_ORDER.filter((roleName) => roleName in source),
    ...Object.keys(source).filter((roleName) => !MODEL_ROLE_DISPLAY_ORDER.includes(roleName as typeof MODEL_ROLE_DISPLAY_ORDER[number])),
  ];

  const rows: WorkflowModelRoleAssignmentRow[] = [];

  for (const roleName of orderedRoleNames) {
    const roleValue = source[roleName];

    if (Array.isArray(roleValue)) {
      roleValue.forEach((slotValue, index) => {
        const slot = isObject(slotValue) ? slotValue as Record<string, unknown> : {};
        rows.push({
          role: `${formatRoleDisplayName(roleName)} (${getRoleSlotLabel(index)})`,
          provider: typeof slot.provider === 'string' ? slot.provider : '-',
          tier: typeof slot.tier === 'string' ? slot.tier : '-',
          tierPath: ['models', 'roles', roleName, index.toString(), 'tier'],
          providerPath: ['models', 'roles', roleName, index.toString(), 'provider'],
        });
      });
      continue;
    }

    const slot = isObject(roleValue) ? roleValue as Record<string, unknown> : {};
    rows.push({
      role: formatRoleDisplayName(roleName),
      provider: typeof slot.provider === 'string' ? slot.provider : '-',
      tier: typeof slot.tier === 'string' ? slot.tier : '-',
      tierPath: ['models', 'roles', roleName, 'tier'],
      providerPath: ['models', 'roles', roleName, 'provider'],
    });
  }

  return rows;
}

function buildInfoFieldRows(config: any, node: WorkflowNode): WorkflowInfoFieldRow[] {
  if (node.kind !== 'info' || !node.configPath) {
    return [];
  }

  const sectionValue = getNestedValueWithArrays(config, node.configPath);
  if (sectionValue === undefined) {
    return [];
  }

  if (isObject(sectionValue)) {
    const focusFields = WORKFLOW_INFO_FOCUS_FIELDS[node.id];
    const keys = (focusFields?.length ? focusFields : Object.keys(sectionValue)).filter((key) => key in sectionValue);

    return keys.map((key) => {
      const fullPath = [...node.configPath!, key];
      const settingDescription = SETTING_DESCRIPTIONS[fullPath.join('.')];
      return {
        key,
        fullPath,
        value: sectionValue[key],
        description: getDescription(settingDescription),
        options: getOptions(settingDescription),
      };
    });
  }

  const fallbackKey = node.configPath[node.configPath.length - 1] ?? node.id;
  const settingDescription = SETTING_DESCRIPTIONS[node.configPath.join('.')];
  return [
    {
      key: fallbackKey,
      fullPath: [...node.configPath],
      value: sectionValue,
      description: getDescription(settingDescription),
      options: getOptions(settingDescription),
    },
  ];
}

function isNodeEnabled(config: any, node: WorkflowNode): boolean {
  if (!node.enabledPath) {
    return true;
  }

  const value = getNestedValueWithArrays(config, node.enabledPath);
  if (typeof value === 'boolean') {
    return value;
  }

  return true;
}

function getNodeRows(config: any, node: WorkflowNode): WorkflowAgentRow[] | null {
  if (node.kind === 'agent-matrix' && node.agentsPath) {
    return buildRowsFromAgentsPath(config, node.agentsPath);
  }

  if (node.kind === 'role-summary' && node.rolesPath) {
    return buildRowsFromRolePath(config, node.rolesPath);
  }

  return null;
}

function computeDiff(original: any, current: any, currentPath: string = ''): PresetDiffChange[] {
  const changes: PresetDiffChange[] = [];

  function compare(a: any, b: any, path: string) {
    if (a === b) return;

    if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') {
      changes.push({ path, from: a, to: b });
      return;
    }

    if (Array.isArray(a) !== Array.isArray(b)) {
      changes.push({ path, from: a, to: b });
      return;
    }

    if (Array.isArray(a) && Array.isArray(b)) {
      if (JSON.stringify(a) !== JSON.stringify(b)) {
        changes.push({ path, from: a, to: b });
      }
      return;
    }

    const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
    for (const key of keys) {
      const nextPath = path ? `${path}.${key}` : key;
      compare(a?.[key], b?.[key], nextPath);
    }
  }

  compare(original, current, currentPath);
  return changes;
}

export function SettingsView() {
  const { projectId, lastSseEvent } = useAppContext();
  const [merged, setMerged] = useState<any>(null);
  const [originalConfig, setOriginalConfig] = useState<any>(null);
  const [overrides, setOverrides] = useState<any>(null);
  const [defaults, setDefaults] = useState<any>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [presetManagerOpen, setPresetManagerOpen] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [diffChanges, setDiffChanges] = useState<PresetDiffChange[]>([]);
  const [openSections, setOpenSections] = useState<string[]>(['workflow']);
  const [activeTab, setActiveTab] = useState<'workflow' | 'behavior' | 'advanced'>('workflow');
  const [selectedNodeId, setSelectedNodeId] = useState<string>('ideation');

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      return;
    }
    fetchConfig();
  }, [projectId]);

  // SSE config_change auto-refresh
  useEffect(() => {
    if (!lastSseEvent || !projectId) return;
    if (lastSseEvent.type === 'config_change') {
      fetchConfig();
    }
  }, [lastSseEvent]);

  async function fetchConfig() {
    setLoading(true);
    try {
      const data = await apiFetch<{ merged: any; overrides: any; defaults: any }>('/api/config', projectId);
      setMerged(data.merged ?? null);
      setOriginalConfig(JSON.parse(JSON.stringify(data.merged ?? null)));
      setOverrides(data.overrides ?? null);
      setDefaults(data.defaults ?? null);
      setIsDirty(false);
    } catch (err) {
      console.error('Failed to fetch config:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(nextConfig?: any) {
    if (!projectId) return;
    const payload = nextConfig ?? merged;
    if (!payload) return;

    setSaving(true);
    try {
      await apiFetch('/api/config', projectId, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      await fetchConfig();
    } catch (err) {
      console.error('Failed to save config:', err);
      alert(`Failed to save config: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }

  function handleSaveButtonClick() {
    if (!merged || !originalConfig) return;
    const diffs = computeDiff(originalConfig, merged);
    if (diffs.length === 0) {
      alert('변경사항이 없습니다');
      return;
    }
    setDiffChanges(diffs);
    setShowConfirmModal(true);
  }

  function handleConfirmSave() {
    setShowConfirmModal(false);
    void handleSave();
  }

  async function handleApplyAll() {
    if (!projectId || !merged) return;

    const confirmed = window.confirm('Apply current settings to all registered projects? This will overwrite project configs.');
    if (!confirmed) return;

    setSaving(true);
    try {
      const result = await apiFetch<{
        ok: boolean;
        applied: number;
        failed: Array<{ id: string; name: string; error: string }>;
      }>('/api/config/apply-all', projectId, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(merged),
      });

      await fetchConfig();

      if (Array.isArray(result.failed) && result.failed.length > 0) {
        const failedSummary = result.failed
          .map((item) => `- ${item.name} (${item.id}): ${item.error}`)
          .join('\n');
        alert(`Applied to ${result.applied} project(s).\nFailed projects:\n${failedSummary}`);
      } else {
        alert(`Successfully applied to ${result.applied} project(s).`);
      }
    } catch (err) {
      console.error('Failed to apply config to all projects:', err);
      alert(`Failed to apply config to all projects: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }

  function handlePanelReplace(newConfig: any) {
    setMerged(newConfig);
    void handleSave(newConfig);
  }

  function getFieldStatus(path: string[]): 'modified' | 'custom' | null {
    const hasOverride = getNestedValueWithArrays(overrides, path) !== undefined;
    if (!hasOverride) return null;
    const hasDefault = getNestedValueWithArrays(defaults, path) !== undefined;
    return hasDefault ? 'modified' : 'custom';
  }

  function handleResetField(path: string[]) {
    if (!defaults) return;
    const defaultValue = getNestedValueWithArrays(defaults, path);
    setMerged((current: any) => deepSetWithArrays(current ?? {}, path, defaultValue));
    setOverrides((current: any) => deepRemoveWithArrays(current, path));
    setIsDirty(true);
  }

  function handleDeleteField(path: string[]) {
    setMerged((current: any) => deepRemoveWithArrays(current, path));
    setOverrides((current: any) => deepRemoveWithArrays(current, path));
    setIsDirty(true);
  }

  function handleFieldChange(path: string[], value: any) {
    setMerged((current: any) => deepSetWithArrays(current, path, value));
    setIsDirty(true);
  }

  function handleWorkflowAgentChange(
    node: WorkflowNode,
    provider: AgentProvider,
    field: 'count' | 'tier',
    value: number | AgentTier
  ) {
    const agentsPath = node.agentsPath;
    if (node.kind !== 'agent-matrix' || !agentsPath) {
      return;
    }

    setMerged((current: any) => {
      const source = getNestedValueWithArrays(current, agentsPath);
      const currentEntry = source?.[provider];
      const fallbackTier = resolveDefaultTier(current, provider);
      const normalized = normalizeAgentEntry(currentEntry, fallbackTier);

      const nextEntry = {
        count: field === 'count' ? Math.max(0, Math.trunc(Number(value) || 0)) : normalized.count,
        tier: field === 'tier' && isTier(value) ? value : normalized.tier,
      };

      const nextSection = {
        ...(isObject(source) ? source : {}),
        [provider]: nextEntry,
      };

      return deepSetWithArrays(current ?? {}, agentsPath, nextSection);
    });
    setIsDirty(true);
  }

  function handleWorkflowRoleEnabledToggle(node: WorkflowNode, roleName: string) {
    const rolesPath = node.rolesPath;
    if (node.kind !== 'role-summary' || !rolesPath) {
      return;
    }

    const enabledPath = [...rolesPath, roleName, 'enabled'];
    setMerged((current: any) => {
      const currentEnabled = getNestedValueWithArrays(current, enabledPath);
      const nextEnabled = currentEnabled === false;
      return deepSetWithArrays(current ?? {}, enabledPath, nextEnabled);
    });
    setIsDirty(true);
  }

  function renderField(path: string[], key: string, value: any, depth = 0, label = key) {
    const indent = depth * 16;
    const fullPath = [...path, key];
    const fullPathKey = fullPath.join('.');
    const descEntry = SETTING_DESCRIPTIONS[fullPath.join('.')];
    const description = getDescription(descEntry);
    const options = getOptions(descEntry);

    if (fullPathKey === 'review.cross_validation' && isObject(value)) {
      const crossValidationValue = value as Record<string, unknown>;
      const orderedKeys = [
        'enabled',
        'line_proximity',
        ...Object.keys(crossValidationValue).filter((subKey) => subKey !== 'enabled' && subKey !== 'line_proximity'),
      ].filter((subKey, index, array) => subKey in crossValidationValue && array.indexOf(subKey) === index);

      return (
        <div key={fullPathKey}>
          <div style={{ paddingLeft: indent }} className="text-xs font-semibold text-muted-foreground py-1 mt-2">
            {label}
          </div>
          {description && (
            <div style={{ paddingLeft: indent }} className="text-xs text-muted-foreground pb-2">
              {description}
            </div>
          )}
          <div className="space-y-4">
            {orderedKeys.map((subKey) => renderField(fullPath, subKey, crossValidationValue[subKey], depth + 1))}
          </div>
        </div>
      );
    }

    if (fullPathKey === 'review.roles.adversarial_reviewer.attack_surfaces' && Array.isArray(value)) {
      const selectedSurfaces = new Set(value.map(String));
      const knownSurfaces = [...ADVERSARIAL_ATTACK_SURFACE_OPTIONS];
      const extraSurfaces = value
        .map(String)
        .filter((surface, index, array) => !knownSurfaces.includes(surface as typeof ADVERSARIAL_ATTACK_SURFACE_OPTIONS[number]) && array.indexOf(surface) === index);
      const allSurfaceOptions = [...knownSurfaces, ...extraSurfaces];

      return (
        <div key={fullPathKey}>
          <div style={{ paddingLeft: indent }} className="text-xs font-semibold text-muted-foreground py-1 mt-2">
            {label}
          </div>
          {description && (
            <div style={{ paddingLeft: indent }} className="text-xs text-muted-foreground pb-2">
              {description}
            </div>
          )}
          <Card style={{ marginLeft: indent }}>
            <CardContent className="p-4 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {allSurfaceOptions.map((surface) => (
                  <label key={surface} className="flex items-center gap-2 rounded border px-2 py-1.5 text-xs font-mono">
                    <input
                      type="checkbox"
                      checked={selectedSurfaces.has(surface)}
                      onChange={(event) => {
                        const nextSelected = new Set(selectedSurfaces);
                        if (event.target.checked) {
                          nextSelected.add(surface);
                        } else {
                          nextSelected.delete(surface);
                        }
                        handleFieldChange(fullPath, allSurfaceOptions.filter((entry) => nextSelected.has(entry)));
                      }}
                    />
                    <span>{surface}</span>
                  </label>
                ))}
              </div>
              {extraSurfaces.length > 0 && (
                <p className="text-[11px] text-muted-foreground">
                  기본 목록 외 surface도 보존됩니다.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      );
    }

    if (
      path.join('.') === 'models.roles' &&
      (key === 'developer' || key === 'reviewer') &&
      Array.isArray(value) &&
      value.every(isObject)
    ) {
      return (
        <div key={fullPath.join('.')}>
          <div style={{ paddingLeft: indent }} className="text-xs font-semibold text-muted-foreground py-1 mt-2">
            {label}
          </div>
          {description && (
            <div style={{ paddingLeft: indent }} className="text-xs text-muted-foreground pb-2">
              {description}
            </div>
          )}
          <div className="space-y-4">
            {value.map((item, index) => renderField(fullPath, String(index), item, depth + 1, getRoleSlotLabel(index)))}
          </div>
        </div>
      );
    }

    if (isObject(value)) {
      return (
        <div key={fullPath.join('.')}>
          <div style={{ paddingLeft: indent }} className="text-xs font-semibold text-muted-foreground py-1 mt-2">
            {label}
          </div>
          {description && (
            <div style={{ paddingLeft: indent }} className="text-xs text-muted-foreground pb-2">
              {description}
            </div>
          )}
          <div className="space-y-4">
            {Object.entries(value).map(([subKey, subVal]) => renderField([...path, key], subKey, subVal, depth + 1))}
          </div>
        </div>
      );
    }

    const fieldStatus = getFieldStatus(fullPath);

    return (
      <FieldCard
        key={fullPath.join('.')}
        fieldKey={label}
        fullPath={fullPath}
        value={value}
        indent={indent}
        description={description}
        options={options}
        fieldStatus={fieldStatus}
        onResetField={handleResetField}
        onDeleteField={handleDeleteField}
        onValueChange={handleFieldChange}
      />
    );
  }

  if (!projectId) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        프로젝트를 선택하세요
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-8 max-w-2xl mx-auto space-y-6">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!merged) return <div className="p-8 text-center">Failed to load config.</div>;

  const getSectionCounts = (sectionKey: string, sectionData: any) => {
    let fieldCount = 0;
    let modifiedCount = 0;

    const traverse = (data: any, path: string[]) => {
      if (Array.isArray(data)) {
        fieldCount++;
        const status = getFieldStatus(path);
        if (status === 'modified' || status === 'custom') modifiedCount++;
        return;
      }
      if (isObject(data)) {
        for (const [k, v] of Object.entries(data)) {
          traverse(v, [...path, k]);
        }
        return;
      }
      fieldCount++;
      const status = getFieldStatus(path);
      if (status === 'modified' || status === 'custom') modifiedCount++;
    };

    traverse(sectionData, [sectionKey]);
    return { fieldCount, modifiedCount };
  };

  const visibleSections = Object.entries(merged).filter(([key]) => !HIDDEN_FIELDS.includes(key));
  const behaviorSections = visibleSections.filter(([key]) => BEHAVIOR_SECTIONS.includes(key));
  const advancedSections = visibleSections.filter(([key]) => !BEHAVIOR_SECTIONS.includes(key));

  const AGENT_SECTIONS = ['discussion', 'ideation', 'collaborative_debug', 'debug', 'explore', 'prereview', 'roles'];
  const agentIndices = advancedSections
    .map(([key], index) => (AGENT_SECTIONS.includes(key) ? index : -1))
    .filter((index) => index !== -1);
  const firstAgentIndex = agentIndices.length > 0 ? agentIndices[0] : -1;
  const lastAgentIndex = agentIndices.length > 0 ? agentIndices[agentIndices.length - 1] : -1;
  const activeAccordionSections =
    activeTab === 'behavior'
      ? behaviorSections
      : activeTab === 'advanced'
        ? advancedSections
        : [];

  const selectedNode = WORKFLOW_NODE_MAP[selectedNodeId] ?? WORKFLOW_PHASES[0].nodes[0];
  const selectedNodeRows = getNodeRows(merged, selectedNode);
  const selectedRoleRows =
    selectedNode.kind === 'role-summary' && selectedNode.rolesPath
      ? buildRoleDetailsFromRolePath(merged, selectedNode.rolesPath)
      : [];
  const selectedModelProviderRows = selectedNode.id === 'models.providers' ? buildModelProviderRows(merged) : [];
  const selectedModelRoleRows = selectedNode.id === 'models.roles' ? buildModelRoleAssignmentRows(merged) : [];
  const selectedInfoRows = selectedNode.kind === 'info' ? buildInfoFieldRows(merged, selectedNode) : [];
  const selectedNodeEnabled = isNodeEnabled(merged, selectedNode);
  const saveAriaLabel = isDirty ? 'Save : 미저장 변경사항이 있습니다' : 'Save : 변경된 설정을 저장합니다';

  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex-1 min-w-0 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="p-8 max-w-6xl mx-auto pb-20">
            <div className="flex justify-between items-center mb-8">
              <div>
                <h2 className="text-2xl font-bold">Settings</h2>
                <p className="text-muted-foreground text-sm">System configuration and preferences.</p>
              </div>
              <div className="flex gap-2">
                <TooltipProvider>
                  {(activeTab === 'behavior' || activeTab === 'advanced') && (
                    <>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="outline"
                            size="icon"
                            onClick={() => setOpenSections(activeAccordionSections.map(([key]) => key))}
                            disabled={saving}
                            aria-label="전부 열기 : 모든 설정 섹션을 펼칩니다"
                          >
                            <UnfoldVertical className="h-4 w-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>전부 열기 : 모든 설정 섹션을 펼칩니다</p>
                        </TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="outline"
                            size="icon"
                            onClick={() => setOpenSections([])}
                            disabled={saving}
                            aria-label="전부 접기 : 모든 설정 섹션을 닫습니다"
                          >
                            <FoldVertical className="h-4 w-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>전부 접기 : 모든 설정 섹션을 닫습니다</p>
                        </TooltipContent>
                      </Tooltip>
                    </>
                  )}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant={panelOpen ? 'secondary' : 'outline'}
                        size="icon"
                        onClick={() => setPanelOpen((open) => !open)}
                        disabled={saving}
                        aria-label="찾아 바꾸기 : 설정값을 검색하고 일괄 교체합니다"
                      >
                        <Replace className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>찾아 바꾸기 : 설정값을 검색하고 일괄 교체합니다</p>
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={fetchConfig}
                        disabled={saving}
                        aria-label="Reload : 서버에서 설정을 다시 불러옵니다"
                      >
                        <RefreshCcw className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Reload : 서버에서 설정을 다시 불러옵니다</p>
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => setWizardOpen(true)}
                        disabled={saving}
                        aria-label="설정 마법사 : 초기 설정을 단계별로 안내합니다"
                      >
                        <Wand2 className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>설정 마법사 : 초기 설정을 단계별로 안내합니다</p>
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => setPresetManagerOpen(true)}
                        disabled={saving}
                        aria-label="프리셋 관리 : 사용자 설정을 프리셋으로 저장하고 불러옵니다"
                      >
                        <Bookmark className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>프리셋 관리 : 사용자 설정을 프리셋으로 저장하고 불러옵니다</p>
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={handleApplyAll}
                        disabled={saving || !merged}
                        aria-label="Apply to All : 현재 설정을 모든 프로젝트에 적용합니다"
                      >
                        <Globe className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Apply to All : 현재 설정을 모든 프로젝트에 적용합니다</p>
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        onClick={handleSaveButtonClick}
                        disabled={saving}
                        variant={isDirty ? 'default' : 'outline'}
                        size="icon"
                        aria-label={saveAriaLabel}
                      >
                        <Save className={saving ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Save : 변경된 설정을 저장합니다</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>

            <Tabs value={activeTab} onValueChange={(tab) => setActiveTab(tab as 'workflow' | 'behavior' | 'advanced')}>
              <TabsList>
                <TabsTrigger value="workflow">워크플로우</TabsTrigger>
                <TabsTrigger value="behavior">동작</TabsTrigger>
                <TabsTrigger value="advanced">고급</TabsTrigger>
              </TabsList>

              <TabsContent value="workflow" className="mt-4">
                <div className="grid grid-cols-[380px_minmax(0,1fr)] gap-6 items-start">
                  <div className="rounded-lg border bg-card p-4">
                    <div className="mb-4">
                      <h3 className="text-sm font-semibold">Workflow Pipeline</h3>
                      <p className="text-xs text-muted-foreground">Models/Phase 1 → 4 흐름에서 단계를 선택하세요.</p>
                    </div>

                    <ScrollArea className="max-h-[calc(100vh-240px)] overflow-y-auto pr-4">
                      <div className="space-y-1">
                        {WORKFLOW_PHASES.map((phase, index) => (
                        <React.Fragment key={phase.id}>
                          <div className="rounded-md border bg-background p-3">
                            <div className="flex items-baseline justify-between mb-2">
                              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{phase.title}</div>
                              <div className="text-xs text-muted-foreground">{phase.subtitle}</div>
                            </div>
                            <div className="space-y-2">
                              {phase.nodes.map((node) => {
                                const enabled = isNodeEnabled(merged, node);
                                const selected = selectedNode.id === node.id;
                                return (
                                  <button
                                    key={node.id}
                                    type="button"
                                    onClick={() => setSelectedNodeId(node.id)}
                                    className={[
                                      'w-full rounded-md border px-3 py-2 text-left transition-colors',
                                      selected ? 'border-primary bg-primary/5' : 'border-border bg-card hover:bg-muted/40',
                                      enabled ? '' : 'opacity-60 border-dashed',
                                    ].join(' ')}
                                  >
                                    <div className="flex items-center justify-between gap-2">
                                      <span className="font-mono text-xs">{node.label}</span>
                                      {!enabled && (
                                        <Badge variant="outline" className="text-[10px] border-dashed">
                                          OFF
                                        </Badge>
                                      )}
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          </div>

                          {index < WORKFLOW_PHASES.length - 1 && (
                            <div className="h-10 flex justify-center" aria-hidden>
                              <svg width="24" height="40" viewBox="0 0 24 40" className="text-muted-foreground">
                                <path d="M12 2 L12 30" stroke="currentColor" strokeWidth="1.5" fill="none" />
                                <path d="M8 27 L12 35 L16 27" stroke="currentColor" strokeWidth="1.5" fill="none" />
                              </svg>
                            </div>
                          )}
                        </React.Fragment>
                      ))}
                      </div>
                    </ScrollArea>
                  </div>

                  <div className="rounded-lg border bg-card p-4">
                    <div className="mb-4">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold font-mono">{selectedNode.label}</h3>
                        {!selectedNodeEnabled && (
                          <Badge variant="outline" className="text-[10px] border-dashed">
                            OFF
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{selectedNode.description}</p>
                    </div>

                    {selectedNode.kind === 'info' ? (
                      selectedNode.id === 'models.providers' ? (
                        selectedModelProviderRows.length > 0 ? (
                          <div className="space-y-3">
                            <div className="rounded-md border overflow-hidden">
                              <table className="w-full text-sm">
                                <thead className="bg-muted/40">
                                  <tr>
                                    <th className="text-left px-3 py-2 text-xs font-semibold">Provider</th>
                                    <th className="text-left px-3 py-2 text-xs font-semibold">Premium</th>
                                    <th className="text-left px-3 py-2 text-xs font-semibold">Economy</th>
                                    <th className="text-left px-3 py-2 text-xs font-semibold">Default Tier</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {selectedModelProviderRows.map((row) => (
                                    <tr key={row.provider} className="border-t">
                                      <td className="px-3 py-2 font-mono text-xs">{row.provider}</td>
                                      <td className="px-3 py-2">
                                        <Input
                                          value={row.premium}
                                          className="h-8 font-mono text-xs"
                                          onChange={(event) =>
                                            handleFieldChange(['models', 'providers', row.provider, 'premium'], event.target.value)
                                          }
                                        />
                                      </td>
                                      <td className="px-3 py-2">
                                        <Input
                                          value={row.economy}
                                          className="h-8 font-mono text-xs"
                                          onChange={(event) =>
                                            handleFieldChange(['models', 'providers', row.provider, 'economy'], event.target.value)
                                          }
                                        />
                                      </td>
                                      <td className="px-3 py-2">
                                        <Select
                                          value={row.defaultTier === 'economy' ? 'economy' : 'premium'}
                                          onValueChange={(value) =>
                                            handleFieldChange(['models', 'providers', row.provider, 'default_tier'], value)
                                          }
                                        >
                                          <SelectTrigger className="h-8 w-32 font-mono text-xs">
                                            <SelectValue />
                                          </SelectTrigger>
                                          <SelectContent>
                                            <SelectItem value="premium" className="font-mono">premium</SelectItem>
                                            <SelectItem value="economy" className="font-mono">economy</SelectItem>
                                          </SelectContent>
                                        </Select>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            <p className="text-xs text-muted-foreground">
                              이 노드는 인라인 편집을 지원합니다. 값을 변경한 뒤 Save 버튼으로 저장하세요.
                            </p>
                          </div>
                        ) : (
                          <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">
                            연결된 설정 경로에 표시할 값이 없습니다.
                          </div>
                        )
                      ) : selectedNode.id === 'models.roles' ? (
                        selectedModelRoleRows.length > 0 ? (
                          <div className="space-y-3">
                            <div className="rounded-md border overflow-hidden">
                              <table className="w-full text-sm">
                                <thead className="bg-muted/40">
                                  <tr>
                                    <th className="text-left px-3 py-2 text-xs font-semibold">Role</th>
                                    <th className="text-left px-3 py-2 text-xs font-semibold">Provider</th>
                                    <th className="text-left px-3 py-2 text-xs font-semibold">Tier</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {selectedModelRoleRows.map((row) => (
                                    <tr key={row.role} className="border-t">
                                      <td className="px-3 py-2 font-mono text-xs">{row.role}</td>
                                      <td className="px-3 py-2">
                                        <Select
                                          value={AGENT_PROVIDERS.includes(row.provider as AgentProvider) ? row.provider : undefined}
                                          onValueChange={(value) => handleFieldChange(row.providerPath, value)}
                                        >
                                          <SelectTrigger className="h-8 w-32 font-mono text-xs">
                                            <SelectValue placeholder={row.provider !== '-' ? row.provider : undefined} />
                                          </SelectTrigger>
                                          <SelectContent>
                                            {AGENT_PROVIDERS.map((provider) => (
                                              <SelectItem key={provider} value={provider} className="font-mono">
                                                {provider}
                                              </SelectItem>
                                            ))}
                                          </SelectContent>
                                        </Select>
                                      </td>
                                      <td className="px-3 py-2">
                                        <Select
                                          value={isTier(row.tier) ? row.tier : undefined}
                                          onValueChange={(value) => handleFieldChange(row.tierPath, value)}
                                        >
                                          <SelectTrigger className="h-8 w-32 font-mono text-xs">
                                            <SelectValue placeholder={row.tier !== '-' ? row.tier : undefined} />
                                          </SelectTrigger>
                                          <SelectContent>
                                            <SelectItem value="premium" className="font-mono">premium</SelectItem>
                                            <SelectItem value="economy" className="font-mono">economy</SelectItem>
                                          </SelectContent>
                                        </Select>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            <p className="text-xs text-muted-foreground">
                              이 노드는 인라인 편집을 지원합니다. 값을 변경한 뒤 Save 버튼으로 저장하세요. 상세 설정은 고급 탭을 이용하세요.
                            </p>
                          </div>
                        ) : (
                          <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">
                            연결된 설정 경로에 표시할 값이 없습니다.
                          </div>
                        )
                      ) : selectedInfoRows.length > 0 ? (
                        <div className="space-y-3">
                          {selectedInfoRows.map((row) => (
                            <ReadonlyFieldCard
                              key={row.fullPath.join('.')}
                              fieldKey={row.key}
                              value={row.value}
                              description={row.description}
                              options={row.options}
                              onValueChange={handleFieldChange}
                              fullPath={row.fullPath}
                            />
                          ))}
                          <p className="text-xs text-muted-foreground">
                            이 노드는 인라인 편집을 지원합니다. 값을 변경한 뒤 Save 버튼으로 저장하세요.
                          </p>
                        </div>
                      ) : (
                        <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">
                          연결된 설정 경로에 표시할 값이 없습니다.
                        </div>
                      )
                    ) : selectedNodeRows ? (
                      <div className="space-y-3">
                        <div className="rounded-md border overflow-hidden">
                          <table className="w-full text-sm">
                            <thead className="bg-muted/40">
                              <tr>
                                <th className="text-left px-3 py-2 text-xs font-semibold">Agent</th>
                                <th className="text-left px-3 py-2 text-xs font-semibold">Count</th>
                                <th className="text-left px-3 py-2 text-xs font-semibold">Tier</th>
                              </tr>
                            </thead>
                            <tbody>
                              {selectedNodeRows.map((row) => (
                                <tr key={row.provider} className="border-t">
                                  <td className="px-3 py-2 font-mono text-xs">{row.provider}</td>
                                  <td className="px-3 py-2">
                                    {row.editable ? (
                                      <Input
                                        defaultValue={row.count}
                                        key={`${selectedNode.id}-${row.provider}-${row.count}`}
                                        type="number"
                                        min={0}
                                        className="h-8 w-28"
                                        onBlur={(event) => {
                                          const parsed = Number(event.target.value);
                                          handleWorkflowAgentChange(
                                            selectedNode,
                                            row.provider,
                                            'count',
                                            Number.isFinite(parsed) ? parsed : 0
                                          );
                                        }}
                                        onKeyDown={(event) => {
                                          if (event.key === 'Enter') {
                                            (event.target as HTMLInputElement).blur();
                                          }
                                        }}
                                      />
                                    ) : (
                                      <Input value={row.count} readOnly className="h-8 w-28" />
                                    )}
                                  </td>
                                  <td className="px-3 py-2">
                                    {row.editable ? (
                                      <Select
                                        value={row.tier}
                                        onValueChange={(value) => handleWorkflowAgentChange(selectedNode, row.provider, 'tier', value as AgentTier)}
                                      >
                                        <SelectTrigger className="h-8 w-32 font-mono text-xs">
                                          <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                          <SelectItem value="premium" className="font-mono">premium</SelectItem>
                                          <SelectItem value="economy" className="font-mono">economy</SelectItem>
                                        </SelectContent>
                                      </Select>
                                    ) : (
                                      <div className="flex items-center gap-2">
                                        <Input value={row.tier} readOnly className="h-8 w-32 font-mono text-xs" />
                                        {row.mixedTier && (
                                          <Badge variant="outline" className="text-[10px]">
                                            mixed
                                          </Badge>
                                        )}
                                      </div>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>

                        {selectedNode.kind === 'role-summary' && selectedRoleRows.length > 0 && (
                          <div className="rounded-md border overflow-hidden">
                            <table className="w-full text-sm">
                              <thead className="bg-muted/40">
                                <tr>
                                  <th className="text-left px-3 py-2 text-xs font-semibold">Role</th>
                                  <th className="text-left px-3 py-2 text-xs font-semibold">Enabled</th>
                                  <th className="text-left px-3 py-2 text-xs font-semibold">Agent</th>
                                  <th className="text-left px-3 py-2 text-xs font-semibold">Tier</th>
                                </tr>
                              </thead>
                              <tbody>
                                {selectedRoleRows.map((row) => (
                                  <tr key={row.name} className="border-t">
                                    <td className="px-3 py-2 font-mono text-xs">{row.name}</td>
                                    <td className="px-3 py-2">
                                      <Badge
                                        variant={row.enabled ? 'default' : 'outline'}
                                        className={
                                          row.enabled
                                            ? 'text-[10px] cursor-pointer'
                                            : 'text-[10px] cursor-pointer border-muted-foreground/40 bg-muted/40 text-muted-foreground'
                                        }
                                        role="button"
                                        tabIndex={0}
                                        onClick={() => handleWorkflowRoleEnabledToggle(selectedNode, row.name)}
                                        aria-pressed={row.enabled}
                                        onKeyDown={(event) => {
                                          if (event.repeat) return;
                                          if (event.key === 'Enter' || event.key === ' ') {
                                            event.preventDefault();
                                            handleWorkflowRoleEnabledToggle(selectedNode, row.name);
                                          }
                                        }}
                                      >
                                        {row.enabled ? 'ON' : 'OFF'}
                                      </Badge>
                                    </td>
                                    <td className="px-3 py-2">
                                      <Select
                                        value={AGENT_PROVIDERS.includes(row.agent as AgentProvider) ? row.agent : undefined}
                                        onValueChange={(value) => handleFieldChange(row.agentPath, value)}
                                      >
                                        <SelectTrigger className="h-8 w-32 font-mono text-xs">
                                          <SelectValue placeholder={row.agent !== '-' ? row.agent : undefined} />
                                        </SelectTrigger>
                                        <SelectContent>
                                          {AGENT_PROVIDERS.map((provider) => (
                                            <SelectItem key={provider} value={provider} className="font-mono">
                                              {provider}
                                            </SelectItem>
                                          ))}
                                        </SelectContent>
                                      </Select>
                                    </td>
                                    <td className="px-3 py-2">
                                      <Select
                                        value={isTier(row.tier) ? row.tier : undefined}
                                        onValueChange={(value) => handleFieldChange(row.tierPath, value)}
                                      >
                                        <SelectTrigger className="h-8 w-32 font-mono text-xs">
                                          <SelectValue placeholder={row.tier !== '-' ? row.tier : undefined} />
                                        </SelectTrigger>
                                        <SelectContent>
                                          <SelectItem value="premium" className="font-mono">premium</SelectItem>
                                          <SelectItem value="economy" className="font-mono">economy</SelectItem>
                                        </SelectContent>
                                      </Select>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}

                        {selectedNode.kind !== 'agent-matrix' && (
                          <p className="text-xs text-muted-foreground">
                            이 노드는 인라인 편집을 지원합니다. 값을 변경한 뒤 Save 버튼으로 저장하세요. 상세 설정은 고급 탭을 이용하세요.
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="rounded-md border border-dashed p-4 text-xs text-muted-foreground">
                        이 단계는 Agent 매트릭스 테이블이 없는 설정입니다. 고급 탭에서 세부 값을 편집하세요.
                      </div>
                    )}
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="behavior" className="mt-4">
                <div className="space-y-4">
                  <Accordion type="multiple" value={openSections} onValueChange={setOpenSections} className="w-full space-y-4">
                    {behaviorSections.map(([sectionKey, sectionData]) => {
                      const { fieldCount, modifiedCount } = getSectionCounts(sectionKey, sectionData);

                      return (
                        <AccordionItem key={sectionKey} value={sectionKey} className="border rounded-md bg-card shadow-sm">
                          <AccordionTrigger className="py-2 px-3 text-sm font-bold uppercase tracking-wider hover:no-underline">
                            <div className="flex items-center gap-2">
                              {sectionKey}
                              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">
                                {fieldCount}
                              </Badge>
                              {modifiedCount > 0 && (
                                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 text-orange-600 border-orange-400 dark:text-orange-400 dark:border-orange-500">
                                  {modifiedCount} modified
                                </Badge>
                              )}
                            </div>
                          </AccordionTrigger>
                          <AccordionContent className="p-3 pt-0 border-t">
                            <div className="grid grid-cols-1 gap-2 mt-3">
                              {isObject(sectionData) ? (
                                Object.entries(sectionData as object).map(([key, value]) =>
                                  renderField([sectionKey], key, value)
                                )
                              ) : (
                                renderField([], sectionKey, sectionData)
                              )}
                            </div>
                          </AccordionContent>
                        </AccordionItem>
                      );
                    })}
                  </Accordion>
                </div>
              </TabsContent>

              <TabsContent value="advanced" className="mt-4">
                <div className="space-y-4">
                  <Accordion type="multiple" value={openSections} onValueChange={setOpenSections} className="w-full space-y-4">
                    {advancedSections.map(([sectionKey, sectionData], index) => {
                      const { fieldCount, modifiedCount } = getSectionCounts(sectionKey, sectionData);
                      const isFirstAgent = index === firstAgentIndex;

                      return (
                        <React.Fragment key={sectionKey}>
                          {isFirstAgent && (
                            <div className="flex items-center gap-3 py-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                              <div className="flex-1 h-px bg-border"></div>
                              <span>에이전트 관련</span>
                              <div className="flex-1 h-px bg-border"></div>
                            </div>
                          )}
                          <AccordionItem value={sectionKey} className="border rounded-md bg-card shadow-sm">
                            <AccordionTrigger className="py-2 px-3 text-sm font-bold uppercase tracking-wider hover:no-underline">
                              <div className="flex items-center gap-2">
                                {sectionKey}
                                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">
                                  {fieldCount}
                                </Badge>
                                {modifiedCount > 0 && (
                                  <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 text-orange-600 border-orange-400 dark:text-orange-400 dark:border-orange-500">
                                    {modifiedCount} modified
                                  </Badge>
                                )}
                              </div>
                            </AccordionTrigger>
                            <AccordionContent className="p-3 pt-0 border-t">
                              <div className="grid grid-cols-1 gap-2 mt-3">
                                {isObject(sectionData) ? (
                                  Object.entries(sectionData as object).map(([key, value]) =>
                                    renderField([sectionKey], key, value)
                                  )
                                ) : (
                                  renderField([], sectionKey, sectionData)
                                )}
                              </div>
                            </AccordionContent>
                          </AccordionItem>
                          {index === lastAgentIndex && (
                            <div className="flex items-center gap-3 py-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                              <div className="flex-1 h-px bg-border"></div>
                            </div>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </Accordion>
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </ScrollArea>
      </div>
      <div
        className="transition-all duration-300 ease-in-out border-l bg-background overflow-hidden shrink-0"
        style={{ width: panelOpen ? '360px' : '0px', pointerEvents: panelOpen ? 'auto' : 'none' }}
      >
        <div className="w-[360px] h-full">
          <SettingsFindReplace config={merged} onReplace={handlePanelReplace} onClose={() => setPanelOpen(false)} />
        </div>
      </div>
      <SetupWizardModal
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        projectId={projectId}
        onApplied={fetchConfig}
      />
      <PresetManagerModal
        open={presetManagerOpen}
        onOpenChange={setPresetManagerOpen}
        projectId={projectId}
        onApplied={fetchConfig}
      />
      <Dialog open={showConfirmModal} onOpenChange={setShowConfirmModal}>
        <DialogContent className="max-h-[80vh] overflow-hidden sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>변경사항 확인</DialogTitle>
          </DialogHeader>
          {diffChanges.length === 0 ? (
            <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground bg-muted/20 rounded-xl border border-dashed">
              변경 사항 없음
            </div>
          ) : (
            <div className="space-y-3 overflow-y-auto pr-1" role="list">
              <div className="text-sm font-medium">{diffChanges.length}건 변경</div>
              {diffChanges.map((change, idx) => (
                <div key={`${change.path}-${idx}`} role="listitem" className="rounded-xl border bg-card p-3 flex flex-col gap-1.5 text-sm">
                  <div className="font-semibold text-foreground break-all">{change.path}</div>
                  <div className="flex items-center gap-2 text-xs font-mono w-full">
                    <span className="text-muted-foreground bg-muted px-2 py-1 rounded truncate flex-1 opacity-70">
                      {change.from === undefined ? '(없음)' : JSON.stringify(change.from)}
                    </span>
                    <span className="text-muted-foreground shrink-0">→</span>
                    <span className="text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/30 px-2 py-1 rounded truncate flex-1 font-semibold">
                      {change.to === undefined ? '(없음)' : JSON.stringify(change.to)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConfirmModal(false)} disabled={saving}>
              취소
            </Button>
            <Button onClick={handleConfirmSave} disabled={saving || diffChanges.length === 0}>
              {saving ? '저장 중...' : '저장'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
