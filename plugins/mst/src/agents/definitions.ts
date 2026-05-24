/**
 * Gran Maestro 플러그인 에이전트 정의
 *
 * Claude Code 플러그인 시스템에서 에이전트를 등록하는 레지스트리입니다.
 * 각 에이전트는 Task(subagent_type="mst:<name>") 형태로 호출됩니다.
 */

export interface AgentDefinition {
  name: string;
  description: string;
  model: 'haiku' | 'sonnet' | 'opus';
  tools: string[];
  systemPromptFile: string;
  /** Fallback agent name when this agent fails */
  fallback?: string;
  /** Maximum fallback chain depth (default: 1) */
  maxFallbackDepth?: number;
  /** Provider for CLI-based agents */
  provider?: 'claude' | 'codex' | 'gemini';
  /** Capabilities for agent selection */
  capabilities?: string[];
  /** Condition for automatic spawning */
  spawnCondition?: string;
  /** Logical category for orchestration compatibility */
  agentCategory?: 'analysis' | 'execution' | 'review' | 'design' | 'feedback';
}

export const agents: Record<string, AgentDefinition> = {
  // ─── Analysis Agents (Phase 1) ────────────────────────────

  // NOTE: model 필드는 기본값. 실제 런타임에서는 config.json의 models.roles.{역할} 경유 후 providers에서 resolve.
  // pm_conductor → models.roles.pm_conductor → providers.claude[tier]
  // architect → models.roles.architect → providers.claude[tier]
  'pm-conductor': {
    name: 'pm-conductor',
    description:
      'PM Conductor — Phase 1 & 3 리더. 요구사항 분석, 스펙 작성, 리뷰 조율, 사용자 커뮤니케이션',
    model: 'opus',
    tools: ['Read', 'Glob', 'Grep', 'Write', 'Bash', 'Task', 'AskUserQuestion'],
    systemPromptFile: 'agents/pm-conductor.md',
    provider: 'claude',
    capabilities: ['analysis', 'spec-writing', 'review', 'coordination'],
    agentCategory: 'analysis',
  },

  // ─── Design Wing (Phase 1, conditional) ───────────────────

  'architect': {
    name: 'architect',
    description:
      'Design Wing — 시스템 아키텍처, API 설계, 모듈 경계, 의존성 방향 설계',
    model: 'opus',
    tools: ['Read', 'Glob', 'Grep', 'Write'],
    systemPromptFile: 'agents/architect.md',
    provider: 'claude',
    capabilities: ['system-design', 'api-design', 'module-boundaries'],
    spawnCondition: 'new_module || structural_change',
    agentCategory: 'design',
  },
};

/**
 * 논리 역할 → 에이전트 키 매핑 테이블
 *
 * | 논리 역할 | agents.json 키 | 유형 | Phase |
 * |----------|----------------|------|-------|
 * | PM Conductor | pm-conductor | analysis | 1, 3 |
 * | Explorer (/mst:codex) | codex (precision symbol tracing) | analysis | 1 |
 * | Analyst (/mst:codex) | codex (requirements gap analysis) | analysis | 1 |
 * | Architect | architect | analysis | 1 |
 * | Schema Designer | (스킬 전환: skills/schema-designer/) | analysis | 1 |
 * | UI Designer | (스킬 전환: skills/ui-designer/) | analysis | 1 |
 * | Codex Developer | codex-dev (agents.json) | execution | 2 |
 * | Gemini Developer | gemini-dev (agents.json) | execution | 2 |
 * | Security Reviewer (/mst:codex) | codex (security review) | review | 3 |
 * | Quality Reviewer (/mst:codex) | codex (quality review) | review | 3 |
 * | Verifier (/mst:codex) | codex (acceptance verification) | review | 3 |
 * | Codex Reviewer | codex-reviewer (agents.json) | review | 3 |
 * | Gemini Reviewer | gemini-reviewer (agents.json) | review | 3 |
 * | Feedback Composer | (스킬 전환: skills/feedback-composer/) | — | 4 |
 *
 * Note: Execution agents (codex-dev, gemini-dev) and review agents
 * (codex-reviewer, gemini-reviewer) are defined in the runtime
 * agents.json file at .gran-maestro/agents.json, not here.
 * They are invoked via CLI (Phase 2) or MCP (Phase 1, 3).
 * Schema Designer, UI Designer, Feedback Composer are migrated to skills
 * and are called through /mst:* Skill invocations.
 *
 * The outsource-brief.md is a template (not an agent).
 * PM Conductor substitutes variables and passes it to CLI agents.
 */
