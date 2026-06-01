import React, { useEffect, useState, useRef } from 'react';
import {
  Bot,
  Brain,
  ClipboardCheck,
  Code2,
  Cpu,
  Gauge,
  PiggyBank,
  Sparkles,
  Users,
  Wrench,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { apiFetch } from '@/hooks/useApi';
import { cn, deepSet, getNestedValue } from '@/lib/utils';
import type { PresetMeta, PresetDiffChange } from '../../../../src/types';

type WizardStep = 1 | 2 | 3 | 4 | 5 | 6;
type AgentSelection = 'codex-primary' | 'claude' | 'claude-codex' | 'claude-agy' | 'full-team';
type TierSelection = 'performance' | 'efficient' | 'budget';

type ToolToggles = {
  stitch: boolean;
  codeReview: boolean;
  planReview: boolean;
};

type SetupWizardModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  onApplied: () => void;
};

type ConfigResponse = {
  merged: Record<string, unknown>;
};

type PresetResponse = {
  builtin: PresetMeta[];
};

const STEP_LABELS = ['Git', '에이전트', '성향', 'Agent 미세조정', '도구', '리뷰'] as const;

const AGENT_FEATURES = [
  { id: 'discussion', label: 'Discussion' },
  { id: 'ideation', label: 'Ideation' },
  { id: 'collaborative_debug', label: 'Collaborative Debug' },
  { id: 'debug', label: 'Debug' },
  { id: 'explore', label: 'Explore' },
  { id: 'prereview', label: 'Prereview' },
];
const AGENT_TYPES = ['codex', 'agy', 'claude'];

const AGENT_OPTIONS: Array<{
  id: AgentSelection;
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  {
    id: 'codex-primary',
    title: 'Codex Primary',
    description: 'Codex를 기본 지휘/구현 런타임으로 사용합니다.',
    icon: Code2,
  },
  {
    id: 'claude',
    title: 'Claude Only',
    description: 'Claude 단독으로 단순하고 안정적인 구성을 사용합니다.',
    icon: Bot,
  },
  {
    id: 'claude-codex',
    title: 'Claude + Codex',
    description: 'Claude 기반에 Codex를 더해 구현 생산성을 높입니다.',
    icon: Brain,
  },
  {
    id: 'claude-agy',
    title: 'Claude + AGY',
    description: 'Claude 기반에 AGY를 더해 다양한 관점을 확보합니다.',
    icon: Sparkles,
  },
  {
    id: 'full-team',
    title: 'Full Team',
    description: 'Claude + Codex + AGY 전체 팀 구성으로 운영합니다.',
    icon: Users,
  },
];

const TIER_OPTIONS: Array<{
  id: TierSelection;
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  {
    id: 'performance',
    title: '성능 (Performance)',
    description: '최고 성능 기준으로 모델과 에이전트를 구성합니다.',
    icon: Gauge,
  },
  {
    id: 'efficient',
    title: '효율 (Efficient)',
    description: '성능과 비용의 균형을 맞춘 기본 구성을 사용합니다.',
    icon: Cpu,
  },
  {
    id: 'budget',
    title: '절약 (Budget)',
    description: '비용 절약 중심으로 경량 구성을 사용합니다.',
    icon: PiggyBank,
  },
];

const INITIAL_TOGGLES: ToolToggles = {
  stitch: false,
  codeReview: false,
  planReview: false,
};

function resolvePresetId(
  selectedAgent: AgentSelection,
  selectedTier: TierSelection,
  builtinPresets: PresetMeta[],
): string | null {
  const matchedPreset = builtinPresets.find(
    (preset) => preset.wizardCategory === selectedAgent && preset.tier === selectedTier,
  );
  return matchedPreset?.id ?? null;
}

export function SetupWizardModal({ open, onOpenChange, projectId, onApplied }: SetupWizardModalProps) {
  const [step, setStep] = useState<WizardStep>(1);
  const [selectedAgent, setSelectedAgent] = useState<AgentSelection | null>(null);
  const [selectedTier, setSelectedTier] = useState<TierSelection | null>(null);
  const [toolToggles, setToolToggles] = useState<ToolToggles>(INITIAL_TOGGLES);
  const [initialToggles, setInitialToggles] = useState<ToolToggles>(INITIAL_TOGGLES);
  const [builtinPresets, setBuiltinPresets] = useState<PresetMeta[]>([]);
  const [initializing, setInitializing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [agentOverrides, setAgentOverrides] = useState<Record<string, number | string>>({});
  const [currentConfig, setCurrentConfig] = useState<Record<string, unknown>>({});

  const [baseBranch, setBaseBranch] = useState<string>('');
  const [baseBranchLoaded, setBaseBranchLoaded] = useState(false);
  const [initialBaseBranch, setInitialBaseBranch] = useState<string>('main');

  const [diffChanges, setDiffChanges] = useState<PresetDiffChange[]>([]);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [agentPreloadError, setAgentPreloadError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const prefetchRequestIdRef = useRef<number>(0);

  useEffect(() => {
    if (!open || !projectId) return;

    let isMounted = true;

    const initializeWizard = async () => {
      setStep(1);
      setSelectedAgent(null);
      setSelectedTier(null);
      setBuiltinPresets([]);
      setToolToggles(INITIAL_TOGGLES);
      setInitialToggles(INITIAL_TOGGLES);
      setDiffChanges([]);
      setDiffError(null);
      setAgentPreloadError(null);
      setApplyError(null);
      setBaseBranch('');
      setBaseBranchLoaded(false);
      setAgentOverrides({});
      setCurrentConfig({});
      setInitializing(true);

      try {
        const [configResponse, presetResponse] = await Promise.all([
          apiFetch<ConfigResponse>('/api/config', projectId),
          apiFetch<PresetResponse>('/api/presets', projectId),
        ]);

        if (!isMounted) return;

        const mergedConfig = configResponse.merged ?? {};
        setCurrentConfig(mergedConfig);
        const loadedToggles = {
          stitch: Boolean(getNestedValue(mergedConfig, ['stitch', 'enabled'])),
          codeReview: Boolean(getNestedValue(mergedConfig, ['code_review', 'enabled'])),
          planReview: Boolean(getNestedValue(mergedConfig, ['plan_review', 'enabled'])),
        };
        setToolToggles(loadedToggles);
        setInitialToggles(loadedToggles);
        setBuiltinPresets(Array.isArray(presetResponse.builtin) ? presetResponse.builtin : []);

        const loadedBaseBranch = String(
          getNestedValue(mergedConfig, ['worktree', 'base_branch']) ?? 'main'
        );
        setBaseBranch(loadedBaseBranch);
        setInitialBaseBranch(loadedBaseBranch);
        setBaseBranchLoaded(true);
      } catch (err) {
        if (!isMounted) return;
        console.error('Failed to initialize setup wizard:', err);
      } finally {
        if (isMounted) {
          setInitializing(false);
        }
      }
    };

    void initializeWizard();

    return () => {
      isMounted = false;
    };
  }, [open, projectId]);

  const canGoBack = step > 1;
  const canGoNext =
    (step === 1 && baseBranch.trim().length > 0) ||
    (step === 2 && !!selectedAgent) ||
    (step === 3 && !!selectedTier) ||
    (step === 4 && !loadingDiff && !agentPreloadError) ||
    step === 5;

  const canApply =
    step === 6 &&
    !!selectedAgent &&
    !!selectedTier &&
    baseBranch.trim().length > 0 &&
    !initializing &&
    !applying &&
    !diffError &&
    !loadingDiff;

  const fetchDiff = async () => {
    if (!projectId || !selectedAgent || !selectedTier) return;
    const presetId = resolvePresetId(selectedAgent, selectedTier, builtinPresets);
    if (!presetId) {
      setDiffError('프리셋을 찾을 수 없습니다.');
      return;
    }

    setLoadingDiff(true);
    setDiffError(null);
    try {
      const diffResponse = await apiFetch<{ changes: PresetDiffChange[] }>(
        `/api/presets/${presetId}/diff`,
        projectId,
        { method: 'POST' }
      );

      const serverChanges = diffResponse.changes || [];
      const toolChanges: PresetDiffChange[] = [];

      if (baseBranch !== initialBaseBranch) {
        toolChanges.push({ path: 'worktree.base_branch', from: initialBaseBranch, to: baseBranch.trim() });
      }

      if (initialToggles.stitch !== toolToggles.stitch) {
        toolChanges.push({ path: 'stitch.enabled', from: initialToggles.stitch, to: toolToggles.stitch });
      }
      if (initialToggles.codeReview !== toolToggles.codeReview) {
        toolChanges.push({ path: 'code_review.enabled', from: initialToggles.codeReview, to: toolToggles.codeReview });
      }
      if (initialToggles.planReview !== toolToggles.planReview) {
        toolChanges.push({ path: 'plan_review.enabled', from: initialToggles.planReview, to: toolToggles.planReview });
      }

      const toolPaths = new Set(toolChanges.map((c) => c.path));
      const filteredServerChanges = serverChanges.filter((c) => !toolPaths.has(c.path));
      const mergedChanges = [...filteredServerChanges, ...toolChanges];

      const finalChanges = [...mergedChanges];
      Object.entries(agentOverrides).forEach(([path, value]) => {
        const existingIndex = finalChanges.findIndex(c => c.path === path);
        if (existingIndex >= 0) {
          finalChanges[existingIndex] = { ...finalChanges[existingIndex], to: value };
        } else {
          finalChanges.push({ path, from: getNestedValue(currentConfig, path.split('.')), to: value });
        }
      });

      setDiffChanges(finalChanges);
    } catch (err) {
      setDiffError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDiff(false);
    }
  };

  const handleNext = async () => {
    if (step === 1 && baseBranch.trim().length > 0) { setStep(2); return; }
    if (step === 2 && selectedAgent) { setStep(3); return; }
    if (step === 3 && selectedTier) {
      setStep(4);
      if (Object.keys(agentOverrides).length === 0) {
        setLoadingDiff(true);
        setAgentPreloadError(null);
        const reqId = ++prefetchRequestIdRef.current;
        try {
          const presetId = resolvePresetId(selectedAgent!, selectedTier, builtinPresets);
          if (presetId) {
            const diffResponse = await apiFetch<{ changes: PresetDiffChange[] }>(
              `/api/presets/${presetId}/diff`,
              projectId,
              { method: 'POST' }
            );
            if (reqId !== prefetchRequestIdRef.current) return;
            const changes = diffResponse.changes || [];
            const overrides: Record<string, number | string> = {};
            changes.forEach((c) => {
              if (c.path.includes('.agents.')) {
                overrides[c.path] = c.to as number | string;
              }
            });
            setAgentOverrides(overrides);
          }
        } catch (err) {
          if (reqId !== prefetchRequestIdRef.current) return;
          console.error(err);
          setAgentPreloadError(err instanceof Error ? err.message : String(err));
        } finally {
          if (reqId === prefetchRequestIdRef.current) {
            setLoadingDiff(false);
          }
        }
      }
      return;
    }
    if (step === 4) { setStep(5); return; }
    if (step === 5) {
      setStep(6);
      setDiffChanges([]);
      void fetchDiff();
      return;
    }
  };

  const handleBack = () => {
    if (step === 6) { setStep(5); return; }
    if (step === 5) { setStep(4); return; }
    if (step === 4) { setStep(3); return; }
    if (step === 3) { setStep(2); return; }
    if (step === 2) { setStep(1); }
  };

  const handleApply = async () => {
    if (!projectId || !selectedAgent || !selectedTier) return;

    const presetId = resolvePresetId(selectedAgent, selectedTier, builtinPresets);
    if (!presetId) {
      setApplyError('프리셋을 찾을 수 없습니다');
      return;
    }
    setApplyError(null);
    setApplying(true);

    try {
      try {
        await apiFetch(`/api/presets/${presetId}/apply`, projectId, { method: 'POST' });
      } catch (err) {
        setApplyError(`프리셋 적용 실패: ${err instanceof Error ? err.message : String(err)}`);
        return;
      }

      try {
        const configResponse = await apiFetch<ConfigResponse>('/api/config', projectId);
        let nextConfig: Record<string, unknown> = configResponse.merged ?? {};
        nextConfig = deepSet(nextConfig, ['stitch', 'enabled'], toolToggles.stitch);
        nextConfig = deepSet(nextConfig, ['code_review', 'enabled'], toolToggles.codeReview);
        nextConfig = deepSet(nextConfig, ['plan_review', 'enabled'], toolToggles.planReview);
        nextConfig = deepSet(nextConfig, ['worktree', 'base_branch'], baseBranch.trim());

        Object.entries(agentOverrides).forEach(([path, value]) => {
          const pathParts = path.split('.');
          nextConfig = deepSet(nextConfig, pathParts, value);
        });

        await apiFetch('/api/config', projectId, {
          method: 'PUT',
          body: JSON.stringify(nextConfig),
        });
      } catch (_err) {
        setApplyError('프리셋은 적용되었으나 도구 설정 적용에 실패했습니다');
        return;
      }

      onOpenChange(false);
      onApplied();
    } finally {
      setApplying(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !applying && onOpenChange(nextOpen)}>
      <DialogContent className="max-w-3xl p-0 overflow-hidden gap-0 flex flex-col max-h-[90vh]">
        <DialogHeader className="px-6 py-5 border-b bg-gradient-to-r from-amber-50 via-orange-50 to-rose-50 dark:from-zinc-900 dark:via-zinc-900 dark:to-zinc-800 shrink-0">
          <DialogTitle className="text-xl flex items-center gap-2">
            <Wrench className="h-5 w-5 text-amber-600 dark:text-amber-400" />
            설정 마법사
          </DialogTitle>
          <DialogDescription>
            6단계로 Git 설정, 에이전트 조합, 성향, 세부 조정 및 도구 설정을 한 번에 적용합니다.
          </DialogDescription>
          <div className="flex items-center gap-2 pt-3">
            {STEP_LABELS.map((label, index) => {
              const stepNumber = (index + 1) as WizardStep;
              const isCurrent = step === stepNumber;
              const isCompleted = step > stepNumber;

              return (
                <React.Fragment key={label}>
                  <div className="flex items-center gap-2">
                    <div
                      className={cn(
                        'h-8 w-8 rounded-full flex items-center justify-center text-sm font-semibold border transition-colors',
                        isCurrent && 'bg-amber-500 border-amber-500 text-white',
                        isCompleted && 'bg-emerald-500 border-emerald-500 text-white',
                        !isCurrent && !isCompleted && 'bg-background border-muted-foreground/30 text-muted-foreground',
                      )}
                    >
                      {stepNumber}
                    </div>
                    <span
                      className={cn(
                        'text-sm',
                        isCurrent ? 'text-foreground font-semibold' : 'text-muted-foreground',
                      )}
                    >
                      {label}
                    </span>
                  </div>
                  {index < STEP_LABELS.length - 1 && (
                    <div className={cn('h-px flex-1', step > stepNumber ? 'bg-emerald-500' : 'bg-muted-foreground/30')} />
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </DialogHeader>

        <div className="px-6 py-6 min-h-[360px] overflow-y-auto">
          {initializing ? (
            <div className="h-[300px] flex items-center justify-center text-sm text-muted-foreground animate-pulse">
              현재 설정을 불러오는 중...
            </div>
          ) : (
            <>
              {step === 1 && (
                <div className="space-y-5">
                  <p className="text-sm text-muted-foreground">
                    새 워크트리를 어느 브랜치 기준으로 생성할지 지정합니다.
                  </p>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Base Branch</label>
                    <div className="flex items-center gap-2">
                      <Input
                        value={baseBranch}
                        onChange={(e) => setBaseBranch(e.target.value)}
                        placeholder="예: master, main, develop"
                        className="font-mono"
                        disabled={initializing || !baseBranchLoaded}
                      />
                      {baseBranch.trim() === 'main' && (
                        <Badge
                          variant="outline"
                          className="text-amber-600 border-amber-400 dark:text-amber-400 dark:border-amber-500 shrink-0"
                        >
                          기본값
                        </Badge>
                      )}
                    </div>
                    {baseBranch.trim() === 'main' && (
                      <p className="text-xs text-amber-600 dark:text-amber-400">
                        현재 "main"으로 설정되어 있습니다. 실제 작업 브랜치로 변경하는 것을 권장합니다.
                      </p>
                    )}
                    {!baseBranchLoaded && !initializing && (
                      <p className="text-xs text-destructive">
                        설정을 불러오지 못했습니다. 페이지를 닫고 다시 시도하세요.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {step === 2 && (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">원하는 에이전트 조합을 선택하세요.</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {AGENT_OPTIONS.map((option) => {
                      const Icon = option.icon;
                      const selected = selectedAgent === option.id;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          aria-pressed={selected}
                          onClick={() => {
                            setSelectedAgent(option.id);
                            setSelectedTier(null);
                            setAgentOverrides({});
                          }}
                          className={cn(
                            'rounded-2xl border p-4 text-left transition-colors',
                            'focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2',
                            'hover:border-amber-400 hover:bg-amber-50/60 dark:hover:bg-zinc-800',
                            selected
                              ? 'border-amber-500 bg-amber-50 dark:bg-amber-950/30'
                              : 'border-border bg-card',
                          )}
                        >
                          <div className="flex items-start gap-3">
                            <div className="rounded-xl bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 p-2">
                              <Icon className="h-4 w-4" />
                            </div>
                            <div className="space-y-1">
                              <div className="font-semibold text-sm">{option.title}</div>
                              <p className="text-xs text-muted-foreground">{option.description}</p>
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {step === 3 && (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">작업 성향을 선택하세요.</p>
                  <div className="grid gap-3 sm:grid-cols-3">
                    {TIER_OPTIONS.map((option) => {
                      const Icon = option.icon;
                      const selected = selectedTier === option.id;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          aria-pressed={selected}
                          onClick={() => {
                            setSelectedTier(option.id);
                            setAgentOverrides({});
                            ++prefetchRequestIdRef.current;
                          }}
                          className={cn(
                            'rounded-2xl border p-4 text-left transition-colors',
                            'focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2',
                            'hover:border-orange-400 hover:bg-orange-50/60 dark:hover:bg-zinc-800',
                            selected
                              ? 'border-orange-500 bg-orange-50 dark:bg-orange-950/30'
                              : 'border-border bg-card',
                          )}
                        >
                          <div className="flex items-start gap-3">
                            <div className="rounded-xl bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300 p-2">
                              <Icon className="h-4 w-4" />
                            </div>
                            <div className="space-y-1">
                              <div className="font-semibold text-sm">{option.title}</div>
                              <p className="text-xs text-muted-foreground">{option.description}</p>
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {step === 4 && (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">기능별 에이전트 할당량과 성향을 미세 조정합니다.</p>
                  {loadingDiff ? (
                    <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground animate-pulse">
                      에이전트 설정을 불러오는 중...
                    </div>
                  ) : agentPreloadError ? (
                    <div className="h-[200px] flex flex-col items-center justify-center gap-2 text-destructive">
                      <div className="text-sm font-semibold">오류가 발생했습니다</div>
                      <div className="text-xs">{agentPreloadError}</div>
                      <Button variant="outline" size="sm" onClick={() => { setAgentPreloadError(null); setAgentOverrides({}); ++prefetchRequestIdRef.current; setStep(3); }} className="mt-2">
                        재시도
                      </Button>
                    </div>
                  ) : (
                    <div className="overflow-x-auto rounded-xl border bg-card">
                      <table className="w-full text-sm text-left">
                        <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
                          <tr>
                            <th className="px-4 py-3 font-semibold">기능</th>
                            {AGENT_TYPES.map(agent => (
                              <th key={agent} className="px-4 py-3 font-semibold capitalize">{agent}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y">
                          {AGENT_FEATURES.map(feature => (
                            <tr key={feature.id} className="hover:bg-muted/30 transition-colors">
                              <td className="px-4 py-3 font-medium whitespace-nowrap">{feature.label}</td>
                              {AGENT_TYPES.map(agent => {
                                const countPath = `${feature.id}.agents.${agent}.count`;
                                const tierPath = `${feature.id}.agents.${agent}.tier`;
                                
                                const countVal = agentOverrides[countPath] ?? (getNestedValue(currentConfig, countPath.split('.')) as number | undefined) ?? 0;
                                const tierVal = agentOverrides[tierPath] ?? (getNestedValue(currentConfig, tierPath.split('.')) as string | undefined) ?? 'economy';

                                return (
                                  <td key={agent} className="px-4 py-3 min-w-[120px]">
                                    <div className="flex flex-col gap-1.5">
                                      <div className="flex items-center gap-2">
                                        <span className="text-xs text-muted-foreground w-10">Count</span>
                                        <Input 
                                          type="number" 
                                          min={0}
                                          className="h-7 w-16 text-xs px-2"
                                          value={countVal}
                                          onChange={(e) => setAgentOverrides(prev => ({ ...prev, [countPath]: Math.max(0, parseInt(e.target.value) || 0) }))}
                                        />
                                      </div>
                                      <div className="flex items-center gap-2">
                                        <span className="text-xs text-muted-foreground w-10">Tier</span>
                                        <select 
                                          className="flex h-7 w-[85px] rounded-md border border-input bg-background px-2 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                          value={tierVal}
                                          onChange={(e) => setAgentOverrides(prev => ({ ...prev, [tierPath]: e.target.value }))}
                                        >
                                          <option value="premium">Premium</option>
                                          <option value="economy">Economy</option>
                                        </select>
                                      </div>
                                    </div>
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {step === 5 && (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">원하는 도구만 켜서 세부 동작을 맞춤화하세요.</p>
                  <div className="space-y-3">
                    <div className="rounded-xl border bg-card p-4 flex items-center justify-between gap-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 text-sm font-semibold">
                          <Sparkles className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                          Stitch
                        </div>
                        <p className="text-xs text-muted-foreground">UI 설계/캡처 기반 워크플로우를 활성화합니다.</p>
                      </div>
                      <Switch
                        aria-label="Stitch"
                        checked={toolToggles.stitch}
                        onCheckedChange={(checked) => setToolToggles((prev) => ({ ...prev, stitch: checked }))}
                      />
                    </div>

                    <div className="rounded-xl border bg-card p-4 flex items-center justify-between gap-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 text-sm font-semibold">
                          <Code2 className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                          Code Review
                        </div>
                        <p className="text-xs text-muted-foreground">구현 완료 후 코드 리뷰 단계를 활성화합니다.</p>
                      </div>
                      <Switch
                        aria-label="Code Review"
                        checked={toolToggles.codeReview}
                        onCheckedChange={(checked) => setToolToggles((prev) => ({ ...prev, codeReview: checked }))}
                      />
                    </div>

                    <div className="rounded-xl border bg-card p-4 flex items-center justify-between gap-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 text-sm font-semibold">
                          <ClipboardCheck className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                          Plan Review
                        </div>
                        <p className="text-xs text-muted-foreground">실행 계획 검토 단계를 활성화합니다.</p>
                      </div>
                      <Switch
                        aria-label="Plan Review"
                        checked={toolToggles.planReview}
                        onCheckedChange={(checked) => setToolToggles((prev) => ({ ...prev, planReview: checked }))}
                      />
                    </div>
                  </div>
                </div>
              )}

              {step === 6 && (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">적용될 설정 변경 사항을 확인하세요.</p>

                  {loadingDiff ? (
                    <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground animate-pulse">
                      변경사항을 계산 중입니다...
                    </div>
                  ) : diffError ? (
                    <div className="h-[200px] flex flex-col items-center justify-center gap-2 text-destructive">
                      <div className="text-sm font-semibold">오류가 발생했습니다</div>
                      <div className="text-xs">{diffError}</div>
                      <Button variant="outline" size="sm" onClick={() => void fetchDiff()} className="mt-2">
                        재시도
                      </Button>
                    </div>
                  ) : diffChanges.length === 0 ? (
                    <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground bg-muted/20 rounded-xl border border-dashed">
                      변경 사항 없음
                    </div>
                  ) : (
                    <div className="space-y-3" role="list">
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
                </div>
              )}
            </>
          )}
        </div>

        <DialogFooter className="px-6 py-4 border-t bg-muted/25 flex-row items-center justify-between shrink-0">
          <div className="text-xs text-muted-foreground">
            {applyError ? (
              <span className="text-destructive font-medium">{applyError}</span>
            ) : (
              <>
                {step === 1 && 'Step 1/6: Git 설정'}
                {step === 2 && 'Step 2/6: 에이전트 조합 선택'}
                {step === 3 && 'Step 3/6: 성향 선택'}
                {step === 4 && 'Step 4/6: Agent 미세조정'}
                {step === 5 && 'Step 5/6: 도구 커스터마이즈'}
                {step === 6 && 'Step 6/6: 리뷰 및 적용'}
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={handleBack} disabled={!canGoBack || initializing || applying}>
              Back
            </Button>
            {step < 6 ? (
              <Button onClick={() => void handleNext()} disabled={!canGoNext || initializing || applying}>
                Next
              </Button>
            ) : (
              <Button onClick={() => void handleApply()} disabled={!canApply}>
                {applying ? 'Applying...' : 'Apply'}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
