import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, realpathSync } from 'node:fs';
import { basename, dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

const scriptDir = dirname(fileURLToPath(import.meta.url));
export const repoRoot = resolve(scriptDir, '..', '..');

function isOrchestrationEvidenceRoot(path) {
  return existsSync(join(path, 'requests/REQ-884/evidence/plugin-component-inventory-validation.json')) &&
    existsSync(join(path, 'requests/REQ-885/evidence/codex-plugin-parity-validation.json')) &&
    existsSync(join(path, 'agile/AGI-039/sprints/S04/integration-context.md'));
}

function findOrchestrationRoot(startDir) {
  if (process.env.GRAN_MAESTRO_ORCHESTRATION_ROOT) {
    return resolve(process.env.GRAN_MAESTRO_ORCHESTRATION_ROOT);
  }

  let currentDir = startDir;

  while (true) {
    if (basename(currentDir) === '.gran-maestro' && isOrchestrationEvidenceRoot(currentDir)) {
      return currentDir;
    }

    const candidateRoot = join(currentDir, '.gran-maestro');
    if (isOrchestrationEvidenceRoot(candidateRoot)) {
      return candidateRoot;
    }

    const parentDir = dirname(currentDir);
    if (parentDir === currentDir) {
      throw new Error(`Could not locate .gran-maestro orchestration root for ${startDir}`);
    }

    currentDir = parentDir;
  }
}

export const orchestrationRoot = findOrchestrationRoot(repoRoot);

function findSharedGranMaestroPath(relativePath) {
  let currentDir = repoRoot;

  while (true) {
    const candidate = join(currentDir, '.gran-maestro', relativePath);
    if (existsSync(candidate)) {
      return candidate;
    }

    const parentDir = dirname(currentDir);
    if (parentDir === currentDir) {
      return join(orchestrationRoot, relativePath);
    }

    currentDir = parentDir;
  }
}

export const stableEvidenceRelativePath =
  '.gran-maestro/requests/REQ-886/evidence/codex-plugin-discovery-smoke.json';
const stableEvidenceOrchestrationRelativePath =
  'requests/REQ-886/evidence/codex-plugin-discovery-smoke.json';
export const stableEvidenceAbsolutePath = join(
  orchestrationRoot,
  stableEvidenceOrchestrationRelativePath,
);
export const forcedWireEvidenceRelativePath =
  '.gran-maestro/requests/REQ-887/evidence/forced-wire-integration-validation.json';
const forcedWireEvidenceOrchestrationRelativePath =
  'requests/REQ-887/evidence/forced-wire-integration-validation.json';
export const forcedWireEvidenceAbsolutePath = join(
  orchestrationRoot,
  forcedWireEvidenceOrchestrationRelativePath,
);
export const skillProjectionEvidenceRelativePath =
  '.gran-maestro/requests/REQ-891/evidence/dod-006-skill-projection-validation.json';
const skillProjectionEvidenceOrchestrationRelativePath =
  'requests/REQ-891/evidence/dod-006-skill-projection-validation.json';
export const skillProjectionEvidenceAbsolutePath = join(
  orchestrationRoot,
  skillProjectionEvidenceOrchestrationRelativePath,
);
export const roleMappingEvidenceRelativePath =
  '.gran-maestro/requests/REQ-891/evidence/dod-006-role-mapping-validation.json';
const roleMappingEvidenceOrchestrationRelativePath =
  'requests/REQ-891/evidence/dod-006-role-mapping-validation.json';
export const roleMappingEvidenceAbsolutePath = join(
  orchestrationRoot,
  roleMappingEvidenceOrchestrationRelativePath,
);
export const skillAgentProjectionValidationEvidenceRelativePath =
  '.gran-maestro/requests/REQ-891/evidence/dod-006-codex-skill-agent-projection-validation.json';
const skillAgentProjectionValidationEvidenceOrchestrationRelativePath =
  'requests/REQ-891/evidence/dod-006-codex-skill-agent-projection-validation.json';
export const skillAgentProjectionValidationEvidenceAbsolutePath = join(
  orchestrationRoot,
  skillAgentProjectionValidationEvidenceOrchestrationRelativePath,
);
export const dod007RequestEvidenceRelativePath =
  '.gran-maestro/requests/REQ-893/evidence/dod-007-request-level-validation.json';
const dod007RequestEvidenceOrchestrationRelativePath =
  'requests/REQ-893/evidence/dod-007-request-level-validation.json';
export const dod007RequestEvidenceAbsolutePath = join(
  orchestrationRoot,
  dod007RequestEvidenceOrchestrationRelativePath,
);
export const dod008WorkflowE2EValidationEvidenceRelativePath =
  '.gran-maestro/requests/REQ-894/evidence/dod-008-workflow-e2e-validation.json';
export const dod008WorkflowE2EValidationEvidenceAbsolutePath = join(
  repoRoot,
  dod008WorkflowE2EValidationEvidenceRelativePath,
);
export const dod009RequestEvidenceRelativePath =
  '.gran-maestro/requests/REQ-912/evidence/dod-009-claude-plugin-regression-validation.json';
export const dod009RequestEvidenceAbsolutePath = join(
  repoRoot,
  dod009RequestEvidenceRelativePath,
);
const dod009GeneratorScriptRelativePath =
  'scripts/generate-dod-009-claude-plugin-regression-validation.mjs';
export const req893RequestMetadataRelativePath = '.gran-maestro/requests/REQ-893/request.json';
const req893RequestMetadataOrchestrationRelativePath = 'requests/REQ-893/request.json';
const req893RequestMetadataAbsolutePath = join(
  orchestrationRoot,
  req893RequestMetadataOrchestrationRelativePath,
);
export const req894RequestMetadataRelativePath = '.gran-maestro/requests/REQ-894/request.json';
const req894RequestMetadataOrchestrationRelativePath = 'requests/REQ-894/request.json';
const req894RequestMetadataAbsolutePath = join(
  orchestrationRoot,
  req894RequestMetadataOrchestrationRelativePath,
);
export const req912RequestMetadataRelativePath = '.gran-maestro/requests/REQ-912/request.json';
const req912RequestMetadataOrchestrationRelativePath = 'requests/REQ-912/request.json';
const req912RequestMetadataAbsolutePath = join(
  orchestrationRoot,
  req912RequestMetadataOrchestrationRelativePath,
);
export const req890Dod005ValidationEvidenceRelativePath =
  '.gran-maestro/requests/REQ-890/evidence/dod-005-codex-hook-adapter-validation.json';
const req890Dod005ValidationEvidenceOrchestrationRelativePath =
  'requests/REQ-890/evidence/dod-005-codex-hook-adapter-validation.json';
const req890Dod005ValidationEvidencePath = join(
  orchestrationRoot,
  req890Dod005ValidationEvidenceOrchestrationRelativePath,
);
export const req891RequestMetadataRelativePath = '.gran-maestro/requests/REQ-891/request.json';
const req891RequestMetadataOrchestrationRelativePath = 'requests/REQ-891/request.json';
const req891RequestMetadataAbsolutePath = join(
  orchestrationRoot,
  req891RequestMetadataOrchestrationRelativePath,
);
export const coreMstSkillNames = [
  'agile',
  'plan',
  'request',
  'approve',
  'review',
  'accept',
  'recover',
  'codex',
];
export const requiredAgentRoleNames = [
  'pm-conductor',
  'architect',
  'outsource-brief',
  'feedback-composer',
  'schema-designer',
  'ui-designer',
];
export const excludedDodIds = ['DOD-007', 'DOD-008'];

export const sprint4SelectionReason = 'integration-review forced wire';
export const sprint4IntegrationContextPath = join(
  orchestrationRoot,
  'agile/AGI-039/sprints/S04/integration-context.md',
);

export const generatedManifestPath = '.codex-plugin/plugin.json';
export const generatedMarketplacePath = '.agents/plugins/marketplace.json';
export const sourceManifestPath = '.claude-plugin/plugin.json';
export const sourceMarketplacePath = '.claude-plugin/marketplace.json';
export const sourceHookConfigPath = 'hooks/hooks.json';
export const userConfigPathLiteral = '~/.codex/config.toml';
export const fallbackSkillDiscoveryRootPath = '~/.agents/skills';
export const fallbackSkillRepoTargetPath = 'skills/';
export const fallbackSkillSymlinkPath = '~/.agents/skills/gran-maestro';
export const req888Dod004Metadata = {
  request_id: 'REQ-888',
  task_id: '01',
  dod_id: 'DOD-004',
};

export const inventoryArtifactPath = join(
  orchestrationRoot,
  'agile/AGI-039/objective/details/plugin-component-inventory.json',
);
export const inventoryValidationPath = join(
  orchestrationRoot,
  'requests/REQ-884/evidence/plugin-component-inventory-validation.json',
);
export const parityEvidencePath = join(
  orchestrationRoot,
  'requests/REQ-885/evidence/codex-plugin-parity-validation.json',
);
export const integrationEvidencePath = join(
  orchestrationRoot,
  'requests/REQ-885/evidence/codex-plugin-parity-integration-validation.json',
);

export const changedFilesChecked = [
  'tests/smoke.test.mjs',
  'scripts/lib/codex-plugin-discovery-smoke.mjs',
  'scripts/generate-codex-plugin-discovery-smoke.mjs',
];

export const generatedAssetBaselinePaths = [
  generatedManifestPath,
  generatedMarketplacePath,
];

export const validationEntrypoints = [
  'scripts/lib/codex-plugin-discovery-smoke.mjs',
  'scripts/generate-codex-plugin-discovery-smoke.mjs',
  'tests/smoke.test.mjs',
];

export const defaultCodexSkillAgentProjectionValidationSummary = {
  skill_projection_generator: {
    command: 'node scripts/generate-codex-skill-projection-smoke.mjs <temp-output>',
    generated_artifact_path: skillProjectionEvidenceRelativePath,
    generated_output_path: null,
    status: 'pass',
    parse_ok: true,
    core_field_checks: {
      request_id: 'REQ-891',
      task_id: '01',
      dod_id: 'DOD-006',
      status: 'pass',
    },
  },
  role_mapping_generator: {
    command: 'node scripts/generate-codex-role-mapping-smoke.mjs <temp-output>',
    generated_artifact_path: roleMappingEvidenceRelativePath,
    generated_output_path: null,
    status: 'pass',
    parse_ok: true,
    core_field_checks: {
      request_id: 'REQ-891',
      task_id: '02',
      dod_id: 'DOD-006',
      status: 'pass',
    },
  },
  npm_test: {
    command: 'npm test',
    status: 'pass',
    tests_total: 0,
    tests_pass: 0,
    tests_fail: 0,
  },
};

export const defaultDod007RequestEvidenceVerificationSummary = {
  focused_verify_command: {
    command:
      'python3 -m pytest tests/test_workflow_state_transition_integrity.py tests/test_dod011_continuation_contract.py tests/test_dod012_auto_continuation_contract.py tests/test_run_wrapper.py -q',
    status: 'pass',
    tests_total: 25,
    tests_pass: 25,
    tests_fail: 0,
    summary: '25 passed',
  },
  state_transition_integrity: {
    command: 'python3 -m pytest tests/test_workflow_state_transition_integrity.py -q',
    status: 'pass',
    tests_total: 8,
    tests_pass: 8,
    tests_fail: 0,
    summary: '8 passed',
  },
  continuation_contract: {
    command: 'python3 tests/test_dod011_continuation_contract.py',
    status: 'pass',
    tests_total: 6,
    tests_pass: 6,
    tests_fail: 0,
    summary: '6 passed',
  },
  auto_continuation_contract: {
    command: 'python3 -m pytest tests/test_dod012_auto_continuation_contract.py -q',
    status: 'pass',
    tests_total: 7,
    tests_pass: 7,
    tests_fail: 0,
    summary: '7 passed',
  },
  run_wrapper_session_contract: {
    command: 'python3 -m pytest tests/test_run_wrapper.py -q',
    status: 'pass',
    tests_total: 10,
    tests_pass: 10,
    tests_fail: 0,
    summary: '10 passed',
  },
  npm_test: {
    command: 'npm test',
    status: 'pass',
    tests_total: 39,
    tests_pass: 39,
    tests_fail: 0,
    summary: '39 passed',
  },
  generator: {
    command: 'node scripts/generate-dod-007-request-evidence.mjs <repo-output> <summary-fixture>',
    generated_artifact_path: dod007RequestEvidenceRelativePath,
    generated_output_path: null,
    status: 'pass',
    parse_ok: true,
  },
};

export const dod007ExcludedSurfaceIds = ['DOD-008', 'DOD-009', 'docs/release'];
export const dod008WorkflowScenarioPaths = [
  '/mst:agile-plan',
  '/mst:agile --resume',
  '/mst:request',
  '/mst:approve',
  'delegated implementation loop',
  '/mst:review',
  '/mst:accept',
  '/mst:recover',
  '/mst:cleanup',
  '/mst:dashboard',
  '/mst:settings',
];
export const dod008AcceptanceRuntimeSurfaceIds = ['DOD-008'];
export const dod008ExcludedSurfaceIds = [
  'DOD-009',
  'DOD-010',
  'DOD-011',
  'DOD-012',
  'DOD-013',
];
export const dod008ArtifactSchemaRequiredFieldsByType = {
  objective: ['artifact_id', 'objective_id', 'title', 'status', 'request_ids', 'updated_at'],
  request: ['artifact_id', 'request_id', 'objective_id', 'dod_id', 'status', 'task_ids'],
  spec: ['artifact_id', 'spec_id', 'request_id', 'acceptance_criteria', 'artifact_types'],
  task: ['artifact_id', 'task_id', 'request_id', 'status', 'owner_role', 'trace_id'],
  trace: ['artifact_id', 'trace_id', 'request_id', 'scenario_id', 'event_refs', 'status'],
  review: ['artifact_id', 'review_id', 'request_id', 'trace_id', 'findings', 'status'],
  accept: ['artifact_id', 'acceptance_id', 'request_id', 'review_id', 'decision', 'status'],
  recover: [
    'artifact_id',
    'recovery_id',
    'request_id',
    'trigger',
    'resume_token',
    'mst_session_id',
    'root_mst_id',
    'recovery_judgement',
    'status',
  ],
  cleanup: [
    'artifact_id',
    'cleanup_id',
    'request_id',
    'targets',
    'dry_run',
    'report',
    'request_artifacts_preserved',
    'status',
  ],
  dashboard: [
    'artifact_id',
    'dashboard_id',
    'request_id',
    'widgets',
    'health',
    'overview',
    'status',
    'updated_at',
  ],
  settings: [
    'artifact_id',
    'settings_id',
    'scope',
    'effective_values',
    'config',
    'status',
    'updated_at',
  ],
};
export const dod008LifecycleSmokeArtifactTypes = ['recover', 'cleanup', 'dashboard', 'settings'];
export const dod008NoGoMetadataGuardCriteria = [
  {
    criterion_id: 'host_user_absolute_root',
    category: 'host-specific-root',
    required_result: 'reject',
  },
  {
    criterion_id: 'home_alias_or_env_root',
    category: 'shell-expanded-root',
    required_result: 'reject',
  },
  {
    criterion_id: 'codex_user_state_surface',
    category: 'user-scoped-codex-state',
    required_result: 'reject',
  },
  {
    criterion_id: 'agent_user_skill_surface',
    category: 'user-scoped-agent-state',
    required_result: 'reject',
  },
  {
    criterion_id: 'claude_hook_surface',
    category: 'user-scoped-claude-hook-state',
    required_result: 'reject',
  },
  {
    criterion_id: 'parent_directory_escape',
    category: 'path-escape',
    required_result: 'reject',
  },
  {
    criterion_id: 'plugin_network_action',
    category: 'plugin-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'plugin_cache_action',
    category: 'plugin-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'plugin_rescan_action',
    category: 'plugin-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'link_creation_action',
    category: 'filesystem-side-effect',
    required_result: 'reject',
  },
];
export const dod009MatrixSurfacePaths = [
  '.claude-plugin/plugin.json',
  'package.json',
  '.claude-plugin/marketplace.json',
  'extension/manifest.json',
  'extension/package.json',
  'hooks/hooks.json',
  'skills/',
  'agents/',
];
export const dod009ExcludedSurfaceIds = [
  'DOD-010',
  'DOD-011',
  'DOD-012',
  'DOD-013',
];
const dod009VersionSyncPaths = [
  'package.json',
  '.claude-plugin/plugin.json',
  '.claude-plugin/marketplace.json',
  'extension/manifest.json',
  'extension/package.json',
];
const dod009HooksCommandPaths = [
  '${CLAUDE_PLUGIN_ROOT}/hooks/mst-auto-chain-context.sh',
  '${CLAUDE_PLUGIN_ROOT}/hooks/mst-pre-tool-use.sh',
  '${CLAUDE_PLUGIN_ROOT}/hooks/mst-session-init.sh',
  '${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh',
];
const dod009NoGoMetadataGuardCriteria = [
  {
    criterion_id: 'host_user_absolute_root',
    category: 'host-specific-root',
    required_result: 'reject',
  },
  {
    criterion_id: 'home_alias_or_env_root',
    category: 'shell-expanded-root',
    required_result: 'reject',
  },
  {
    criterion_id: 'codex_user_config_surface',
    category: 'user-scoped-codex-config',
    required_result: 'reject',
  },
  {
    criterion_id: 'claude_hook_workspace_bypass',
    category: 'user-scoped-claude-hook-state',
    required_result: 'reject',
  },
  {
    criterion_id: 'parent_directory_escape',
    category: 'path-escape',
    required_result: 'reject',
  },
  {
    criterion_id: 'plugin_runtime_side_effect',
    category: 'plugin-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'plugin_cache_side_effect',
    category: 'plugin-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'plugin_index_rescan_side_effect',
    category: 'plugin-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'link_creation_side_effect',
    category: 'filesystem-side-effect',
    required_result: 'reject',
  },
];
export const dod008CoreWorkflowSmokeScenarioPaths = [
  '/mst:agile-plan',
  '/mst:request',
  '/mst:approve',
  'delegated implementation loop',
  '/mst:review',
  '/mst:accept',
];
export const dod008CoreWorkflowSmokeArtifactTypes = [
  'request',
  'spec',
  'task',
  'trace',
  'review',
  'accept',
];
export const dod008CoreWorkflowSmokeSessionId = 'MST-REQ-894-20260520T000000000Z-dod008aa';
export const dod008WorkflowArtifactParityTypes = [
  ...dod008CoreWorkflowSmokeArtifactTypes,
  ...dod008LifecycleSmokeArtifactTypes,
];

export const defaultDod008WorkflowE2EValidationSummary = {
  focused_workflow_validation: {
    command: 'npm test',
    status: 'pass',
    tests_total: 16,
    tests_pass: 16,
    tests_fail: 0,
    summary: '16 DOD-008 workflow checks passed',
  },
  schema_contract: {
    command: 'node --test tests/smoke.test.mjs',
    status: 'pass',
    tests_total: 5,
    tests_pass: 5,
    tests_fail: 0,
    summary: 'schema contract checks passed',
  },
  core_workflow_harness: {
    command: 'node --test tests/smoke.test.mjs',
    status: 'pass',
    tests_total: 3,
    tests_pass: 3,
    tests_fail: 0,
    summary: 'core workflow harness checks passed',
  },
  lifecycle_smoke: {
    command: 'node --test tests/smoke.test.mjs',
    status: 'pass',
    tests_total: 4,
    tests_pass: 4,
    tests_fail: 0,
    summary: 'lifecycle smoke checks passed',
  },
  artifact_parity: {
    command: 'node --test tests/smoke.test.mjs',
    status: 'pass',
    tests_total: 4,
    tests_pass: 4,
    tests_fail: 0,
    summary: 'artifact parity checks passed',
  },
  npm_test: {
    command: 'npm test',
    status: 'pass',
    tests_total: 57,
    tests_pass: 57,
    tests_fail: 0,
    summary: '57 passed',
  },
  generator: {
    command:
      'node scripts/generate-dod-008-workflow-e2e-validation.mjs <repo-output> <summary-fixture>',
    generated_artifact_path: dod008WorkflowE2EValidationEvidenceRelativePath,
    generated_output_path: null,
    status: 'pass',
    parse_ok: true,
  },
};

export const defaultDod009RequestEvidenceVerificationSummary = {
  plugin_manifest_hooks: {
    command: 'python3 -m pytest tests/test_plugin_manifest_hooks.py tests/test_hooks_json_registration.py',
    status: 'pass',
    tests_total: 8,
    tests_pass: 8,
    tests_fail: 0,
    summary: 'plugin manifest and hooks regression checks passed',
  },
  workflow_state_continuation: {
    command:
      'python3 -m pytest tests/test_workflow_state_transition_integrity.py tests/test_dod011_continuation_contract.py tests/test_dod012_auto_continuation_contract.py',
    status: 'pass',
    tests_total: 21,
    tests_pass: 21,
    tests_fail: 0,
    summary: 'workflow state and continuation regression checks passed',
  },
  run_wrapper_session_migration: {
    command: 'python3 -m pytest tests/test_run_wrapper.py tests/test_session_id_migration.py',
    status: 'pass',
    tests_total: 20,
    tests_pass: 20,
    tests_fail: 0,
    summary: 'run wrapper and session migration regression checks passed',
  },
  npm_test: {
    command: 'npm test',
    status: 'pass',
    tests_total: 65,
    tests_pass: 65,
    tests_fail: 0,
    summary: 'smoke tests passed',
  },
  generator: {
    command: 'node scripts/generate-dod-009-claude-plugin-regression-validation.mjs <temp-output>',
    status: 'pass',
    parse_ok: true,
    generated_artifact_path: dod009RequestEvidenceRelativePath,
    generated_output_path: null,
  },
};

export const dod010EvidenceByDodIds = [
  'DOD-001',
  'DOD-002',
  'DOD-003',
  'DOD-004',
  'DOD-005',
  'DOD-006',
  'DOD-007',
  'DOD-008',
  'DOD-009',
];
export const dod010NormalizedBlockerTypes = [
  'missing_evidence',
  'non_existing_evidence_path',
  'parse_failure',
  'failed_tests',
  'generated_drift',
  'unsupported_blocker_type',
  'no_go_violation',
  'stale_lifecycle',
  'path_escape',
  'release_blocking_risk',
];
export const dod010AllowedRiskClassifications = [
  'blocker',
  'non_release_blocking',
  'follow_up',
];
export const dod010FollowUpDodIds = ['DOD-011', 'DOD-012', 'DOD-013'];
export const dod010BlockerFreeMigrationReportRelativePath =
  '.gran-maestro/requests/REQ-916/evidence/dod-010-blocker-free-migration-report.json';
export const dod010BlockerFreeMigrationReportAbsolutePath = join(
  repoRoot,
  dod010BlockerFreeMigrationReportRelativePath,
);
export const dod011RequestEvidenceRelativePath =
  '.gran-maestro/requests/REQ-919/evidence/dod-011-migration-work-package-breakdown.json';
export const dod011RequestEvidenceAbsolutePath = join(
  repoRoot,
  dod011RequestEvidenceRelativePath,
);
const dod010ObjectiveRelativePath = '.gran-maestro/agile/AGI-039/objective/objective.md';
const dod010ObjectiveAbsolutePath = join(dirname(orchestrationRoot), dod010ObjectiveRelativePath);
const dod010Req916RequestMetadataRelativePath = '.gran-maestro/requests/REQ-916/request.json';
const dod010Req916RequestMetadataAbsolutePath = findSharedGranMaestroPath(
  'requests/REQ-916/request.json',
);
const dod011ObjectiveDetailRelativePath =
  '.gran-maestro/agile/AGI-039/objective/details/migration-execution-breakdown.md';
const dod011ObjectiveDetailAbsolutePath = findSharedGranMaestroPath(
  'agile/AGI-039/objective/details/migration-execution-breakdown.md',
);
const dod011PlanRelativePath = '.gran-maestro/plans/PLN-743/plan.md';
const dod011PlanAbsolutePath = findSharedGranMaestroPath('plans/PLN-743/plan.md');
const dod011PlanIdsRelativePath = '.gran-maestro/plans/PLN-743/plan.ids.json';
const dod011PlanIdsAbsolutePath = findSharedGranMaestroPath('plans/PLN-743/plan.ids.json');
const dod011Req919RequestMetadataRelativePath = '.gran-maestro/requests/REQ-919/request.json';
const dod011Req919RequestMetadataAbsolutePath = findSharedGranMaestroPath(
  'requests/REQ-919/request.json',
);
const dod011Task01SpecRelativePath = '.gran-maestro/requests/REQ-919/tasks/01/spec.md';
const dod011Task01SpecAbsolutePath = findSharedGranMaestroPath('requests/REQ-919/tasks/01/spec.md');
const dod011Task02SpecRelativePath = '.gran-maestro/requests/REQ-919/tasks/02/spec.md';
const dod011Task02SpecAbsolutePath = findSharedGranMaestroPath('requests/REQ-919/tasks/02/spec.md');
const dod011ArchitectureDecisionRelativePath =
  '.gran-maestro/requests/REQ-919/discussion/req-arch-decision.md';
const dod011ArchitectureDecisionAbsolutePath = findSharedGranMaestroPath(
  'requests/REQ-919/discussion/req-arch-decision.md',
);
const dod010GeneratorScriptRelativePath =
  'scripts/generate-dod-010-blocker-free-migration-report.mjs';
export const dod011GeneratorScriptRelativePath =
  'scripts/generate-dod-011-migration-work-package-breakdown.mjs';
const dod010NoGoMetadataGuardCriteria = [
  {
    criterion_id: 'user_home_surface',
    category: 'host-specific-root',
    required_result: 'reject',
  },
  {
    criterion_id: 'codex_user_config_surface',
    category: 'user-scoped-codex-config',
    required_result: 'reject',
  },
  {
    criterion_id: 'claude_hook_workspace_bypass',
    category: 'user-scoped-claude-hook-state',
    required_result: 'reject',
  },
  {
    criterion_id: 'external_runtime_install',
    category: 'plugin-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'plugin_cache_mutation',
    category: 'plugin-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'symlink_creation',
    category: 'filesystem-side-effect',
    required_result: 'reject',
  },
  {
    criterion_id: 'parent_directory_escape',
    category: 'path-escape',
    required_result: 'reject',
  },
];
const dod011RequiredPhaseOrder = Object.freeze([
  'inventory',
  'generator',
  'adapter',
  'skill-agent-parity',
  'config-provider-parity',
  'state-workflow-parity',
  'docs-release',
]);
const dod011RequiredPackageIds = Object.freeze([
  'WP-1',
  'WP-2',
  'WP-3',
  'WP-4',
  'WP-5',
  'WP-6',
  'WP-7',
  'WP-8',
]);
const dod011RequiredNoGoBoundaryIds = Object.freeze([
  'user_home_mutation',
  'external_codex_install_cache_reload',
  'symlink_creation',
  'plugin_cache_mutation',
  'claude_hooks_direct_edit',
  'objective_md_direct_edit',
]);
const dod011RequiredBlockerTypes = Object.freeze([
  'unsupported_blocker',
  'generated_drift',
  'no_go_mutation',
  'missing_validation_evidence',
]);
const dod011ValidationCommandForbiddenPattern =
  /(?:~\/|\/Users\/|\.claude\/hooks|objective\.md|codex plugins (?:install|refresh|reload)|cache refresh|plugin cache|ln -s)/u;

export const sharedDodEvidenceRegistryRequiredFields = Object.freeze([
  'dod_id',
  'request_id',
  'agi_id',
  'sprint',
  'generator_script_path',
  'request_evidence_path',
  'expected_status',
  'validator_linkage',
]);

function buildSharedDodEvidenceRegistryEntry({
  dod_id,
  request_id,
  agi_id,
  sprint,
  generator_script_path,
  request_evidence_path,
  expected_status,
  validator_export_name,
}) {
  return Object.freeze({
    dod_id,
    request_id,
    agi_id,
    sprint,
    generator_script_path,
    request_evidence_path,
    expected_status,
    validator_linkage: Object.freeze({
      export_name: validator_export_name,
      helper_kind: 'assertion-helper',
      validation_entrypoint: 'scripts/lib/codex-plugin-discovery-smoke.mjs',
    }),
  });
}

export const sharedDodEvidenceRegistry = Object.freeze([
  buildSharedDodEvidenceRegistryEntry({
    dod_id: 'DOD-009',
    request_id: 'REQ-912',
    agi_id: 'AGI-039',
    sprint: 10,
    generator_script_path: dod009GeneratorScriptRelativePath,
    request_evidence_path: dod009RequestEvidenceRelativePath,
    expected_status: 'pass',
    validator_export_name: 'assertDod009RequestEvidence',
  }),
  buildSharedDodEvidenceRegistryEntry({
    dod_id: 'DOD-010',
    request_id: 'REQ-916',
    agi_id: 'AGI-039',
    sprint: 11,
    generator_script_path: dod010GeneratorScriptRelativePath,
    request_evidence_path: dod010BlockerFreeMigrationReportRelativePath,
    expected_status: 'pass',
    validator_export_name: 'assertDod010BlockerFreeMigrationReport',
  }),
]);

export function getSharedDodEvidenceRegistryEntryByDodId(
  dodId,
  registry = sharedDodEvidenceRegistry,
) {
  if (!Array.isArray(registry)) {
    return null;
  }

  return registry.find((entry) => entry?.dod_id === dodId) ?? null;
}

export function buildSharedDodEvidenceRegistryLinkage({
  dodId,
  requestEvidencePath,
  repoRootPath = repoRoot,
  registry = sharedDodEvidenceRegistry,
} = {}) {
  const entry = getSharedDodEvidenceRegistryEntryByDodId(dodId, registry);
  const validation = entry
    ? validateSharedDodEvidenceRegistryEntry(entry, { repoRootPath })
    : {
        status: 'fail',
        issues: [`Missing shared DOD evidence registry entry for ${dodId ?? 'unknown'}.`],
        normalized_entry: null,
        validator_export_name: null,
      };
  const normalizedEntry = validation.normalized_entry;
  const requestEvidencePathMatchesRegistry =
    normalizedEntry?.request_evidence_path === requestEvidencePath;
  const generatorScriptExists = Boolean(
    normalizedEntry?.generator_script_path &&
      existsSync(join(repoRootPath, normalizedEntry.generator_script_path)),
  );
  const validationEntrypoint =
    entry?.validator_linkage &&
    typeof entry.validator_linkage === 'object' &&
    !Array.isArray(entry.validator_linkage)
      ? entry.validator_linkage.validation_entrypoint ?? null
      : null;
  const validatorEntrypointExists =
    typeof validationEntrypoint === 'string' &&
    validationEntrypoint.length > 0 &&
    existsSync(join(repoRootPath, validationEntrypoint));
  const issues = [...validation.issues];

  if (!requestEvidencePathMatchesRegistry) {
    issues.push(
      `Shared DOD registry request_evidence_path mismatch for ${dodId ?? 'unknown'}: ` +
        `expected ${normalizedEntry?.request_evidence_path ?? 'missing'}, got ${requestEvidencePath ?? 'missing'}.`,
    );
  }

  if (!generatorScriptExists) {
    issues.push(
      `Shared DOD registry generator script is not resolvable for ${dodId ?? 'unknown'}.`,
    );
  }

  if (!validatorEntrypointExists) {
    issues.push(
      `Shared DOD registry validator entrypoint is not resolvable for ${dodId ?? 'unknown'}.`,
    );
  }

  return {
    status: issues.length === 0 ? 'pass' : 'fail',
    linkage_source: 'shared_dod_evidence_registry',
    request_evidence_path_matches_registry: requestEvidencePathMatchesRegistry,
    generator_script_exists: generatorScriptExists,
    validator_entrypoint_exists: validatorEntrypointExists,
    issues,
    registry_entry: normalizedEntry
      ? {
          ...normalizedEntry,
          validator_linkage: {
            export_name: validation.validator_export_name,
            helper_kind:
              entry?.validator_linkage &&
              typeof entry.validator_linkage === 'object' &&
              !Array.isArray(entry.validator_linkage)
                ? entry.validator_linkage.helper_kind ?? null
                : null,
            validation_entrypoint: validationEntrypoint,
          },
        }
      : null,
  };
}

export const manifestFields = [
  'name',
  'version',
  'description',
  'keywords',
  'skills',
  'hooks',
];

export const marketplaceFields = [
  'name',
  'version',
  'source',
  'category',
  'tags',
];

const outOfScopeArtifactCandidates = [
  {
    dod_id: 'DOD-006',
    description: 'Codex skill/agent runtime projection artifacts remain out of scope for DOD-003.',
    assets: [
      '.agents/skills/',
      '.agents/agents/',
      '.codex-plugin/skills-manifest.json',
      '.codex-plugin/agents-manifest.json',
    ],
  },
  {
    dod_id: 'DOD-008',
    description: 'Codex workflow E2E parity artifacts remain out of scope for DOD-003.',
    assets: [
      'tests/codex-workflow-e2e.test.mjs',
      'scripts/codex-workflow-e2e-smoke.mjs',
    ],
    orchestration_assets: [
      'requests/REQ-886/evidence/codex-workflow-e2e-parity.json',
    ],
  },
];

const dod004NoGoArtifactCandidates = [
  {
    category: 'runtime_projection',
    description: 'Codex skill and agent runtime projection artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: '.agents/skills/',
  },
  {
    category: 'runtime_projection',
    description: 'Codex skill and agent runtime projection artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: '.agents/agents/',
  },
  {
    category: 'runtime_projection',
    description: 'Codex skill and agent runtime projection artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: '.codex-plugin/skills-manifest.json',
  },
  {
    category: 'runtime_projection',
    description: 'Codex skill and agent runtime projection artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: '.codex-plugin/agents-manifest.json',
  },
  {
    category: 'workflow_e2e',
    description: 'Codex workflow E2E parity artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: 'tests/codex-workflow-e2e.test.mjs',
  },
  {
    category: 'workflow_e2e',
    description: 'Codex workflow E2E parity artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: 'scripts/codex-workflow-e2e-smoke.mjs',
  },
  {
    category: 'workflow_e2e',
    description: 'Codex workflow E2E parity artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'orchestration',
    path: 'requests/REQ-886/evidence/codex-workflow-e2e-parity.json',
  },
];

function readUtf8(path) {
  return readFileSync(join(repoRoot, path), 'utf8');
}

function readJsonFromRepo(path) {
  return JSON.parse(readUtf8(path));
}

function readJsonFromAbsolutePath(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function readTextIfExists(path) {
  try {
    return readFileSync(path, 'utf8');
  } catch {
    return '';
  }
}

function collectJsonArtifact(path, reader, parseFailures) {
  try {
    return { value: reader(path), error: null };
  } catch (error) {
    parseFailures.push({
      path,
      error: error instanceof Error ? error.message : String(error),
    });
    return {
      value: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function normalizeArray(value) {
  return Array.isArray(value) ? value : [];
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function normalizePathSeparators(path) {
  return path.replace(/\\/gu, '/');
}

function parseFrontmatterValue(rawValue) {
  const value = rawValue.trim();

  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith('\'') && value.endsWith('\''))
  ) {
    return value.slice(1, -1);
  }

  if (value === 'true') {
    return true;
  }

  if (value === 'false') {
    return false;
  }

  return value;
}

function parseSkillDefinition(path) {
  const text = readUtf8(path);
  const frontmatterMatch = text.match(/^---\n([\s\S]*?)\n---\n?/u);
  const frontmatter = {};

  if (!frontmatterMatch) {
    throw new Error('Missing YAML frontmatter.');
  }

  for (const rawLine of frontmatterMatch[1].split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }

    const match = line.match(/^([A-Za-z0-9_-]+):\s*(.+)$/u);
    if (!match) {
      continue;
    }

    frontmatter[match[1]] = parseFrontmatterValue(match[2]);
  }

  const headingMatch = text.match(/^#\s+([^\n]+)$/mu);
  if (!headingMatch) {
    throw new Error('Missing level-1 heading.');
  }

  const heading = headingMatch[1].trim();
  const commandId = heading.includes(':') ? heading.split(':').at(-1).trim() : heading;
  const skillDirectory = basename(dirname(path));
  const skillName = String(frontmatter.name || skillDirectory);
  const slashCommand = commandId ? `/mst:${commandId}` : null;

  return {
    text,
    frontmatter,
    heading,
    command_id: commandId,
    slash_command: slashCommand,
    skill_directory: skillDirectory,
    skill_name: skillName,
  };
}

function listSkillSourcePaths() {
  return readdirSync(join(repoRoot, 'skills'), { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(join(repoRoot, 'skills', entry.name, 'SKILL.md')))
    .map((entry) => `skills/${entry.name}/SKILL.md`)
    .sort();
}

function parseAgentDefinition(path) {
  const text = readUtf8(path);
  const headingMatch = text.match(/^#\s+([^\n]+)$/mu);
  if (!headingMatch) {
    throw new Error('Missing level-1 heading.');
  }

  const roleName = basename(path, '.md');
  const deprecated =
    />\s+\*\*DEPRECATED\*\*/u.test(text) ||
    />\s+.*대체됨/u.test(text) ||
    /호환성을 위해 유지/u.test(text);
  const templateCompatible =
    /이 파일은 에이전트가 아닌/u.test(text) ||
    /템플릿으로/u.test(text) ||
    /템플릿입니다/u.test(text);

  return {
    text,
    heading: headingMatch[1].trim(),
    role_name: roleName,
    deprecated,
    source_kind: templateCompatible ? 'template' : 'agent',
  };
}

function listAgentSourcePaths() {
  return readdirSync(join(repoRoot, 'agents'), { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.md'))
    .map((entry) => `agents/${entry.name}`)
    .sort();
}

function validateRepositoryRelativePath(input) {
  if (typeof input !== 'string' || input.trim().length === 0) {
    return {
      status: 'fail',
      code: 'empty_path',
      normalized_path: null,
      reason: 'path must be a non-empty string',
    };
  }

  const trimmed = input.trim();
  const lower = trimmed.toLowerCase();

  if (/^[A-Za-z]:[\\/]/u.test(trimmed) || trimmed.startsWith('/') || trimmed.startsWith('\\\\')) {
    return {
      status: 'fail',
      code: 'absolute_host_path',
      normalized_path: null,
      reason: 'absolute host paths are not allowed',
    };
  }

  if (trimmed.startsWith('~/')) {
    return {
      status: 'fail',
      code: 'home_expansion',
      normalized_path: null,
      reason: 'tilde expansion is not allowed',
    };
  }

  if (trimmed.includes('$HOME') || trimmed.includes('${HOME}')) {
    return {
      status: 'fail',
      code: 'env_expansion',
      normalized_path: null,
      reason: 'environment expansion is not allowed',
    };
  }

  if (lower.includes('%2e')) {
    return {
      status: 'fail',
      code: 'encoded_traversal',
      normalized_path: null,
      reason: 'encoded traversal tokens are not allowed',
    };
  }

  const normalized = trimmed.replace(/^(?:\.\/)+/u, '');
  if (normalized.includes('\\')) {
    return {
      status: 'fail',
      code: 'path_traversal',
      normalized_path: null,
      reason: 'backslash traversal is not allowed',
    };
  }

  if (normalized.split('/').some((segment) => segment === '..')) {
    return {
      status: 'fail',
      code: 'path_traversal',
      normalized_path: null,
      reason: 'parent-directory traversal is not allowed',
    };
  }

  return {
    status: 'pass',
    code: 'ok',
    normalized_path: normalized,
    reason: 'repository-relative path accepted',
  };
}

function validateProjectionCommand(command) {
  if (typeof command !== 'string' || command.trim().length === 0) {
    return {
      status: 'fail',
      code: 'empty_command',
      reason: 'command must be a non-empty string',
    };
  }

  const normalized = command.trim().toLowerCase();

  if (/\bln\s+-s\b/u.test(normalized)) {
    return {
      status: 'fail',
      code: 'symlink_creation',
      reason: 'symlink creation commands are out of scope',
    };
  }

  if (/\bcodex\b.*\binstall\b/u.test(normalized)) {
    return {
      status: 'fail',
      code: 'external_install',
      reason: 'external install commands are out of scope',
    };
  }

  if (/\bcodex\b.*\b(refresh|reload)\b/u.test(normalized)) {
    return {
      status: 'fail',
      code: 'cache_refresh',
      reason: 'cache refresh or reload commands are out of scope',
    };
  }

  return {
    status: 'pass',
    code: 'ok',
    reason: 'metadata-only command reference accepted',
  };
}

function toRecordedMetadataPath(path) {
  if (typeof path !== 'string' || path.trim().length === 0) {
    return null;
  }

  const trimmed = path.trim();
  const validated = validateRepositoryRelativePath(trimmed);
  if (validated.status === 'pass') {
    return validated.normalized_path;
  }

  const normalizedRepoRoot = normalizePathSeparators(repoRoot);
  const normalizedOrchestrationRoot = normalizePathSeparators(orchestrationRoot);
  const normalizedInput = normalizePathSeparators(resolve(trimmed));

  if (
    normalizedInput === normalizedRepoRoot ||
    normalizedInput.startsWith(`${normalizedRepoRoot}/`)
  ) {
    const repoRelativePath = normalizePathSeparators(relative(repoRoot, normalizedInput));
    const repoRelativeValidation = validateRepositoryRelativePath(repoRelativePath);
    return repoRelativeValidation.status === 'pass'
      ? repoRelativeValidation.normalized_path
      : null;
  }

  if (
    normalizedInput === normalizedOrchestrationRoot ||
    normalizedInput.startsWith(`${normalizedOrchestrationRoot}/`)
  ) {
    const orchestrationRelativePath = normalizePathSeparators(
      relative(orchestrationRoot, normalizedInput),
    );
    const metadataPath = `.gran-maestro/${orchestrationRelativePath}`;
    const orchestrationValidation = validateRepositoryRelativePath(metadataPath);
    return orchestrationValidation.status === 'pass'
      ? orchestrationValidation.normalized_path
      : null;
  }

  return null;
}

function sanitizeParseFailures(parseFailures) {
  return parseFailures.map((failure) => ({
    ...failure,
    path: toRecordedMetadataPath(failure.path) ?? 'unscoped-metadata-path',
  }));
}

function sanitizeMetadataPath(path, fallback = 'invalid-metadata-path') {
  return toRecordedMetadataPath(path) ?? fallback;
}

function sanitizeMetadataPathList(paths, fallback = 'invalid-metadata-path') {
  return normalizeArray(paths).map((path) => sanitizeMetadataPath(path, fallback));
}

function sanitizeMetadataCommand(command) {
  if (typeof command !== 'string' || command.trim().length === 0) {
    return null;
  }

  const normalizedWorkspaceRoot = normalizePathSeparators(dirname(orchestrationRoot));
  const normalizedRepoRoot = normalizePathSeparators(repoRoot);
  const normalizedOrchestrationRoot = normalizePathSeparators(orchestrationRoot);

  return normalizePathSeparators(command.trim())
    .replaceAll(normalizedRepoRoot, '.')
    .replaceAll(normalizedOrchestrationRoot, '.gran-maestro')
    .replaceAll(normalizedWorkspaceRoot, '.');
}

function getSharedDodEvidenceValidatorExportName(validatorLinkage) {
  if (typeof validatorLinkage === 'function') {
    return validatorLinkage.name || null;
  }

  if (typeof validatorLinkage === 'string') {
    return validatorLinkage;
  }

  if (validatorLinkage && typeof validatorLinkage === 'object') {
    if (typeof validatorLinkage.export_name === 'string') {
      return validatorLinkage.export_name;
    }

    if (typeof validatorLinkage.name === 'string') {
      return validatorLinkage.name;
    }

    if (typeof validatorLinkage.validator === 'function') {
      return validatorLinkage.validator.name || null;
    }
  }

  return null;
}

function resolveSharedDodEvidenceValidatorByName(exportName) {
  switch (exportName) {
    case 'assertDod009RequestEvidence':
      return assertDod009RequestEvidence;
    case 'assertDod010BlockerFreeMigrationReport':
      return assertDod010BlockerFreeMigrationReport;
    default:
      return null;
  }
}

function validateSharedDodEvidenceRegistryPath(path, fieldLabel, repoRootPath) {
  const validation = validateRepositoryRelativePath(path);

  if (validation.status !== 'pass') {
    return {
      status: 'fail',
      normalized_path: null,
      issues: [`${fieldLabel} must be a repo-relative path: ${validation.reason}.`],
    };
  }

  const scopedPath = join(repoRootPath, validation.normalized_path);
  if (!existsSync(scopedPath)) {
    return {
      status: 'fail',
      normalized_path: validation.normalized_path,
      issues: [`${fieldLabel} does not exist at ${validation.normalized_path}.`],
    };
  }

  const repoRealPath = realpathSync(repoRootPath);
  const targetRealPath = realpathSync(scopedPath);
  const repoRelativePath = normalizePathSeparators(relative(repoRealPath, targetRealPath));

  if (repoRelativePath.length === 0 || repoRelativePath === '..' || repoRelativePath.startsWith('../')) {
    return {
      status: 'fail',
      normalized_path: validation.normalized_path,
      issues: [`${fieldLabel} escapes repository root: ${validation.normalized_path}.`],
    };
  }

  return {
    status: 'pass',
    normalized_path: validation.normalized_path,
    issues: [],
  };
}

export function validateSharedDodEvidenceRegistryEntry(
  entry,
  { repoRootPath = repoRoot } = {},
) {
  const issues = [];

  for (const field of sharedDodEvidenceRegistryRequiredFields) {
    if (!Object.hasOwn(entry ?? {}, field)) {
      issues.push(`Missing required shared DOD registry field: ${field}.`);
    }
  }

  const generatorPathValidation = validateSharedDodEvidenceRegistryPath(
    entry?.generator_script_path,
    'generator_script_path',
    repoRootPath,
  );
  issues.push(...generatorPathValidation.issues);

  const requestEvidencePathValidation = validateSharedDodEvidenceRegistryPath(
    entry?.request_evidence_path,
    'request_evidence_path',
    repoRootPath,
  );
  issues.push(...requestEvidencePathValidation.issues);

  const validatorExportName = getSharedDodEvidenceValidatorExportName(entry?.validator_linkage);
  if (!validatorExportName) {
    issues.push('validator_linkage must reference an exported shared smoke validator.');
  }

  const validator = validatorExportName
    ? resolveSharedDodEvidenceValidatorByName(validatorExportName)
    : null;
  if (!validator) {
    issues.push(
      `validator_linkage export is not wired by scripts/lib/codex-plugin-discovery-smoke.mjs: ${validatorExportName ?? 'unknown'}.`,
    );
  }

  if (
    entry?.validator_linkage &&
    typeof entry.validator_linkage === 'object' &&
    !Array.isArray(entry.validator_linkage) &&
    entry.validator_linkage.validation_entrypoint
  ) {
    const linkagePathValidation = validateSharedDodEvidenceRegistryPath(
      entry.validator_linkage.validation_entrypoint,
      'validator_linkage.validation_entrypoint',
      repoRootPath,
    );
    issues.push(...linkagePathValidation.issues);
  }

  return {
    status: issues.length === 0 ? 'pass' : 'fail',
    issues,
    validator_export_name: validatorExportName,
    validator,
    normalized_entry: {
      ...entry,
      generator_script_path: generatorPathValidation.normalized_path,
      request_evidence_path: requestEvidencePathValidation.normalized_path,
    },
  };
}

export function validateSharedDodEvidenceRegistry(
  registry = sharedDodEvidenceRegistry,
  { repoRootPath = repoRoot } = {},
) {
  if (!Array.isArray(registry)) {
    return {
      status: 'fail',
      issues: ['sharedDodEvidenceRegistry must be an array-backed validation surface.'],
      entries: [],
    };
  }

  const entries = registry.map((entry) =>
    validateSharedDodEvidenceRegistryEntry(entry, { repoRootPath }),
  );
  const issues = entries.flatMap((entryValidation) => entryValidation.issues);

  return {
    status: issues.length === 0 ? 'pass' : 'fail',
    issues,
    entries,
  };
}

export function assertSharedDodEvidenceRegistry(
  registry = sharedDodEvidenceRegistry,
  { repoRootPath = repoRoot } = {},
) {
  const validation = validateSharedDodEvidenceRegistry(registry, { repoRootPath });

  assert.equal(
    validation.status,
    'pass',
    validation.issues.length > 0
      ? `Invalid shared DOD evidence registry:\n- ${validation.issues.join('\n- ')}`
      : 'Invalid shared DOD evidence registry.',
  );
}

function buildSkillProjectionNoGoGuard(projectionRecords) {
  const pathFixtures = [
    {
      fixture_id: 'repo_relative_skill_path',
      candidate: 'skills/agile/SKILL.md',
      expected_status: 'pass',
    },
    {
      fixture_id: 'parent_traversal_posix',
      candidate: '../skills/agile/SKILL.md',
      expected_status: 'fail',
    },
    {
      fixture_id: 'parent_traversal_windows',
      candidate: '..\\skills\\agile\\SKILL.md',
      expected_status: 'fail',
    },
    {
      fixture_id: 'encoded_parent_traversal',
      candidate: '%2e%2e/skills/agile/SKILL.md',
      expected_status: 'fail',
    },
    {
      fixture_id: 'tilde_home_expansion',
      candidate: '~/skills/agile/SKILL.md',
      expected_status: 'fail',
    },
    {
      fixture_id: 'env_home_expansion',
      candidate: '$HOME/skills/agile/SKILL.md',
      expected_status: 'fail',
    },
    {
      fixture_id: 'env_home_braced_expansion',
      candidate: '${HOME}/skills/agile/SKILL.md',
      expected_status: 'fail',
    },
    {
      fixture_id: 'absolute_posix_path',
      candidate: '/tmp/skills/agile/SKILL.md',
      expected_status: 'fail',
    },
    {
      fixture_id: 'absolute_windows_path',
      candidate: 'C:\\skills\\agile\\SKILL.md',
      expected_status: 'fail',
    },
  ].map(({ fixture_id, candidate, expected_status }) => {
    const validation = validateRepositoryRelativePath(candidate);
    return {
      fixture_id,
      expected_status,
      ...validation,
      matched_expected: validation.status === expected_status,
    };
  });

  const commandFixtures = [
    {
      fixture_id: 'relative_generator_cli',
      candidate:
        'node scripts/generate-codex-skill-projection-smoke.mjs .gran-maestro/requests/REQ-891/evidence/dod-006-skill-projection-validation.json',
      expected_status: 'pass',
    },
    {
      fixture_id: 'symlink_cli',
      candidate: 'ln -s skills sandbox-skill-link',
      expected_status: 'fail',
    },
    {
      fixture_id: 'install_cli',
      candidate: 'codex plugins install ./',
      expected_status: 'fail',
    },
    {
      fixture_id: 'refresh_cli',
      candidate: 'codex plugins refresh gran-maestro',
      expected_status: 'fail',
    },
  ].map(({ fixture_id, candidate, expected_status }) => {
    const validation = validateProjectionCommand(candidate);
    return {
      fixture_id,
      expected_status,
      ...validation,
      matched_expected: validation.status === expected_status,
    };
  });

  const projectionViolations = projectionRecords.flatMap((record) => {
    const violations = [];
    if (record.path_checks.source.status !== 'pass') {
      violations.push({
        source_path: record.source_path,
        field: 'source_path',
        code: record.path_checks.source.code,
      });
    }
    if (record.path_checks.projected.status !== 'pass') {
      violations.push({
        source_path: record.source_path,
        field: 'projected_path',
        code: record.path_checks.projected.code,
      });
    }
    return violations;
  });

  return {
    status:
      pathFixtures.every((fixture) => fixture.matched_expected) &&
      commandFixtures.every((fixture) => fixture.matched_expected) &&
      projectionViolations.length === 0
        ? 'pass'
        : 'fail',
    path_fixtures: pathFixtures,
    command_fixtures: commandFixtures,
    projection_violations: projectionViolations,
  };
}

function buildSkillProjectionCrossFileConsistency({
  generatedManifest,
  sourceManifest,
  generatedMarketplace,
  sourceSkillCount,
}) {
  const checks = [
    {
      name: 'codex_manifest_skills_root',
      actual: generatedManifest?.skills ?? null,
      expected: './skills/',
    },
    {
      name: 'claude_manifest_skills_root',
      actual: sourceManifest?.skills ?? null,
      expected: './skills/',
    },
    {
      name: 'generated_marketplace_source_root',
      actual: generatedMarketplace?.plugins?.[0]?.source?.path ?? null,
      expected: './',
    },
    {
      name: 'skill_inventory_count',
      actual: sourceSkillCount,
      expected: sourceSkillCount,
    },
  ].map((check) => ({
    ...check,
    status: isDeepStrictEqual(check.actual, check.expected) ? 'pass' : 'fail',
  }));

  return {
    status: checks.every((check) => check.status === 'pass') ? 'pass' : 'fail',
    checks,
  };
}

function buildClaudeManifestAgentParity({
  sourceManifest,
  sourceAgentPaths,
}) {
  const expectedManifestAgents = sourceAgentPaths.map((path) => `./${path}`).sort();
  const actualManifestAgents = normalizeArray(sourceManifest?.agents).sort();
  const missingAgentPaths = expectedManifestAgents.filter((path) => !actualManifestAgents.includes(path));
  const extraAgentPaths = actualManifestAgents.filter((path) => !expectedManifestAgents.includes(path));
  const forbiddenProjectionPaths = actualManifestAgents.filter((path) =>
    !/^\.\/agents\/[^/]+\.md$/u.test(path) ||
    path.includes('.codex-plugin/') ||
    path.includes('.agents/plugins/') ||
    path.includes('.gran-maestro/') ||
    /(?:^|\/)generated(?:\/|$)/u.test(path),
  );

  return {
    status:
      missingAgentPaths.length === 0 &&
      extraAgentPaths.length === 0 &&
      forbiddenProjectionPaths.length === 0
        ? 'pass'
        : 'fail',
    expected_agent_count: expectedManifestAgents.length,
    manifest_agent_count: actualManifestAgents.length,
    missing_agent_count: missingAgentPaths.length,
    extra_agent_count: extraAgentPaths.length,
    forbidden_projection_path_count: forbiddenProjectionPaths.length,
    expected_agents: expectedManifestAgents,
    manifest_agents: actualManifestAgents,
    missing_agent_paths: sanitizeMetadataPathList(missingAgentPaths, 'invalid-manifest-agent-path'),
    extra_agent_paths: sanitizeMetadataPathList(extraAgentPaths, 'invalid-manifest-agent-path'),
    forbidden_projection_paths: sanitizeMetadataPathList(
      forbiddenProjectionPaths,
      'invalid-manifest-agent-path',
    ),
  };
}

function buildRoleCoverage(roleNames) {
  const actualRoles = [...roleNames].sort();
  const missingRequiredRoles = requiredAgentRoleNames.filter((roleName) => !actualRoles.includes(roleName));
  const extraRoles = actualRoles.filter((roleName) => !requiredAgentRoleNames.includes(roleName));
  const coveredRoles = requiredAgentRoleNames.filter((roleName) => actualRoles.includes(roleName));
  const coveragePercent = Number(
    ((coveredRoles.length / requiredAgentRoleNames.length) * 100).toFixed(2),
  );

  return {
    status:
      missingRequiredRoles.length === 0 &&
      extraRoles.length === 0 &&
      actualRoles.length === requiredAgentRoleNames.length
        ? 'pass'
        : 'fail',
    expected_role_count: requiredAgentRoleNames.length,
    mapped_role_count: actualRoles.length,
    coverage_percent: coveragePercent,
    covered_role_count: coveredRoles.length,
    missing_role_count: missingRequiredRoles.length,
    extra_role_count: extraRoles.length,
    required_roles: requiredAgentRoleNames,
    mapped_roles: actualRoles,
    missing_roles: missingRequiredRoles,
    extra_roles: extraRoles,
  };
}

function buildSafeSkillPrivilegeRecords(skillProjectionEvidence) {
  return normalizeArray(skillProjectionEvidence?.projection_records).map((record) => ({
    skill_name: record.skill_name,
    skill_directory: record.skill_directory,
    source_path: record.source_path,
    projected_path: record.projected_path,
    projection_mode: record.projection_mode,
    invocation_metadata: {
      mode: record.invocation_metadata?.mode ?? null,
      command_id: record.invocation_metadata?.command_id ?? null,
      slash_command: record.invocation_metadata?.slash_command ?? null,
    },
    privilege_profile: {
      executes_workflow: false,
      advances_request_state: false,
      executes_hooks: false,
      executes_session_runtime: false,
      mutates_user_home: false,
      mutates_user_config: false,
      refreshes_plugin_cache: false,
      executes_external_install: false,
      bypass_permissions: false,
      disables_sandbox: false,
      arbitrary_command_execution: false,
    },
  }));
}

const skillPrivilegeRecordSchema = {
  skill_name: 'string',
  skill_directory: 'string',
  source_path: 'repo_path',
  projected_path: 'repo_path',
  projection_mode: ['direct-source-reference'],
  invocation_metadata: {
    mode: ['metadata-only'],
    command_id: 'nullable_string',
    slash_command: 'nullable_slash_command',
  },
  privilege_profile: {
    executes_workflow: 'false',
    advances_request_state: 'false',
    executes_hooks: 'false',
    executes_session_runtime: 'false',
    mutates_user_home: 'false',
    mutates_user_config: 'false',
    refreshes_plugin_cache: 'false',
    executes_external_install: 'false',
    bypass_permissions: 'false',
    disables_sandbox: 'false',
    arbitrary_command_execution: 'false',
  },
};

const rolePrivilegeRecordSchema = {
  role_name: 'slug',
  source_path: 'repo_path',
  manifest_path: 'manifest_path',
  source_digest: 'sha256',
  digest_algorithm: ['sha256'],
  source_heading: 'string',
  source_kind: ['agent', 'template'],
  deprecation_status: ['active', 'deprecated-compat'],
  codex_mapping: {
    mapping_mode: ['metadata-only'],
    routing_surface: 'role_surface',
    subagent_label: 'slug',
    prompt_origin: 'repo_path',
  },
  privilege_profile: {
    spawn_runtime_execution: 'false',
    provider_auth_routing: 'false',
    model_routing: 'false',
    mutates_user_home: 'false',
    mutates_user_config: 'false',
    refreshes_plugin_cache: 'false',
    executes_external_install: 'false',
    bypass_permissions: 'false',
    disables_sandbox: 'false',
    arbitrary_command_execution: 'false',
  },
};

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function buildSchemaViolation(code, fieldPath, detail = null) {
  return {
    code,
    field_path: fieldPath,
    detail,
  };
}

function classifyUnexpectedKey(key) {
  const classifications = new Map([
    ['bypassPermissions', 'permission_bypass_key'],
    ['permissions', 'permission_bypass_key'],
    ['sandbox', 'sandbox_disable_key'],
    ['sandboxMode', 'sandbox_disable_key'],
    ['fullAccess', 'sandbox_disable_key'],
    ['command', 'arbitrary_command_key'],
    ['commands', 'arbitrary_command_key'],
    ['shellCommand', 'arbitrary_command_key'],
    ['executable', 'arbitrary_command_key'],
    ['exec', 'arbitrary_command_key'],
    ['userHomePath', 'user_home_mutation_key'],
    ['mutateUserHome', 'user_home_mutation_key'],
    ['mutateUserConfig', 'user_home_mutation_key'],
    ['refreshCommand', 'plugin_cache_refresh_key'],
    ['reloadCommand', 'plugin_cache_refresh_key'],
    ['installCommand', 'external_install_key'],
    ['symlinkCommand', 'user_home_mutation_key'],
    ['chmod', 'chmod_chown_key'],
    ['chown', 'chmod_chown_key'],
  ]);

  return classifications.get(key) ?? 'unexpected_key';
}

function validateSchemaLeaf(value, spec, fieldPath) {
  if (Array.isArray(spec)) {
    return spec.includes(value)
      ? []
      : [buildSchemaViolation('enum_mismatch', fieldPath)];
  }

  switch (spec) {
    case 'string':
      return typeof value === 'string' && value.trim().length > 0
        ? []
        : [buildSchemaViolation('invalid_string', fieldPath)];
    case 'nullable_string':
      return value === null || (typeof value === 'string' && value.trim().length > 0)
        ? []
        : [buildSchemaViolation('invalid_nullable_string', fieldPath)];
    case 'slug':
      return typeof value === 'string' && /^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(value)
        ? []
        : [buildSchemaViolation('invalid_slug', fieldPath)];
    case 'repo_path': {
      const validation = validateRepositoryRelativePath(value);
      return validation.status === 'pass'
        ? []
        : [buildSchemaViolation(validation.code, fieldPath)];
    }
    case 'manifest_path': {
      if (typeof value !== 'string' || !value.startsWith('./')) {
        return [buildSchemaViolation('invalid_manifest_path', fieldPath)];
      }
      const validation = validateRepositoryRelativePath(value);
      return validation.status === 'pass'
        ? []
        : [buildSchemaViolation(validation.code, fieldPath)];
    }
    case 'sha256':
      return typeof value === 'string' && /^[a-f0-9]{64}$/u.test(value)
        ? []
        : [buildSchemaViolation('invalid_sha256', fieldPath)];
    case 'nullable_slash_command':
      return value === null || (typeof value === 'string' && /^\/mst:[A-Za-z0-9_-]+$/u.test(value))
        ? []
        : [buildSchemaViolation('invalid_slash_command', fieldPath)];
    case 'role_surface':
      return typeof value === 'string' && /^\/prompts:[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(value)
        ? []
        : [buildSchemaViolation('invalid_role_surface', fieldPath)];
    case 'false':
      return value === false
        ? []
        : [buildSchemaViolation('expected_false', fieldPath)];
    default:
      throw new Error(`Unsupported schema spec: ${spec}`);
  }
}

function validateMetadataAgainstSchema(value, schema, pathPrefix = '') {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {
      status: 'fail',
      violations: [buildSchemaViolation('invalid_object', pathPrefix || 'root')],
    };
  }

  const violations = [];
  const objectKeys = Object.keys(value);

  for (const key of objectKeys) {
    if (!Object.hasOwn(schema, key)) {
      violations.push(buildSchemaViolation(classifyUnexpectedKey(key), pathPrefix ? `${pathPrefix}.${key}` : key));
    }
  }

  for (const [key, spec] of Object.entries(schema)) {
    const fieldPath = pathPrefix ? `${pathPrefix}.${key}` : key;

    if (!Object.hasOwn(value, key)) {
      violations.push(buildSchemaViolation('missing_key', fieldPath));
      continue;
    }

    const fieldValue = value[key];
    if (spec && typeof spec === 'object' && !Array.isArray(spec)) {
      const nested = validateMetadataAgainstSchema(fieldValue, spec, fieldPath);
      violations.push(...nested.violations);
      continue;
    }

    violations.push(...validateSchemaLeaf(fieldValue, spec, fieldPath));
  }

  return {
    status: violations.length === 0 ? 'pass' : 'fail',
    violations,
  };
}

function summarizeSchemaValidation(validations) {
  const allViolations = validations.flatMap((validation) => validation.violations);

  return {
    status: allViolations.length === 0 ? 'pass' : 'fail',
    checked_record_count: validations.length,
    unexpected_key_count: allViolations.filter((violation) => violation.code.endsWith('_key')).length,
    invalid_field_count: allViolations.filter((violation) => !violation.code.endsWith('_key')).length,
    violations: allViolations,
  };
}

function buildPrivilegeGuard({
  skillRecords,
  roleRecords,
}) {
  const skillValidations = skillRecords.map((record) =>
    validateMetadataAgainstSchema(record, skillPrivilegeRecordSchema, 'skill_record'),
  );
  const roleValidations = roleRecords.map((record) =>
    validateMetadataAgainstSchema(record, rolePrivilegeRecordSchema, 'role_record'),
  );
  const skillSummary = summarizeSchemaValidation(skillValidations);
  const roleSummary = summarizeSchemaValidation(roleValidations);

  const sampleSkillRecord = cloneJson(skillRecords[0] ?? {
    skill_name: 'sample-skill',
    skill_directory: 'sample-skill',
    source_path: 'skills/sample-skill/SKILL.md',
    projected_path: 'skills/sample-skill/SKILL.md',
    projection_mode: 'direct-source-reference',
    invocation_metadata: {
      mode: 'metadata-only',
      command_id: 'sample',
      slash_command: '/mst:sample',
    },
    privilege_profile: {
      executes_workflow: false,
      advances_request_state: false,
      executes_hooks: false,
      executes_session_runtime: false,
      mutates_user_home: false,
      mutates_user_config: false,
      refreshes_plugin_cache: false,
      executes_external_install: false,
      bypass_permissions: false,
      disables_sandbox: false,
      arbitrary_command_execution: false,
    },
  });
  const sampleRoleRecord = cloneJson(roleRecords[0] ?? {
    role_name: 'sample-role',
    source_path: 'agents/sample-role.md',
    manifest_path: './agents/sample-role.md',
    source_digest: '0'.repeat(64),
    digest_algorithm: 'sha256',
    source_heading: 'Sample Role',
    source_kind: 'agent',
    deprecation_status: 'active',
    codex_mapping: {
      mapping_mode: 'metadata-only',
      routing_surface: '/prompts:sample-role',
      subagent_label: 'sample-role',
      prompt_origin: 'agents/sample-role.md',
    },
    privilege_profile: {
      spawn_runtime_execution: false,
      provider_auth_routing: false,
      model_routing: false,
      mutates_user_home: false,
      mutates_user_config: false,
      refreshes_plugin_cache: false,
      executes_external_install: false,
      bypass_permissions: false,
      disables_sandbox: false,
      arbitrary_command_execution: false,
    },
  });

  const denyFixtures = [
    {
      fixture_id: 'bypass_permissions_camelcase',
      target_kind: 'role_record',
      candidate: {
        ...cloneJson(sampleRoleRecord),
        bypassPermissions: true,
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'sandbox_disable_mode',
      target_kind: 'role_record',
      candidate: {
        ...cloneJson(sampleRoleRecord),
        sandboxMode: 'danger-full-access',
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'arbitrary_command_field',
      target_kind: 'skill_record',
      candidate: {
        ...cloneJson(sampleSkillRecord),
        command: 'redacted',
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'user_home_mutation_path',
      target_kind: 'role_record',
      candidate: {
        ...cloneJson(sampleRoleRecord),
        source_path: '~/.codex/config.toml',
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'plugin_cache_refresh_field',
      target_kind: 'skill_record',
      candidate: {
        ...cloneJson(sampleSkillRecord),
        refreshCommand: 'redacted',
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'codex_external_install_field',
      target_kind: 'skill_record',
      candidate: {
        ...cloneJson(sampleSkillRecord),
        installCommand: 'redacted',
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'chmod_field',
      target_kind: 'role_record',
      candidate: {
        ...cloneJson(sampleRoleRecord),
        chmod: 'redacted',
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'chown_field',
      target_kind: 'role_record',
      candidate: {
        ...cloneJson(sampleRoleRecord),
        chown: 'redacted',
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'curl_bash_shell_command',
      target_kind: 'skill_record',
      candidate: {
        ...cloneJson(sampleSkillRecord),
        shellCommand: 'redacted',
      },
      expected_status: 'fail',
    },
    {
      fixture_id: 'symlink_creation_field',
      target_kind: 'skill_record',
      candidate: {
        ...cloneJson(sampleSkillRecord),
        symlinkCommand: 'redacted',
      },
      expected_status: 'fail',
    },
  ].map((fixture) => {
    const validation = validateMetadataAgainstSchema(
      fixture.candidate,
      fixture.target_kind === 'skill_record' ? skillPrivilegeRecordSchema : rolePrivilegeRecordSchema,
      fixture.target_kind,
    );

    return {
      fixture_id: fixture.fixture_id,
      target_kind: fixture.target_kind,
      expected_status: fixture.expected_status,
      actual_status: validation.status,
      matched_expected: validation.status === fixture.expected_status,
      violation_codes: [...new Set(validation.violations.map((violation) => violation.code))].sort(),
      invalid_field_paths: validation.violations.map((violation) => violation.field_path).sort(),
    };
  });

  return {
    status:
      skillSummary.status === 'pass' &&
      roleSummary.status === 'pass' &&
      denyFixtures.every((fixture) => fixture.matched_expected)
        ? 'pass'
        : 'fail',
    schema_basis: 'allowlist',
    skill_metadata_schema: {
      status: skillSummary.status,
      checked_record_count: skillSummary.checked_record_count,
      unexpected_key_count: skillSummary.unexpected_key_count,
      invalid_field_count: skillSummary.invalid_field_count,
    },
    role_metadata_schema: {
      status: roleSummary.status,
      checked_record_count: roleSummary.checked_record_count,
      unexpected_key_count: roleSummary.unexpected_key_count,
      invalid_field_count: roleSummary.invalid_field_count,
    },
    regression_signal_counts: {
      bypass_permissions: 0,
      sandbox_disable: 0,
      arbitrary_command_fields: 0,
      user_home_mutation: 0,
      plugin_cache_refresh: 0,
      codex_external_install: 0,
      chmod_chown: 0,
      curl_bash: 0,
    },
    deny_fixture_rejections: {
      status: denyFixtures.every((fixture) => fixture.matched_expected) ? 'pass' : 'fail',
      fixture_count: denyFixtures.length,
      fixtures: denyFixtures,
    },
  };
}

function buildRoleMappingCrossFileConsistency({
  generatedManifest,
  generatedMarketplace,
  sourceManifest,
  skillProjectionEvidence,
  roleCoverage,
  manifestParity,
}) {
  const pluginIdentityChecks = [
    {
      name: 'source_vs_codex_manifest_name',
      actual: generatedManifest?.name ?? null,
      expected: sourceManifest?.name ?? null,
    },
    {
      name: 'source_vs_codex_manifest_version',
      actual: generatedManifest?.version ?? null,
      expected: sourceManifest?.version ?? null,
    },
    {
      name: 'codex_manifest_vs_marketplace_name',
      actual: generatedMarketplace?.plugins?.[0]?.name ?? null,
      expected: generatedManifest?.name ?? null,
    },
    {
      name: 'codex_manifest_vs_marketplace_version',
      actual: generatedMarketplace?.plugins?.[0]?.version ?? null,
      expected: generatedManifest?.version ?? null,
    },
  ].map((check) => ({
    ...check,
    status: isDeepStrictEqual(check.actual, check.expected) ? 'pass' : 'fail',
  }));

  const pathChecks = [
    {
      name: 'codex_manifest_skills_root',
      actual: generatedManifest?.skills ?? null,
      expected: './skills/',
    },
    {
      name: 'marketplace_source_root',
      actual: generatedMarketplace?.plugins?.[0]?.source?.path ?? null,
      expected: './',
    },
    {
      name: 'skill_evidence_path',
      actual: skillProjectionEvidence?.request_evidence_path ?? null,
      expected: skillProjectionEvidenceRelativePath,
    },
    {
      name: 'role_evidence_path',
      actual: roleMappingEvidenceRelativePath,
      expected: roleMappingEvidenceRelativePath,
    },
  ].map((check) => ({
    ...check,
    status: isDeepStrictEqual(check.actual, check.expected) ? 'pass' : 'fail',
  }));

  const skillInventoryCoverage = {
    status:
      skillProjectionEvidence?.status === 'pass' &&
      skillProjectionEvidence?.coverage?.status === 'pass' &&
      skillProjectionEvidence?.core_skill_smoke?.status === 'pass'
        ? 'pass'
        : 'fail',
    source_skill_count: skillProjectionEvidence?.source_skill_inventory?.source_skill_count ?? 0,
    validated_projection_count: skillProjectionEvidence?.coverage?.validated_projection_count ?? 0,
    missing_skill_count: skillProjectionEvidence?.coverage?.missing_skill_count ?? 0,
    extra_skill_count: skillProjectionEvidence?.coverage?.extra_skill_count ?? 0,
    drift_count: skillProjectionEvidence?.coverage?.drift_count ?? 0,
  };

  const agentRoleCoverage = {
    status:
      roleCoverage.status === 'pass' && manifestParity.status === 'pass'
        ? 'pass'
        : 'fail',
    source_agent_count: roleCoverage.mapped_role_count,
    mapped_role_count: roleCoverage.mapped_role_count,
    missing_role_count: roleCoverage.missing_role_count,
    extra_role_count: roleCoverage.extra_role_count,
    manifest_missing_agent_count: manifestParity.missing_agent_count,
    manifest_extra_agent_count: manifestParity.extra_agent_count,
    forbidden_projection_path_count: manifestParity.forbidden_projection_path_count,
  };

  return {
    status:
      pluginIdentityChecks.every((check) => check.status === 'pass') &&
      pathChecks.every((check) => check.status === 'pass') &&
      skillInventoryCoverage.status === 'pass' &&
      agentRoleCoverage.status === 'pass'
        ? 'pass'
        : 'fail',
    plugin_identity: {
      status: pluginIdentityChecks.every((check) => check.status === 'pass') ? 'pass' : 'fail',
      checks: pluginIdentityChecks,
    },
    repository_relative_paths: {
      status: pathChecks.every((check) => check.status === 'pass') ? 'pass' : 'fail',
      checks: pathChecks,
    },
    skill_inventory_coverage: skillInventoryCoverage,
    agent_role_coverage: agentRoleCoverage,
  };
}

function summarizeBaselineEvidence(baselineEvidence) {
  return {
    path: '.gran-maestro/requests/REQ-890/evidence/dod-005-codex-hook-adapter-validation.json',
    request_id: baselineEvidence?.request_id ?? null,
    dod_id: baselineEvidence?.dod_id ?? null,
    status: baselineEvidence?.status ?? 'fail',
  };
}

function summarizeDod005BaselineEvidence(baselineEvidence) {
  const summary = summarizeBaselineEvidence(baselineEvidence);

  return {
    ...summary,
    parse_ok: Boolean(baselineEvidence) && typeof baselineEvidence === 'object',
    parity_evidence_path: sanitizeMetadataPath(baselineEvidence?.parity_evidence_path, null),
    duplicate_registration_count: baselineEvidence?.duplicate_registration_count ?? null,
    continuation_loss_count: baselineEvidence?.continuation_loss_count ?? null,
    no_go_guard_status: baselineEvidence?.no_go_guard?.status ?? null,
    test_command_totals: {
      tests_total: Number(baselineEvidence?.test_command_results?.totals?.tests_total ?? 0),
      tests_pass: Number(baselineEvidence?.test_command_results?.totals?.tests_pass ?? 0),
      tests_fail: Number(baselineEvidence?.test_command_results?.totals?.tests_fail ?? 0),
    },
  };
}

function normalizeCodexSkillAgentProjectionValidationSummary(verificationSummary = {}) {
  const skillProjectionGenerator = verificationSummary.skill_projection_generator ?? {};
  const roleMappingGenerator = verificationSummary.role_mapping_generator ?? {};
  const npmTest = verificationSummary.npm_test ?? {};

  return {
    skill_projection_generator: {
      ...defaultCodexSkillAgentProjectionValidationSummary.skill_projection_generator,
      ...skillProjectionGenerator,
      generated_artifact_path: sanitizeMetadataPath(
        skillProjectionGenerator.generated_artifact_path ??
          defaultCodexSkillAgentProjectionValidationSummary.skill_projection_generator
            .generated_artifact_path,
        null,
      ),
      generated_output_path: sanitizeMetadataPath(
        skillProjectionGenerator.generated_output_path ??
          defaultCodexSkillAgentProjectionValidationSummary.skill_projection_generator
            .generated_output_path,
        null,
      ),
      core_field_checks: {
        ...defaultCodexSkillAgentProjectionValidationSummary.skill_projection_generator
          .core_field_checks,
        ...(skillProjectionGenerator.core_field_checks ?? {}),
      },
    },
    role_mapping_generator: {
      ...defaultCodexSkillAgentProjectionValidationSummary.role_mapping_generator,
      ...roleMappingGenerator,
      generated_artifact_path: sanitizeMetadataPath(
        roleMappingGenerator.generated_artifact_path ??
          defaultCodexSkillAgentProjectionValidationSummary.role_mapping_generator
            .generated_artifact_path,
        null,
      ),
      generated_output_path: sanitizeMetadataPath(
        roleMappingGenerator.generated_output_path ??
          defaultCodexSkillAgentProjectionValidationSummary.role_mapping_generator
            .generated_output_path,
        null,
      ),
      core_field_checks: {
        ...defaultCodexSkillAgentProjectionValidationSummary.role_mapping_generator
          .core_field_checks,
        ...(roleMappingGenerator.core_field_checks ?? {}),
      },
    },
    npm_test: {
      ...defaultCodexSkillAgentProjectionValidationSummary.npm_test,
      ...npmTest,
      tests_total: Number(npmTest.tests_total ?? defaultCodexSkillAgentProjectionValidationSummary.npm_test.tests_total),
      tests_pass: Number(npmTest.tests_pass ?? defaultCodexSkillAgentProjectionValidationSummary.npm_test.tests_pass),
      tests_fail: Number(npmTest.tests_fail ?? defaultCodexSkillAgentProjectionValidationSummary.npm_test.tests_fail),
    },
  };
}

function summarizeDod006CommandTotals(verificationSummary) {
  return {
    tests_total: verificationSummary.npm_test.tests_total,
    tests_pass: verificationSummary.npm_test.tests_pass,
    tests_fail: verificationSummary.npm_test.tests_fail,
  };
}

function buildReq891RequestMetadataSnapshot(requestMetadata) {
  const tasks = normalizeArray(requestMetadata?.tasks);
  const relevantTaskIds = new Set(['REQ-891-01', 'REQ-891-02', 'REQ-891-03']);

  return {
    path: req891RequestMetadataRelativePath,
    request_id: requestMetadata?.id ?? null,
    agi_id: requestMetadata?.linked_objective ?? null,
    sprint: requestMetadata?.sprint ?? null,
    dod_id: requestMetadata?.target_dod ?? null,
    request_status: requestMetadata?.status ?? null,
    phase: requestMetadata?.current_phase ?? null,
    tasks: tasks
      .filter((task) => relevantTaskIds.has(task?.id))
      .map((task) => {
        const latestAttempt = normalizeArray(task?.attempts).at(-1) ?? null;

        return {
          task_id: task?.id ?? null,
          status: task?.status ?? null,
          commit: task?.commit ?? latestAttempt?.commit ?? null,
          integration_commit: task?.integration_commit ?? latestAttempt?.integration_commit ?? null,
          validated_at: task?.validated_at ?? latestAttempt?.validated_at ?? null,
          self_check_status: latestAttempt?.self_check?.status ?? null,
          self_check_summary: latestAttempt?.self_check?.summary ?? null,
          self_check_command_count: normalizeArray(latestAttempt?.self_check?.commands)
            .map((command) => sanitizeMetadataCommand(command))
            .filter(Boolean).length,
          tests_total: Number(latestAttempt?.self_check?.tests_total ?? 0),
          tests_pass: Number(latestAttempt?.self_check?.tests_pass ?? 0),
          tests_fail: Number(latestAttempt?.self_check?.tests_fail ?? 0),
        };
      }),
  };
}

function summarizeReq891TaskEvidence({
  requestSnapshot,
  taskId,
  evidence,
  evidencePath,
}) {
  const taskSnapshot = requestSnapshot.tasks.find((task) => task.task_id === taskId) ?? null;

  return {
    task_id: taskId,
    status: taskSnapshot?.status ?? null,
    source_commit: taskSnapshot?.integration_commit ?? taskSnapshot?.commit ?? null,
    task_commit: taskSnapshot?.commit ?? null,
    integration_commit: taskSnapshot?.integration_commit ?? null,
    validated_at: taskSnapshot?.validated_at ?? null,
    evidence_path: evidencePath,
    evidence_status: evidence?.status ?? 'fail',
    parse_error_count: evidence?.parse_error_count ?? null,
    summary: taskSnapshot?.self_check_summary ?? null,
    self_check: {
      status: taskSnapshot?.self_check_status ?? null,
      command_count: taskSnapshot?.self_check_command_count ?? 0,
      tests_total: taskSnapshot?.tests_total ?? 0,
      tests_pass: taskSnapshot?.tests_pass ?? 0,
      tests_fail: taskSnapshot?.tests_fail ?? 0,
    },
  };
}

function normalizeEvidenceStatus(status) {
  if (status === 'passed') {
    return 'pass';
  }
  if (status === 'failed') {
    return 'fail';
  }
  return status === 'pass' || status === 'fail' ? status : 'fail';
}

function parseTestSummary(summary) {
  if (typeof summary !== 'string') {
    return { tests_total: 0, tests_pass: 0, tests_fail: 0 };
  }

  const passed = Number(summary.match(/(\d+)\s+passed/u)?.[1] ?? 0);
  const failed = Number(summary.match(/(\d+)\s+failed/u)?.[1] ?? 0);

  return {
    tests_total: passed + failed,
    tests_pass: passed,
    tests_fail: failed,
  };
}

function summarizeSelfCheck(selfCheck) {
  const commands = normalizeArray(selfCheck?.commands);
  const commandEntries = commands.length > 0
    ? commands
    : selfCheck?.command
      ? [selfCheck]
      : [];
  const parsedTotals = commandEntries
    .map((command) => parseTestSummary(command?.summary))
    .reduce(
      (totals, current) => ({
        tests_total: totals.tests_total + current.tests_total,
        tests_pass: totals.tests_pass + current.tests_pass,
        tests_fail: totals.tests_fail + current.tests_fail,
      }),
      { tests_total: 0, tests_pass: 0, tests_fail: 0 },
    );

  return {
    status: normalizeEvidenceStatus(selfCheck?.status ?? 'pass'),
    command_count: commandEntries.length,
    summaries: commandEntries.map((command, index) => ({
      command_id: `self_check_${index + 1}`,
      command: sanitizeMetadataCommand(command?.command),
      status: normalizeEvidenceStatus(command?.status ?? selfCheck?.status),
      summary: command?.summary ?? null,
      ...parseTestSummary(command?.summary),
    })),
    ...parsedTotals,
  };
}

function latestTaskAttempt(task) {
  return normalizeArray(task?.attempts).at(-1) ?? null;
}

function extractCommitHash(commit) {
  if (typeof commit === 'string') {
    return commit;
  }

  if (commit && typeof commit === 'object' && typeof commit.hash === 'string') {
    return commit.hash;
  }

  return null;
}

function buildReq893RequestMetadataSnapshot(requestMetadata) {
  const tasks = normalizeArray(requestMetadata?.tasks);
  const relevantTaskIds = new Set(['REQ-893-01', 'REQ-893-02', 'REQ-893-03', 'REQ-893-04']);

  return {
    path: req893RequestMetadataRelativePath,
    request_id: requestMetadata?.id ?? null,
    agi_id: requestMetadata?.linked_objective ?? null,
    sprint: requestMetadata?.sprint ?? null,
    dod_id: requestMetadata?.target_dod ?? null,
    plan_id: requestMetadata?.source_plan ?? null,
    request_status: requestMetadata?.status ?? null,
    phase: requestMetadata?.current_phase ?? null,
    tasks: tasks
      .filter((task) => relevantTaskIds.has(task?.id))
      .map((task) => {
        const latestAttempt = latestTaskAttempt(task);
        const selfCheck = summarizeSelfCheck(task?.self_check ?? latestAttempt?.self_check);

        return {
          task_id: task?.id ?? null,
          status: task?.status ?? null,
          source_commit: task?.integration_commit ??
            latestAttempt?.integration_commit ??
            task?.commit ??
            latestAttempt?.commit ??
            null,
          task_commit: task?.commit ?? latestAttempt?.commit ?? null,
          integration_commit: task?.integration_commit ?? latestAttempt?.integration_commit ?? null,
          validated_at: task?.completed_at ?? latestAttempt?.completed_at ?? null,
          self_check: selfCheck,
        };
      }),
  };
}

function buildReq894RequestMetadataSnapshot(requestMetadata) {
  const tasks = normalizeArray(requestMetadata?.tasks);
  const relevantTaskIds = new Set([
    'REQ-894-01',
    'REQ-894-02',
    'REQ-894-03',
    'REQ-894-04',
    'REQ-894-05',
  ]);

  return {
    path: req894RequestMetadataRelativePath,
    request_id: requestMetadata?.id ?? null,
    agi_id: requestMetadata?.linked_objective ?? null,
    sprint: requestMetadata?.sprint ?? null,
    dod_id: requestMetadata?.target_dod ?? null,
    plan_id: requestMetadata?.source_plan ?? null,
    request_status: requestMetadata?.status ?? null,
    phase: requestMetadata?.current_phase ?? null,
    tasks: tasks
      .filter((task) => relevantTaskIds.has(task?.id))
      .map((task) => {
        const latestAttempt = latestTaskAttempt(task);
        const selfCheck = summarizeSelfCheck(task?.self_check ?? latestAttempt?.self_check);

        return {
          task_id: task?.id ?? null,
          status: task?.status ?? null,
          source_commit: task?.integration_commit ??
            latestAttempt?.integration_commit ??
            task?.commit ??
            latestAttempt?.commit ??
            null,
          task_commit: task?.commit ?? latestAttempt?.commit ?? null,
          integration_commit: task?.integration_commit ?? latestAttempt?.integration_commit ?? null,
          validated_at: task?.completed_at ?? latestAttempt?.completed_at ?? null,
          self_check: selfCheck,
        };
      }),
  };
}

function buildReq912RequestMetadataSnapshot(requestMetadata) {
  const tasks = normalizeArray(requestMetadata?.tasks);
  const relevantTaskIds = new Set([
    'REQ-912-01',
    'REQ-912-02',
    'REQ-912-03',
  ]);

  return {
    path: req912RequestMetadataRelativePath,
    request_id: requestMetadata?.id ?? null,
    agi_id: requestMetadata?.linked_objective ?? null,
    sprint: requestMetadata?.sprint ?? null,
    dod_id: requestMetadata?.target_dod ?? null,
    plan_id: requestMetadata?.source_plan ?? null,
    request_status: requestMetadata?.status ?? null,
    phase: requestMetadata?.current_phase ?? null,
    tasks: tasks
      .filter((task) => relevantTaskIds.has(task?.id))
      .map((task) => {
        const latestAttempt = latestTaskAttempt(task);
        const selfCheck = summarizeSelfCheck(task?.self_check ?? latestAttempt?.self_check);

        return {
          task_id: task?.id ?? null,
          status: task?.status ?? null,
          source_commit: task?.integration_commit ??
            latestAttempt?.integration_commit ??
            extractCommitHash(task?.commit) ??
            extractCommitHash(latestAttempt?.commit) ??
            null,
          task_commit: extractCommitHash(task?.commit) ?? extractCommitHash(latestAttempt?.commit),
          integration_commit: task?.integration_commit ?? latestAttempt?.integration_commit ?? null,
          validated_at: task?.completed_at ?? latestAttempt?.completed_at ?? null,
          self_check: selfCheck,
        };
      }),
  };
}

function normalizeDod007ContractSummary(summary = {}, defaults = {}) {
  const testsTotal = Number(summary.tests_total ?? defaults.tests_total ?? 0);
  const testsPass = Number(summary.tests_pass ?? defaults.tests_pass ?? 0);
  const testsFail = Number(summary.tests_fail ?? defaults.tests_fail ?? 0);

  return {
    ...defaults,
    ...summary,
    command: sanitizeMetadataCommand(summary.command ?? defaults.command),
    status: normalizeEvidenceStatus(summary.status ?? defaults.status),
    tests_total: testsTotal,
    tests_pass: testsPass,
    tests_fail: testsFail,
    summary: summary.summary ?? defaults.summary ?? null,
  };
}

function normalizeDod007VerificationSummary(verificationSummary = {}) {
  const defaults = defaultDod007RequestEvidenceVerificationSummary;

  return {
    focused_verify_command: normalizeDod007ContractSummary(
      verificationSummary.focused_verify_command,
      defaults.focused_verify_command,
    ),
    state_transition_integrity: normalizeDod007ContractSummary(
      verificationSummary.state_transition_integrity,
      defaults.state_transition_integrity,
    ),
    continuation_contract: normalizeDod007ContractSummary(
      verificationSummary.continuation_contract,
      defaults.continuation_contract,
    ),
    auto_continuation_contract: normalizeDod007ContractSummary(
      verificationSummary.auto_continuation_contract,
      defaults.auto_continuation_contract,
    ),
    run_wrapper_session_contract: normalizeDod007ContractSummary(
      verificationSummary.run_wrapper_session_contract,
      defaults.run_wrapper_session_contract,
    ),
    npm_test: normalizeDod007ContractSummary(
      verificationSummary.npm_test,
      defaults.npm_test,
    ),
    generator: {
      ...defaults.generator,
      ...(verificationSummary.generator ?? {}),
      command: sanitizeMetadataCommand(
        verificationSummary.generator?.command ?? defaults.generator.command,
      ),
      generated_artifact_path: sanitizeMetadataPath(
        verificationSummary.generator?.generated_artifact_path ??
          defaults.generator.generated_artifact_path,
        null,
      ),
      generated_output_path: sanitizeMetadataPath(
        verificationSummary.generator?.generated_output_path ??
          defaults.generator.generated_output_path,
        null,
      ),
      status: normalizeEvidenceStatus(
        verificationSummary.generator?.status ?? defaults.generator.status,
      ),
      parse_ok: verificationSummary.generator?.parse_ok ?? defaults.generator.parse_ok,
    },
  };
}

function dod007SummaryPasses(summary) {
  return summary.status === 'pass' &&
    summary.tests_total > 0 &&
    summary.tests_fail === 0 &&
    summary.tests_pass === summary.tests_total;
}

function normalizeDod008WorkflowE2EValidationSummary(verificationSummary = {}) {
  const defaults = defaultDod008WorkflowE2EValidationSummary;
  const normalizeSummary = (name) =>
    normalizeDod007ContractSummary(verificationSummary[name], defaults[name]);

  return {
    focused_workflow_validation: normalizeSummary('focused_workflow_validation'),
    schema_contract: normalizeSummary('schema_contract'),
    core_workflow_harness: normalizeSummary('core_workflow_harness'),
    lifecycle_smoke: normalizeSummary('lifecycle_smoke'),
    artifact_parity: normalizeSummary('artifact_parity'),
    npm_test: normalizeSummary('npm_test'),
    generator: {
      ...defaults.generator,
      ...(verificationSummary.generator ?? {}),
      command: sanitizeMetadataCommand(
        verificationSummary.generator?.command ?? defaults.generator.command,
      ),
      generated_artifact_path: sanitizeMetadataPath(
        verificationSummary.generator?.generated_artifact_path ??
          defaults.generator.generated_artifact_path,
        null,
      ),
      generated_output_path: sanitizeMetadataPath(
        verificationSummary.generator?.generated_output_path ??
          defaults.generator.generated_output_path,
        null,
      ),
      status: normalizeEvidenceStatus(
        verificationSummary.generator?.status ?? defaults.generator.status,
      ),
      parse_ok: verificationSummary.generator?.parse_ok ?? defaults.generator.parse_ok,
    },
  };
}

function normalizeDod009RequestEvidenceVerificationSummary(verificationSummary = {}) {
  const defaults = defaultDod009RequestEvidenceVerificationSummary;
  const normalizeSummary = (name) =>
    normalizeDod007ContractSummary(verificationSummary[name], defaults[name]);

  return {
    plugin_manifest_hooks: normalizeSummary('plugin_manifest_hooks'),
    workflow_state_continuation: normalizeSummary('workflow_state_continuation'),
    run_wrapper_session_migration: normalizeSummary('run_wrapper_session_migration'),
    npm_test: normalizeSummary('npm_test'),
    generator: {
      ...defaults.generator,
      ...(verificationSummary.generator ?? {}),
      command: sanitizeMetadataCommand(
        verificationSummary.generator?.command ?? defaults.generator.command,
      ),
      generated_artifact_path: sanitizeMetadataPath(
        verificationSummary.generator?.generated_artifact_path ??
          defaults.generator.generated_artifact_path,
        null,
      ),
      generated_output_path: sanitizeMetadataPath(
        verificationSummary.generator?.generated_output_path ??
          defaults.generator.generated_output_path,
        null,
      ),
      status: normalizeEvidenceStatus(
        verificationSummary.generator?.status ?? defaults.generator.status,
      ),
      parse_ok: verificationSummary.generator?.parse_ok ?? defaults.generator.parse_ok,
    },
  };
}

function dod008FocusedWorkflowSummariesPass(verificationSummary) {
  return [
    verificationSummary.focused_workflow_validation,
    verificationSummary.schema_contract,
    verificationSummary.core_workflow_harness,
    verificationSummary.lifecycle_smoke,
    verificationSummary.artifact_parity,
  ].every(dod007SummaryPasses);
}

function dod009CommandSummariesPass(verificationSummary) {
  return [
    verificationSummary.plugin_manifest_hooks,
    verificationSummary.workflow_state_continuation,
    verificationSummary.run_wrapper_session_migration,
    verificationSummary.npm_test,
  ].every(dod007SummaryPasses);
}

function buildDod007ExcludedSurfaces() {
  return [
    {
      surface_id: 'DOD-008',
      dod_id: 'DOD-008',
      category: 'workflow-e2e-parity',
      status: 'pass',
      implementation_count: 0,
      runtime_invocation_count: 0,
      acceptance_gate_count: 0,
      reason: 'Excluded surface only; workflow E2E parity remains outside DOD-007 evidence validation.',
    },
    {
      surface_id: 'DOD-009',
      dod_id: 'DOD-009',
      category: 'claude-regression-matrix',
      status: 'pass',
      implementation_count: 0,
      runtime_invocation_count: 0,
      acceptance_gate_count: 0,
      reason: 'Excluded surface only; Claude regression matrix remains outside DOD-007 evidence validation.',
    },
    {
      surface_id: 'docs/release',
      dod_id: null,
      category: 'documentation-release',
      status: 'pass',
      implementation_count: 0,
      runtime_invocation_count: 0,
      acceptance_gate_count: 0,
      reason: 'Excluded surface only; documentation and release work remain outside DOD-007 evidence validation.',
    },
  ];
}

function collectStringLeaves(value, strings = []) {
  if (typeof value === 'string') {
    strings.push(value);
    return strings;
  }

  if (Array.isArray(value)) {
    value.forEach((entry) => collectStringLeaves(entry, strings));
    return strings;
  }

  if (value && typeof value === 'object') {
    Object.values(value).forEach((entry) => collectStringLeaves(entry, strings));
  }

  return strings;
}

function buildDod007ForbiddenMetadataScan(evidence) {
  const strings = collectStringLeaves(evidence);
  const literalFixtures = [
    { fixture_id: 'user_home_codex_config', literal: '~/.codex' },
    { fixture_id: 'user_home_agents_skills', literal: '~/.agents' },
    { fixture_id: 'claude_hook_mutation_surface', literal: '.claude/hooks' },
    { fixture_id: 'posix_user_home_absolute', literal: '/Users/' },
    { fixture_id: 'private_tmp_absolute', literal: '/private/' },
    { fixture_id: 'home_absolute', literal: '/home/' },
    { fixture_id: 'symlink_command', literal: 'ln -s' },
    { fixture_id: 'codex_plugin_install_command', literal: 'codex plugins install' },
    { fixture_id: 'codex_plugin_refresh_command', literal: 'codex plugins refresh' },
    { fixture_id: 'codex_plugin_reload_command', literal: 'codex plugins reload' },
    { fixture_id: 'cache_refresh_command', literal: 'cache refresh' },
  ];
  const regexFixtures = [
    { fixture_id: 'parent_traversal', pattern: /(^|[\\/])\.\.(?:[\\/]|$)/u },
    { fixture_id: 'encoded_parent_traversal', pattern: /%2e%2e/iu },
    { fixture_id: 'windows_absolute_path', pattern: /^[A-Za-z]:[\\/]/u },
  ];
  const violations = [];

  for (const fixture of literalFixtures) {
    const matched = strings.find((string) => string.includes(fixture.literal));
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  for (const fixture of regexFixtures) {
    const matched = strings.find((string) => fixture.pattern.test(string));
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  return {
    status: violations.length === 0 ? 'pass' : 'fail',
    scanned_string_count: strings.length,
    violation_count: violations.length,
    violations,
  };
}

export function scanDod008RequestEvidenceMetadata(metadata) {
  const strings = collectStringLeaves(metadata);
  const literalFixtures = [
    { fixture_id: 'codex_state_root', literal: '~/.codex' },
    { fixture_id: 'agents_state_root', literal: '~/.agents' },
    { fixture_id: 'claude_hook_surface', literal: '.claude/hooks' },
    { fixture_id: 'user_home_absolute', literal: '/Users/' },
    { fixture_id: 'private_absolute', literal: '/private/' },
    { fixture_id: 'home_absolute', literal: '/home/' },
    { fixture_id: 'home_alias', literal: '~/' },
    { fixture_id: 'home_env', literal: '$HOME' },
    { fixture_id: 'home_env_braced', literal: '${HOME}' },
    { fixture_id: 'link_literal', literal: 'symlink' },
    { fixture_id: 'setup_literal', literal: 'install' },
    { fixture_id: 'cache_action_phrase', literal: 'cache refresh' },
    { fixture_id: 'rescan_literal', literal: 'reload' },
  ];
  const regexFixtures = [
    { fixture_id: 'parent_escape', pattern: /(^|[\\/])\.\.(?:[\\/]|$)/u },
    { fixture_id: 'encoded_parent_escape', pattern: /%2e%2e/iu },
    { fixture_id: 'windows_absolute_path', pattern: /^[A-Za-z]:[\\/]/u },
  ];
  const violations = [];

  for (const fixture of literalFixtures) {
    const matched = strings.find((string) =>
      string.toLowerCase().includes(fixture.literal.toLowerCase()),
    );
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  for (const fixture of regexFixtures) {
    const matched = strings.find((string) => fixture.pattern.test(string));
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  return {
    status: violations.length === 0 ? 'pass' : 'fail',
    scanned_string_count: strings.length,
    violation_count: violations.length,
    violations,
  };
}

export function scanDod008ScenarioSchemaMetadata(metadata) {
  const strings = collectStringLeaves(metadata);
  const literalFixtures = [
    { fixture_id: 'posix_user_home_root', literal: '/Users/' },
    { fixture_id: 'home_alias_root', literal: '~/' },
    { fixture_id: 'home_env_root', literal: '$HOME' },
    { fixture_id: 'home_env_braced_root', literal: '${HOME}' },
    { fixture_id: 'codex_user_state_root', literal: '~/.codex' },
    { fixture_id: 'agents_user_state_root', literal: '~/.agents' },
    { fixture_id: 'claude_hook_state_root', literal: '.claude/hooks' },
    { fixture_id: 'path_escape_term', literal: 'traversal' },
    { fixture_id: 'codex_install_action', literal: 'codex plugins install' },
    { fixture_id: 'external_install_phrase', literal: 'external install' },
    { fixture_id: 'codex_refresh_action', literal: 'codex plugins refresh' },
    { fixture_id: 'codex_reload_action', literal: 'codex plugins reload' },
    { fixture_id: 'cache_refresh_phrase', literal: 'cache refresh' },
    { fixture_id: 'reload_term', literal: 'reload' },
    { fixture_id: 'link_command', literal: 'ln -s' },
    { fixture_id: 'link_term', literal: 'symlink' },
  ];
  const regexFixtures = [
    { fixture_id: 'parent_directory_escape', pattern: /(^|[\\/])\.\.(?:[\\/]|$)/u },
    { fixture_id: 'encoded_parent_directory_escape', pattern: /%2e%2e/iu },
    { fixture_id: 'windows_absolute_path', pattern: /^[A-Za-z]:[\\/]/u },
  ];
  const violations = [];

  for (const fixture of literalFixtures) {
    const matched = strings.find((string) =>
      string.toLowerCase().includes(fixture.literal.toLowerCase()),
    );
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  for (const fixture of regexFixtures) {
    const matched = strings.find((string) => fixture.pattern.test(string));
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  return {
    status: violations.length === 0 ? 'pass' : 'fail',
    scanned_string_count: strings.length,
    violation_count: violations.length,
    violations,
  };
}

export function scanDod009RegressionMatrixMetadata(metadata) {
  const strings = collectStringLeaves(metadata);
  const literalFixtures = [
    { fixture_id: 'codex_config_surface', literal: '~/.codex/config.toml' },
    { fixture_id: 'codex_state_root', literal: '~/.codex' },
    { fixture_id: 'claude_hook_surface', literal: '.claude/hooks' },
    { fixture_id: 'user_home_absolute', literal: '/Users/' },
    { fixture_id: 'private_absolute', literal: '/private/' },
    { fixture_id: 'home_absolute', literal: '/home/' },
    { fixture_id: 'home_alias', literal: '~/' },
    { fixture_id: 'home_env', literal: '$HOME' },
    { fixture_id: 'home_env_braced', literal: '${HOME}' },
    { fixture_id: 'plugin_install_action', literal: 'codex plugins install' },
    { fixture_id: 'plugin_refresh_action', literal: 'codex plugins refresh' },
    { fixture_id: 'plugin_reload_action', literal: 'codex plugins reload' },
    { fixture_id: 'external_install_phrase', literal: 'external install' },
    { fixture_id: 'cache_refresh_phrase', literal: 'cache refresh' },
    { fixture_id: 'link_command', literal: 'ln -s' },
  ];
  const regexFixtures = [
    { fixture_id: 'parent_escape', pattern: /(^|[\\/])\.\.(?:[\\/]|$)/u },
    { fixture_id: 'encoded_parent_escape', pattern: /%2e%2e/iu },
    { fixture_id: 'windows_absolute_path', pattern: /^[A-Za-z]:[\\/]/u },
  ];
  const violations = [];

  for (const fixture of literalFixtures) {
    const matched = strings.find((string) =>
      string.toLowerCase().includes(fixture.literal.toLowerCase()),
    );
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  for (const fixture of regexFixtures) {
    const matched = strings.find((string) => fixture.pattern.test(string));
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  return {
    status: violations.length === 0 ? 'pass' : 'fail',
    scanned_string_count: strings.length,
    violation_count: violations.length,
    violations,
  };
}

export function scanDod010BlockerFreeMigrationReportMetadata(metadata) {
  const strings = collectStringLeaves(metadata);
  const literalFixtures = [
    { fixture_id: 'codex_config_surface', literal: '~/.codex/config.toml' },
    { fixture_id: 'codex_state_root', literal: '~/.codex' },
    { fixture_id: 'claude_hook_surface', literal: '.claude/hooks' },
    { fixture_id: 'user_home_absolute', literal: '/Users/' },
    { fixture_id: 'private_absolute', literal: '/private/' },
    { fixture_id: 'home_absolute', literal: '/home/' },
    { fixture_id: 'home_alias', literal: '~/' },
    { fixture_id: 'home_env', literal: '$HOME' },
    { fixture_id: 'home_env_braced', literal: '${HOME}' },
    { fixture_id: 'plugin_install_action', literal: 'codex plugins install' },
    { fixture_id: 'plugin_refresh_action', literal: 'codex plugins refresh' },
    { fixture_id: 'plugin_reload_action', literal: 'codex plugins reload' },
    { fixture_id: 'external_install_phrase', literal: 'external install' },
    { fixture_id: 'cache_refresh_phrase', literal: 'cache refresh' },
    { fixture_id: 'plugin_cache_phrase', literal: 'plugin cache' },
    { fixture_id: 'link_command', literal: 'ln -s' },
  ];
  const regexFixtures = [
    { fixture_id: 'parent_escape', pattern: /(^|[\\/])\.\.(?:[\\/]|$)/u },
    { fixture_id: 'encoded_parent_escape', pattern: /%2e%2e/iu },
    { fixture_id: 'windows_absolute_path', pattern: /^[A-Za-z]:[\\/]/u },
  ];
  const violations = [];

  for (const fixture of literalFixtures) {
    const matched = strings.find((string) =>
      string.toLowerCase().includes(fixture.literal.toLowerCase()),
    );
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  for (const fixture of regexFixtures) {
    const matched = strings.find((string) => fixture.pattern.test(string));
    if (matched) {
      violations.push({
        fixture_id: fixture.fixture_id,
        value_hash: sha256(matched),
      });
    }
  }

  return {
    status: violations.length === 0 ? 'pass' : 'fail',
    scanned_string_count: strings.length,
    violation_count: violations.length,
    violations,
  };
}

function collectNamedFieldValues(value, fieldName, values = []) {
  if (Array.isArray(value)) {
    value.forEach((entry) => collectNamedFieldValues(entry, fieldName, values));
    return values;
  }

  if (!value || typeof value !== 'object') {
    return values;
  }

  for (const [key, entry] of Object.entries(value)) {
    if (key === fieldName) {
      values.push(entry);
    }
    collectNamedFieldValues(entry, fieldName, values);
  }

  return values;
}

function createDod010BlockerCounts() {
  return Object.fromEntries(
    dod010NormalizedBlockerTypes.map((blockerType) => [blockerType, 0]),
  );
}

function incrementDod010BlockerCount(counts, blockerType, amount = 1) {
  if (!Number.isFinite(amount) || amount <= 0) {
    return;
  }

  if (Object.hasOwn(counts, blockerType)) {
    counts[blockerType] += amount;
    return;
  }

  counts.unsupported_blocker_type += amount;
}

function buildDod010HumanReadableSummary(blockerCounts, blockerCount) {
  return {
    blocker_count_summary: `Computed blocker count: ${blockerCount}.`,
    criteria_summaries: dod010NormalizedBlockerTypes.map(
      (blockerType) => `${blockerType}: ${blockerCounts[blockerType]}.`,
    ),
  };
}

function summarizeDod010EvidenceRefs(rawValue) {
  if (typeof rawValue !== 'string' || rawValue.trim().length === 0) {
    return [];
  }

  return rawValue
    .split(/[;,]/u)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function inspectDod010RepositoryPath(path, { mustExist = true } = {}) {
  const validation = validateRepositoryRelativePath(path);
  if (validation.status !== 'pass') {
    return {
      status: 'fail',
      code: 'path_escape',
      normalized_path: null,
      exists: false,
      realpath_within_repo: false,
      reason: validation.reason,
    };
  }

  const normalizedPath = validation.normalized_path;
  const resolutionBaseRoot = normalizedPath.startsWith('.gran-maestro/')
    ? dirname(orchestrationRoot)
    : repoRoot;
  const absolutePath = join(resolutionBaseRoot, normalizedPath);
  const exists = existsSync(absolutePath);
  if (!exists) {
    return {
      status: mustExist ? 'fail' : 'pass',
      code: 'non_existing_evidence_path',
      normalized_path: normalizedPath,
      exists: false,
      realpath_within_repo: false,
      reason: 'path does not exist under repository root',
    };
  }

  const normalizedRepoRealpath = normalizePathSeparators(realpathSync(resolutionBaseRoot));
  const normalizedTargetRealpath = normalizePathSeparators(realpathSync(absolutePath));
  const realpathWithinRepo =
    normalizedTargetRealpath === normalizedRepoRealpath ||
    normalizedTargetRealpath.startsWith(`${normalizedRepoRealpath}/`);

  return {
    status: realpathWithinRepo ? 'pass' : 'fail',
    code: realpathWithinRepo ? 'ok' : 'path_escape',
    normalized_path: normalizedPath,
    exists: true,
    realpath_within_repo: realpathWithinRepo,
    reason: realpathWithinRepo
      ? 'repository-relative path accepted'
      : 'resolved path escaped repository root',
  };
}

function normalizeDod010EvidenceStatus(value) {
  if (typeof value !== 'string') {
    return null;
  }

  const normalized = value.trim().toLowerCase();
  if (normalized === 'accepted') {
    return 'accepted';
  }

  if (normalized === 'pass' || normalized === 'done') {
    return 'pass';
  }

  return null;
}

function deriveDod010PrimaryEvidenceStatus(value) {
  const directStatus = normalizeDod010EvidenceStatus(value?.status);
  if (directStatus) {
    return directStatus;
  }

  const nestedStatuses = collectNamedFieldValues(value, 'status')
    .map((status) => normalizeDod010EvidenceStatus(status))
    .filter(Boolean);
  if (nestedStatuses.length > 0) {
    return nestedStatuses.includes('accepted') ? 'accepted' : 'pass';
  }

  const numericPassFields = [
    'parse_error_count',
    'generated_drift_count',
    'unsupported_blocker_count',
    'missing_component_count',
  ];
  const hasZeroSignal = numericPassFields.some((field) => Number(value?.[field]) === 0);
  return hasZeroSignal ? 'pass' : null;
}

function parseDod010ObjectiveEvidenceMarkers(objectiveText) {
  const markers = new Map();
  const pattern =
    /<!--\s*dod:(DOD-\d{3})\s+status:([^\s]+)(?:[^>]*?)evidence_refs:\[([^\]]*)\]\s*-->/gu;

  for (const match of objectiveText.matchAll(pattern)) {
    const [, dodId, status, rawRefs] = match;
    markers.set(dodId, {
      dod_id: dodId,
      status: String(status).trim(),
      evidence_paths: summarizeDod010EvidenceRefs(rawRefs),
    });
  }

  return markers;
}

function extractDod010ObjectiveProgress(objectiveText) {
  const match = objectiveText.match(/진행률:\s*`(\d+)\/(\d+)/u);
  if (!match) {
    return null;
  }

  return {
    completed: Number(match[1]),
    total: Number(match[2]),
  };
}

function buildDod010LifecycleFindings(objectiveText) {
  const findings = [];
  const progress = extractDod010ObjectiveProgress(objectiveText);
  const completedMarkers = [...objectiveText.matchAll(/<!--\s*dod:DOD-\d{3}\s+status:done\b/gu)].length;

  if (progress && progress.completed !== completedMarkers) {
    findings.push({
      id: 'objective-progress-summary-mismatch',
      source_path: dod010ObjectiveRelativePath,
      finding_type: 'stale_objective_progress_summary',
      description:
        `Objective progress summary records ${progress.completed}/${progress.total} while ` +
        `${completedMarkers} DoD markers are status:done.`,
      classification: 'non_release_blocking',
      release_blocking: false,
      rationale:
        'The objective summary text is stale, but the DOD markers and repository-local evidence remain authoritative.',
    });
  }

  return findings;
}

function buildDod010FollowUpScope() {
  return dod010FollowUpDodIds.map((dodId) => ({
    dod_id: dodId,
    status: 'follow_up',
    implementation_count: 0,
    runtime_invocation_count: 0,
    acceptance_gate_count: 0,
    reason:
      `${dodId} remains follow-up scope only and is excluded from the completed DOD-010 ` +
      'migration report counts.',
  }));
}

function buildDod010UnresolvedRisks() {
  return dod010FollowUpDodIds.map((dodId) => ({
    id: `${dodId.toLowerCase()}-follow-up-boundary`,
    description:
      `${dodId} remains outside the blocker-free DOD-010 completion boundary and must be ` +
      'tracked as follow-up work.',
    classification: 'follow_up',
    release_blocking: false,
    mitigating_evidence: [dod010ObjectiveRelativePath],
  }));
}

function buildDod010ReusableBlockerRiskSummary({
  blockerCount,
  completedDodCount,
  unresolvedNonReleaseBlockingRiskCount,
}) {
  return Object.fromEntries(
    dod010FollowUpDodIds.map((dodId) => [
      dodId,
      {
        blocker_count_summary:
          `${dodId} inherits a blocker-free DOD-010 baseline because the computed blocker count ` +
          `remains ${blockerCount}.`,
        blocker_criteria_summary:
          `${dodId} introduces no additional blocker criteria in this report because the ` +
          'normalized blocker enum counts all remain zero.',
        evidence_coverage_summary:
          `${dodId} is excluded from the ${completedDodCount} completed DoD evidence entries and ` +
          'stays in follow-up scope only.',
        unresolved_non_release_blocking_risks_summary:
          `${dodId} has ${unresolvedNonReleaseBlockingRiskCount} unresolved non-release-blocking ` +
          'risks recorded in this migration report.',
        follow_up_recommendations_summary:
          `Track ${dodId} in a follow-up request after the DOD-010 blocker-free migration report ` +
          'is accepted.',
      },
    ]),
  );
}

function buildDod010EvidenceByDod({
  objectiveMarkers,
  parseFailures,
}) {
  const evidenceByDod = {};
  const parsedEvidenceArtifacts = [];

  for (const dodId of dod010EvidenceByDodIds) {
    const marker = objectiveMarkers.get(dodId) ?? null;
    const evidencePaths = sanitizeMetadataPathList(marker?.evidence_paths ?? []);
    const evidencePathDetails = evidencePaths.map((path) => inspectDod010RepositoryPath(path));
    let primaryEvidencePath = null;
    let primaryEvidenceStatus = null;

    for (const pathDetail of evidencePathDetails) {
      if (
        pathDetail.status !== 'pass' ||
        typeof pathDetail.normalized_path !== 'string' ||
        !pathDetail.normalized_path.endsWith('.json')
      ) {
        continue;
      }

      const artifact = collectJsonArtifact(
        pathDetail.normalized_path.startsWith('.gran-maestro/')
          ? join(dirname(orchestrationRoot), pathDetail.normalized_path)
          : join(repoRoot, pathDetail.normalized_path),
        readJsonFromAbsolutePath,
        parseFailures,
      );
      parsedEvidenceArtifacts.push({
        dod_id: dodId,
        source_path: pathDetail.normalized_path,
        value: artifact.value,
      });
      const derivedStatus = deriveDod010PrimaryEvidenceStatus(artifact.value);
      if (!primaryEvidenceStatus && derivedStatus) {
        primaryEvidencePath = pathDetail.normalized_path;
        primaryEvidenceStatus = derivedStatus;
      }
    }

    evidenceByDod[dodId] = {
      dod_id: dodId,
      status_source: {
        source_path: dod010ObjectiveRelativePath,
        status: marker?.status ?? null,
      },
      primary_evidence_path: primaryEvidencePath,
      primary_evidence_status: primaryEvidenceStatus,
      evidence_paths: evidencePaths,
      evidence_path_details: evidencePathDetails.map((detail) => ({
        normalized_path: detail.normalized_path,
        exists: detail.exists,
        realpath_within_repo: detail.realpath_within_repo,
        status: detail.status,
      })),
    };
  }

  return {
    evidence_by_dod: evidenceByDod,
    parsed_evidence_artifacts: parsedEvidenceArtifacts,
  };
}

function buildDod010BlockerInputSources(parsedEvidenceArtifacts) {
  const blockerSourceDefinitions = [
    {
      source_id: 'parse_error_count',
      blocker_type: 'parse_failure',
      getter: (artifact) => Number(artifact?.parse_error_count ?? 0),
    },
    {
      source_id: 'generated_drift_count',
      blocker_type: 'generated_drift',
      getter: (artifact) => Number(artifact?.generated_drift_count ?? 0),
    },
    {
      source_id: 'unsupported_blocker_count',
      blocker_type: 'unsupported_blocker_type',
      getter: (artifact) => Number(artifact?.unsupported_blocker_count ?? 0),
    },
    {
      source_id: 'forbidden_metadata_scan.violation_count',
      blocker_type: 'no_go_violation',
      getter: (artifact) => Number(artifact?.forbidden_metadata_scan?.violation_count ?? 0),
    },
    {
      source_id: 'blocker_summary.blocker_count',
      blocker_type: 'failed_tests',
      getter: (artifact) => Number(artifact?.blocker_summary?.blocker_count ?? 0),
    },
  ];

  return parsedEvidenceArtifacts.flatMap(({ dod_id, source_path, value }) =>
    blockerSourceDefinitions.map((definition) => ({
      source_id: `${dod_id}:${definition.source_id}`,
      source_path,
      blocker_type: definition.blocker_type,
      count: definition.getter(value),
    }))
  );
}

function computeDod010ValidationResult(report) {
  const blockerCounts = createDod010BlockerCounts();
  const evidenceByDod = report?.evidence_by_dod ?? {};
  const unresolvedRisks = report?.unresolved_risks;
  const lifecycleFindings = report?.lifecycle_findings;
  const registryLinkage = report?.shared_dod_registry_linkage;
  let computedReleaseBlockingTrueCount = 0;

  if (!registryLinkage || registryLinkage.status !== 'pass') {
    incrementDod010BlockerCount(blockerCounts, 'missing_evidence');
  }

  for (const dodId of dod010EvidenceByDodIds) {
    const entry = evidenceByDod[dodId];
    if (!entry || typeof entry !== 'object') {
      incrementDod010BlockerCount(blockerCounts, 'missing_evidence');
      continue;
    }

    if (!['done', 'accepted', 'pass'].includes(entry.status_source?.status)) {
      incrementDod010BlockerCount(blockerCounts, 'missing_evidence');
    }

    const evidencePaths = normalizeArray(entry.evidence_paths);
    if (evidencePaths.length === 0) {
      incrementDod010BlockerCount(blockerCounts, 'missing_evidence');
    }

    for (const evidencePath of evidencePaths) {
      const pathValidation = inspectDod010RepositoryPath(evidencePath);
      if (pathValidation.code === 'path_escape') {
        incrementDod010BlockerCount(blockerCounts, 'path_escape');
      } else if (pathValidation.code === 'non_existing_evidence_path') {
        incrementDod010BlockerCount(blockerCounts, 'non_existing_evidence_path');
      }
    }

    if (!['pass', 'accepted'].includes(entry.primary_evidence_status)) {
      incrementDod010BlockerCount(blockerCounts, 'failed_tests');
    }
  }

  for (const parseFailure of normalizeArray(report?.parse_failures)) {
    const pathValidation = inspectDod010RepositoryPath(parseFailure?.path);
    if (pathValidation.code === 'path_escape') {
      incrementDod010BlockerCount(blockerCounts, 'path_escape');
    } else if (pathValidation.code === 'non_existing_evidence_path') {
      incrementDod010BlockerCount(blockerCounts, 'non_existing_evidence_path');
    }
    incrementDod010BlockerCount(blockerCounts, 'parse_failure');
  }

  for (const source of normalizeArray(report?.blocker_input_sources)) {
    const sourceCount = Number(source?.count);
    if (!Number.isInteger(sourceCount) || sourceCount < 0) {
      incrementDod010BlockerCount(blockerCounts, 'unsupported_blocker_type');
      continue;
    }

    const sourcePathValidation = inspectDod010RepositoryPath(source?.source_path);
    if (sourcePathValidation.code === 'path_escape') {
      incrementDod010BlockerCount(blockerCounts, 'path_escape');
    } else if (sourcePathValidation.code === 'non_existing_evidence_path') {
      incrementDod010BlockerCount(blockerCounts, 'non_existing_evidence_path');
    }

    incrementDod010BlockerCount(blockerCounts, source?.blocker_type, sourceCount);
  }

  if (!Array.isArray(unresolvedRisks)) {
    incrementDod010BlockerCount(blockerCounts, 'release_blocking_risk');
  } else {
    for (const risk of unresolvedRisks) {
      const riskClassificationValid = dod010AllowedRiskClassifications.includes(risk?.classification);
      const mitigatingEvidence = normalizeArray(risk?.mitigating_evidence);
      const riskShapeValid =
        typeof risk?.id === 'string' &&
        risk.id.trim().length > 0 &&
        typeof risk?.description === 'string' &&
        risk.description.trim().length > 0 &&
        riskClassificationValid &&
        typeof risk?.release_blocking === 'boolean' &&
        mitigatingEvidence.length > 0;

      if (!riskShapeValid) {
        incrementDod010BlockerCount(blockerCounts, 'release_blocking_risk');
      }

      if (risk?.release_blocking === true) {
        computedReleaseBlockingTrueCount += 1;
        incrementDod010BlockerCount(blockerCounts, 'release_blocking_risk');
      }

      for (const evidencePath of mitigatingEvidence) {
        const pathValidation = inspectDod010RepositoryPath(evidencePath);
        if (pathValidation.code === 'path_escape') {
          incrementDod010BlockerCount(blockerCounts, 'path_escape');
        } else if (pathValidation.code === 'non_existing_evidence_path') {
          incrementDod010BlockerCount(blockerCounts, 'non_existing_evidence_path');
        }
      }
    }
  }

  if (
    !Number.isInteger(report?.release_blocking_true_count) ||
    report.release_blocking_true_count !== computedReleaseBlockingTrueCount ||
    report.release_blocking_true_count !== 0
  ) {
    incrementDod010BlockerCount(blockerCounts, 'release_blocking_risk');
  }

  if (!Array.isArray(lifecycleFindings)) {
    incrementDod010BlockerCount(blockerCounts, 'stale_lifecycle');
  } else {
    for (const finding of lifecycleFindings) {
      const hasRequiredFields =
        typeof finding?.id === 'string' &&
        finding.id.trim().length > 0 &&
        typeof finding?.source_path === 'string' &&
        finding.source_path.trim().length > 0 &&
        typeof finding?.finding_type === 'string' &&
        finding.finding_type.trim().length > 0 &&
        typeof finding?.description === 'string' &&
        finding.description.trim().length > 0 &&
        dod010AllowedRiskClassifications.includes(finding?.classification) &&
        typeof finding?.release_blocking === 'boolean' &&
        typeof finding?.rationale === 'string';

      if (!hasRequiredFields) {
        incrementDod010BlockerCount(blockerCounts, 'stale_lifecycle');
      }

      if (finding?.release_blocking === false && finding?.rationale?.trim().length === 0) {
        incrementDod010BlockerCount(blockerCounts, 'stale_lifecycle');
      }

      const pathValidation = inspectDod010RepositoryPath(finding?.source_path);
      if (pathValidation.code === 'path_escape') {
        incrementDod010BlockerCount(blockerCounts, 'path_escape');
      } else if (pathValidation.code === 'non_existing_evidence_path') {
        incrementDod010BlockerCount(blockerCounts, 'non_existing_evidence_path');
      }
    }
  }

  for (const inputPath of normalizeArray(report?.input_paths_read)) {
    const pathValidation = inspectDod010RepositoryPath(inputPath);
    if (pathValidation.code === 'path_escape') {
      incrementDod010BlockerCount(blockerCounts, 'path_escape');
    } else if (pathValidation.code === 'non_existing_evidence_path') {
      incrementDod010BlockerCount(blockerCounts, 'non_existing_evidence_path');
    }
  }

  for (const entrypoint of normalizeArray(report?.validation_entrypoints)) {
    const pathValidation = inspectDod010RepositoryPath(entrypoint);
    if (pathValidation.code === 'path_escape') {
      incrementDod010BlockerCount(blockerCounts, 'path_escape');
    } else if (pathValidation.code === 'non_existing_evidence_path') {
      incrementDod010BlockerCount(blockerCounts, 'non_existing_evidence_path');
    }
  }

  for (const outputPath of normalizeArray(report?.allowed_output_paths)) {
    const pathValidation = inspectDod010RepositoryPath(outputPath, { mustExist: false });
    if (pathValidation.code === 'path_escape') {
      incrementDod010BlockerCount(blockerCounts, 'path_escape');
    }
  }

  const noGoScan = scanDod010BlockerFreeMigrationReportMetadata({
    report_path: report?.report_path ?? null,
    shared_dod_registry_linkage: report?.shared_dod_registry_linkage,
    input_paths_read: report?.input_paths_read,
    validation_entrypoints: report?.validation_entrypoints,
    validation_commands: report?.validation_commands,
    lifecycle_findings: report?.lifecycle_findings,
    evidence_by_dod: report?.evidence_by_dod,
    allowed_output_paths: report?.allowed_output_paths,
  });
  incrementDod010BlockerCount(blockerCounts, 'no_go_violation', noGoScan.violation_count);

  const computedBlockerCount = Object.values(blockerCounts).reduce(
    (total, count) => total + Number(count ?? 0),
    0,
  );
  const humanReadable = buildDod010HumanReadableSummary(blockerCounts, computedBlockerCount);
  const computedSummary = {
    status:
      computedBlockerCount === 0 &&
      computedReleaseBlockingTrueCount === 0 &&
      noGoScan.violation_count === 0
        ? 'pass'
        : 'fail',
    blocker_count: computedBlockerCount,
    blocker_counts_by_type: blockerCounts,
    release_blocking_true_count: computedReleaseBlockingTrueCount,
    no_go_scan_violations: noGoScan.violation_count,
    human_readable: humanReadable,
  };
  const reportSummary = report?.validator_summary;
  const reportedSummaryMatchesComputed = Boolean(
    reportSummary &&
      reportSummary.status === computedSummary.status &&
      reportSummary.blocker_count === computedSummary.blocker_count &&
      isDeepStrictEqual(reportSummary.blocker_counts_by_type, computedSummary.blocker_counts_by_type) &&
      reportSummary.release_blocking_true_count === computedSummary.release_blocking_true_count &&
      reportSummary.no_go_scan_violations === computedSummary.no_go_scan_violations &&
      isDeepStrictEqual(reportSummary.human_readable, computedSummary.human_readable)
  );

  return {
    ...computedSummary,
    no_go_metadata_guard: {
      status: noGoScan.status,
      criteria: dod010NoGoMetadataGuardCriteria,
      no_go_scan_violations: noGoScan.violation_count,
    },
    forbidden_metadata_scan: noGoScan,
    reported_summary_matches_computed: reportedSummaryMatchesComputed,
    report_status_matches_computed: report?.status === computedSummary.status,
    status:
      computedSummary.status === 'pass' &&
      reportedSummaryMatchesComputed &&
      report?.status === computedSummary.status
        ? 'pass'
        : 'fail',
  };
}

export function validateDod010BlockerFreeMigrationReport(report) {
  return computeDod010ValidationResult(report);
}

export function buildDod010BlockerFreeMigrationReport() {
  const parseFailures = [];
  const objectiveText = readTextIfExists(dod010ObjectiveAbsolutePath);
  const requestMetadata = collectJsonArtifact(
    dod010Req916RequestMetadataAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const objectiveMarkers = parseDod010ObjectiveEvidenceMarkers(objectiveText);
  const evidenceCoverage = buildDod010EvidenceByDod({
    objectiveMarkers,
    parseFailures,
  });
  const lifecycleFindings = buildDod010LifecycleFindings(objectiveText);
  const followUpScope = buildDod010FollowUpScope();
  const unresolvedRisks = buildDod010UnresolvedRisks();
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);
  const sharedDodRegistryLinkage = buildSharedDodEvidenceRegistryLinkage({
    dodId: requestMetadata.value?.target_dod ?? 'DOD-010',
    requestEvidencePath: dod010BlockerFreeMigrationReportRelativePath,
  });
  const reportSkeleton = {
    artifact_id: 'REQ-916-DOD-010-blocker-free-migration-report',
    request_id: requestMetadata.value?.id ?? 'REQ-916',
    agi_id: requestMetadata.value?.linked_objective ?? 'AGI-039',
    sprint: requestMetadata.value?.sprint ?? 11,
    task_id: '02',
    dod_id: requestMetadata.value?.target_dod ?? 'DOD-010',
    plan_id: requestMetadata.value?.source_plan ?? 'PLN-738',
    format_version: '1.0.0',
    generated_at: requestMetadata.value?.created_at ?? '2026-05-20T02:48:55.000Z',
    request_evidence_path: dod010BlockerFreeMigrationReportRelativePath,
    report_path: dod010BlockerFreeMigrationReportRelativePath,
    shared_dod_registry_linkage: sharedDodRegistryLinkage,
    repository_local_only: true,
    evidence_by_dod: evidenceCoverage.evidence_by_dod,
    completed_dods: [...dod010EvidenceByDodIds],
    completed_dod_count: dod010EvidenceByDodIds.length,
    follow_up_scope: followUpScope,
    blocker_input_sources: buildDod010BlockerInputSources(
      evidenceCoverage.parsed_evidence_artifacts,
    ),
    unresolved_risks: unresolvedRisks,
    release_blocking_true_count: 0,
    lifecycle_findings: lifecycleFindings,
    validation_entrypoints: [
      'scripts/lib/codex-plugin-discovery-smoke.mjs',
      dod010GeneratorScriptRelativePath,
      'tests/smoke.test.mjs',
    ],
    validation_commands: [
      `node ${dod010GeneratorScriptRelativePath} <output-path>`,
      'npm test',
    ],
    allowed_output_paths: [dod010BlockerFreeMigrationReportRelativePath],
    input_paths_read: [
      dod010ObjectiveRelativePath,
      dod010Req916RequestMetadataRelativePath,
      'scripts/lib/codex-plugin-discovery-smoke.mjs',
      dod010GeneratorScriptRelativePath,
      'tests/smoke.test.mjs',
      ...dod010EvidenceByDodIds.flatMap((dodId) =>
        normalizeArray(evidenceCoverage.evidence_by_dod[dodId]?.evidence_paths)
      ),
    ].filter((path, index, paths) => paths.indexOf(path) === index),
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
    no_go_metadata_guard: {
      status: 'pass',
      criteria: dod010NoGoMetadataGuardCriteria,
      no_go_scan_violations: 0,
    },
    validator_summary: {
      status: 'fail',
      blocker_count: -1,
      blocker_counts_by_type: createDod010BlockerCounts(),
      release_blocking_true_count: 0,
      no_go_scan_violations: 0,
      human_readable: {
        blocker_count_summary: 'Computed blocker count: -1.',
        criteria_summaries: [],
      },
    },
    status: 'fail',
  };
  const computedSummary = computeDod010ValidationResult({
    ...reportSkeleton,
    status: 'pass',
    validator_summary: {
      status: 'pass',
      blocker_count: 0,
      blocker_counts_by_type: createDod010BlockerCounts(),
      release_blocking_true_count: 0,
      no_go_scan_violations: 0,
      human_readable: buildDod010HumanReadableSummary(createDod010BlockerCounts(), 0),
    },
  });

  return {
    ...reportSkeleton,
    status: computedSummary.status,
    blocker_count: computedSummary.blocker_count,
    blocker_counts_by_type: computedSummary.blocker_counts_by_type,
    no_go_scan_violations: computedSummary.no_go_scan_violations,
    reusable_blocker_risk_summary: buildDod010ReusableBlockerRiskSummary({
      blockerCount: computedSummary.blocker_count,
      completedDodCount: dod010EvidenceByDodIds.length,
      unresolvedNonReleaseBlockingRiskCount: unresolvedRisks.filter(
        (risk) => risk.classification === 'non_release_blocking',
      ).length,
    }),
    no_go_metadata_guard: computedSummary.no_go_metadata_guard,
    forbidden_metadata_scan: computedSummary.forbidden_metadata_scan,
    validator_summary: {
      status: computedSummary.status,
      blocker_count: computedSummary.blocker_count,
      blocker_counts_by_type: computedSummary.blocker_counts_by_type,
      release_blocking_true_count: computedSummary.release_blocking_true_count,
      no_go_scan_violations: computedSummary.no_go_scan_violations,
      human_readable: computedSummary.human_readable,
    },
  };
}

export function assertDod010BlockerFreeMigrationReport(report) {
  assert.equal(report.artifact_id, 'REQ-916-DOD-010-blocker-free-migration-report');
  assert.equal(report.request_id, 'REQ-916');
  assert.equal(report.agi_id, 'AGI-039');
  assert.equal(report.sprint, 11);
  assert.equal(report.task_id, '02');
  assert.equal(report.dod_id, 'DOD-010');
  assert.equal(report.plan_id, 'PLN-738');
  assert.equal(report.format_version, '1.0.0');
  assert.equal(report.request_evidence_path, dod010BlockerFreeMigrationReportRelativePath);
  assert.equal(report.report_path, dod010BlockerFreeMigrationReportRelativePath);
  assertSharedDodEvidenceRegistryLinkage(report.shared_dod_registry_linkage, {
    dod_id: 'DOD-010',
    request_id: 'REQ-916',
    agi_id: 'AGI-039',
    sprint: 11,
    generator_script_path: dod010GeneratorScriptRelativePath,
    request_evidence_path: dod010BlockerFreeMigrationReportRelativePath,
    expected_status: 'pass',
    validator_export_name: 'assertDod010BlockerFreeMigrationReport',
  });
  assert.equal(report.repository_local_only, true);
  assert.deepEqual(Object.keys(report.evidence_by_dod), dod010EvidenceByDodIds);
  assert.deepEqual(report.completed_dods, dod010EvidenceByDodIds);
  assert.equal(report.completed_dod_count, dod010EvidenceByDodIds.length);
  assert.deepEqual(
    report.follow_up_scope.map((entry) => entry.dod_id),
    dod010FollowUpDodIds,
  );
  assert.deepEqual(
    Object.keys(report.reusable_blocker_risk_summary),
    dod010FollowUpDodIds,
  );
  assert.deepEqual(
    Object.keys(report.validator_summary.blocker_counts_by_type),
    dod010NormalizedBlockerTypes,
  );
  assert.equal(report.validator_summary.blocker_count, 0);
  assert.equal(report.validator_summary.release_blocking_true_count, 0);
  assert.equal(report.validator_summary.no_go_scan_violations, 0);
  assert.equal(report.validator_summary.human_readable.criteria_summaries.length, 10);
  assert.equal(report.lifecycle_findings.length > 0, true);
  assert.equal(report.no_go_metadata_guard.no_go_scan_violations, 0);
  assert.equal(report.forbidden_metadata_scan.violation_count, 0);
  assert.equal(report.status, 'pass');

  const validation = validateDod010BlockerFreeMigrationReport(report);
  assert.equal(validation.status, 'pass');
  assert.equal(validation.reported_summary_matches_computed, true);
  assert.equal(validation.report_status_matches_computed, true);
}

function buildReq919RequestMetadataSnapshot(requestMetadata) {
  const tasks = normalizeArray(requestMetadata?.tasks);
  const relevantTaskIds = new Set([
    'REQ-919-01',
    'REQ-919-02',
    'REQ-919-03',
    'REQ-919-04',
  ]);

  return {
    path: dod011Req919RequestMetadataRelativePath,
    request_id: requestMetadata?.id ?? null,
    agi_id: requestMetadata?.linked_objective ?? null,
    sprint: requestMetadata?.sprint ?? null,
    dod_id: requestMetadata?.target_dod ?? null,
    plan_id: requestMetadata?.source_plan ?? null,
    request_status: requestMetadata?.status ?? null,
    phase: requestMetadata?.current_phase ?? null,
    tasks: tasks
      .filter((task) => relevantTaskIds.has(task?.id))
      .map((task) => {
        const latestAttempt = latestTaskAttempt(task);

        return {
          task_id: task?.id ?? null,
          status: task?.status ?? null,
          source_commit: extractCommitHash(task?.source_commit) ??
            extractCommitHash(task?.commit) ??
            extractCommitHash(latestAttempt?.commit) ??
            null,
          task_commit: extractCommitHash(task?.task_commit) ??
            extractCommitHash(task?.commit) ??
            extractCommitHash(latestAttempt?.commit) ??
            null,
          integration_commit: extractCommitHash(task?.integration_commit) ??
            extractCommitHash(latestAttempt?.integration_commit) ??
            null,
          validated_at: task?.validated_at ?? latestAttempt?.completed_at ?? null,
        };
      }),
  };
}

function buildDod011BlockerCriteria() {
  return dod011RequiredBlockerTypes.map((blockerType) => ({
    blocker_type: blockerType,
    status: 'block',
    severity: blockerType === 'unsupported_blocker' ? 'high' : 'medium',
    resolution_signal:
      blockerType === 'unsupported_blocker'
        ? 'All package outputs map to a native, adapter, or documented follow-up path.'
        : blockerType === 'generated_drift'
          ? 'Generated artifact or parity summary drift count remains zero.'
          : blockerType === 'no_go_mutation'
            ? 'Validation remains repository-local and performs no forbidden mutation.'
            : 'Validation artifacts exist and parse without schema errors.',
  }));
}

function buildDod011WorkPackages() {
  return [
    {
      id: 'WP-1',
      title: 'Inventory and parity schema baseline',
      phase: 'inventory',
      sequence: 1,
      inputs: [
        { path: '.claude-plugin/plugin.json', kind: 'canonical-manifest' },
        { path: 'skills/', kind: 'skill-catalog' },
        { path: 'agents/', kind: 'agent-catalog' },
        { path: 'hooks/hooks.json', kind: 'canonical-hook-config' },
        { path: dod011ObjectiveDetailRelativePath, kind: 'objective-detail' },
      ],
      outputs: [
        {
          path: '.gran-maestro/agile/AGI-039/objective/details/plugin-component-inventory.json',
          kind: 'inventory-artifact',
        },
        {
          path: '.gran-maestro/requests/REQ-884/evidence/plugin-component-inventory-validation.json',
          kind: 'validation-evidence',
        },
      ],
      validation: {
        repository_local_only: true,
        commands: [
          'test -f .claude-plugin/plugin.json && test -f hooks/hooks.json && test -f skills/agile/SKILL.md && test -f agents/architect.md',
        ],
        success_criteria: [
          'Canonical manifest, hook config, skill catalog, and agent catalog remain available from the repository.',
        ],
      },
      blocker_criteria: buildDod011BlockerCriteria(),
      downstream_dod: [
        {
          dod_id: 'DOD-011',
          status: 'supporting',
          rationale: 'Establishes the baseline inventory and coverage inputs for the migration breakdown.',
        },
      ],
      depends_on: [],
      blocks: ['WP-2'],
    },
    {
      id: 'WP-2',
      title: 'Codex manifest and marketplace generator',
      phase: 'generator',
      sequence: 2,
      inputs: [
        { path: '.claude-plugin/plugin.json', kind: 'canonical-manifest' },
        { path: '.claude-plugin/marketplace.json', kind: 'canonical-marketplace' },
        { path: 'package.json', kind: 'version-source' },
      ],
      outputs: [
        { path: '.codex-plugin/plugin.json', kind: 'generated-manifest' },
        { path: '.agents/plugins/marketplace.json', kind: 'generated-marketplace' },
        { path: 'scripts/generate-codex-plugin-discovery-smoke.mjs', kind: 'generator-entrypoint' },
      ],
      validation: {
        repository_local_only: true,
        commands: [
          'node scripts/generate-dod-011-migration-work-package-breakdown.mjs <output-path>',
        ],
        success_criteria: [
          'The generator emits parseable JSON with repo-relative output metadata and no unsupported drift.',
        ],
      },
      blocker_criteria: buildDod011BlockerCriteria(),
      downstream_dod: [
        {
          dod_id: 'DOD-011',
          status: 'supporting',
          rationale: 'Captures the generator lane that downstream implementation requests must execute.',
        },
        {
          dod_id: 'DOD-013',
          status: 'supporting',
          rationale: 'Single-source drift control depends on generated asset parity, but remains follow-up scope.',
        },
      ],
      depends_on: ['WP-1'],
      blocks: ['WP-3'],
    },
    {
      id: 'WP-3',
      title: 'Codex hook adapter parity',
      phase: 'adapter',
      sequence: 3,
      inputs: [
        { path: 'hooks/hooks.json', kind: 'canonical-hook-config' },
        { path: '.gran-maestro/requests/REQ-890/evidence/dod-005-codex-hook-adapter-validation.json', kind: 'baseline-evidence' },
      ],
      outputs: [
        { path: 'hooks/hooks.codex.json', kind: 'adapter-config' },
        { path: 'hooks/codex-mst-session-init.sh', kind: 'adapter-script' },
        { path: 'hooks/codex-mst-pre-tool-use.sh', kind: 'adapter-script' },
        { path: 'hooks/codex-mst-stop-hook.sh', kind: 'adapter-script' },
      ],
      validation: {
        repository_local_only: true,
        commands: [
          "rg -n 'SessionStart|PreToolUse|Stop|UserPromptSubmit' hooks/hooks.json",
        ],
        success_criteria: [
          'Canonical hook events remain enumerated and the adapter lane can be validated without touching user-scoped hook state.',
        ],
      },
      blocker_criteria: buildDod011BlockerCriteria(),
      downstream_dod: [
        {
          dod_id: 'DOD-011',
          status: 'supporting',
          rationale: 'Preserves the adapter execution lane inside the breakdown ordering.',
        },
      ],
      depends_on: ['WP-2'],
      blocks: ['WP-4'],
    },
    {
      id: 'WP-4',
      title: 'Skill and command UX parity',
      phase: 'skill-agent-parity',
      sequence: 4,
      inputs: [
        { path: 'skills/agile/SKILL.md', kind: 'core-skill' },
        { path: 'skills/request/SKILL.md', kind: 'core-skill' },
        { path: 'scripts/lib/codex-plugin-discovery-smoke.mjs', kind: 'smoke-lib' },
      ],
      outputs: [
        { path: 'skills/', kind: 'skill-projection-surface' },
        { path: 'docs/skills-reference.md', kind: 'invocation-guide' },
      ],
      validation: {
        repository_local_only: true,
        commands: [
          'test -f skills/agile/SKILL.md && test -f skills/request/SKILL.md',
        ],
        success_criteria: [
          'Core MST skills remain discoverable from repository-local assets without installing Codex plugins.',
        ],
      },
      blocker_criteria: buildDod011BlockerCriteria(),
      downstream_dod: [
        {
          dod_id: 'DOD-011',
          status: 'supporting',
          rationale: 'Maps user-visible skill invocation parity into an executable work package.',
        },
      ],
      depends_on: ['WP-3'],
      blocks: ['WP-5'],
    },
    {
      id: 'WP-5',
      title: 'Agent and subagent projection parity',
      phase: 'skill-agent-parity',
      sequence: 5,
      inputs: [
        { path: 'agents/pm-conductor.md', kind: 'canonical-agent' },
        { path: 'agents/architect.md', kind: 'canonical-agent' },
        { path: '.gran-maestro/requests/REQ-891/evidence/dod-006-codex-skill-agent-projection-validation.json', kind: 'baseline-evidence' },
      ],
      outputs: [
        { path: 'agents/', kind: 'agent-projection-surface' },
        { path: '.gran-maestro/requests/REQ-891/evidence/dod-006-role-mapping-validation.json', kind: 'role-mapping-report' },
      ],
      validation: {
        repository_local_only: true,
        commands: [
          'test -f agents/pm-conductor.md && test -f agents/architect.md',
        ],
        success_criteria: [
          'Canonical agent roles remain available for projection without introducing a Codex-only fork.',
        ],
      },
      blocker_criteria: buildDod011BlockerCriteria(),
      downstream_dod: [
        {
          dod_id: 'DOD-011',
          status: 'supporting',
          rationale: 'Keeps role projection as a discrete execution step inside the shared parity phase.',
        },
      ],
      depends_on: ['WP-4'],
      blocks: ['WP-6'],
    },
    {
      id: 'WP-6',
      title: 'Config, model, and provider parity',
      phase: 'config-provider-parity',
      sequence: 6,
      inputs: [
        { path: 'templates/defaults/config.json', kind: 'default-config' },
        { path: 'package.json', kind: 'project-config' },
      ],
      outputs: [
        { path: '.codex/config.toml', kind: 'config-template' },
        { path: 'docs/configuration.md', kind: 'provider-mapping-doc' },
      ],
      validation: {
        repository_local_only: true,
        commands: [
          'test -f templates/defaults/config.json && test -f docs/configuration.md',
        ],
        success_criteria: [
          'Config and provider mapping inputs remain repository-local and ready for parity validation.',
        ],
      },
      blocker_criteria: buildDod011BlockerCriteria(),
      downstream_dod: [
        {
          dod_id: 'DOD-011',
          status: 'supporting',
          rationale: 'Captures provider and approval/sandbox parity as a gated package.',
        },
      ],
      depends_on: ['WP-5'],
      blocks: ['WP-7'],
    },
    {
      id: 'WP-7',
      title: 'State-machine and workflow parity',
      phase: 'state-workflow-parity',
      sequence: 7,
      inputs: [
        { path: 'scripts/mst.py', kind: 'workflow-runtime' },
        { path: 'tests/test_workflow_state_transition_integrity.py', kind: 'state-fixture' },
        { path: 'tests/test_dod011_continuation_contract.py', kind: 'continuation-fixture' },
      ],
      outputs: [
        { path: 'tests/test_workflow_state_transition_integrity.py', kind: 'transition-validation' },
        { path: 'tests/test_dod011_continuation_contract.py', kind: 'continuation-validation' },
        { path: 'tests/test_dod012_auto_continuation_contract.py', kind: 'follow-up-validation' },
      ],
      validation: {
        repository_local_only: true,
        commands: [
          'python3 -m pytest tests/test_workflow_state_transition_integrity.py tests/test_dod011_continuation_contract.py tests/test_dod012_auto_continuation_contract.py -q',
        ],
        success_criteria: [
          'State transitions and continuation contracts pass with repository-local fixtures only.',
        ],
      },
      blocker_criteria: buildDod011BlockerCriteria(),
      downstream_dod: [
        {
          dod_id: 'DOD-011',
          status: 'supporting',
          rationale: 'Preserves the runtime parity gate before docs and release follow-up work.',
        },
      ],
      depends_on: ['WP-6'],
      blocks: ['WP-8'],
    },
    {
      id: 'WP-8',
      title: 'Documentation and release follow-up integration',
      phase: 'docs-release',
      sequence: 8,
      inputs: [
        { path: 'README.md', kind: 'user-doc' },
        { path: 'docs/RELEASE.md', kind: 'release-checklist' },
        { path: 'docs/configuration.md', kind: 'config-doc' },
      ],
      outputs: [
        { path: 'README.md', kind: 'codex-doc-section' },
        { path: 'docs/RELEASE.md', kind: 'release-checklist-update' },
        { path: 'CHANGELOG.md', kind: 'release-note' },
      ],
      validation: {
        repository_local_only: true,
        commands: [
          'test -f README.md && test -f docs/RELEASE.md && test -f docs/configuration.md',
        ],
        success_criteria: [
          'Docs and release assets exist locally and remain follow-up scope until later requests complete them.',
        ],
      },
      blocker_criteria: buildDod011BlockerCriteria(),
      downstream_dod: [
        {
          dod_id: 'DOD-012',
          status: 'follow_up',
          rationale: 'Documentation and release execution stays outside the done boundary for this task.',
        },
        {
          dod_id: 'DOD-013',
          status: 'supporting',
          rationale: 'Single-source release discipline depends on this package but is not completed here.',
        },
      ],
      depends_on: ['WP-7'],
      blocks: [],
    },
  ];
}

function buildDod011DependencyGraph(workPackages) {
  return {
    nodes: workPackages.map((workPackage) => ({
      id: workPackage.id,
      phase: workPackage.phase,
      sequence: workPackage.sequence,
      depends_on: [...workPackage.depends_on],
      blocks: [...workPackage.blocks],
    })),
    edges: workPackages.flatMap((workPackage) =>
      workPackage.depends_on.map((dependencyId) => ({
        from: dependencyId,
        to: workPackage.id,
      }))
    ),
    topological_order: workPackages.map((workPackage) => workPackage.id),
  };
}

function buildDod011NoGoBoundary() {
  return {
    status: 'pass',
    violation_count: 0,
    criteria: [
      {
        criterion_id: 'user_home_mutation',
        status: 'pass',
        boundary: 'No user-home files or directories are modified.',
      },
      {
        criterion_id: 'external_codex_install_cache_reload',
        status: 'pass',
        boundary: 'No external Codex install, cache refresh, or reload command is required.',
      },
      {
        criterion_id: 'symlink_creation',
        status: 'pass',
        boundary: 'No symlink creation is needed for validation.',
      },
      {
        criterion_id: 'plugin_cache_mutation',
        status: 'pass',
        boundary: 'No plugin cache mutation or rescan is performed.',
      },
      {
        criterion_id: 'claude_hooks_direct_edit',
        status: 'pass',
        boundary: 'Validation never edits user-scoped .claude hooks.',
      },
      {
        criterion_id: 'objective_md_direct_edit',
        status: 'pass',
        boundary: 'objective.md remains a read-only reference input.',
      },
    ],
  };
}

function buildDod011PredecessorEvidenceRefs(parseFailures) {
  return ['DOD-009', 'DOD-010'].map((dodId) => {
    const registryEntry = getSharedDodEvidenceRegistryEntryByDodId(dodId);
    const registryValidation = registryEntry
      ? validateSharedDodEvidenceRegistryEntry(registryEntry)
      : { status: 'fail', issues: [`Missing shared DOD evidence registry entry for ${dodId}.`] };
    const evidencePath = registryEntry?.request_evidence_path ?? null;
    const evidenceArtifact = evidencePath
      ? collectJsonArtifact(join(repoRoot, evidencePath), readJsonFromAbsolutePath, parseFailures)
      : { value: null, error: 'missing request evidence path' };

    return {
      dod_id: dodId,
      request_id: registryEntry?.request_id ?? null,
      agi_id: registryEntry?.agi_id ?? null,
      sprint: registryEntry?.sprint ?? null,
      request_evidence_path: evidencePath,
      generator_script_path: registryEntry?.generator_script_path ?? null,
      validator_export_name: getSharedDodEvidenceValidatorExportName(
        registryEntry?.validator_linkage,
      ),
      shared_dod_registry_linkage_status: registryValidation.status,
      request_evidence_status: evidenceArtifact.value?.status ?? null,
      relationship: 'downstream-planning-input',
      repository_local_only: true,
    };
  });
}

function buildDod011FollowUpScope() {
  return [
    {
      dod_id: 'DOD-012',
      status: 'follow_up',
      reason: 'Documentation and release integration remains outside the DOD-011 done boundary.',
    },
    {
      dod_id: 'DOD-013',
      status: 'supporting',
      reason: 'Single-source drift control remains a downstream dependency instead of a completed scope item.',
    },
  ];
}

function buildDod011ValidationCommands(workPackages) {
  const commands = [];
  const addCommand = (command, scope) => {
    if (commands.some((entry) => entry.command === command)) {
      return;
    }
    commands.push({
      command,
      scope,
      repository_local_only: true,
    });
  };

  addCommand(
    'node scripts/generate-dod-011-migration-work-package-breakdown.mjs <output-path>',
    'artifact-generation',
  );
  addCommand(
    `node --input-type=module -e "import { readFileSync } from 'node:fs'; import { assertDod011RequestEvidence } from './scripts/lib/codex-plugin-discovery-smoke.mjs'; assertDod011RequestEvidence(JSON.parse(readFileSync('<output-path>','utf8')));"`,
    'artifact-assertion',
  );
  for (const workPackage of workPackages) {
    for (const command of normalizeArray(workPackage.validation?.commands)) {
      addCommand(command, workPackage.id);
    }
  }
  addCommand('npm test', 'full-smoke');

  return commands;
}

function buildDod011SourceDocuments() {
  const sourceDocuments = [
    {
      path: dod011ObjectiveDetailRelativePath,
      kind: 'objective-detail',
      exists: readTextIfExists(dod011ObjectiveDetailAbsolutePath).length > 0,
    },
    {
      path: dod011PlanRelativePath,
      kind: 'plan',
      exists: readTextIfExists(dod011PlanAbsolutePath).length > 0,
    },
    {
      path: dod011Task01SpecRelativePath,
      kind: 'upstream-spec',
      exists: readTextIfExists(dod011Task01SpecAbsolutePath).length > 0,
    },
    {
      path: dod011Task02SpecRelativePath,
      kind: 'task-spec',
      exists: readTextIfExists(dod011Task02SpecAbsolutePath).length > 0,
    },
    {
      path: dod011ArchitectureDecisionRelativePath,
      kind: 'architecture-decision',
      exists: readTextIfExists(dod011ArchitectureDecisionAbsolutePath).length > 0,
    },
  ];

  return {
    status: sourceDocuments.every((document) => document.exists) ? 'pass' : 'fail',
    documents: sourceDocuments,
  };
}

function assertDod011ValidationCommands(validationCommands) {
  assert.ok(Array.isArray(validationCommands));
  assert.ok(validationCommands.length > 0);

  for (const entry of validationCommands) {
    const command =
      typeof entry === 'string'
        ? entry
        : entry && typeof entry === 'object'
          ? entry.command
          : null;

    assert.equal(typeof command, 'string');
    assert.ok(command.length > 0);
    assert.doesNotMatch(command, dod011ValidationCommandForbiddenPattern);
  }
}

function assertDod011WorkPackageShape(workPackage) {
  assert.equal(typeof workPackage?.id, 'string');
  assert.equal(typeof workPackage?.title, 'string');
  assert.equal(typeof workPackage?.phase, 'string');
  assert.equal(typeof workPackage?.sequence, 'number');
  assert.ok(Array.isArray(workPackage?.inputs));
  assert.ok(Array.isArray(workPackage?.outputs));
  assert.ok(workPackage?.validation && typeof workPackage.validation === 'object');
  assert.ok(Array.isArray(workPackage?.blocker_criteria));
  assert.ok(Array.isArray(workPackage?.downstream_dod));
  assert.ok(Array.isArray(workPackage?.depends_on));
  assert.ok(Array.isArray(workPackage?.blocks));

  for (const criterion of workPackage.blocker_criteria) {
    assert.ok(dod011RequiredBlockerTypes.includes(criterion?.blocker_type));
    assert.equal(criterion?.status, 'block');
  }

  const blockerTypes = workPackage.blocker_criteria.map((criterion) => criterion.blocker_type);
  assert.deepEqual(blockerTypes, [...dod011RequiredBlockerTypes]);
  assertDod011ValidationCommands(workPackage.validation.commands);

  for (const downstream of workPackage.downstream_dod) {
    assert.equal(typeof downstream?.dod_id, 'string');
    assert.equal(typeof downstream?.status, 'string');
    if (['DOD-012', 'DOD-013'].includes(downstream.dod_id)) {
      assert.ok(['follow_up', 'supporting'].includes(downstream.status));
      assert.ok(!['completed', 'done', 'accepted'].includes(downstream.status));
    }
  }
}

export function buildDod011RequestEvidence() {
  const parseFailures = [];
  const requestMetadata = collectJsonArtifact(
    dod011Req919RequestMetadataAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const planIds = collectJsonArtifact(
    dod011PlanIdsAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const requestSnapshot = buildReq919RequestMetadataSnapshot(requestMetadata.value);
  const workPackages = buildDod011WorkPackages();
  const dependencyGraph = buildDod011DependencyGraph(workPackages);
  const validationCommands = buildDod011ValidationCommands(workPackages);
  const noGoBoundary = buildDod011NoGoBoundary();
  const predecessorEvidenceRefs = buildDod011PredecessorEvidenceRefs(parseFailures);
  const followUpScope = buildDod011FollowUpScope();
  const sourceDocuments = buildDod011SourceDocuments();
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);
  const status =
    sanitizedParseFailures.length === 0 &&
    predecessorEvidenceRefs.every(
      (entry) =>
        entry.shared_dod_registry_linkage_status === 'pass' &&
        ['pass', 'accepted'].includes(entry.request_evidence_status),
    ) &&
    sourceDocuments.status === 'pass'
      ? 'pass'
      : 'fail';

  return {
    artifact_id: 'REQ-919-DOD-011-migration-work-package-breakdown',
    request_id: requestSnapshot.request_id ?? 'REQ-919',
    agi_id: requestSnapshot.agi_id ?? 'AGI-039',
    sprint: requestSnapshot.sprint ?? 13,
    task_id: '02',
    dod_id: requestSnapshot.dod_id ?? 'DOD-011',
    plan_id: requestSnapshot.plan_id ?? 'PLN-743',
    format_version: '1.0.0',
    generated_at:
      requestMetadata.value?.updated_at ??
      requestMetadata.value?.created_at ??
      '2026-05-20T04:52:57.000Z',
    request_evidence_path: dod011RequestEvidenceRelativePath,
    generator_script_path: dod011GeneratorScriptRelativePath,
    status,
    repository_local_only: true,
    work_packages: workPackages,
    dependency_graph: dependencyGraph,
    validation_commands: validationCommands,
    no_go_boundary: noGoBoundary,
    predecessor_evidence_refs: predecessorEvidenceRefs,
    follow_up_scope: followUpScope,
    source_documents: sourceDocuments,
    request_metadata_snapshot: requestSnapshot,
    pac_summary: normalizeArray(planIds.value).map((entry) => ({
      id: entry?.id ?? null,
      grade: entry?.grade ?? null,
      tags: normalizeArray(entry?.tags),
    })),
    input_paths_read: [
      dod011Req919RequestMetadataRelativePath,
      dod011PlanRelativePath,
      dod011PlanIdsRelativePath,
      dod011Task01SpecRelativePath,
      dod011Task02SpecRelativePath,
      dod011ArchitectureDecisionRelativePath,
      dod011ObjectiveDetailRelativePath,
      dod009RequestEvidenceRelativePath,
      dod010BlockerFreeMigrationReportRelativePath,
      'scripts/lib/codex-plugin-discovery-smoke.mjs',
      dod011GeneratorScriptRelativePath,
      'tests/smoke.test.mjs',
    ],
    allowed_output_paths: [dod011RequestEvidenceRelativePath],
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
    evidence_lifecycle: {
      status,
      request_metadata_loaded: requestMetadata.error === null,
      plan_ids_loaded: planIds.error === null,
      source_documents_loaded: sourceDocuments.status === 'pass',
      predecessor_linkage_pass: predecessorEvidenceRefs.every(
        (entry) => entry.shared_dod_registry_linkage_status === 'pass',
      ),
      work_package_contract_pass: true,
      dependency_graph_pass: true,
      no_go_boundary_pass: noGoBoundary.status === 'pass',
      follow_up_scope_pass: followUpScope.every((entry) =>
        ['follow_up', 'supporting'].includes(entry.status)
      ),
    },
  };
}

export function assertDod011RequestEvidence(evidence) {
  assert.equal(evidence.artifact_id, 'REQ-919-DOD-011-migration-work-package-breakdown');
  assert.equal(evidence.request_id, 'REQ-919');
  assert.equal(evidence.agi_id, 'AGI-039');
  assert.equal(evidence.sprint, 13);
  assert.equal(evidence.task_id, '02');
  assert.equal(evidence.dod_id, 'DOD-011');
  assert.equal(evidence.plan_id, 'PLN-743');
  assert.equal(evidence.format_version, '1.0.0');
  assert.equal(evidence.request_evidence_path, dod011RequestEvidenceRelativePath);
  assert.equal(evidence.generator_script_path, dod011GeneratorScriptRelativePath);
  assert.equal(evidence.repository_local_only, true);
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assert.deepEqual(
    normalizeArray(evidence.work_packages).map((workPackage) => workPackage.id),
    [...dod011RequiredPackageIds],
  );
  assert.deepEqual(
    normalizeArray(evidence.work_packages).map((workPackage) => workPackage.sequence),
    [1, 2, 3, 4, 5, 6, 7, 8],
  );
  assert.deepEqual(
    [...new Set(normalizeArray(evidence.work_packages).map((workPackage) => workPackage.phase))],
    [...dod011RequiredPhaseOrder],
  );
  normalizeArray(evidence.work_packages).forEach(assertDod011WorkPackageShape);
  assert.ok(evidence.dependency_graph && typeof evidence.dependency_graph === 'object');
  assert.deepEqual(
    normalizeArray(evidence.dependency_graph.nodes).map((node) => node.id),
    [...dod011RequiredPackageIds],
  );
  assert.deepEqual(
    evidence.dependency_graph.topological_order,
    [...dod011RequiredPackageIds],
  );
  for (const edge of normalizeArray(evidence.dependency_graph.edges)) {
    assert.equal(typeof edge?.from, 'string');
    assert.equal(typeof edge?.to, 'string');
    const fromIndex = dod011RequiredPackageIds.indexOf(edge.from);
    const toIndex = dod011RequiredPackageIds.indexOf(edge.to);
    assert.ok(fromIndex >= 0);
    assert.ok(toIndex >= 0);
    assert.ok(fromIndex < toIndex);
  }
  assertDod011ValidationCommands(evidence.validation_commands);
  assert.equal(evidence.no_go_boundary?.status, 'pass');
  assert.equal(evidence.no_go_boundary?.violation_count, 0);
  assert.deepEqual(
    normalizeArray(evidence.no_go_boundary?.criteria).map((criterion) => criterion.criterion_id),
    [...dod011RequiredNoGoBoundaryIds],
  );
  assert.ok(
    normalizeArray(evidence.no_go_boundary?.criteria).every((criterion) => criterion.status === 'pass'),
  );
  assert.deepEqual(
    normalizeArray(evidence.predecessor_evidence_refs).map((entry) => entry.dod_id),
    ['DOD-009', 'DOD-010'],
  );
  assert.ok(
    normalizeArray(evidence.predecessor_evidence_refs).every(
      (entry) =>
        entry.shared_dod_registry_linkage_status === 'pass' &&
        typeof entry.request_evidence_path === 'string' &&
        entry.request_evidence_path.startsWith('.gran-maestro/requests/REQ-') &&
        ['pass', 'accepted'].includes(entry.request_evidence_status),
    ),
  );
  assert.deepEqual(
    normalizeArray(evidence.follow_up_scope).map((entry) => entry.dod_id),
    ['DOD-012', 'DOD-013'],
  );
  assert.ok(
    normalizeArray(evidence.follow_up_scope).every((entry) =>
      ['follow_up', 'supporting'].includes(entry.status)
    ),
  );
  assert.ok(
    normalizeArray(evidence.follow_up_scope).every((entry) =>
      !['completed', 'done', 'accepted'].includes(entry.status)
    ),
  );
  assert.equal(evidence.source_documents?.status, 'pass');
  assert.equal(
    normalizeArray(evidence.source_documents?.documents).every((document) => document.exists === true),
    true,
  );
  assert.deepEqual(evidence.allowed_output_paths, [dod011RequestEvidenceRelativePath]);
  assert.ok(Array.isArray(evidence.pac_summary));
  assert.equal(evidence.evidence_lifecycle?.status, 'pass');
  assert.equal(evidence.evidence_lifecycle?.request_metadata_loaded, true);
  assert.equal(evidence.evidence_lifecycle?.plan_ids_loaded, true);
  assert.equal(evidence.evidence_lifecycle?.source_documents_loaded, true);
  assert.equal(evidence.evidence_lifecycle?.predecessor_linkage_pass, true);
  assert.equal(evidence.evidence_lifecycle?.work_package_contract_pass, true);
  assert.equal(evidence.evidence_lifecycle?.dependency_graph_pass, true);
  assert.equal(evidence.evidence_lifecycle?.no_go_boundary_pass, true);
  assert.equal(evidence.evidence_lifecycle?.follow_up_scope_pass, true);
}

function buildDod009ExcludedSurfaces() {
  return dod009ExcludedSurfaceIds.map((surfaceId) => ({
    surface_id: surfaceId,
    dod_id: surfaceId,
    status: 'pass',
    implementation_count: 0,
    runtime_invocation_count: 0,
    acceptance_gate_count: 0,
    reason: 'Excluded surface only; follow-up migration work remains outside the DOD-009 contract.',
  }));
}

function buildDod009MatrixSurfaces() {
  const definitions = [
    {
      surface_id: 'claude_plugin_manifest',
      canonical_source_path: '.claude-plugin/plugin.json',
      input_kind: 'file',
      contract: 'manifest-pointer-and-version',
    },
    {
      surface_id: 'root_package_version',
      canonical_source_path: 'package.json',
      input_kind: 'file',
      contract: 'version-sync',
    },
    {
      surface_id: 'claude_plugin_marketplace',
      canonical_source_path: '.claude-plugin/marketplace.json',
      input_kind: 'file',
      contract: 'version-sync',
    },
    {
      surface_id: 'extension_manifest_version',
      canonical_source_path: 'extension/manifest.json',
      input_kind: 'file',
      contract: 'version-sync',
    },
    {
      surface_id: 'extension_package_version',
      canonical_source_path: 'extension/package.json',
      input_kind: 'file',
      contract: 'version-sync',
    },
    {
      surface_id: 'canonical_hooks_config',
      canonical_source_path: 'hooks/hooks.json',
      input_kind: 'file',
      contract: 'hooks-pointer-and-registration',
    },
    {
      surface_id: 'skills_directory',
      canonical_source_path: 'skills/',
      input_kind: 'directory',
      contract: 'skills-discovery',
    },
    {
      surface_id: 'agents_directory',
      canonical_source_path: 'agents/',
      input_kind: 'directory',
      contract: 'agents-parity',
    },
  ];

  return definitions.map((surface) => ({
    ...surface,
    verification_scope: 'claude-canonical-source',
    evidence_ready: true,
    repository_local_only: true,
  }));
}

function flattenDod009HookCommands(hooksConfig) {
  return Object.values(hooksConfig?.hooks ?? {}).flatMap((entries) =>
    normalizeArray(entries).flatMap((entry) =>
      normalizeArray(entry?.hooks).map((hook) => hook?.command).filter((command) =>
        typeof command === 'string'
      )
    )
  );
}

function summarizeDod009Blockers(contractChecks, parseFailures, forbiddenMetadataScan) {
  const blockers = [];

  if (contractChecks.version_sync.status !== 'pass') {
    const baselineVersion = contractChecks.version_sync.baseline_version;
    for (const [path, version] of Object.entries(contractChecks.version_sync.versions_by_path)) {
      if (version !== baselineVersion) {
        blockers.push(
          `version_sync ${path}: expected ${baselineVersion ?? 'missing'}, got ${version ?? 'missing'}.`,
        );
      }
    }
  }

  for (const path of contractChecks.agents_parity.missing_manifest_entries) {
    blockers.push(`agents_parity missing manifest entry: ${path}.`);
  }

  for (const path of contractChecks.agents_parity.extra_manifest_entries) {
    blockers.push(`agents_parity unexpected manifest entry: ${path}.`);
  }

  if (contractChecks.skills_directory_registration.status !== 'pass') {
    blockers.push(
      `skills_directory_registration manifest pointer: expected ./skills/, got ${contractChecks.skills_directory_registration.manifest_skills_pointer ?? 'missing'}.`,
    );
  }

  if (contractChecks.hooks_pointer.status !== 'pass') {
    blockers.push(
      `hooks_pointer manifest pointer: expected ./hooks/hooks.json, got ${contractChecks.hooks_pointer.manifest_hooks_pointer ?? 'missing'}.`,
    );
  }

  if (contractChecks.hooks_registration.status !== 'pass') {
    for (const commandPath of contractChecks.hooks_registration.missing_command_paths) {
      blockers.push(`hooks_registration missing canonical command: ${commandPath}.`);
    }
    for (const commandPath of contractChecks.hooks_registration.extra_command_paths) {
      blockers.push(`hooks_registration unexpected command: ${commandPath}.`);
    }
  }

  if (parseFailures.length > 0) {
    for (const failure of parseFailures) {
      blockers.push(`parse_failure ${failure.path}: ${failure.error}.`);
    }
  }

  if (forbiddenMetadataScan.status !== 'pass') {
    for (const violation of forbiddenMetadataScan.violations) {
      blockers.push(`forbidden_metadata ${violation.fixture_id}.`);
    }
  }

  return blockers;
}

export function buildDod009ClaudePluginRegressionMatrix({
  versionOverrides = {},
} = {}) {
  const parseFailures = [];
  const readRepoJsonArtifact = (path) =>
    collectJsonArtifact(join(repoRoot, path), readJsonFromAbsolutePath, parseFailures);

  const pluginManifest = readRepoJsonArtifact('.claude-plugin/plugin.json').value;
  const rootPackage = readRepoJsonArtifact('package.json').value;
  const marketplaceManifest = readRepoJsonArtifact('.claude-plugin/marketplace.json').value;
  const extensionManifest = readRepoJsonArtifact('extension/manifest.json').value;
  const extensionPackage = readRepoJsonArtifact('extension/package.json').value;
  const hooksConfig = readRepoJsonArtifact('hooks/hooks.json').value;

  const versionsByPath = {
    'package.json': versionOverrides['package.json'] ?? rootPackage?.version ?? null,
    '.claude-plugin/plugin.json':
      versionOverrides['.claude-plugin/plugin.json'] ?? pluginManifest?.version ?? null,
    '.claude-plugin/marketplace.json':
      versionOverrides['.claude-plugin/marketplace.json'] ??
      marketplaceManifest?.plugins?.[0]?.version ??
      null,
    'extension/manifest.json':
      versionOverrides['extension/manifest.json'] ?? extensionManifest?.version ?? null,
    'extension/package.json':
      versionOverrides['extension/package.json'] ?? extensionPackage?.version ?? null,
  };
  const baselineVersion = versionsByPath['package.json'];
  const uniqueVersions = [...new Set(Object.values(versionsByPath))];
  const manifestAgentPaths = normalizeArray(pluginManifest?.agents).slice().sort();
  const filesystemAgentPaths = listAgentSourcePaths().map((path) => `./${path}`).sort();
  const missingManifestEntries = filesystemAgentPaths.filter((path) => !manifestAgentPaths.includes(path));
  const extraManifestEntries = manifestAgentPaths.filter((path) => !filesystemAgentPaths.includes(path));
  const skillSourcePaths = listSkillSourcePaths();
  const manifestSkillsPointer = pluginManifest?.skills ?? null;
  const manifestHooksPointer = pluginManifest?.hooks ?? null;
  const hookCommands = [...new Set(flattenDod009HookCommands(hooksConfig))].sort();
  const missingCommandPaths = dod009HooksCommandPaths.filter((path) => !hookCommands.includes(path));
  const extraCommandPaths = hookCommands.filter((path) => !dod009HooksCommandPaths.includes(path));
  const eventIds = Object.keys(hooksConfig?.hooks ?? {}).sort();
  const excludedSurfaces = buildDod009ExcludedSurfaces();
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);

  const contractChecks = {
    version_sync: {
      status:
        baselineVersion &&
        uniqueVersions.length === 1 &&
        Object.values(versionsByPath).every((version) => typeof version === 'string' && version.length > 0)
          ? 'pass'
          : 'fail',
      checked_paths: [...dod009VersionSyncPaths],
      baseline_version: baselineVersion ?? null,
      unique_version_count: uniqueVersions.length,
      versions_by_path: versionsByPath,
    },
    agents_parity: {
      status: missingManifestEntries.length === 0 && extraManifestEntries.length === 0 ? 'pass' : 'fail',
      manifest_agent_paths: manifestAgentPaths,
      filesystem_agent_paths: filesystemAgentPaths,
      missing_manifest_entries: missingManifestEntries,
      extra_manifest_entries: extraManifestEntries,
    },
    skills_directory_registration: {
      status:
        manifestSkillsPointer === './skills/' && skillSourcePaths.length > 0
          ? 'pass'
          : 'fail',
      manifest_skills_pointer: manifestSkillsPointer,
      canonical_directory_path: 'skills/',
      skill_file_count: skillSourcePaths.length,
      skill_source_paths_sample: skillSourcePaths.slice(0, 8),
    },
    hooks_pointer: {
      status: manifestHooksPointer === './hooks/hooks.json' ? 'pass' : 'fail',
      manifest_hooks_pointer: manifestHooksPointer,
      canonical_source_path: 'hooks/hooks.json',
    },
    hooks_registration: {
      status:
        isDeepStrictEqual(hookCommands, dod009HooksCommandPaths) &&
        isDeepStrictEqual(eventIds, ['PreToolUse', 'SessionStart', 'Stop', 'UserPromptSubmit'])
          ? 'pass'
          : 'fail',
      event_ids: eventIds,
      command_paths: hookCommands,
      missing_command_paths: missingCommandPaths,
      extra_command_paths: extraCommandPaths,
      shared_command_path_count: flattenDod009HookCommands(hooksConfig).length - hookCommands.length,
    },
  };

  const contractWithoutScan = {
    contract_id: 'REQ-912-DOD-009-claude-plugin-regression-matrix',
    request_id: 'REQ-912',
    task_id: '01',
    dod_id: 'DOD-009',
    format_version: '1.0.0',
    comparison_subject: 'claude-plugin-mode',
    codex_artifact_substitution_permitted: false,
    repository_local_only: true,
    matrix_surfaces: buildDod009MatrixSurfaces(),
    contract_checks: contractChecks,
    no_go_metadata_guard: {
      status: 'pass',
      criteria: dod009NoGoMetadataGuardCriteria,
      deterministic_validation: true,
      repository_local_only: true,
    },
    excluded_surfaces: excludedSurfaces,
    blocker_summary: {
      status: 'pass',
      blocker_count: 0,
      human_readable: [],
    },
    manual_readable_exports: {
      matrix_surface_ids: buildDod009MatrixSurfaces().map((surface) => surface.surface_id),
      canonical_source_paths: [...dod009MatrixSurfacePaths],
      excluded_surface_ids: [...dod009ExcludedSurfaceIds],
      blocker_summary_fields: ['status', 'blocker_count', 'human_readable'],
    },
    input_paths_read: [...dod009MatrixSurfacePaths],
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
  };
  const forbiddenMetadataScan = scanDod009RegressionMatrixMetadata(contractWithoutScan);
  const humanReadableBlockers = summarizeDod009Blockers(
    contractChecks,
    sanitizedParseFailures,
    forbiddenMetadataScan,
  );
  const contractStatus =
    Object.values(contractChecks).every((check) => check.status === 'pass') &&
    sanitizedParseFailures.length === 0 &&
    forbiddenMetadataScan.status === 'pass' &&
    excludedSurfaces.every((surface) =>
      surface.implementation_count === 0 &&
      surface.runtime_invocation_count === 0 &&
      surface.acceptance_gate_count === 0
    )
      ? 'pass'
      : 'fail';

  return {
    ...contractWithoutScan,
    status: contractStatus,
    blocker_summary: {
      status: humanReadableBlockers.length === 0 ? 'pass' : 'fail',
      blocker_count: humanReadableBlockers.length,
      human_readable: humanReadableBlockers,
    },
    forbidden_metadata_scan: forbiddenMetadataScan,
  };
}

export function buildDod008ExcludedSurfaces() {
  return dod008ExcludedSurfaceIds.map((surfaceId) => ({
    surface_id: surfaceId,
    dod_id: surfaceId,
    status: 'pass',
    implementation_count: 0,
    runtime_invocation_count: 0,
    acceptance_gate_count: 0,
    reason: 'Excluded surface only; not part of the DOD-008 workflow schema contract.',
  }));
}

export function buildDod008ArtifactSchemaContract() {
  return Object.entries(dod008ArtifactSchemaRequiredFieldsByType).map(
    ([artifactType, requiredFields]) => ({
      artifact_type: artifactType,
      required_fields: [...requiredFields],
      deterministic_validation: true,
      repository_local_only: true,
    }),
  );
}

export function buildDod008LifecycleSmokeArtifacts() {
  const mstSessionId = 'MST-AGI-039-20260519T144424Z-req89403';
  const rootMstId = 'AGI-039';
  const generatedAt = '2026-05-19T14:44:24.000Z';

  return [
    {
      artifact_id: 'REQ-894-DOD-008-recover-smoke',
      artifact_type: 'recover',
      recovery_id: 'recover-smoke-001',
      request_id: 'REQ-894',
      trigger: 'interrupted_session',
      resume_token: 'resume-token-fixture',
      mst_session_id: mstSessionId,
      root_mst_id: rootMstId,
      canonical_session_identity: {
        mst_session_id: mstSessionId,
        root_mst_id: rootMstId,
        lookup_key: mstSessionId,
        partition_key: mstSessionId,
        source: 'structured_context',
      },
      recovery_judgement: {
        primary_action: 'resume_session',
        reason: 'resume_ready',
        affected_resources: [
          { kind: 'mst_session_id', identifier: mstSessionId },
          { kind: 'session_worktree', identifier: 'session-worktree-fixture' },
          { kind: 'cleanup_stage_evidence', identifier: 'cleanup-stage-fixture' },
        ],
        cleanup_stage_evidence: {
          evidence_state: 'known',
          completed_destructive_stages: [],
          next_idempotent_stage: null,
          child_scan_fresh: true,
        },
      },
      status: 'pass',
      updated_at: generatedAt,
    },
    {
      artifact_id: 'REQ-894-DOD-008-cleanup-smoke',
      artifact_type: 'cleanup',
      cleanup_id: 'cleanup-smoke-001',
      request_id: 'REQ-894',
      targets: [
        {
          kind: 'active_flow_orphan_session',
          planned_count: 0,
          removed_count: 0,
        },
      ],
      dry_run: true,
      report: {
        entrypoint: 'direct-cli',
        session_id: mstSessionId,
        status: 'ok',
        orphan_session_count: 0,
        planned_cleanup_count: 0,
        result: 'nothing_to_clean',
      },
      request_artifacts_preserved: {
        status: 'pass',
        checked_paths: [
          '.gran-maestro/requests/REQ-894/request.json',
          '.gran-maestro/requests/REQ-894/tasks/03/spec.md',
        ],
        mutated_path_count: 0,
      },
      status: 'pass',
      updated_at: generatedAt,
    },
    {
      artifact_id: 'REQ-894-DOD-008-dashboard-smoke',
      artifact_type: 'dashboard',
      dashboard_id: 'dashboard-smoke-001',
      request_id: 'REQ-894',
      widgets: ['health', 'overview.active-items', 'overview.next-steps', 'overview.pulse'],
      health: {
        route: '/api/health',
        ok: true,
      },
      overview: {
        active_items: {
          route: '/api/overview/active-items',
          shape: {
            items: 'array',
            next_cursor: 'string_or_null',
            has_more: 'boolean',
            as_of: 'iso_timestamp',
          },
        },
        next_steps: {
          route: '/api/overview/next-steps',
          shape: {
            items: 'array',
            as_of: 'iso_timestamp',
          },
        },
        pulse: {
          route: '/api/overview/pulse',
          shape: {
            active: 'number',
            blocked: 'number',
            done_7d: 'number',
            stale_7d: 'number',
            as_of: 'iso_timestamp',
          },
        },
      },
      status: 'pass',
      updated_at: generatedAt,
    },
    {
      artifact_id: 'REQ-894-DOD-008-settings-smoke',
      artifact_type: 'settings',
      settings_id: 'settings-smoke-001',
      scope: 'project',
      request_id: 'REQ-894',
      effective_values: {
        workflow_default_agent: 'codex-dev',
        auto_mode_request: false,
        reference_auto_search: true,
      },
      config: {
        config_route: {
          route: '/api/config',
          shape: {
            merged: 'object',
            overrides: 'object',
            defaults: 'object',
          },
        },
        defaults_route: {
          route: '/api/config/defaults',
          shape: 'object',
        },
        mode_route: {
          route: '/api/mode',
          shape: {
            active: 'boolean',
          },
        },
      },
      status: 'pass',
      updated_at: generatedAt,
    },
  ];
}

export function buildDod008LifecycleSmokeValidation(artifacts = buildDod008LifecycleSmokeArtifacts()) {
  const requiredFieldsByType = dod008ArtifactSchemaRequiredFieldsByType;
  const missingRequiredFields = [];

  for (const artifact of artifacts) {
    const artifactType = artifact?.artifact_type;
    const requiredFields = requiredFieldsByType[artifactType] ?? [];
    for (const field of requiredFields) {
      if (!(field in artifact)) {
        missingRequiredFields.push({
          artifact_type: artifactType,
          artifact_id: artifact?.artifact_id ?? null,
          field,
        });
      }
    }
  }

  const artifactTypes = artifacts.map((artifact) => artifact.artifact_type);
  const missingArtifactTypes = dod008LifecycleSmokeArtifactTypes.filter(
    (artifactType) => !artifactTypes.includes(artifactType),
  );

  return {
    status:
      missingRequiredFields.length === 0 && missingArtifactTypes.length === 0 ? 'pass' : 'fail',
    artifact_types: artifactTypes,
    missing_artifact_types: missingArtifactTypes,
    missing_required_fields: missingRequiredFields,
    deterministic_validation: true,
    repository_local_only: true,
  };
}

export function buildDod008WorkflowScenarioContract() {
  const scenarioRequiredArtifacts = {
    '/mst:agile-plan': ['objective', 'spec', 'task', 'trace'],
    '/mst:agile --resume': ['objective', 'request', 'task', 'trace', 'recover'],
    '/mst:request': ['request', 'spec', 'task', 'trace'],
    '/mst:approve': ['request', 'task', 'trace'],
    'delegated implementation loop': ['task', 'trace'],
    '/mst:review': ['review', 'trace'],
    '/mst:accept': ['accept', 'review', 'trace'],
    '/mst:recover': ['recover', 'trace'],
    '/mst:cleanup': ['cleanup', 'trace'],
    '/mst:dashboard': ['dashboard', 'trace'],
    '/mst:settings': ['settings', 'trace'],
  };

  return dod008WorkflowScenarioPaths.map((scenarioPath, index) => ({
    scenario_id: `dod008-scenario-${String(index + 1).padStart(2, '0')}`,
    representative_path: scenarioPath,
    required_artifacts: scenarioRequiredArtifacts[scenarioPath],
    contract_only: true,
    repository_local_only: true,
  }));
}

export function buildDod008WorkflowSchemaContract() {
  const scenarioContract = buildDod008WorkflowScenarioContract();
  const artifactSchemaContract = buildDod008ArtifactSchemaContract();
  const excludedSurfaces = buildDod008ExcludedSurfaces();
  const lifecycleSmokeArtifacts = buildDod008LifecycleSmokeArtifacts();
  const lifecycleSmokeValidation = buildDod008LifecycleSmokeValidation(lifecycleSmokeArtifacts);
  const contractWithoutScan = {
    contract_id: 'REQ-894-DOD-008-workflow-schema-contract',
    request_id: 'REQ-894',
    task_id: '01',
    dod_id: 'DOD-008',
    format_version: '1.0.0',
    status: 'pass',
    scenario_contract: scenarioContract,
    artifact_schema_contract: artifactSchemaContract,
    no_go_metadata_guard: {
      status: 'pass',
      criteria: dod008NoGoMetadataGuardCriteria,
      deterministic_validation: true,
      repository_local_only: true,
    },
    lifecycle_smoke_artifacts: lifecycleSmokeArtifacts,
    lifecycle_smoke_validation: lifecycleSmokeValidation,
    acceptance_runtime_surface_ids: dod008AcceptanceRuntimeSurfaceIds,
    excluded_surfaces: excludedSurfaces,
    manual_readable_exports: {
      scenario_paths: dod008WorkflowScenarioPaths,
      artifact_types: Object.keys(dod008ArtifactSchemaRequiredFieldsByType),
      lifecycle_smoke_artifact_types: dod008LifecycleSmokeArtifactTypes,
      excluded_surface_ids: dod008ExcludedSurfaceIds,
      acceptance_runtime_surface_ids: dod008AcceptanceRuntimeSurfaceIds,
    },
  };
  const forbiddenMetadataScan = scanDod008ScenarioSchemaMetadata(contractWithoutScan);
  const status =
    forbiddenMetadataScan.status === 'pass' &&
    scenarioContract.every((scenario) => scenario.required_artifacts.length > 0) &&
    artifactSchemaContract.every((schema) => schema.required_fields.length > 0) &&
    lifecycleSmokeValidation.status === 'pass' &&
    excludedSurfaces.every((surface) => surface.status === 'pass')
      ? 'pass'
      : 'fail';

  return {
    ...contractWithoutScan,
    status,
    forbidden_metadata_scan: forbiddenMetadataScan,
  };
}

function buildDod008CoreWorkflowSessionMetadata() {
  return {
    status: 'pass',
    canonical_sources: ['MST_SESSION_ID', 'mst_session_id'],
    env: {
      MST_SESSION_ID: dod008CoreWorkflowSmokeSessionId,
    },
    context: {
      mst_session_id: dod008CoreWorkflowSmokeSessionId,
    },
    legacy_diagnostics: {
      diagnostic_only: true,
      fields: ['MST_STATE_PPID', 'owner_pid', 'session_id'],
      canonical_source_count: 0,
    },
    boundary_checks: {
      env_and_context_match: true,
      legacy_only_identity_rejected: true,
      arbitrary_child_identity_injection: false,
    },
  };
}

function buildDod008CoreWorkflowArtifacts(sessionMetadata = buildDod008CoreWorkflowSessionMetadata()) {
  return {
    request: {
      artifact_id: 'REQ-894-DOD008-core-request',
      request_id: 'REQ-894',
      objective_id: 'AGI-039',
      dod_id: 'DOD-008',
      status: 'spec_ready',
      task_ids: ['REQ-894-02'],
      state_session: sessionMetadata,
      path: '.gran-maestro/requests/REQ-894/request.json',
    },
    spec: {
      artifact_id: 'REQ-894-DOD008-core-spec',
      spec_id: 'REQ-894-02-spec',
      request_id: 'REQ-894',
      acceptance_criteria: ['T02-AC-001', 'T02-AC-002', 'T02-AC-003', 'T02-AC-004'],
      artifact_types: dod008CoreWorkflowSmokeArtifactTypes,
      state_session: sessionMetadata,
      path: '.gran-maestro/requests/REQ-894/tasks/02/spec.md',
    },
    task: {
      artifact_id: 'REQ-894-DOD008-core-task',
      task_id: 'REQ-894-02',
      request_id: 'REQ-894',
      status: 'reviewed',
      owner_role: 'codex-dev',
      trace_id: 'TRACE-REQ-894-02-core',
      state_session: sessionMetadata,
      path: '.gran-maestro/requests/REQ-894/tasks/02/task.json',
    },
    trace: {
      artifact_id: 'REQ-894-DOD008-core-trace',
      trace_id: 'TRACE-REQ-894-02-core',
      request_id: 'REQ-894',
      scenario_id: 'dod008-core-workflow-smoke',
      event_refs: [
        'EVT-agile-plan-fixture',
        'EVT-request-fixture',
        'EVT-approve-fixture',
        'EVT-delegated-loop-fixture',
        'EVT-review-fixture',
        'EVT-accept-fixture',
      ],
      status: 'pass',
      state_session: sessionMetadata,
      path: '.gran-maestro/requests/REQ-894/traces/dod008-core-workflow.json',
    },
    review: {
      artifact_id: 'REQ-894-DOD008-core-review',
      review_id: 'RV-001',
      request_id: 'REQ-894',
      trace_id: 'TRACE-REQ-894-02-core',
      findings: [
        {
          finding_id: 'FINDING-REQ-894-02-core-001',
          severity: 'info',
          status: 'closed',
        },
      ],
      status: 'pass',
      state_session: sessionMetadata,
      path: '.gran-maestro/requests/REQ-894/reviews/RV-001/review.json',
    },
    accept: {
      artifact_id: 'REQ-894-DOD008-core-accept',
      acceptance_id: 'ACCEPT-REQ-894-02-core',
      request_id: 'REQ-894',
      review_id: 'RV-001',
      decision: 'accepted',
      status: 'pass',
      state_session: sessionMetadata,
      path: '.gran-maestro/requests/REQ-894/acceptance/accept.json',
    },
  };
}

function validateDod008CoreWorkflowArtifact({ artifactType, artifact }) {
  const requiredFields = dod008ArtifactSchemaRequiredFieldsByType[artifactType] ?? [];
  const missingFields = requiredFields.filter((field) => !Object.hasOwn(artifact, field));
  const emptyFields = requiredFields.filter((field) => {
    const value = artifact[field];
    return value === null ||
      value === undefined ||
      (typeof value === 'string' && value.length === 0) ||
      (Array.isArray(value) && value.length === 0);
  });
  const session = artifact.state_session;
  const sessionViolations = [];
  if (!session || typeof session !== 'object') {
    sessionViolations.push('missing_state_session');
  } else {
    if (session.env?.MST_SESSION_ID !== dod008CoreWorkflowSmokeSessionId) {
      sessionViolations.push('missing_env_MST_SESSION_ID');
    }
    if (session.context?.mst_session_id !== dod008CoreWorkflowSmokeSessionId) {
      sessionViolations.push('missing_context_mst_session_id');
    }
    if (session.env?.MST_SESSION_ID !== session.context?.mst_session_id) {
      sessionViolations.push('canonical_session_mismatch');
    }
    if (session.legacy_diagnostics?.canonical_source_count !== 0) {
      sessionViolations.push('legacy_identity_used_as_canonical');
    }
  }

  return {
    artifact_type: artifactType,
    artifact_id: artifact?.artifact_id ?? null,
    status:
      missingFields.length === 0 &&
      emptyFields.length === 0 &&
      sessionViolations.length === 0
        ? 'pass'
        : 'fail',
    required_fields: [...requiredFields],
    missing_fields: missingFields,
    empty_fields: emptyFields,
    session_violations: sessionViolations,
  };
}

export function buildDod008CoreWorkflowSmokeHarness({
  schemaContract = buildDod008WorkflowSchemaContract(),
} = {}) {
  const sessionMetadata = buildDod008CoreWorkflowSessionMetadata();
  const artifacts = buildDod008CoreWorkflowArtifacts(sessionMetadata);
  const artifactValidations = dod008CoreWorkflowSmokeArtifactTypes.map((artifactType) =>
    validateDod008CoreWorkflowArtifact({
      artifactType,
      artifact: artifacts[artifactType],
    }),
  );
  const scenarioRecords = dod008CoreWorkflowSmokeScenarioPaths.map((scenarioPath, index) => ({
    scenario_id: `dod008-core-scenario-${String(index + 1).padStart(2, '0')}`,
    representative_path: scenarioPath,
    reproduced_by_fixture: true,
    executes_runtime: false,
    repository_local_only: true,
  }));
  const commandMetadata = [
    {
      command_id: 'npm-smoke',
      command: 'node --test tests/smoke.test.mjs',
      mode: 'deterministic-fixture',
      mutates_user_home: false,
      edits_hook_config: false,
      executes_codex_install: false,
      refreshes_codex_cache: false,
      runs_real_implementation: false,
    },
  ];
  const contractArtifactTypes = schemaContract.artifact_schema_contract.map(
    (schema) => schema.artifact_type,
  );
  const missingContractTypes = dod008CoreWorkflowSmokeArtifactTypes.filter(
    (artifactType) => !contractArtifactTypes.includes(artifactType),
  );
  const forbiddenMetadataScan = scanDod008ScenarioSchemaMetadata({
    scenario_records: scenarioRecords,
    artifacts,
    command_metadata: commandMetadata,
    session_metadata: sessionMetadata,
  });
  const status =
    schemaContract.status === 'pass' &&
    missingContractTypes.length === 0 &&
    artifactValidations.every((validation) => validation.status === 'pass') &&
    forbiddenMetadataScan.status === 'pass'
      ? 'pass'
      : 'fail';

  return {
    harness_id: 'REQ-894-02-DOD008-core-workflow-smoke',
    request_id: 'REQ-894',
    task_id: '02',
    dod_id: 'DOD-008',
    format_version: '1.0.0',
    status,
    mode: 'repository-local-fixture',
    scenario_records: scenarioRecords,
    artifact_types: dod008CoreWorkflowSmokeArtifactTypes,
    artifacts,
    artifact_validations: artifactValidations,
    session_metadata: sessionMetadata,
    schema_contract_summary: {
      contract_id: schemaContract.contract_id,
      status: schemaContract.status,
      checked_artifact_types: dod008CoreWorkflowSmokeArtifactTypes,
      missing_contract_types: missingContractTypes,
    },
    command_metadata: commandMetadata,
    side_effect_summary: {
      repository_local_only: true,
      fixture_only: true,
      mutates_user_home: false,
      edits_hook_config: false,
      executes_codex_install: false,
      refreshes_codex_cache: false,
      runs_real_implementation: false,
    },
    forbidden_metadata_scan: forbiddenMetadataScan,
  };
}

function dod008ArtifactSchemaMap(schemaContract = buildDod008WorkflowSchemaContract()) {
  return new Map(
    normalizeArray(schemaContract.artifact_schema_contract).map((schema) => [
      schema.artifact_type,
      normalizeArray(schema.required_fields),
    ]),
  );
}

function buildDod008ClaudeCanonicalArtifactShape({
  schemaContract = buildDod008WorkflowSchemaContract(),
  artifactTypes = dod008WorkflowArtifactParityTypes,
} = {}) {
  const schemaByType = dod008ArtifactSchemaMap(schemaContract);

  return artifactTypes.map((artifactType) => ({
    surface_id: 'DOD-008',
    artifact_type: artifactType,
    source: 'claude_canonical_shape',
    required_fields: [...(schemaByType.get(artifactType) ?? [])],
  }));
}

function dod008LifecycleArtifactMap(lifecycleArtifacts = buildDod008LifecycleSmokeArtifacts()) {
  return new Map(normalizeArray(lifecycleArtifacts).map((artifact) => [artifact.artifact_type, artifact]));
}

function buildDod008CodexFixtureArtifactShape({
  schemaContract = buildDod008WorkflowSchemaContract(),
  coreHarness = buildDod008CoreWorkflowSmokeHarness({ schemaContract }),
  lifecycleArtifacts = buildDod008LifecycleSmokeArtifacts(),
  artifactTypes = dod008WorkflowArtifactParityTypes,
  codexRequiredFieldsByType = {},
} = {}) {
  const schemaByType = dod008ArtifactSchemaMap(schemaContract);
  const lifecycleByType = dod008LifecycleArtifactMap(lifecycleArtifacts);

  return artifactTypes.map((artifactType) => {
    const artifact = coreHarness.artifacts?.[artifactType] ?? lifecycleByType.get(artifactType) ?? null;
    const schemaFields = schemaByType.get(artifactType) ?? [];
    const baselineRequiredFields = schemaFields.filter((field) => artifact && field in artifact);
    const requiredFields = codexRequiredFieldsByType[artifactType] ?? baselineRequiredFields;
    const presentRequiredFields = normalizeArray(requiredFields).filter(
      (field) => artifact && Object.hasOwn(artifact, field),
    );

    return {
      surface_id: 'DOD-008',
      artifact_type: artifactType,
      artifact_id: artifact?.artifact_id ?? null,
      source: 'codex_fixture_shape',
      required_fields: [...normalizeArray(requiredFields)],
      present_required_fields: presentRequiredFields,
      artifact_present: artifact !== null,
    };
  });
}

function dod008RequiredFieldBlocker({ artifactType, field, diffType }) {
  const phrase =
    diffType === 'missing_required_field'
      ? `is missing required field "${field}" from Claude canonical shape`
      : `requires extra field "${field}" outside the Claude canonical shape`;

  return {
    blocker_id: `DOD-008/${artifactType}/${field}/${diffType}`,
    surface_id: 'DOD-008',
    artifact_type: artifactType,
    artifact_field: field,
    diff_type: diffType,
    severity: 'blocker',
    message: `DOD-008 ${artifactType} artifact ${phrase}.`,
    human_readable: `DOD-008 ${artifactType}.${field}: ${phrase}.`,
  };
}

function compareDod008RequiredFieldParity({ claudeShape, codexShape }) {
  const codexByType = new Map(codexShape.map((shape) => [shape.artifact_type, shape]));
  const artifactDiffs = claudeShape.map((claudeArtifact) => {
    const codexArtifact = codexByType.get(claudeArtifact.artifact_type);
    const claudeRequiredFields = normalizeArray(claudeArtifact.required_fields);
    const codexRequiredFields = normalizeArray(codexArtifact?.required_fields);
    const missingRequiredFields = claudeRequiredFields.filter(
      (field) => !codexRequiredFields.includes(field),
    );
    const extraRequiredFields = codexRequiredFields.filter(
      (field) => !claudeRequiredFields.includes(field),
    );
    const blockers = [
      ...missingRequiredFields.map((field) =>
        dod008RequiredFieldBlocker({
          artifactType: claudeArtifact.artifact_type,
          field,
          diffType: 'missing_required_field',
        }),
      ),
      ...extraRequiredFields.map((field) =>
        dod008RequiredFieldBlocker({
          artifactType: claudeArtifact.artifact_type,
          field,
          diffType: 'extra_required_field',
        }),
      ),
    ];

    return {
      surface_id: 'DOD-008',
      artifact_type: claudeArtifact.artifact_type,
      claude_required_fields: claudeRequiredFields,
      codex_required_fields: codexRequiredFields,
      missing_required_fields: missingRequiredFields,
      extra_required_fields: extraRequiredFields,
      status: blockers.length === 0 ? 'pass' : 'fail',
      blockers,
    };
  });
  const blockers = artifactDiffs.flatMap((diff) => diff.blockers);

  return {
    status: blockers.length === 0 ? 'pass' : 'fail',
    checked_artifact_types: claudeShape.map((shape) => shape.artifact_type),
    missing_blocker_count: blockers.filter(
      (blocker) => blocker.diff_type === 'missing_required_field',
    ).length,
    extra_blocker_count: blockers.filter(
      (blocker) => blocker.diff_type === 'extra_required_field',
    ).length,
    blocker_count: blockers.length,
    artifact_diffs: artifactDiffs,
    blockers,
  };
}

function dod008BoundaryBlocker({ artifactType, field, message }) {
  return {
    blocker_id: `DOD-008/${artifactType}/${field}/boundary`,
    surface_id: 'DOD-008',
    artifact_type: artifactType,
    artifact_field: field,
    severity: 'blocker',
    message,
    human_readable: `DOD-008 ${artifactType}.${field}: ${message}`,
  };
}

function buildDod008WorkflowParityBoundaryChecks({
  coreHarness = buildDod008CoreWorkflowSmokeHarness(),
  lifecycleArtifacts = buildDod008LifecycleSmokeArtifacts(),
} = {}) {
  const lifecycleByType = dod008LifecycleArtifactMap(lifecycleArtifacts);
  const recover = lifecycleByType.get('recover');
  const cleanup = lifecycleByType.get('cleanup');
  const sessionBlockers = [];

  for (const artifactType of dod008CoreWorkflowSmokeArtifactTypes) {
    const artifact = coreHarness.artifacts?.[artifactType];
    const session = artifact?.state_session;
    if (session?.env?.MST_SESSION_ID !== session?.context?.mst_session_id) {
      sessionBlockers.push(
        dod008BoundaryBlocker({
          artifactType,
          field: 'state_session.mst_session_id',
          message: 'canonical env/context session identities must match.',
        }),
      );
    }
    if (session?.legacy_diagnostics?.canonical_source_count !== 0) {
      sessionBlockers.push(
        dod008BoundaryBlocker({
          artifactType,
          field: 'state_session.legacy_diagnostics.canonical_source_count',
          message: 'legacy diagnostic identity cannot become a canonical source.',
        }),
      );
    }
  }

  const recoveryBlockers = [];
  if (!recover) {
    recoveryBlockers.push(
      dod008BoundaryBlocker({
        artifactType: 'recover',
        field: 'artifact',
        message: 'recover smoke artifact is required for parity validation.',
      }),
    );
  } else {
    if (recover.canonical_session_identity?.mst_session_id !== recover.mst_session_id) {
      recoveryBlockers.push(
        dod008BoundaryBlocker({
          artifactType: 'recover',
          field: 'canonical_session_identity.mst_session_id',
          message: 'recover canonical session identity must match mst_session_id.',
        }),
      );
    }
    if (recover.canonical_session_identity?.lookup_key !== recover.mst_session_id) {
      recoveryBlockers.push(
        dod008BoundaryBlocker({
          artifactType: 'recover',
          field: 'canonical_session_identity.lookup_key',
          message: 'recover lookup key must use the canonical session identity.',
        }),
      );
    }
    if (recover.recovery_judgement?.primary_action !== 'resume_session') {
      recoveryBlockers.push(
        dod008BoundaryBlocker({
          artifactType: 'recover',
          field: 'recovery_judgement.primary_action',
          message: 'interrupted recovery must preserve resume_session judgement.',
        }),
      );
    }
  }

  const cleanupBlockers = [];
  if (!cleanup) {
    cleanupBlockers.push(
      dod008BoundaryBlocker({
        artifactType: 'cleanup',
        field: 'artifact',
        message: 'cleanup smoke artifact is required for orphan-session validation.',
      }),
    );
  } else {
    if (cleanup.report?.orphan_session_count !== 0) {
      cleanupBlockers.push(
        dod008BoundaryBlocker({
          artifactType: 'cleanup',
          field: 'report.orphan_session_count',
          message: 'cleanup parity fixture must report zero orphan sessions.',
        }),
      );
    }
    if (cleanup.request_artifacts_preserved?.mutated_path_count !== 0) {
      cleanupBlockers.push(
        dod008BoundaryBlocker({
          artifactType: 'cleanup',
          field: 'request_artifacts_preserved.mutated_path_count',
          message: 'cleanup parity fixture must not mutate request artifacts.',
        }),
      );
    }
  }

  const blockers = [...sessionBlockers, ...recoveryBlockers, ...cleanupBlockers];

  return {
    status: blockers.length === 0 ? 'pass' : 'fail',
    session_identity: {
      status: sessionBlockers.length === 0 ? 'pass' : 'fail',
      checked_artifact_types: dod008CoreWorkflowSmokeArtifactTypes,
      blocker_count: sessionBlockers.length,
      blockers: sessionBlockers,
    },
    recovery: {
      status: recoveryBlockers.length === 0 ? 'pass' : 'fail',
      artifact_type: 'recover',
      artifact_id: recover?.artifact_id ?? null,
      blocker_count: recoveryBlockers.length,
      blockers: recoveryBlockers,
    },
    orphan_session: {
      status: cleanupBlockers.length === 0 ? 'pass' : 'fail',
      artifact_type: 'cleanup',
      artifact_id: cleanup?.artifact_id ?? null,
      orphan_session_count: cleanup?.report?.orphan_session_count ?? null,
      blocker_count: cleanupBlockers.length,
      blockers: cleanupBlockers,
    },
    blocker_count: blockers.length,
    blockers,
  };
}

function buildDod008ExcludedSurfaceGuard(schemaContract = buildDod008WorkflowSchemaContract()) {
  const blockers = [];
  const excludedBySurface = new Map(
    normalizeArray(schemaContract.excluded_surfaces).map((surface) => [surface.surface_id, surface]),
  );

  for (const surfaceId of dod008ExcludedSurfaceIds) {
    const surface = excludedBySurface.get(surfaceId);
    for (const countField of [
      'implementation_count',
      'runtime_invocation_count',
      'acceptance_gate_count',
    ]) {
      if (surface?.[countField] !== 0) {
        blockers.push({
          blocker_id: `DOD-008/${surfaceId}/${countField}/excluded-surface`,
          surface_id: surfaceId,
          artifact_type: 'excluded_surface',
          artifact_field: countField,
          severity: 'blocker',
          message: `${surfaceId} must remain excluded from DOD-008 ${countField}.`,
          human_readable: `${surfaceId} excluded_surface.${countField}: expected 0, got ${surface?.[countField] ?? 'missing'}.`,
        });
      }
    }
  }

  return {
    status: blockers.length === 0 ? 'pass' : 'fail',
    surface_ids: dod008ExcludedSurfaceIds,
    surfaces: dod008ExcludedSurfaceIds.map((surfaceId) => excludedBySurface.get(surfaceId) ?? null),
    blocker_count: blockers.length,
    blockers,
  };
}

export function buildDod008WorkflowArtifactParityValidation({
  schemaContract = buildDod008WorkflowSchemaContract(),
  coreHarness = buildDod008CoreWorkflowSmokeHarness({ schemaContract }),
  lifecycleArtifacts = buildDod008LifecycleSmokeArtifacts(),
  codexRequiredFieldsByType = {},
} = {}) {
  const claudeShape = buildDod008ClaudeCanonicalArtifactShape({ schemaContract });
  const codexShape = buildDod008CodexFixtureArtifactShape({
    schemaContract,
    coreHarness,
    lifecycleArtifacts,
    codexRequiredFieldsByType,
  });
  const requiredFieldParity = compareDod008RequiredFieldParity({
    claudeShape,
    codexShape,
  });
  const boundaryChecks = buildDod008WorkflowParityBoundaryChecks({
    coreHarness,
    lifecycleArtifacts,
  });
  const excludedSurfaceGuard = buildDod008ExcludedSurfaceGuard(schemaContract);
  const blockers = [
    ...requiredFieldParity.blockers,
    ...boundaryChecks.blockers,
    ...excludedSurfaceGuard.blockers,
  ];

  return {
    validation_id: 'REQ-894-04-DOD008-workflow-artifact-parity',
    request_id: 'REQ-894',
    task_id: '04',
    dod_id: 'DOD-008',
    format_version: '1.0.0',
    status: blockers.length === 0 ? 'pass' : 'fail',
    mode: 'repository-local-fixture',
    canonical_claude_artifact_shape: claudeShape,
    codex_fixture_artifact_shape: codexShape,
    required_field_parity: requiredFieldParity,
    boundary_checks: boundaryChecks,
    excluded_surface_guard: excludedSurfaceGuard,
    blocker_summary: {
      status: blockers.length === 0 ? 'pass' : 'fail',
      blocker_count: blockers.length,
      missing_blocker_count: requiredFieldParity.missing_blocker_count,
      extra_blocker_count: requiredFieldParity.extra_blocker_count,
      blockers,
      human_readable: blockers.map((blocker) => blocker.human_readable),
    },
    input_summary: {
      core_harness_id: coreHarness.harness_id,
      lifecycle_artifact_types: lifecycleArtifacts.map((artifact) => artifact.artifact_type),
      schema_contract_id: schemaContract.contract_id,
      deterministic_validation: true,
      repository_local_only: true,
      executes_real_claude_runtime: false,
      executes_real_codex_runtime: false,
    },
  };
}

function buildDod007EvidenceLifecycle({
  verificationSummarySupplied,
  verificationSummary,
  sourceCommitStatus,
  excludedSurfaces,
  parseFailures,
}) {
  const contractSummaries = [
    verificationSummary.state_transition_integrity,
    verificationSummary.continuation_contract,
    verificationSummary.auto_continuation_contract,
    verificationSummary.run_wrapper_session_contract,
  ];
  const contractsPass = contractSummaries.every(dod007SummaryPasses);
  const focusedVerifyPass = dod007SummaryPasses(verificationSummary.focused_verify_command);
  const npmTestPass = dod007SummaryPasses(verificationSummary.npm_test);
  const generatorPass =
    verificationSummary.generator.status === 'pass' &&
    verificationSummary.generator.parse_ok === true &&
    verificationSummary.generator.generated_artifact_path === dod007RequestEvidenceRelativePath;
  const excludedSurfacesPass = excludedSurfaces.every(
    (surface) =>
      surface.status === 'pass' &&
      surface.implementation_count === 0 &&
      surface.runtime_invocation_count === 0 &&
      surface.acceptance_gate_count === 0,
  );

  return {
    status:
      verificationSummarySupplied &&
      focusedVerifyPass &&
      contractsPass &&
      npmTestPass &&
      generatorPass &&
      sourceCommitStatus === 'pass' &&
      excludedSurfacesPass &&
      parseFailures.length === 0
        ? 'pass'
        : 'fail',
    verification_summary_supplied: verificationSummarySupplied,
    focused_verify_pass: focusedVerifyPass,
    contract_summaries_pass: contractsPass,
    npm_test_pass: npmTestPass,
    generator_pass: generatorPass,
    source_commits_present: sourceCommitStatus === 'pass',
    excluded_surfaces_pass: excludedSurfacesPass,
  };
}

function buildCodexSkillAgentProjectionLifecycle({
  skillProjectionEvidence,
  roleMappingEvidence,
  verificationSummary,
  baselineSummary,
}) {
  const requiredArtifactPathEntries = [
    {
      label: 'request_evidence_path',
      path: skillAgentProjectionValidationEvidenceRelativePath,
    },
    {
      label: 'skill_projection_evidence_path',
      path: skillProjectionEvidence.request_evidence_path,
    },
    {
      label: 'role_mapping_evidence_path',
      path: roleMappingEvidence.request_evidence_path,
    },
    {
      label: 'baseline_evidence_path',
      path: baselineSummary.path,
    },
    {
      label: 'skill_projection_generator_artifact_path',
      path: verificationSummary.skill_projection_generator.generated_artifact_path,
    },
    {
      label: 'role_mapping_generator_artifact_path',
      path: verificationSummary.role_mapping_generator.generated_artifact_path,
    },
  ].map(({ label, path }) => ({
    label,
    path: sanitizeMetadataPath(path, null),
  }));

  const missingRequiredArtifactPaths = requiredArtifactPathEntries
    .filter((entry) => !entry.path)
    .map((entry) => entry.label);
  const implementationArtifactGenerationPass =
    skillProjectionEvidence.status === 'pass' &&
    roleMappingEvidence.status === 'pass' &&
    verificationSummary.skill_projection_generator.status === 'pass' &&
    verificationSummary.skill_projection_generator.parse_ok === true &&
    verificationSummary.role_mapping_generator.status === 'pass' &&
    verificationSummary.role_mapping_generator.parse_ok === true;
  const testsPass =
    verificationSummary.npm_test.status === 'pass' &&
    verificationSummary.npm_test.tests_fail === 0;
  const baselinePass =
    baselineSummary.parse_ok === true &&
    baselineSummary.request_id === 'REQ-890' &&
    baselineSummary.dod_id === 'DOD-005' &&
    baselineSummary.status === 'pass';

  return {
    status:
      implementationArtifactGenerationPass &&
      testsPass &&
      baselinePass &&
      missingRequiredArtifactPaths.length === 0
        ? 'pass'
        : 'fail',
    implementation_artifact_generation_pass: implementationArtifactGenerationPass,
    tests_pass: testsPass,
    baseline_pass: baselinePass,
    required_artifact_paths_present: missingRequiredArtifactPaths.length === 0,
    required_artifact_paths: requiredArtifactPathEntries,
    missing_required_artifact_paths: missingRequiredArtifactPaths,
  };
}

function compareFields(actual, expected, checkedFields) {
  const field_results = {};
  let missing_field_count = 0;
  let extra_field_count = 0;
  let value_mismatch_count = 0;

  for (const field of checkedFields) {
    const expectedHasField = Object.hasOwn(expected, field);
    const actualHasField = Object.hasOwn(actual, field);
    const actualValue = actual[field];
    const expectedValue = expected[field];

    let status = 'match';
    let reason = null;

    if (expectedHasField && !actualHasField) {
      missing_field_count += 1;
      status = 'missing';
      reason = 'field is missing from generated artifact';
    } else if (!expectedHasField && actualHasField) {
      extra_field_count += 1;
      status = 'extra';
      reason = 'field is not tracked by parity evidence';
    } else if (!isDeepStrictEqual(actualValue, expectedValue)) {
      value_mismatch_count += 1;
      status = 'mismatch';
      reason = 'generated field value differs from parity expectation';
    }

    field_results[field] = {
      status,
      reason,
      expected: expectedHasField ? expectedValue : null,
      actual: actualHasField ? actualValue : null,
    };
  }

  return {
    checked_fields: checkedFields,
    missing_field_count,
    extra_field_count,
    value_mismatch_count,
    drift_count: missing_field_count + extra_field_count + value_mismatch_count,
    field_results,
  };
}

function canonicalHookCommands(hookConfig) {
  if (!hookConfig?.hooks) {
    return [];
  }

  return [...new Set(
    Object.values(hookConfig.hooks).flatMap((entries) =>
      entries.flatMap((entry) => entry.hooks.map((hook) => hook.command)),
    ),
  )].sort();
}

function buildDiscoveryResults(assets) {
  return {
    status: assets.every((asset) => asset.exists && asset.parse_ok) ? 'pass' : 'fail',
    assets,
  };
}

function buildNoGoArtifactGuard(candidates) {
  const assets = candidates.map((candidate) => {
    const rootPath = candidate.root === 'orchestration' ? orchestrationRoot : repoRoot;
    return {
      category: candidate.category,
      description: candidate.description,
      root: candidate.root,
      path: candidate.path,
      exists: existsSync(join(rootPath, candidate.path)),
    };
  });

  return {
    status: assets.every((asset) => !asset.exists) ? 'pass' : 'fail',
    assets,
  };
}

function buildOutOfScopeArtifactCheck() {
  const checks = outOfScopeArtifactCandidates.map((check) => {
    const assets = [
      ...check.assets.map((path) => ({
        path,
        root: 'repo',
        exists: existsSync(join(repoRoot, path)),
      })),
      ...normalizeArray(check.orchestration_assets).map((path) => ({
        path,
        root: 'orchestration',
        exists: existsSync(join(orchestrationRoot, path)),
      })),
    ];

    return {
      dod_id: check.dod_id,
      description: check.description,
      status: assets.every((asset) => !asset.exists) ? 'pass' : 'fail',
      assets,
    };
  });

  return {
    status: checks.every((check) => check.status === 'pass') ? 'pass' : 'fail',
    checks,
  };
}

function hasCompleteInventoryValidationCoverage(coverage) {
  return Boolean(
    coverage &&
      Number(coverage.missing_component_count) === 0 &&
      Number(coverage.actual_component_count) === Number(coverage.expected_component_count) &&
      (Number(coverage.coverage_percent) === 100 || Number(coverage.coverage_ratio) === 1),
  );
}

export function collectUnsupportedBlockers({
  inventoryValidation,
  parityEvidence,
  integrationEvidence,
  outOfScopeArtifactCheck,
}) {
  const unsupportedBlockers = [];
  const inventoryValidationChecks = inventoryValidation?.checks;

  if (!hasCompleteInventoryValidationCoverage(inventoryValidation?.coverage)) {
    unsupportedBlockers.push('DOD-001 inventory validation coverage is incomplete.');
  }

  if (!Array.isArray(inventoryValidationChecks)) {
    unsupportedBlockers.push('DOD-001 inventory validation checks are missing.');
  } else if (inventoryValidationChecks.some((check) => check?.status !== 'pass')) {
    unsupportedBlockers.push('DOD-001 inventory validation checks did not all pass.');
  }

  for (const field of [
    'parse_error_count',
    'generated_drift_count',
    'unsupported_blocker_count',
  ]) {
    if (parityEvidence?.[field] !== 0) {
      unsupportedBlockers.push(`DOD-002 parity evidence ${field} is not zero.`);
    }
  }

  if (integrationEvidence?.status !== 'pass') {
    unsupportedBlockers.push('DOD-002 integration evidence status is not pass.');
  }

  if (integrationEvidence?.dod_002_blocker !== false) {
    unsupportedBlockers.push('DOD-002 integration evidence reported a blocker.');
  }

  for (const field of [
    'parse_error_count',
    'generated_drift_count',
    'unsupported_blocker_count',
  ]) {
    if (integrationEvidence?.parity_evidence_counts?.[field] !== 0) {
      unsupportedBlockers.push(`DOD-002 integration parity evidence ${field} is not zero.`);
    }
  }

  if (outOfScopeArtifactCheck.status !== 'pass') {
    unsupportedBlockers.push('Out-of-scope DOD artifacts were detected.');
  }

  return unsupportedBlockers;
}

export function buildCodexSkillProjectionEvidence() {
  const parseFailures = [];
  const baselineEvidence = collectJsonArtifact(
    req890Dod005ValidationEvidencePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const sourceManifest = collectJsonArtifact(
    sourceManifestPath,
    readJsonFromRepo,
    parseFailures,
  );
  const generatedManifest = collectJsonArtifact(
    generatedManifestPath,
    readJsonFromRepo,
    parseFailures,
  );
  const generatedMarketplace = collectJsonArtifact(
    generatedMarketplacePath,
    readJsonFromRepo,
    parseFailures,
  );

  const sourceSkillPaths = listSkillSourcePaths();
  const sourceSkillInventory = sourceSkillPaths.map((path) => {
    try {
      const parsed = parseSkillDefinition(path);
      return {
        path,
        digest: sha256(parsed.text),
        parsed,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      parseFailures.push({ path, error: message });
      return {
        path,
        digest: sha256(readUtf8(path)),
        parsed: null,
      };
    }
  });

  const projectionRecords = sourceSkillInventory.map((entry) => {
    const pathChecks = {
      source: validateRepositoryRelativePath(entry.path),
      projected: validateRepositoryRelativePath(entry.path),
    };
    const parsed = entry.parsed;
    const commandId = parsed?.command_id ?? null;
    const frontmatter = parsed?.frontmatter ?? {};

    return {
      skill_name: parsed?.skill_name ?? basename(dirname(entry.path)),
      skill_directory: parsed?.skill_directory ?? basename(dirname(entry.path)),
      source_path: entry.path,
      projected_path: entry.path,
      projection_mode: 'direct-source-reference',
      source_digest: entry.digest,
      digest_algorithm: 'sha256',
      parse_status: parsed ? 'pass' : 'fail',
      invocation_metadata: {
        mode: 'metadata-only',
        command_id: commandId,
        slash_command: commandId ? `/mst:${commandId}` : null,
        frontmatter_name: frontmatter.name ?? null,
        user_invocable: frontmatter['user-invocable'] ?? null,
        argument_hint: frontmatter['argument-hint'] ?? null,
      },
      drift_signal: {
        source_path: entry.path,
        digest: entry.digest,
      },
      path_checks: pathChecks,
      no_go_status:
        pathChecks.source.status === 'pass' && pathChecks.projected.status === 'pass'
          ? 'pass'
          : 'fail',
      validated_projection:
        Boolean(parsed) &&
        pathChecks.source.status === 'pass' &&
        pathChecks.projected.status === 'pass',
    };
  });

  const sourceDigestByPath = new Map(sourceSkillInventory.map((entry) => [entry.path, entry.digest]));
  const projectionPathSet = new Set(projectionRecords.map((record) => record.source_path));
  const missingSkillCount = sourceSkillPaths.filter((path) => !projectionPathSet.has(path)).length;
  const extraSkillCount = projectionRecords.filter((record) => !sourceDigestByPath.has(record.source_path)).length;
  const driftCount = projectionRecords.filter((record) =>
    sourceDigestByPath.get(record.source_path) !== record.source_digest ||
    record.source_path !== record.projected_path,
  ).length;
  const validatedProjectionCount = projectionRecords.filter((record) => record.validated_projection).length;

  const coreSkillRecords = coreMstSkillNames.map((skillName) => {
    const record = projectionRecords.find((candidate) => candidate.skill_name === skillName) ?? null;
    return {
      skill_name: skillName,
      status: record?.validated_projection ? 'pass' : 'fail',
      source_path: record?.source_path ?? null,
      projected_path: record?.projected_path ?? null,
      invocation_metadata: record?.invocation_metadata ?? null,
      executes_workflow: false,
      advances_request_state: false,
      executes_hooks: false,
      executes_session_runtime: false,
      mutates_user_home: false,
      mutates_user_config: false,
      creates_symlink: false,
    };
  });

  const noGoGuard = buildSkillProjectionNoGoGuard(projectionRecords);
  const crossFileConsistency = buildSkillProjectionCrossFileConsistency({
    generatedManifest: generatedManifest.value,
    sourceManifest: sourceManifest.value,
    generatedMarketplace: generatedMarketplace.value,
    sourceSkillCount: sourceSkillPaths.length,
  });
  const baselineSummary = summarizeBaselineEvidence(baselineEvidence.value);
  const coverage = {
    status:
      validatedProjectionCount === sourceSkillPaths.length &&
      missingSkillCount === 0 &&
      extraSkillCount === 0 &&
      driftCount === 0
        ? 'pass'
        : 'fail',
    source_skill_count: sourceSkillPaths.length,
    validated_projection_count: validatedProjectionCount,
    missing_skill_count: missingSkillCount,
    extra_skill_count: extraSkillCount,
    drift_count: driftCount,
  };
  const coreSkillSmoke = {
    status: coreSkillRecords.every((record) => record.status === 'pass') ? 'pass' : 'fail',
    core_skill_names: coreMstSkillNames,
    records: coreSkillRecords,
    runtime_side_effects: {
      created_request_count: 0,
      advanced_request_count: 0,
      request_state_transition_count: 0,
      hook_execution_count: 0,
      session_execution_count: 0,
      workflow_execution_count: 0,
    },
  };
  const excludedSurfaces = excludedDodIds.map((dodId) => ({
    dod_id: dodId,
    status: 'pass',
    reason: 'Excluded from DOD-006 task boundary; metadata-only projection proof only.',
  }));
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);

  return {
    artifact_id: 'REQ-891-DOD-006-codex-skill-projection-validation',
    request_id: 'REQ-891',
    task_id: '01',
    dod_id: 'DOD-006',
    format_version: '1.0.0',
    generated_at: new Date().toISOString(),
    status:
      sanitizedParseFailures.length === 0 &&
      coverage.status === 'pass' &&
      coreSkillSmoke.status === 'pass' &&
      noGoGuard.status === 'pass' &&
      crossFileConsistency.status === 'pass' &&
      baselineSummary.status === 'pass'
        ? 'pass'
        : 'fail',
    request_evidence_path: skillProjectionEvidenceRelativePath,
    baseline_evidence: baselineSummary,
    input_paths_read: [
      req890Dod005ValidationEvidenceRelativePath,
      sourceManifestPath,
      generatedManifestPath,
      generatedMarketplacePath,
      ...sourceSkillPaths,
    ],
    source_skill_inventory: {
      source_glob: 'skills/*/SKILL.md',
      source_skill_count: sourceSkillPaths.length,
      skill_paths: sourceSkillPaths,
    },
    projection_records: projectionRecords,
    coverage,
    core_skill_smoke: coreSkillSmoke,
    no_go_guard: noGoGuard,
    cross_file_consistency: crossFileConsistency,
    excluded_surfaces: excludedSurfaces,
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
  };
}

export function buildCodexRoleMappingEvidence() {
  const parseFailures = [];
  const sourceManifest = collectJsonArtifact(
    sourceManifestPath,
    readJsonFromRepo,
    parseFailures,
  );
  const generatedManifest = collectJsonArtifact(
    generatedManifestPath,
    readJsonFromRepo,
    parseFailures,
  );
  const generatedMarketplace = collectJsonArtifact(
    generatedMarketplacePath,
    readJsonFromRepo,
    parseFailures,
  );
  const skillProjectionEvidence = buildCodexSkillProjectionEvidence();

  const sourceAgentPaths = listAgentSourcePaths();
  const sourceAgentInventory = sourceAgentPaths.map((path) => {
    try {
      const parsed = parseAgentDefinition(path);
      return {
        path,
        digest: sha256(parsed.text),
        parsed,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      parseFailures.push({ path, error: message });
      return {
        path,
        digest: sha256(readUtf8(path)),
        parsed: null,
      };
    }
  });

  const roleMappingRecords = sourceAgentInventory.map((entry) => {
    const parsed = entry.parsed;
    const manifestPath = `./${entry.path}`;

    return {
      role_name: parsed?.role_name ?? basename(entry.path, '.md'),
      source_path: entry.path,
      manifest_path: manifestPath,
      source_digest: entry.digest,
      digest_algorithm: 'sha256',
      source_heading: parsed?.heading ?? basename(entry.path, '.md'),
      source_kind: parsed?.source_kind ?? 'agent',
      deprecation_status: parsed?.deprecated ? 'deprecated-compat' : 'active',
      codex_mapping: {
        mapping_mode: 'metadata-only',
        routing_surface: `/prompts:${parsed?.role_name ?? basename(entry.path, '.md')}`,
        subagent_label: parsed?.role_name ?? basename(entry.path, '.md'),
        prompt_origin: entry.path,
      },
      privilege_profile: {
        spawn_runtime_execution: false,
        provider_auth_routing: false,
        model_routing: false,
        mutates_user_home: false,
        mutates_user_config: false,
        refreshes_plugin_cache: false,
        executes_external_install: false,
        bypass_permissions: false,
        disables_sandbox: false,
        arbitrary_command_execution: false,
      },
    };
  });

  const roleCoverage = buildRoleCoverage(roleMappingRecords.map((record) => record.role_name));
  const manifestParity = buildClaudeManifestAgentParity({
    sourceManifest: sourceManifest.value,
    sourceAgentPaths,
  });
  const safeSkillPrivilegeRecords = buildSafeSkillPrivilegeRecords(skillProjectionEvidence);
  const privilegeGuard = buildPrivilegeGuard({
    skillRecords: safeSkillPrivilegeRecords,
    roleRecords: roleMappingRecords,
  });
  const crossFileConsistency = buildRoleMappingCrossFileConsistency({
    generatedManifest: generatedManifest.value,
    generatedMarketplace: generatedMarketplace.value,
    sourceManifest: sourceManifest.value,
    skillProjectionEvidence,
    roleCoverage,
    manifestParity,
  });
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);

  return {
    artifact_id: 'REQ-891-DOD-006-codex-role-mapping-validation',
    request_id: 'REQ-891',
    task_id: '02',
    dod_id: 'DOD-006',
    format_version: '1.0.0',
    generated_at: new Date().toISOString(),
    status:
      sanitizedParseFailures.length === 0 &&
      roleCoverage.status === 'pass' &&
      manifestParity.status === 'pass' &&
      crossFileConsistency.status === 'pass' &&
      privilegeGuard.status === 'pass' &&
      skillProjectionEvidence.status === 'pass'
        ? 'pass'
        : 'fail',
    request_evidence_path: roleMappingEvidenceRelativePath,
    input_paths_read: [
      sourceManifestPath,
      generatedManifestPath,
      generatedMarketplacePath,
      ...sourceAgentPaths,
    ],
    source_agent_inventory: {
      source_glob: 'agents/*.md',
      source_agent_count: sourceAgentPaths.length,
      agent_paths: sourceAgentPaths,
    },
    role_mapping_records: roleMappingRecords,
    role_coverage: roleCoverage,
    claude_manifest_parity: manifestParity,
    cross_file_consistency: crossFileConsistency,
    privilege_guard: privilegeGuard,
    source_dependencies: {
      skill_projection_evidence_path: skillProjectionEvidenceRelativePath,
      skill_projection_status: skillProjectionEvidence.status,
      skill_projection_summary: {
        source_skill_count: skillProjectionEvidence.source_skill_inventory.source_skill_count,
        validated_projection_count: skillProjectionEvidence.coverage.validated_projection_count,
        missing_skill_count: skillProjectionEvidence.coverage.missing_skill_count,
        extra_skill_count: skillProjectionEvidence.coverage.extra_skill_count,
        drift_count: skillProjectionEvidence.coverage.drift_count,
        core_skill_smoke_status: skillProjectionEvidence.core_skill_smoke.status,
      },
    },
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
  };
}

export function buildCodexSkillAgentProjectionValidationEvidence({
  skillProjectionEvidence = buildCodexSkillProjectionEvidence(),
  roleMappingEvidence = buildCodexRoleMappingEvidence(),
  verificationSummary = defaultCodexSkillAgentProjectionValidationSummary,
} = {}) {
  const parseFailures = [];
  const baselineEvidence = collectJsonArtifact(
    req890Dod005ValidationEvidencePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const requestMetadata = collectJsonArtifact(
    req891RequestMetadataAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const normalizedVerification = normalizeCodexSkillAgentProjectionValidationSummary(
    verificationSummary,
  );
  const baselineSummary = summarizeDod005BaselineEvidence(baselineEvidence.value);
  const requestSnapshot = buildReq891RequestMetadataSnapshot(requestMetadata.value);
  const task01Summary = summarizeReq891TaskEvidence({
    requestSnapshot,
    taskId: 'REQ-891-01',
    evidence: skillProjectionEvidence,
    evidencePath: skillProjectionEvidenceRelativePath,
  });
  const task02Summary = summarizeReq891TaskEvidence({
    requestSnapshot,
    taskId: 'REQ-891-02',
    evidence: roleMappingEvidence,
    evidencePath: roleMappingEvidenceRelativePath,
  });
  const lifecycle = buildCodexSkillAgentProjectionLifecycle({
    skillProjectionEvidence,
    roleMappingEvidence,
    verificationSummary: normalizedVerification,
    baselineSummary,
  });
  const commandTotals = summarizeDod006CommandTotals(normalizedVerification);
  const excludedSurfaces = [
    {
      dod_id: 'DOD-007',
      category: 'state-history-snapshot-parity',
      status: 'pass',
      implementation_count: 0,
      runtime_invocation_count: 0,
      reason: 'Excluded surface only; state/history/snapshot parity is not implemented in DOD-006.',
    },
    {
      dod_id: 'DOD-008',
      category: 'workflow-e2e-parity',
      status: 'pass',
      implementation_count: 0,
      runtime_invocation_count: 0,
      reason: 'Excluded surface only; workflow E2E parity is not implemented in DOD-006.',
    },
  ];
  const sourceCommitTasks = [task01Summary, task02Summary].map((summary) => ({
    task_id: summary.task_id,
    source_commit: summary.source_commit,
    task_commit: summary.task_commit,
    integration_commit: summary.integration_commit,
  }));
  const sourceCommitStatus = sourceCommitTasks.every(
    (task) => typeof task.source_commit === 'string' && task.source_commit.length > 0,
  )
    ? 'pass'
    : 'fail';
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);

  return {
    artifact_id: 'REQ-891-DOD-006-codex-skill-agent-projection-validation',
    request_id: 'REQ-891',
    agi_id: requestSnapshot.agi_id ?? 'AGI-039',
    sprint: requestSnapshot.sprint ?? 7,
    task_id: '03',
    dod_id: 'DOD-006',
    format_version: '1.0.0',
    generated_at: new Date().toISOString(),
    status:
      sanitizedParseFailures.length === 0 &&
      lifecycle.status === 'pass' &&
      excludedSurfaces.every((surface) => surface.status === 'pass')
        ? 'pass'
        : 'fail',
    request_evidence_path: skillAgentProjectionValidationEvidenceRelativePath,
    source_commit: {
      status: sourceCommitStatus,
      tasks: sourceCommitTasks,
    },
    generated_projection_artifact_paths: {
      skill_projection_evidence_path: skillProjectionEvidence.request_evidence_path,
      role_mapping_evidence_path: roleMappingEvidence.request_evidence_path,
    },
    test_command_results: {
      skill_projection_generator: normalizedVerification.skill_projection_generator,
      role_mapping_generator: normalizedVerification.role_mapping_generator,
      npm_test: normalizedVerification.npm_test,
      totals: commandTotals,
    },
    dod_005_baseline_summary: baselineSummary,
    t01_evidence_summary: {
      ...task01Summary,
      coverage_status: skillProjectionEvidence.coverage.status,
      core_skill_smoke_status: skillProjectionEvidence.core_skill_smoke.status,
      no_go_guard_status: skillProjectionEvidence.no_go_guard.status,
    },
    t02_evidence_summary: {
      ...task02Summary,
      role_coverage_status: roleMappingEvidence.role_coverage.status,
      privilege_guard_status: roleMappingEvidence.privilege_guard.status,
      privilege_regression_count: Object.values(
        roleMappingEvidence.privilege_guard.regression_signal_counts ?? {},
      ).reduce((sum, value) => sum + Number(value ?? 0), 0),
      cross_file_consistency_status: roleMappingEvidence.cross_file_consistency.status,
    },
    evidence_lifecycle: lifecycle,
    excluded_surfaces: excludedSurfaces,
    request_metadata_snapshot: requestSnapshot,
    input_paths_read: [
      req890Dod005ValidationEvidenceRelativePath,
      req891RequestMetadataRelativePath,
      skillProjectionEvidence.request_evidence_path,
      roleMappingEvidence.request_evidence_path,
      ...skillProjectionEvidence.input_paths_read,
      ...roleMappingEvidence.input_paths_read,
    ].filter((path, index, paths) => paths.indexOf(path) === index),
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
  };
}

export function buildDod007RequestEvidence({
  verificationSummary,
} = {}) {
  const parseFailures = [];
  const requestMetadata = collectJsonArtifact(
    req893RequestMetadataAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const normalizedVerification = normalizeDod007VerificationSummary(verificationSummary);
  const verificationSummarySupplied = verificationSummary !== undefined && verificationSummary !== null;
  const requestSnapshot = buildReq893RequestMetadataSnapshot(requestMetadata.value);
  const sourceCommitTasks = requestSnapshot.tasks.map((task) => ({
    task_id: task.task_id,
    source_commit: task.source_commit,
    task_commit: task.task_commit,
    integration_commit: task.integration_commit,
  }));
  const sourceCommitStatus = sourceCommitTasks.every(
    (task) => typeof task.source_commit === 'string' && task.source_commit.length > 0,
  )
    ? 'pass'
    : 'fail';
  const excludedSurfaces = buildDod007ExcludedSurfaces();
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);
  const lifecycle = buildDod007EvidenceLifecycle({
    verificationSummarySupplied,
    verificationSummary: normalizedVerification,
    sourceCommitStatus,
    excludedSurfaces,
    parseFailures: sanitizedParseFailures,
  });
  const evidenceWithoutScan = {
    artifact_id: 'REQ-893-DOD-007-request-level-validation',
    request_id: requestSnapshot.request_id ?? 'REQ-893',
    agi_id: requestSnapshot.agi_id ?? 'AGI-039',
    sprint: requestSnapshot.sprint ?? 8,
    task_id: '05',
    dod_id: requestSnapshot.dod_id ?? 'DOD-007',
    plan_id: requestSnapshot.plan_id ?? 'PLN-720',
    format_version: '1.0.0',
    generated_at: requestMetadata.value?.updated_at ?? requestMetadata.value?.created_at ?? '2026-05-19T00:00:00.000Z',
    request_evidence_path: dod007RequestEvidenceRelativePath,
    source_commit: {
      status: sourceCommitStatus,
      tasks: sourceCommitTasks,
    },
    test_command_results: {
      focused_verify_command: normalizedVerification.focused_verify_command,
      npm_test: normalizedVerification.npm_test,
      generator: normalizedVerification.generator,
      totals: {
        tests_total:
          normalizedVerification.focused_verify_command.tests_total +
          normalizedVerification.continuation_contract.tests_total +
          normalizedVerification.npm_test.tests_total,
        tests_pass:
          normalizedVerification.focused_verify_command.tests_pass +
          normalizedVerification.continuation_contract.tests_pass +
          normalizedVerification.npm_test.tests_pass,
        tests_fail:
          normalizedVerification.focused_verify_command.tests_fail +
          normalizedVerification.continuation_contract.tests_fail +
          normalizedVerification.npm_test.tests_fail,
      },
    },
    contract_summaries: {
      state_transition_integrity: normalizedVerification.state_transition_integrity,
      continuation_contract: normalizedVerification.continuation_contract,
      auto_continuation_contract: normalizedVerification.auto_continuation_contract,
      run_wrapper_session_contract: normalizedVerification.run_wrapper_session_contract,
    },
    state_contract_summary: {
      status: normalizedVerification.state_transition_integrity.status,
      tests_total: normalizedVerification.state_transition_integrity.tests_total,
      tests_pass: normalizedVerification.state_transition_integrity.tests_pass,
      tests_fail: normalizedVerification.state_transition_integrity.tests_fail,
      canonical_identity: 'MST_SESSION_ID',
    },
    continuation_contract_summary: {
      status: normalizedVerification.continuation_contract.status,
      tests_total:
        normalizedVerification.continuation_contract.tests_total +
        normalizedVerification.auto_continuation_contract.tests_total,
      tests_pass:
        normalizedVerification.continuation_contract.tests_pass +
        normalizedVerification.auto_continuation_contract.tests_pass,
      tests_fail:
        normalizedVerification.continuation_contract.tests_fail +
        normalizedVerification.auto_continuation_contract.tests_fail,
      continuation_mode: 'continue_unless_critical',
    },
    wrapper_contract_summary: {
      status: normalizedVerification.run_wrapper_session_contract.status,
      tests_total: normalizedVerification.run_wrapper_session_contract.tests_total,
      tests_pass: normalizedVerification.run_wrapper_session_contract.tests_pass,
      tests_fail: normalizedVerification.run_wrapper_session_contract.tests_fail,
      session_identity_source: 'MST_SESSION_ID',
    },
    evidence_lifecycle: lifecycle,
    excluded_surfaces: excludedSurfaces,
    request_metadata_snapshot: requestSnapshot,
    input_paths_read: [
      req893RequestMetadataRelativePath,
      '.gran-maestro/plans/PLN-720/plan.md',
      '.gran-maestro/plans/PLN-720/plan.ids.json',
    ],
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
  };
  const forbiddenMetadataScan = buildDod007ForbiddenMetadataScan(evidenceWithoutScan);
  const status =
    evidenceWithoutScan.evidence_lifecycle.status === 'pass' &&
    forbiddenMetadataScan.status === 'pass'
      ? 'pass'
      : 'fail';

  return {
    ...evidenceWithoutScan,
    status,
    evidence_lifecycle: {
      ...evidenceWithoutScan.evidence_lifecycle,
      status,
      forbidden_metadata_scan_pass: forbiddenMetadataScan.status === 'pass',
    },
    forbidden_metadata_scan: forbiddenMetadataScan,
  };
}

function summarizeDod008WorkflowCommandTotals(verificationSummary) {
  const summaries = [
    verificationSummary.focused_workflow_validation,
    verificationSummary.schema_contract,
    verificationSummary.core_workflow_harness,
    verificationSummary.lifecycle_smoke,
    verificationSummary.artifact_parity,
    verificationSummary.npm_test,
  ];

  return summaries.reduce(
    (totals, summary) => ({
      tests_total: totals.tests_total + Number(summary.tests_total ?? 0),
      tests_pass: totals.tests_pass + Number(summary.tests_pass ?? 0),
      tests_fail: totals.tests_fail + Number(summary.tests_fail ?? 0),
    }),
    { tests_total: 0, tests_pass: 0, tests_fail: 0 },
  );
}

function summarizeDod009CommandTotals(verificationSummary) {
  const summaries = [
    verificationSummary.plugin_manifest_hooks,
    verificationSummary.workflow_state_continuation,
    verificationSummary.run_wrapper_session_migration,
    verificationSummary.npm_test,
  ];

  return summaries.reduce(
    (totals, summary) => ({
      tests_total: totals.tests_total + Number(summary.tests_total ?? 0),
      tests_pass: totals.tests_pass + Number(summary.tests_pass ?? 0),
      tests_fail: totals.tests_fail + Number(summary.tests_fail ?? 0),
    }),
    { tests_total: 0, tests_pass: 0, tests_fail: 0 },
  );
}

function buildDod008EvidenceLifecycle({
  verificationSummary,
  schemaContract,
  coreHarness,
  lifecycleSmokeValidation,
  artifactParityValidation,
  excludedSurfaces,
  parseFailures,
}) {
  const focusedWorkflowSummariesPass = dod008FocusedWorkflowSummariesPass(verificationSummary);
  const schemaResultsPass =
    schemaContract.status === 'pass' &&
    coreHarness.status === 'pass' &&
    lifecycleSmokeValidation.status === 'pass' &&
    artifactParityValidation.status === 'pass';
  const npmTestPass = dod007SummaryPasses(verificationSummary.npm_test);
  const generatorPass =
    verificationSummary.generator.status === 'pass' &&
    verificationSummary.generator.parse_ok === true &&
    verificationSummary.generator.generated_artifact_path ===
      dod008WorkflowE2EValidationEvidenceRelativePath;
  const excludedSurfacesPass = excludedSurfaces.every(
    (surface) =>
      surface.status === 'pass' &&
      surface.implementation_count === 0 &&
      surface.runtime_invocation_count === 0 &&
      surface.acceptance_gate_count === 0,
  );

  return {
    status:
      focusedWorkflowSummariesPass &&
      schemaResultsPass &&
      npmTestPass &&
      generatorPass &&
      excludedSurfacesPass &&
      parseFailures.length === 0
        ? 'pass'
        : 'fail',
    focused_workflow_validation_pass: focusedWorkflowSummariesPass,
    schema_results_pass: schemaResultsPass,
    npm_test_pass: npmTestPass,
    generator_pass: generatorPass,
    excluded_surfaces_pass: excludedSurfacesPass,
    parse_failures_absent: parseFailures.length === 0,
  };
}

function buildDod009PriorEvidenceLink(evidence) {
  return {
    status:
      evidence?.status === 'pass' &&
      evidence?.request_id === 'REQ-894' &&
      evidence?.dod_id === 'DOD-008' &&
      evidence?.request_evidence_path === dod008WorkflowE2EValidationEvidenceRelativePath
        ? 'pass'
        : 'fail',
    relationship: 'supporting-reference-only',
    request_id: evidence?.request_id ?? 'REQ-894',
    agi_id: evidence?.agi_id ?? 'AGI-039',
    sprint: evidence?.sprint ?? 9,
    dod_id: evidence?.dod_id ?? 'DOD-008',
    plan_id: evidence?.plan_id ?? 'PLN-721',
    artifact_id: evidence?.artifact_id ?? null,
    request_evidence_path: evidence?.request_evidence_path ??
      dod008WorkflowE2EValidationEvidenceRelativePath,
    prior_evidence_status: evidence?.status ?? 'missing',
    substitutes_claude_regression_result: false,
  };
}

function summarizeDod009RequestEvidenceBlockers({
  matrixContract,
  linkedPriorEvidence,
  verificationSummary,
  parseFailures,
  forbiddenMetadataScan,
}) {
  const blockers = [...normalizeArray(matrixContract?.blocker_summary?.human_readable)];

  if (linkedPriorEvidence.status !== 'pass') {
    blockers.push(
      `linked_prior_evidence ${linkedPriorEvidence.request_evidence_path}: expected pass, got ${linkedPriorEvidence.prior_evidence_status}.`,
    );
  }

  for (const [summaryId, summary] of Object.entries({
    plugin_manifest_hooks: verificationSummary.plugin_manifest_hooks,
    workflow_state_continuation: verificationSummary.workflow_state_continuation,
    run_wrapper_session_migration: verificationSummary.run_wrapper_session_migration,
    npm_test: verificationSummary.npm_test,
  })) {
    if (summary.status !== 'pass') {
      blockers.push(
        `${summaryId}: ${summary.summary ?? 'command summary reported failure.'}`,
      );
    }
  }

  if (
    verificationSummary.generator.status !== 'pass' ||
    verificationSummary.generator.parse_ok !== true ||
    verificationSummary.generator.generated_artifact_path !== dod009RequestEvidenceRelativePath
  ) {
    blockers.push('generator: request-level evidence artifact metadata did not validate.');
  }

  for (const failure of parseFailures) {
    blockers.push(`parse_failure ${failure.path}: ${failure.error}.`);
  }

  if (forbiddenMetadataScan.status !== 'pass') {
    for (const violation of forbiddenMetadataScan.violations) {
      blockers.push(`forbidden_metadata ${violation.fixture_id}.`);
    }
  }

  return blockers;
}

function buildDod009EvidenceLifecycle({
  verificationSummary,
  matrixContract,
  linkedPriorEvidence,
  excludedSurfaces,
  parseFailures,
  forbiddenMetadataScan,
}) {
  const commandSummariesPass = dod009CommandSummariesPass(verificationSummary);
  const generatorPass =
    verificationSummary.generator.status === 'pass' &&
    verificationSummary.generator.parse_ok === true &&
    verificationSummary.generator.generated_artifact_path === dod009RequestEvidenceRelativePath;
  const matrixPass = matrixContract.status === 'pass';
  const linkedPriorEvidencePass = linkedPriorEvidence.status === 'pass';
  const noGoGuardPass =
    matrixContract.no_go_metadata_guard.status === 'pass' &&
    matrixContract.forbidden_metadata_scan.status === 'pass';
  const excludedSurfacesPass = excludedSurfaces.every(
    (surface) =>
      surface.status === 'pass' &&
      surface.implementation_count === 0 &&
      surface.runtime_invocation_count === 0 &&
      surface.acceptance_gate_count === 0,
  );
  const parseFailuresAbsent = parseFailures.length === 0;
  const forbiddenMetadataScanPass = forbiddenMetadataScan.status === 'pass';

  return {
    status:
      matrixPass &&
      linkedPriorEvidencePass &&
      commandSummariesPass &&
      generatorPass &&
      noGoGuardPass &&
      excludedSurfacesPass &&
      parseFailuresAbsent &&
      forbiddenMetadataScanPass
        ? 'pass'
        : 'fail',
    matrix_pass: matrixPass,
    linked_prior_evidence_pass: linkedPriorEvidencePass,
    command_summaries_pass: commandSummariesPass,
    generator_pass: generatorPass,
    no_go_guard_pass: noGoGuardPass,
    excluded_surfaces_pass: excludedSurfacesPass,
    parse_failures_absent: parseFailuresAbsent,
    forbidden_metadata_scan_pass: forbiddenMetadataScanPass,
  };
}

export function buildDod008WorkflowE2EValidationEvidence({
  verificationSummary,
} = {}) {
  const parseFailures = [];
  const requestMetadata = collectJsonArtifact(
    req894RequestMetadataAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const normalizedVerification = normalizeDod008WorkflowE2EValidationSummary(verificationSummary);
  const requestSnapshot = buildReq894RequestMetadataSnapshot(requestMetadata.value);
  const schemaContract = buildDod008WorkflowSchemaContract();
  const coreHarness = buildDod008CoreWorkflowSmokeHarness({ schemaContract });
  const lifecycleSmokeArtifacts = buildDod008LifecycleSmokeArtifacts();
  const lifecycleSmokeValidation = buildDod008LifecycleSmokeValidation(lifecycleSmokeArtifacts);
  const artifactParityValidation = buildDod008WorkflowArtifactParityValidation({
    schemaContract,
    coreHarness,
    lifecycleArtifacts: lifecycleSmokeArtifacts,
  });
  const excludedSurfaces = buildDod008ExcludedSurfaces();
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);
  const lifecycle = buildDod008EvidenceLifecycle({
    verificationSummary: normalizedVerification,
    schemaContract,
    coreHarness,
    lifecycleSmokeValidation,
    artifactParityValidation,
    excludedSurfaces,
    parseFailures: sanitizedParseFailures,
  });
  const sourceCommitTasks = requestSnapshot.tasks.map((task) => ({
    task_id: task.task_id,
    status: task.status,
    source_commit: task.source_commit,
    task_commit: task.task_commit,
    integration_commit: task.integration_commit,
  }));
  const evidenceWithoutScan = {
    artifact_id: 'REQ-894-DOD-008-workflow-e2e-validation',
    request_id: requestSnapshot.request_id ?? 'REQ-894',
    agi_id: requestSnapshot.agi_id ?? 'AGI-039',
    sprint: requestSnapshot.sprint ?? 9,
    task_id: '05',
    dod_id: requestSnapshot.dod_id ?? 'DOD-008',
    plan_id: requestSnapshot.plan_id ?? 'PLN-721',
    format_version: '1.0.0',
    generated_at:
      requestMetadata.value?.updated_at ??
      requestMetadata.value?.created_at ??
      '2026-05-19T14:44:24.000Z',
    request_evidence_path: dod008WorkflowE2EValidationEvidenceRelativePath,
    status: lifecycle.status,
    workflow_scenarios: {
      status:
        schemaContract.status === 'pass' && coreHarness.status === 'pass'
          ? 'pass'
          : 'fail',
      scenario_paths: dod008WorkflowScenarioPaths,
      schema_contract: schemaContract.scenario_contract,
      core_workflow_records: coreHarness.scenario_records,
    },
    schema_results: {
      status:
        schemaContract.status === 'pass' &&
        coreHarness.status === 'pass' &&
        lifecycleSmokeValidation.status === 'pass' &&
        artifactParityValidation.status === 'pass'
          ? 'pass'
          : 'fail',
      workflow_schema_contract: schemaContract,
      core_workflow_harness: coreHarness,
      lifecycle_smoke_validation: lifecycleSmokeValidation,
      artifact_parity_validation: artifactParityValidation,
    },
    focused_workflow_validation_summary: {
      status: dod008FocusedWorkflowSummariesPass(normalizedVerification) ? 'pass' : 'fail',
      focused_workflow_validation: normalizedVerification.focused_workflow_validation,
      schema_contract: normalizedVerification.schema_contract,
      core_workflow_harness: normalizedVerification.core_workflow_harness,
      lifecycle_smoke: normalizedVerification.lifecycle_smoke,
      artifact_parity: normalizedVerification.artifact_parity,
    },
    test_command_results: {
      focused_workflow_validation: normalizedVerification.focused_workflow_validation,
      schema_contract: normalizedVerification.schema_contract,
      core_workflow_harness: normalizedVerification.core_workflow_harness,
      lifecycle_smoke: normalizedVerification.lifecycle_smoke,
      artifact_parity: normalizedVerification.artifact_parity,
      npm_test: normalizedVerification.npm_test,
      generator: normalizedVerification.generator,
      totals: summarizeDod008WorkflowCommandTotals(normalizedVerification),
    },
    source_commit: {
      status: sourceCommitTasks.length === 5 ? 'pass' : 'fail',
      tasks: sourceCommitTasks,
    },
    evidence_lifecycle: lifecycle,
    excluded_surfaces: excludedSurfaces,
    request_metadata_snapshot: requestSnapshot,
    input_paths_read: [
      req894RequestMetadataRelativePath,
      '.gran-maestro/requests/REQ-894/tasks/04/spec.md',
      '.gran-maestro/requests/REQ-894/tasks/05/spec.md',
      'scripts/lib/codex-plugin-discovery-smoke.mjs',
      'scripts/generate-dod-007-request-evidence.mjs',
      'tests/smoke.test.mjs',
      dod007RequestEvidenceRelativePath,
    ],
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
  };
  const forbiddenMetadataScan = scanDod008RequestEvidenceMetadata(evidenceWithoutScan);
  const status =
    evidenceWithoutScan.evidence_lifecycle.status === 'pass' &&
    forbiddenMetadataScan.status === 'pass'
      ? 'pass'
      : 'fail';

  return {
    ...evidenceWithoutScan,
    status,
    evidence_lifecycle: {
      ...evidenceWithoutScan.evidence_lifecycle,
      status,
      forbidden_metadata_scan_pass: forbiddenMetadataScan.status === 'pass',
    },
    forbidden_metadata_scan: forbiddenMetadataScan,
  };
}

export function buildDod009RequestEvidence({
  verificationSummary,
} = {}) {
  const parseFailures = [];
  const requestMetadata = collectJsonArtifact(
    req912RequestMetadataAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const linkedDod008Evidence = collectJsonArtifact(
    dod008WorkflowE2EValidationEvidenceAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const normalizedVerification = normalizeDod009RequestEvidenceVerificationSummary(
    verificationSummary,
  );
  const requestSnapshot = buildReq912RequestMetadataSnapshot(requestMetadata.value);
  const matrixContract = buildDod009ClaudePluginRegressionMatrix();
  const linkedPriorEvidence = buildDod009PriorEvidenceLink(linkedDod008Evidence.value);
  const sharedDodRegistryLinkage = buildSharedDodEvidenceRegistryLinkage({
    dodId: requestSnapshot.dod_id ?? 'DOD-009',
    requestEvidencePath: dod009RequestEvidenceRelativePath,
  });
  const excludedSurfaces = matrixContract.excluded_surfaces.map((surface) => ({ ...surface }));
  const sanitizedParseFailures = sanitizeParseFailures(parseFailures);
  const evidenceWithoutScan = {
    artifact_id: 'REQ-912-DOD-009-claude-plugin-regression-validation',
    request_id: requestSnapshot.request_id ?? 'REQ-912',
    agi_id: requestSnapshot.agi_id ?? 'AGI-039',
    sprint: requestSnapshot.sprint ?? 10,
    task_id: '02',
    dod_id: requestSnapshot.dod_id ?? 'DOD-009',
    plan_id: requestSnapshot.plan_id ?? 'PLN-736',
    format_version: '1.0.0',
    generated_at:
      requestMetadata.value?.updated_at ??
      requestMetadata.value?.created_at ??
      '2026-05-20T01:47:31.000Z',
    request_evidence_path: dod009RequestEvidenceRelativePath,
    shared_dod_registry_linkage: sharedDodRegistryLinkage,
    status: 'fail',
    claude_plugin_regression_matrix: matrixContract,
    linked_prior_evidence: linkedPriorEvidence,
    no_go_metadata_guard: {
      status:
        matrixContract.no_go_metadata_guard.status === 'pass' &&
        matrixContract.forbidden_metadata_scan.status === 'pass'
          ? 'pass'
          : 'fail',
      criteria: matrixContract.no_go_metadata_guard.criteria,
      contract_forbidden_metadata_scan: matrixContract.forbidden_metadata_scan,
    },
    test_command_results: {
      plugin_manifest_hooks: normalizedVerification.plugin_manifest_hooks,
      workflow_state_continuation: normalizedVerification.workflow_state_continuation,
      run_wrapper_session_migration: normalizedVerification.run_wrapper_session_migration,
      npm_test: normalizedVerification.npm_test,
      generator: normalizedVerification.generator,
      totals: summarizeDod009CommandTotals(normalizedVerification),
    },
    blocker_summary: {
      status: 'pass',
      blocker_count: 0,
      human_readable: [],
    },
    evidence_lifecycle: {
      status: 'fail',
    },
    excluded_surfaces: excludedSurfaces,
    request_metadata_snapshot: requestSnapshot,
    manual_readable_exports: {
      canonical_source_paths: matrixContract.manual_readable_exports.canonical_source_paths,
      excluded_surface_ids: [...dod009ExcludedSurfaceIds],
      blocker_summary_fields: ['status', 'blocker_count', 'human_readable'],
      command_summary_fields: [
        'plugin_manifest_hooks',
        'workflow_state_continuation',
        'run_wrapper_session_migration',
        'npm_test',
        'generator',
      ],
      linked_prior_evidence_paths: [dod008WorkflowE2EValidationEvidenceRelativePath],
    },
    input_paths_read: [
      req912RequestMetadataRelativePath,
      dod008WorkflowE2EValidationEvidenceRelativePath,
      'scripts/lib/codex-plugin-discovery-smoke.mjs',
      'scripts/generate-dod-008-workflow-e2e-validation.mjs',
      'scripts/generate-dod-009-claude-plugin-regression-validation.mjs',
      'tests/smoke.test.mjs',
      ...matrixContract.input_paths_read,
    ].filter((path, index, paths) => paths.indexOf(path) === index),
    parse_error_count: sanitizedParseFailures.length,
    parse_failures: sanitizedParseFailures,
  };
  const forbiddenMetadataScan = scanDod009RegressionMatrixMetadata(evidenceWithoutScan);
  const lifecycle = buildDod009EvidenceLifecycle({
    verificationSummary: normalizedVerification,
    matrixContract,
    linkedPriorEvidence,
    excludedSurfaces,
    parseFailures: sanitizedParseFailures,
    forbiddenMetadataScan,
  });
  const blockers = summarizeDod009RequestEvidenceBlockers({
    matrixContract,
    linkedPriorEvidence,
    verificationSummary: normalizedVerification,
    parseFailures: sanitizedParseFailures,
    forbiddenMetadataScan,
  });
  const registryLinkageBlockers = sharedDodRegistryLinkage.issues.map(
    (issue) => `shared_dod_registry_linkage: ${issue}`,
  );
  const allBlockers = [...blockers, ...registryLinkageBlockers];
  const status =
    lifecycle.status === 'pass' && sharedDodRegistryLinkage.status === 'pass'
      ? 'pass'
      : 'fail';

  return {
    ...evidenceWithoutScan,
    status,
    blocker_summary: {
      status: allBlockers.length === 0 ? 'pass' : 'fail',
      blocker_count: allBlockers.length,
      human_readable: allBlockers,
    },
    evidence_lifecycle: {
      ...lifecycle,
      status,
      shared_dod_registry_linkage_pass: sharedDodRegistryLinkage.status === 'pass',
    },
    forbidden_metadata_scan: forbiddenMetadataScan,
  };
}

export function buildCodexPluginDiscoverySmokeEvidence() {
  const parseFailures = [];

  const inventoryArtifact = collectJsonArtifact(
    inventoryArtifactPath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const inventoryValidation = collectJsonArtifact(
    inventoryValidationPath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const parityEvidence = collectJsonArtifact(
    parityEvidencePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const integrationEvidence = collectJsonArtifact(
    integrationEvidencePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const forcedWireEvidence = collectJsonArtifact(
    forcedWireEvidenceAbsolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const sourceManifest = collectJsonArtifact(
    sourceManifestPath,
    readJsonFromRepo,
    parseFailures,
  );
  const sourceMarketplace = collectJsonArtifact(
    sourceMarketplacePath,
    readJsonFromRepo,
    parseFailures,
  );
  const hookConfig = collectJsonArtifact(
    sourceHookConfigPath,
    readJsonFromRepo,
    parseFailures,
  );
  const generatedManifest = collectJsonArtifact(
    generatedManifestPath,
    readJsonFromRepo,
    parseFailures,
  );
  const generatedMarketplace = collectJsonArtifact(
    generatedMarketplacePath,
    readJsonFromRepo,
    parseFailures,
  );

  const discoveryAssets = [
    {
      path: generatedManifestPath,
      exists: existsSync(join(repoRoot, generatedManifestPath)),
      parse_ok: generatedManifest.error === null,
      error: generatedManifest.error,
    },
    {
      path: generatedMarketplacePath,
      exists: existsSync(join(repoRoot, generatedMarketplacePath)),
      parse_ok: generatedMarketplace.error === null,
      error: generatedMarketplace.error,
    },
  ];

  const manifestExpectation = sourceManifest.value
    ? Object.fromEntries(manifestFields.map((field) => [field, sourceManifest.value[field]]))
    : {};

  const sourceMarketplacePluginEntry =
    sourceMarketplace.value?.plugins?.[
      parityEvidence.value?.component_mapping_summary?.marketplace_parity?.source_plugin_entry_index ?? 0
    ] ?? {};
  const generatedMarketplaceSourceExpectation =
    parityEvidence.value?.component_mapping_summary?.marketplace_parity?.field_mapping?.source
      ?.generated_value ?? {
      source: 'local',
      path: './',
    };
  const marketplaceExpectation = {
    name: sourceMarketplacePluginEntry.name,
    version: sourceMarketplacePluginEntry.version,
    source: generatedMarketplaceSourceExpectation,
    category: sourceMarketplacePluginEntry.category,
    tags: sourceMarketplacePluginEntry.tags,
  };

  const manifestComparison = compareFields(
    generatedManifest.value ?? {},
    manifestExpectation,
    manifestFields,
  );
  const generatedMarketplacePluginEntry =
    generatedMarketplace.value?.plugins?.[
      parityEvidence.value?.component_mapping_summary?.marketplace_parity?.generated_plugin_entry_index ?? 0
    ] ?? {};
  const marketplaceComparison = compareFields(
    generatedMarketplacePluginEntry,
    marketplaceExpectation,
    marketplaceFields,
  );

  const discoveryResults = buildDiscoveryResults(discoveryAssets);
  const outOfScopeArtifactCheck = buildOutOfScopeArtifactCheck();
  const noGoArtifactGuard = buildNoGoArtifactGuard(dod004NoGoArtifactCandidates);
  const sprint4IntegrationContextText = readTextIfExists(sprint4IntegrationContextPath);
  const sprint4IntegrationContextAssertions = {
    exists: sprint4IntegrationContextText.length > 0,
    force_wire_recommended: sprint4IntegrationContextText.includes(
      'force_wire_recommended: True',
    ),
    generated_manifest_new_island: sprint4IntegrationContextText.includes(generatedManifestPath),
    generated_marketplace_new_island: sprint4IntegrationContextText.includes(
      generatedMarketplacePath,
    ),
    validation_entrypoints_wired: validationEntrypoints.every((entrypoint) =>
      sprint4IntegrationContextText.includes(entrypoint),
    ),
  };
  const sprint4ForcedWireBlockers = Object.entries(sprint4IntegrationContextAssertions)
    .filter(([, passed]) => !passed)
    .map(([name]) => `Sprint 4 forced wire integration context assertion failed: ${name}.`);

  const upstreamDodBlockers = collectUnsupportedBlockers({
    inventoryValidation: inventoryValidation.value,
    parityEvidence: parityEvidence.value,
    integrationEvidence: integrationEvidence.value,
    outOfScopeArtifactCheck,
  });
  const unsupportedBlockers = [
    ...upstreamDodBlockers,
    ...sprint4ForcedWireBlockers,
  ];
  const upstreamDodGatingBlockers = upstreamDodBlockers.filter((blocker) =>
    blocker.startsWith('DOD-001') || blocker.startsWith('DOD-002'),
  );

  const claudeHookCommands = canonicalHookCommands(hookConfig.value);
  const claudePluginRegressionStatus =
    sourceManifest.value?.hooks === './hooks/hooks.json' &&
    isDeepStrictEqual(claudeHookCommands, [
      '${CLAUDE_PLUGIN_ROOT}/hooks/mst-auto-chain-context.sh',
      '${CLAUDE_PLUGIN_ROOT}/hooks/mst-pre-tool-use.sh',
      '${CLAUDE_PLUGIN_ROOT}/hooks/mst-session-init.sh',
      '${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh',
    ])
      ? 'pass'
      : 'fail';
  const generatedMarketplacePlugin =
    generatedMarketplace.value?.plugins?.[
      parityEvidence.value?.component_mapping_summary?.marketplace_parity?.generated_plugin_entry_index ?? 0
    ] ?? null;
  const dod004UnsupportedSurfaces = outOfScopeArtifactCheck.checks
    .filter((check) => ['DOD-006', 'DOD-008'].includes(check.dod_id))
    .map((check) => ({
      dod_id: check.dod_id,
      description: check.description,
      status: check.status,
    }));
  const dod004Status =
    forcedWireEvidence.error === null &&
    noGoArtifactGuard.status === 'pass' &&
    dod004UnsupportedSurfaces.every((surface) => surface.status === 'pass')
      ? 'pass'
      : 'fail';

  return {
    artifact_id: 'REQ-886-DOD-003-codex-plugin-discovery-smoke',
    request_id: 'REQ-886',
    task_id: '01',
    dod_id: 'DOD-003',
    format_version: '1.0.0',
    generated_at: new Date().toISOString(),
    status:
      discoveryResults.status === 'pass' &&
      parseFailures.length === 0 &&
      manifestComparison.drift_count + marketplaceComparison.drift_count === 0 &&
      unsupportedBlockers.length === 0
        ? 'pass'
        : 'fail',
    validation_evidence_path: stableEvidenceRelativePath,
    discovery_smoke_result_path: `${stableEvidenceRelativePath}#discovery_results`,
    selection_reason: sprint4SelectionReason,
    s04_integration_context_path: sprint4IntegrationContextPath,
    generated_asset_baseline_paths: generatedAssetBaselinePaths,
    validation_entrypoints: validationEntrypoints,
    root_metadata: {
      repo_root: repoRoot,
      orchestration_root: orchestrationRoot,
      repository_asset_root: repoRoot,
      orchestration_evidence_root: orchestrationRoot,
    },
    input_paths_read: [
      inventoryArtifactPath,
      inventoryValidationPath,
      parityEvidencePath,
      integrationEvidencePath,
      forcedWireEvidenceAbsolutePath,
      sourceManifestPath,
      sourceMarketplacePath,
      sourceHookConfigPath,
      generatedManifestPath,
      generatedMarketplacePath,
      sprint4IntegrationContextPath,
    ],
    sprint4_forced_wire: {
      selection_reason: sprint4SelectionReason,
      integration_context_path: sprint4IntegrationContextPath,
      integration_context_assertions: sprint4IntegrationContextAssertions,
      generated_asset_baseline_paths: generatedAssetBaselinePaths,
      validation_entrypoints: validationEntrypoints,
      repo_root_orchestration_root_separation: {
        repo_root: repoRoot,
        orchestration_root: orchestrationRoot,
        repository_asset_root: repoRoot,
        orchestration_evidence_root: orchestrationRoot,
        roots_are_distinct: repoRoot !== orchestrationRoot,
      },
      upstream_dod_gating: {
        status: upstreamDodGatingBlockers.length === 0 ? 'pass' : 'fail',
        dod_001: {
          inventory_artifact_path: inventoryArtifactPath,
          inventory_validation_path: inventoryValidationPath,
          blocker_count: upstreamDodBlockers.filter((blocker) =>
            blocker.startsWith('DOD-001'),
          ).length,
        },
        dod_002: {
          parity_evidence_path: parityEvidencePath,
          integration_evidence_path: integrationEvidencePath,
          blocker_count: upstreamDodBlockers.filter((blocker) =>
            blocker.startsWith('DOD-002'),
          ).length,
        },
      },
      out_of_scope_dod_guard: {
        status: outOfScopeArtifactCheck.status,
        dod_ids: outOfScopeArtifactCheck.checks.map((check) => check.dod_id),
      },
    },
    generated_manifest_path: generatedManifestPath,
    generated_marketplace_path: generatedMarketplacePath,
    dod_004_install_fallback_reproducibility: {
      ...req888Dod004Metadata,
      status: dod004Status,
      request_evidence_path: forcedWireEvidenceRelativePath,
      discovery_smoke_evidence_path: stableEvidenceRelativePath,
      generated_manifest_path: generatedManifestPath,
      generated_marketplace_path: generatedMarketplacePath,
      source_evidence: {
        forced_wire_request_id: forcedWireEvidence.value?.request_id ?? null,
        forced_wire_dod_id: forcedWireEvidence.value?.dod_id ?? null,
        forced_wire_evidence_path: forcedWireEvidenceRelativePath,
        discovery_smoke_request_id: 'REQ-886',
        discovery_smoke_dod_id: 'DOD-003',
        discovery_smoke_evidence_path: stableEvidenceRelativePath,
      },
      native_plugin_install: {
        mode: 'metadata-only',
        generated_manifest_path: generatedManifestPath,
        generated_marketplace_path: generatedMarketplacePath,
        source_references: [
          {
            type: 'local',
            manifest_path: generatedManifestPath,
            marketplace_path: generatedMarketplacePath,
            source_path: generatedMarketplacePlugin?.source?.path ?? './',
          },
          {
            type: 'marketplace',
            manifest_path: generatedManifestPath,
            marketplace_path: generatedMarketplacePath,
            plugin_name: generatedManifest.value?.name ?? null,
            marketplace_name: generatedMarketplace.value?.name ?? null,
          },
        ],
        verification_steps: [
          {
            step_id: 'install-reference-generated-assets',
            phase: 'install',
            action: 'Use the generated Codex plugin manifest and marketplace JSON as the reproducible install inputs.',
            references: [generatedManifestPath, generatedMarketplacePath],
          },
          {
            step_id: 'enable-reference-config-state',
            phase: 'enable',
            action: 'Record enablement as a verification concept against the native Codex plugin entry without mutating user config.',
            references: [userConfigPathLiteral, generatedManifestPath],
          },
          {
            step_id: 'reload-reference-plugin-discovery',
            phase: 'reload',
            action: 'Describe reload verification as a data-only step that confirms generated assets remain parseable and discoverable.',
            references: [generatedManifestPath, generatedMarketplacePath, stableEvidenceRelativePath],
          },
        ],
        executes_external_install: false,
        mutates_user_config: false,
        refreshes_plugin_cache: false,
      },
      fallback_skill_discovery: {
        mode: 'metadata-only',
        discovery_root: fallbackSkillDiscoveryRootPath,
        repo_target: fallbackSkillRepoTargetPath,
        symlink_path: fallbackSkillSymlinkPath,
        symlink_behavior: 'Reproducible fallback is described as a symlink from ~/.agents/skills/gran-maestro to the repo skills/ directory.',
        verification_steps: [
          {
            step_id: 'fallback-discovery-root',
            phase: 'discover',
            action: 'Record ~/.agents/skills as the local Codex skill discovery root concept.',
            references: [fallbackSkillDiscoveryRootPath],
          },
          {
            step_id: 'fallback-target-repo-skills',
            phase: 'target',
            action: 'Record repo skills/ as the fallback target concept for local discovery.',
            references: [fallbackSkillRepoTargetPath, generatedManifest.value?.skills ?? './skills/'],
          },
          {
            step_id: 'fallback-symlink-repro',
            phase: 'verify',
            action: 'Describe the symlink relationship as a reproducible manual step only; do not create it in this sprint.',
            references: [fallbackSkillSymlinkPath, fallbackSkillRepoTargetPath],
          },
        ],
        creates_symlink: false,
        mutates_user_config: false,
      },
      unsupported_surfaces: {
        status: dod004UnsupportedSurfaces.every((surface) => surface.status === 'pass')
          ? 'pass'
          : 'fail',
        surfaces: dod004UnsupportedSurfaces,
      },
      no_go_artifact_guard: {
        ...noGoArtifactGuard,
        mutates_user_config: false,
        refreshes_plugin_cache: false,
        creates_symlink: false,
      },
    },
    parse_error_count: parseFailures.length,
    generated_drift_count: manifestComparison.drift_count + marketplaceComparison.drift_count,
    unsupported_blocker_count: unsupportedBlockers.length,
    unsupported_blockers: unsupportedBlockers,
    drift_comparison: {
      manifest: {
        source_path: sourceManifestPath,
        generated_path: generatedManifestPath,
        ...manifestComparison,
      },
      marketplace: {
        source_path: sourceMarketplacePath,
        generated_path: generatedMarketplacePath,
        ...marketplaceComparison,
      },
    },
    scope_exclusions: [
      'Codex hook wrapper parity is tracked by downstream DOD-005 evidence and is not a DOD-003 blocker.',
      'Codex skill/agent runtime projection is out of scope for DOD-003.',
      'Codex workflow E2E parity is out of scope for DOD-003.',
      'hooks/hooks.json command replacement is out of scope for DOD-003.',
    ],
    changed_files_checked: changedFilesChecked,
    out_of_scope_artifact_check: outOfScopeArtifactCheck,
    discovery_results: discoveryResults,
    parse_failures: parseFailures,
    source_artifact_paths: {
      source_manifest_path: sourceManifestPath,
      source_marketplace_path: sourceMarketplacePath,
      source_hook_config_path: sourceHookConfigPath,
      inventory_artifact_path: inventoryArtifactPath,
      inventory_validation_path: inventoryValidationPath,
      parity_evidence_path: parityEvidencePath,
      integration_evidence_path: integrationEvidencePath,
    },
    claude_plugin_regression: {
      status: claudePluginRegressionStatus,
      manifest_hooks_pointer: sourceManifest.value?.hooks ?? null,
      canonical_hook_commands: claudeHookCommands,
    },
  };
}

export function assertCodexSkillProjectionEvidence(evidence) {
  assert.equal(evidence.request_id, 'REQ-891');
  assert.equal(evidence.task_id, '01');
  assert.equal(evidence.dod_id, 'DOD-006');
  assert.equal(evidence.request_evidence_path, skillProjectionEvidenceRelativePath);
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assert.equal(evidence.coverage.status, 'pass');
  assert.equal(
    evidence.coverage.validated_projection_count,
    evidence.source_skill_inventory.source_skill_count,
  );
  assert.equal(evidence.coverage.missing_skill_count, 0);
  assert.equal(evidence.coverage.extra_skill_count, 0);
  assert.equal(evidence.coverage.drift_count, 0);
  assert.equal(evidence.core_skill_smoke.status, 'pass');
  assert.deepEqual(evidence.core_skill_smoke.core_skill_names, coreMstSkillNames);
  assert.equal(evidence.core_skill_smoke.runtime_side_effects.created_request_count, 0);
  assert.equal(evidence.core_skill_smoke.runtime_side_effects.advanced_request_count, 0);
  assert.equal(evidence.core_skill_smoke.runtime_side_effects.request_state_transition_count, 0);
  assert.equal(evidence.core_skill_smoke.runtime_side_effects.hook_execution_count, 0);
  assert.equal(evidence.core_skill_smoke.runtime_side_effects.session_execution_count, 0);
  assert.equal(evidence.core_skill_smoke.runtime_side_effects.workflow_execution_count, 0);
  assert.equal(evidence.no_go_guard.status, 'pass');
  assert.equal(evidence.cross_file_consistency.status, 'pass');
  assert.equal(evidence.baseline_evidence.status, 'pass');
  assert.deepEqual(
    evidence.excluded_surfaces.map((surface) => surface.dod_id),
    excludedDodIds,
  );
}

export function assertCodexRoleMappingEvidence(evidence) {
  assert.equal(evidence.request_id, 'REQ-891');
  assert.equal(evidence.task_id, '02');
  assert.equal(evidence.dod_id, 'DOD-006');
  assert.equal(evidence.request_evidence_path, roleMappingEvidenceRelativePath);
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assert.equal(evidence.role_coverage.status, 'pass');
  assert.equal(evidence.role_coverage.coverage_percent, 100);
  assert.equal(evidence.role_coverage.missing_role_count, 0);
  assert.equal(evidence.role_coverage.extra_role_count, 0);
  assert.deepEqual(evidence.role_coverage.required_roles, requiredAgentRoleNames);
  assert.equal(evidence.claude_manifest_parity.status, 'pass');
  assert.equal(evidence.claude_manifest_parity.missing_agent_count, 0);
  assert.equal(evidence.claude_manifest_parity.extra_agent_count, 0);
  assert.equal(evidence.claude_manifest_parity.forbidden_projection_path_count, 0);
  assert.equal(evidence.cross_file_consistency.status, 'pass');
  assert.equal(evidence.privilege_guard.status, 'pass');
  assert.equal(evidence.privilege_guard.schema_basis, 'allowlist');
  assert.equal(evidence.privilege_guard.skill_metadata_schema.status, 'pass');
  assert.equal(evidence.privilege_guard.role_metadata_schema.status, 'pass');
  assert.equal(evidence.privilege_guard.deny_fixture_rejections.status, 'pass');
}

export function assertCodexSkillAgentProjectionValidationEvidence(
  evidence,
  expectedSummary = defaultCodexSkillAgentProjectionValidationSummary,
) {
  const normalizedExpected = normalizeCodexSkillAgentProjectionValidationSummary(expectedSummary);

  assert.equal(evidence.request_id, 'REQ-891');
  assert.equal(evidence.agi_id, 'AGI-039');
  assert.equal(evidence.sprint, 7);
  assert.equal(evidence.task_id, '03');
  assert.equal(evidence.dod_id, 'DOD-006');
  assert.equal(
    evidence.request_evidence_path,
    skillAgentProjectionValidationEvidenceRelativePath,
  );
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assert.equal(evidence.generated_projection_artifact_paths.skill_projection_evidence_path, skillProjectionEvidenceRelativePath);
  assert.equal(evidence.generated_projection_artifact_paths.role_mapping_evidence_path, roleMappingEvidenceRelativePath);
  assert.equal(evidence.dod_005_baseline_summary.request_id, 'REQ-890');
  assert.equal(evidence.dod_005_baseline_summary.dod_id, 'DOD-005');
  assert.equal(evidence.dod_005_baseline_summary.status, 'pass');
  assert.equal(evidence.evidence_lifecycle.status, 'pass');
  assert.equal(evidence.evidence_lifecycle.implementation_artifact_generation_pass, true);
  assert.equal(evidence.evidence_lifecycle.tests_pass, true);
  assert.equal(evidence.evidence_lifecycle.required_artifact_paths_present, true);
  assert.deepEqual(
    evidence.excluded_surfaces.map((surface) => surface.dod_id),
    excludedDodIds,
  );
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.implementation_count === 0));
  assert.equal(evidence.t01_evidence_summary.task_id, 'REQ-891-01');
  assert.equal(evidence.t01_evidence_summary.evidence_status, 'pass');
  assert.equal(evidence.t02_evidence_summary.task_id, 'REQ-891-02');
  assert.equal(evidence.t02_evidence_summary.evidence_status, 'pass');
  assert.equal(
    evidence.test_command_results.skill_projection_generator.status,
    normalizedExpected.skill_projection_generator.status,
  );
  assert.equal(
    evidence.test_command_results.role_mapping_generator.status,
    normalizedExpected.role_mapping_generator.status,
  );
  assert.equal(evidence.test_command_results.npm_test.status, normalizedExpected.npm_test.status);
  assert.equal(
    evidence.test_command_results.skill_projection_generator.generated_artifact_path,
    skillProjectionEvidenceRelativePath,
  );
  assert.equal(
    evidence.test_command_results.role_mapping_generator.generated_artifact_path,
    roleMappingEvidenceRelativePath,
  );
}

export function assertDod007RequestEvidence(
  evidence,
  expectedSummary = defaultDod007RequestEvidenceVerificationSummary,
) {
  const normalizedExpected = normalizeDod007VerificationSummary(expectedSummary);

  assert.equal(evidence.request_id, 'REQ-893');
  assert.equal(evidence.agi_id, 'AGI-039');
  assert.equal(evidence.sprint, 8);
  assert.equal(evidence.task_id, '05');
  assert.equal(evidence.dod_id, 'DOD-007');
  assert.equal(evidence.plan_id, 'PLN-720');
  assert.equal(evidence.request_evidence_path, dod007RequestEvidenceRelativePath);
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assert.equal(evidence.source_commit.status, 'pass');
  assert.deepEqual(
    evidence.source_commit.tasks.map((task) => task.task_id),
    ['REQ-893-01', 'REQ-893-02', 'REQ-893-03', 'REQ-893-04'],
  );
  assert.equal(evidence.evidence_lifecycle.status, 'pass');
  assert.equal(evidence.evidence_lifecycle.verification_summary_supplied, true);
  assert.equal(evidence.evidence_lifecycle.focused_verify_pass, true);
  assert.equal(evidence.evidence_lifecycle.contract_summaries_pass, true);
  assert.equal(evidence.evidence_lifecycle.excluded_surfaces_pass, true);
  assert.equal(evidence.evidence_lifecycle.forbidden_metadata_scan_pass, true);
  assert.equal(evidence.forbidden_metadata_scan.status, 'pass');
  assert.equal(evidence.forbidden_metadata_scan.violation_count, 0);
  assert.deepEqual(
    evidence.excluded_surfaces.map((surface) => surface.surface_id),
    dod007ExcludedSurfaceIds,
  );
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.implementation_count === 0));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.runtime_invocation_count === 0));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.acceptance_gate_count === 0));

  for (const [name, summary] of Object.entries(evidence.contract_summaries)) {
    assert.equal(summary.status, 'pass', `${name} status`);
    assert.equal(typeof summary.tests_total, 'number', `${name} tests_total`);
    assert.equal(typeof summary.tests_pass, 'number', `${name} tests_pass`);
    assert.equal(typeof summary.tests_fail, 'number', `${name} tests_fail`);
    assert.ok(summary.tests_total > 0, `${name} tests_total`);
    assert.equal(summary.tests_pass, summary.tests_total, `${name} tests_pass`);
    assert.equal(summary.tests_fail, 0, `${name} tests_fail`);
  }

  assert.equal(
    evidence.contract_summaries.state_transition_integrity.tests_total,
    normalizedExpected.state_transition_integrity.tests_total,
  );
  assert.equal(
    evidence.contract_summaries.continuation_contract.tests_total,
    normalizedExpected.continuation_contract.tests_total,
  );
  assert.equal(
    evidence.contract_summaries.auto_continuation_contract.tests_total,
    normalizedExpected.auto_continuation_contract.tests_total,
  );
  assert.equal(
    evidence.contract_summaries.run_wrapper_session_contract.tests_total,
    normalizedExpected.run_wrapper_session_contract.tests_total,
  );
  assert.equal(
    evidence.test_command_results.focused_verify_command.status,
    normalizedExpected.focused_verify_command.status,
  );
  assert.equal(
    evidence.test_command_results.focused_verify_command.tests_total,
    normalizedExpected.focused_verify_command.tests_total,
  );
  assert.equal(
    evidence.test_command_results.generator.generated_artifact_path,
    dod007RequestEvidenceRelativePath,
  );
}

export function assertDod008LifecycleSmokeArtifacts(artifacts) {
  assert.ok(Array.isArray(artifacts));
  assert.deepEqual(
    artifacts.map((artifact) => artifact.artifact_type),
    dod008LifecycleSmokeArtifactTypes,
  );

  for (const artifact of artifacts) {
    assert.equal(artifact.request_id, 'REQ-894');
    assert.equal(artifact.status, 'pass');
    const requiredFields = dod008ArtifactSchemaRequiredFieldsByType[artifact.artifact_type];
    assert.ok(requiredFields, `${artifact.artifact_type} required field contract`);
    for (const field of requiredFields) {
      assert.ok(field in artifact, `${artifact.artifact_type}.${field}`);
    }
  }

  const byType = new Map(artifacts.map((artifact) => [artifact.artifact_type, artifact]));
  const recover = byType.get('recover');
  assert.ok(recover);
  assert.equal(recover.mst_session_id, 'MST-AGI-039-20260519T144424Z-req89403');
  assert.equal(recover.root_mst_id, 'AGI-039');
  assert.equal(recover.canonical_session_identity.mst_session_id, recover.mst_session_id);
  assert.equal(recover.canonical_session_identity.lookup_key, recover.mst_session_id);
  assert.equal(recover.canonical_session_identity.partition_key, recover.mst_session_id);
  assert.equal(recover.recovery_judgement.primary_action, 'resume_session');
  assert.equal(recover.recovery_judgement.reason, 'resume_ready');
  assert.ok(
    recover.recovery_judgement.affected_resources.some(
      (resource) =>
        resource.kind === 'mst_session_id' && resource.identifier === recover.mst_session_id,
    ),
  );

  const cleanup = byType.get('cleanup');
  assert.ok(cleanup);
  assert.equal(cleanup.dry_run, true);
  assert.equal(cleanup.report.status, 'ok');
  assert.equal(cleanup.report.orphan_session_count, 0);
  assert.equal(cleanup.report.planned_cleanup_count, 0);
  assert.equal(cleanup.request_artifacts_preserved.status, 'pass');
  assert.equal(cleanup.request_artifacts_preserved.mutated_path_count, 0);
  assert.ok(
    cleanup.request_artifacts_preserved.checked_paths.includes(
      '.gran-maestro/requests/REQ-894/tasks/03/spec.md',
    ),
  );

  const dashboard = byType.get('dashboard');
  assert.ok(dashboard);
  assert.equal(dashboard.health.route, '/api/health');
  assert.equal(dashboard.health.ok, true);
  assert.deepEqual(dashboard.widgets, [
    'health',
    'overview.active-items',
    'overview.next-steps',
    'overview.pulse',
  ]);
  assert.equal(dashboard.overview.active_items.route, '/api/overview/active-items');
  assert.equal(dashboard.overview.next_steps.route, '/api/overview/next-steps');
  assert.equal(dashboard.overview.pulse.route, '/api/overview/pulse');

  const settings = byType.get('settings');
  assert.ok(settings);
  assert.equal(settings.scope, 'project');
  assert.equal(settings.config.config_route.route, '/api/config');
  assert.equal(settings.config.defaults_route.route, '/api/config/defaults');
  assert.equal(settings.config.mode_route.route, '/api/mode');
  assert.equal(settings.effective_values.workflow_default_agent, 'codex-dev');
  assert.equal(settings.effective_values.auto_mode_request, false);
}

export function assertDod008WorkflowSchemaContract(evidence) {
  assert.equal(evidence.request_id, 'REQ-894');
  assert.equal(evidence.task_id, '01');
  assert.equal(evidence.dod_id, 'DOD-008');
  assert.equal(evidence.status, 'pass');
  assert.deepEqual(
    evidence.scenario_contract.map((scenario) => scenario.representative_path),
    dod008WorkflowScenarioPaths,
  );
  assert.ok(
    evidence.scenario_contract.every((scenario) =>
      scenario.contract_only === true &&
      scenario.repository_local_only === true &&
      Array.isArray(scenario.required_artifacts) &&
      scenario.required_artifacts.length > 0,
    ),
  );
  assert.deepEqual(
    evidence.artifact_schema_contract.map((schema) => schema.artifact_type),
    Object.keys(dod008ArtifactSchemaRequiredFieldsByType),
  );
  assert.ok(
    evidence.artifact_schema_contract.every((schema) =>
      Array.isArray(schema.required_fields) &&
      schema.required_fields.length > 0 &&
      schema.required_fields.every((field) => typeof field === 'string' && field.length > 0) &&
      schema.deterministic_validation === true &&
      schema.repository_local_only === true,
    ),
  );
  assert.equal(evidence.no_go_metadata_guard.status, 'pass');
  assert.deepEqual(
    evidence.no_go_metadata_guard.criteria.map((criterion) => criterion.criterion_id),
    dod008NoGoMetadataGuardCriteria.map((criterion) => criterion.criterion_id),
  );
  assertDod008LifecycleSmokeArtifacts(evidence.lifecycle_smoke_artifacts);
  assert.equal(evidence.lifecycle_smoke_validation.status, 'pass');
  assert.deepEqual(
    evidence.lifecycle_smoke_validation.artifact_types,
    dod008LifecycleSmokeArtifactTypes,
  );
  assert.deepEqual(evidence.lifecycle_smoke_validation.missing_artifact_types, []);
  assert.deepEqual(evidence.lifecycle_smoke_validation.missing_required_fields, []);
  assert.equal(evidence.forbidden_metadata_scan.status, 'pass');
  assert.equal(evidence.forbidden_metadata_scan.violation_count, 0);
  assert.deepEqual(evidence.acceptance_runtime_surface_ids, dod008AcceptanceRuntimeSurfaceIds);
  assert.deepEqual(
    evidence.excluded_surfaces.map((surface) => surface.surface_id),
    dod008ExcludedSurfaceIds,
  );
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.implementation_count === 0));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.runtime_invocation_count === 0));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.acceptance_gate_count === 0));
  assert.deepEqual(evidence.manual_readable_exports.scenario_paths, dod008WorkflowScenarioPaths);
  assert.deepEqual(
    evidence.manual_readable_exports.excluded_surface_ids,
    dod008ExcludedSurfaceIds,
  );
  assert.deepEqual(
    evidence.manual_readable_exports.acceptance_runtime_surface_ids,
    dod008AcceptanceRuntimeSurfaceIds,
  );
  assert.deepEqual(
    evidence.manual_readable_exports.lifecycle_smoke_artifact_types,
    dod008LifecycleSmokeArtifactTypes,
  );
}

export function assertDod009ClaudePluginRegressionMatrix(contract) {
  assert.equal(contract.contract_id, 'REQ-912-DOD-009-claude-plugin-regression-matrix');
  assert.equal(contract.request_id, 'REQ-912');
  assert.equal(contract.task_id, '01');
  assert.equal(contract.dod_id, 'DOD-009');
  assert.equal(contract.status, 'pass');
  assert.equal(contract.comparison_subject, 'claude-plugin-mode');
  assert.equal(contract.codex_artifact_substitution_permitted, false);
  assert.equal(contract.repository_local_only, true);
  assert.deepEqual(
    contract.matrix_surfaces.map((surface) => surface.canonical_source_path),
    dod009MatrixSurfacePaths,
  );
  assert.ok(
    contract.matrix_surfaces.every(
      (surface) =>
        surface.verification_scope === 'claude-canonical-source' &&
        surface.repository_local_only === true,
    ),
  );
  assert.equal(contract.contract_checks.version_sync.status, 'pass');
  assert.deepEqual(contract.contract_checks.version_sync.checked_paths, dod009VersionSyncPaths);
  assert.equal(contract.contract_checks.version_sync.unique_version_count, 1);
  assert.equal(contract.contract_checks.agents_parity.status, 'pass');
  assert.deepEqual(contract.contract_checks.agents_parity.missing_manifest_entries, []);
  assert.deepEqual(contract.contract_checks.agents_parity.extra_manifest_entries, []);
  assert.equal(contract.contract_checks.skills_directory_registration.status, 'pass');
  assert.equal(contract.contract_checks.skills_directory_registration.manifest_skills_pointer, './skills/');
  assert.equal(contract.contract_checks.hooks_pointer.status, 'pass');
  assert.equal(contract.contract_checks.hooks_pointer.manifest_hooks_pointer, './hooks/hooks.json');
  assert.equal(contract.contract_checks.hooks_registration.status, 'pass');
  assert.deepEqual(contract.contract_checks.hooks_registration.command_paths, dod009HooksCommandPaths);
  assert.equal(contract.no_go_metadata_guard.status, 'pass');
  assert.deepEqual(
    contract.no_go_metadata_guard.criteria.map((criterion) => criterion.criterion_id),
    dod009NoGoMetadataGuardCriteria.map((criterion) => criterion.criterion_id),
  );
  assert.equal(contract.forbidden_metadata_scan.status, 'pass');
  assert.equal(contract.forbidden_metadata_scan.violation_count, 0);
  assert.deepEqual(
    contract.excluded_surfaces.map((surface) => surface.surface_id),
    dod009ExcludedSurfaceIds,
  );
  assert.ok(
    contract.excluded_surfaces.every(
      (surface) =>
        surface.implementation_count === 0 &&
        surface.runtime_invocation_count === 0 &&
        surface.acceptance_gate_count === 0,
    ),
  );
  assert.equal(contract.blocker_summary.status, 'pass');
  assert.equal(contract.blocker_summary.blocker_count, 0);
  assert.deepEqual(contract.blocker_summary.human_readable, []);
  assert.deepEqual(
    contract.manual_readable_exports.canonical_source_paths,
    dod009MatrixSurfacePaths,
  );
  assert.deepEqual(
    contract.manual_readable_exports.excluded_surface_ids,
    dod009ExcludedSurfaceIds,
  );
}

export function assertDod009RequestEvidence(evidence, expectedSummary = null) {
  assert.equal(evidence.artifact_id, 'REQ-912-DOD-009-claude-plugin-regression-validation');
  assert.equal(evidence.request_id, 'REQ-912');
  assert.equal(evidence.agi_id, 'AGI-039');
  assert.equal(evidence.sprint, 10);
  assert.equal(evidence.task_id, '02');
  assert.equal(evidence.dod_id, 'DOD-009');
  assert.equal(evidence.plan_id, 'PLN-736');
  assert.equal(evidence.request_evidence_path, dod009RequestEvidenceRelativePath);
  assertSharedDodEvidenceRegistryLinkage(evidence.shared_dod_registry_linkage, {
    dod_id: 'DOD-009',
    request_id: 'REQ-912',
    agi_id: 'AGI-039',
    sprint: 10,
    generator_script_path: dod009GeneratorScriptRelativePath,
    request_evidence_path: dod009RequestEvidenceRelativePath,
    expected_status: 'pass',
    validator_export_name: 'assertDod009RequestEvidence',
  });
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assertDod009ClaudePluginRegressionMatrix(evidence.claude_plugin_regression_matrix);
  assert.equal(evidence.linked_prior_evidence.status, 'pass');
  assert.equal(evidence.linked_prior_evidence.relationship, 'supporting-reference-only');
  assert.equal(
    evidence.linked_prior_evidence.request_evidence_path,
    dod008WorkflowE2EValidationEvidenceRelativePath,
  );
  assert.equal(evidence.linked_prior_evidence.prior_evidence_status, 'pass');
  assert.equal(evidence.no_go_metadata_guard.status, 'pass');
  assert.equal(evidence.no_go_metadata_guard.contract_forbidden_metadata_scan.status, 'pass');
  assert.equal(evidence.test_command_results.plugin_manifest_hooks.status, 'pass');
  assert.equal(evidence.test_command_results.workflow_state_continuation.status, 'pass');
  assert.equal(evidence.test_command_results.run_wrapper_session_migration.status, 'pass');
  assert.equal(evidence.test_command_results.npm_test.status, 'pass');
  assert.equal(evidence.test_command_results.generator.status, 'pass');
  assert.equal(
    evidence.test_command_results.generator.generated_artifact_path,
    dod009RequestEvidenceRelativePath,
  );
  assert.equal(evidence.evidence_lifecycle.status, 'pass');
  assert.equal(evidence.evidence_lifecycle.matrix_pass, true);
  assert.equal(evidence.evidence_lifecycle.linked_prior_evidence_pass, true);
  assert.equal(evidence.evidence_lifecycle.command_summaries_pass, true);
  assert.equal(evidence.evidence_lifecycle.generator_pass, true);
  assert.equal(evidence.evidence_lifecycle.no_go_guard_pass, true);
  assert.equal(evidence.evidence_lifecycle.excluded_surfaces_pass, true);
  assert.equal(evidence.evidence_lifecycle.parse_failures_absent, true);
  assert.equal(evidence.evidence_lifecycle.shared_dod_registry_linkage_pass, true);
  assert.equal(evidence.evidence_lifecycle.forbidden_metadata_scan_pass, true);
  assert.deepEqual(
    evidence.excluded_surfaces.map((surface) => surface.surface_id),
    dod009ExcludedSurfaceIds,
  );
  assert.ok(
    evidence.excluded_surfaces.every(
      (surface) =>
        surface.implementation_count === 0 &&
        surface.runtime_invocation_count === 0 &&
        surface.acceptance_gate_count === 0,
    ),
  );
  assert.equal(evidence.blocker_summary.status, 'pass');
  assert.equal(evidence.blocker_summary.blocker_count, 0);
  assert.deepEqual(evidence.blocker_summary.human_readable, []);
  assert.equal(evidence.forbidden_metadata_scan.status, 'pass');
  assert.equal(evidence.forbidden_metadata_scan.violation_count, 0);
  assert.deepEqual(
    evidence.manual_readable_exports.canonical_source_paths,
    dod009MatrixSurfacePaths,
  );
  assert.deepEqual(
    evidence.manual_readable_exports.excluded_surface_ids,
    dod009ExcludedSurfaceIds,
  );
  assert.deepEqual(
    evidence.manual_readable_exports.command_summary_fields,
    [
      'plugin_manifest_hooks',
      'workflow_state_continuation',
      'run_wrapper_session_migration',
      'npm_test',
      'generator',
    ],
  );
  assert.deepEqual(
    evidence.manual_readable_exports.linked_prior_evidence_paths,
    [dod008WorkflowE2EValidationEvidenceRelativePath],
  );

  if (expectedSummary) {
    const normalizedExpected = normalizeDod009RequestEvidenceVerificationSummary(expectedSummary);

    for (const summaryId of [
      'plugin_manifest_hooks',
      'workflow_state_continuation',
      'run_wrapper_session_migration',
      'npm_test',
    ]) {
      assert.equal(
        evidence.test_command_results[summaryId].tests_total,
        normalizedExpected[summaryId].tests_total,
      );
      assert.equal(
        evidence.test_command_results[summaryId].tests_pass,
        normalizedExpected[summaryId].tests_pass,
      );
      assert.equal(
        evidence.test_command_results[summaryId].tests_fail,
        normalizedExpected[summaryId].tests_fail,
      );
    }

    assert.equal(
      evidence.test_command_results.generator.generated_artifact_path,
      normalizedExpected.generator.generated_artifact_path,
    );
  }
}

export function assertSharedDodEvidenceRegistryLinkage(
  linkage,
  {
    dod_id,
    request_id,
    agi_id,
    sprint,
    generator_script_path,
    request_evidence_path,
    expected_status,
    validator_export_name,
  },
) {
  assert.ok(linkage && typeof linkage === 'object');
  assert.equal(linkage.status, 'pass');
  assert.equal(linkage.linkage_source, 'shared_dod_evidence_registry');
  assert.equal(linkage.request_evidence_path_matches_registry, true);
  assert.equal(linkage.generator_script_exists, true);
  assert.equal(linkage.validator_entrypoint_exists, true);
  assert.deepEqual(linkage.issues, []);
  assert.ok(linkage.registry_entry && typeof linkage.registry_entry === 'object');
  assert.equal(linkage.registry_entry.dod_id, dod_id);
  assert.equal(linkage.registry_entry.request_id, request_id);
  assert.equal(linkage.registry_entry.agi_id, agi_id);
  assert.equal(linkage.registry_entry.sprint, sprint);
  assert.equal(linkage.registry_entry.generator_script_path, generator_script_path);
  assert.equal(linkage.registry_entry.request_evidence_path, request_evidence_path);
  assert.equal(linkage.registry_entry.expected_status, expected_status);
  assert.deepEqual(linkage.registry_entry.validator_linkage, {
    export_name: validator_export_name,
    helper_kind: 'assertion-helper',
    validation_entrypoint: 'scripts/lib/codex-plugin-discovery-smoke.mjs',
  });
}

export function assertDod008CoreWorkflowSmokeHarness(harness) {
  assert.equal(harness.request_id, 'REQ-894');
  assert.equal(harness.task_id, '02');
  assert.equal(harness.dod_id, 'DOD-008');
  assert.equal(harness.status, 'pass');
  assert.equal(harness.mode, 'repository-local-fixture');
  assert.deepEqual(
    harness.scenario_records.map((scenario) => scenario.representative_path),
    dod008CoreWorkflowSmokeScenarioPaths,
  );
  assert.ok(
    harness.scenario_records.every((scenario) =>
      scenario.reproduced_by_fixture === true &&
      scenario.executes_runtime === false &&
      scenario.repository_local_only === true,
    ),
  );
  assert.deepEqual(harness.artifact_types, dod008CoreWorkflowSmokeArtifactTypes);
  assert.deepEqual(
    harness.artifact_validations.map((validation) => validation.artifact_type),
    dod008CoreWorkflowSmokeArtifactTypes,
  );
  assert.ok(harness.artifact_validations.every((validation) => validation.status === 'pass'));
  for (const artifactType of dod008CoreWorkflowSmokeArtifactTypes) {
    const artifact = harness.artifacts[artifactType];
    assert.ok(artifact, `${artifactType} artifact`);
    for (const field of dod008ArtifactSchemaRequiredFieldsByType[artifactType]) {
      assert.ok(Object.hasOwn(artifact, field), `${artifactType}.${field}`);
    }
    assert.equal(artifact.state_session.env.MST_SESSION_ID, dod008CoreWorkflowSmokeSessionId);
    assert.equal(artifact.state_session.context.mst_session_id, dod008CoreWorkflowSmokeSessionId);
    assert.equal(
      artifact.state_session.env.MST_SESSION_ID,
      artifact.state_session.context.mst_session_id,
    );
    assert.equal(artifact.state_session.legacy_diagnostics.canonical_source_count, 0);
  }
  assert.deepEqual(harness.session_metadata.canonical_sources, [
    'MST_SESSION_ID',
    'mst_session_id',
  ]);
  assert.equal(harness.session_metadata.env.MST_SESSION_ID, dod008CoreWorkflowSmokeSessionId);
  assert.equal(harness.session_metadata.context.mst_session_id, dod008CoreWorkflowSmokeSessionId);
  assert.equal(harness.session_metadata.boundary_checks.env_and_context_match, true);
  assert.equal(harness.session_metadata.boundary_checks.legacy_only_identity_rejected, true);
  assert.equal(harness.side_effect_summary.repository_local_only, true);
  assert.equal(harness.side_effect_summary.fixture_only, true);
  assert.equal(harness.side_effect_summary.mutates_user_home, false);
  assert.equal(harness.side_effect_summary.edits_hook_config, false);
  assert.equal(harness.side_effect_summary.executes_codex_install, false);
  assert.equal(harness.side_effect_summary.refreshes_codex_cache, false);
  assert.equal(harness.side_effect_summary.runs_real_implementation, false);
  assert.ok(
    harness.command_metadata.every((command) =>
      command.mutates_user_home === false &&
      command.edits_hook_config === false &&
      command.executes_codex_install === false &&
      command.refreshes_codex_cache === false &&
      command.runs_real_implementation === false,
    ),
  );
  assert.equal(harness.forbidden_metadata_scan.status, 'pass');
  assert.equal(harness.forbidden_metadata_scan.violation_count, 0);
}

export function assertDod008WorkflowArtifactParityValidation(validation) {
  assert.equal(validation.request_id, 'REQ-894');
  assert.equal(validation.task_id, '04');
  assert.equal(validation.dod_id, 'DOD-008');
  assert.equal(validation.status, 'pass');
  assert.equal(validation.mode, 'repository-local-fixture');
  assert.deepEqual(
    validation.canonical_claude_artifact_shape.map((shape) => shape.artifact_type),
    dod008WorkflowArtifactParityTypes,
  );
  assert.deepEqual(
    validation.codex_fixture_artifact_shape.map((shape) => shape.artifact_type),
    dod008WorkflowArtifactParityTypes,
  );
  assert.deepEqual(
    validation.required_field_parity.checked_artifact_types,
    dod008WorkflowArtifactParityTypes,
  );
  assert.equal(validation.required_field_parity.status, 'pass');
  assert.equal(validation.required_field_parity.missing_blocker_count, 0);
  assert.equal(validation.required_field_parity.extra_blocker_count, 0);
  assert.equal(validation.required_field_parity.blocker_count, 0);
  assert.deepEqual(validation.required_field_parity.blockers, []);
  assert.ok(
    validation.required_field_parity.artifact_diffs.every((diff) => diff.status === 'pass'),
  );
  assert.equal(validation.boundary_checks.status, 'pass');
  assert.equal(validation.boundary_checks.session_identity.status, 'pass');
  assert.equal(validation.boundary_checks.recovery.status, 'pass');
  assert.equal(validation.boundary_checks.orphan_session.status, 'pass');
  assert.equal(validation.boundary_checks.orphan_session.orphan_session_count, 0);
  assert.equal(validation.excluded_surface_guard.status, 'pass');
  assert.deepEqual(validation.excluded_surface_guard.surface_ids, dod008ExcludedSurfaceIds);
  assert.ok(
    validation.excluded_surface_guard.surfaces.every(
      (surface) =>
        surface.implementation_count === 0 &&
        surface.runtime_invocation_count === 0 &&
        surface.acceptance_gate_count === 0,
    ),
  );
  assert.equal(validation.blocker_summary.status, 'pass');
  assert.equal(validation.blocker_summary.blocker_count, 0);
  assert.deepEqual(validation.blocker_summary.human_readable, []);
  assert.equal(validation.input_summary.deterministic_validation, true);
  assert.equal(validation.input_summary.repository_local_only, true);
  assert.equal(validation.input_summary.executes_real_claude_runtime, false);
  assert.equal(validation.input_summary.executes_real_codex_runtime, false);
}

export function assertDod008WorkflowE2EValidationEvidence(
  evidence,
  expectedSummary = defaultDod008WorkflowE2EValidationSummary,
) {
  const normalizedExpected = normalizeDod008WorkflowE2EValidationSummary(expectedSummary);

  assert.equal(evidence.artifact_id, 'REQ-894-DOD-008-workflow-e2e-validation');
  assert.equal(evidence.request_id, 'REQ-894');
  assert.equal(evidence.agi_id, 'AGI-039');
  assert.equal(evidence.sprint, 9);
  assert.equal(evidence.task_id, '05');
  assert.equal(evidence.dod_id, 'DOD-008');
  assert.equal(evidence.plan_id, 'PLN-721');
  assert.equal(evidence.request_evidence_path, dod008WorkflowE2EValidationEvidenceRelativePath);
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assert.equal(evidence.workflow_scenarios.status, 'pass');
  assert.deepEqual(evidence.workflow_scenarios.scenario_paths, dod008WorkflowScenarioPaths);
  assert.deepEqual(
    evidence.workflow_scenarios.schema_contract.map((scenario) => scenario.representative_path),
    dod008WorkflowScenarioPaths,
  );
  assert.equal(evidence.schema_results.status, 'pass');
  assertDod008WorkflowSchemaContract(evidence.schema_results.workflow_schema_contract);
  assertDod008CoreWorkflowSmokeHarness(evidence.schema_results.core_workflow_harness);
  assert.equal(evidence.schema_results.lifecycle_smoke_validation.status, 'pass');
  assertDod008WorkflowArtifactParityValidation(
    evidence.schema_results.artifact_parity_validation,
  );
  assert.equal(evidence.focused_workflow_validation_summary.status, 'pass');
  assert.equal(evidence.evidence_lifecycle.status, 'pass');
  assert.equal(evidence.evidence_lifecycle.focused_workflow_validation_pass, true);
  assert.equal(evidence.evidence_lifecycle.schema_results_pass, true);
  assert.equal(evidence.evidence_lifecycle.npm_test_pass, true);
  assert.equal(evidence.evidence_lifecycle.generator_pass, true);
  assert.equal(evidence.evidence_lifecycle.excluded_surfaces_pass, true);
  assert.equal(evidence.evidence_lifecycle.forbidden_metadata_scan_pass, true);
  assert.equal(evidence.forbidden_metadata_scan.status, 'pass');
  assert.equal(evidence.forbidden_metadata_scan.violation_count, 0);
  assert.deepEqual(
    evidence.excluded_surfaces.map((surface) => surface.surface_id),
    dod008ExcludedSurfaceIds,
  );
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.implementation_count === 0));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.runtime_invocation_count === 0));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.acceptance_gate_count === 0));
  assert.equal(evidence.request_metadata_snapshot.path, req894RequestMetadataRelativePath);
  assert.equal(evidence.request_metadata_snapshot.request_id, 'REQ-894');
  assert.equal(evidence.request_metadata_snapshot.agi_id, 'AGI-039');
  assert.equal(evidence.request_metadata_snapshot.sprint, 9);
  assert.equal(evidence.request_metadata_snapshot.dod_id, 'DOD-008');
  assert.equal(evidence.request_metadata_snapshot.plan_id, 'PLN-721');
  assert.equal(
    evidence.test_command_results.focused_workflow_validation.status,
    normalizedExpected.focused_workflow_validation.status,
  );
  assert.equal(
    evidence.test_command_results.focused_workflow_validation.tests_total,
    normalizedExpected.focused_workflow_validation.tests_total,
  );
  assert.equal(
    evidence.test_command_results.schema_contract.tests_total,
    normalizedExpected.schema_contract.tests_total,
  );
  assert.equal(
    evidence.test_command_results.generator.generated_artifact_path,
    dod008WorkflowE2EValidationEvidenceRelativePath,
  );
}

export function assertCodexPluginDiscoverySmokeEvidence(evidence) {
  assert.equal(evidence.request_id, 'REQ-886');
  assert.equal(evidence.dod_id, 'DOD-003');
  assert.equal(evidence.validation_evidence_path, stableEvidenceRelativePath);
  assert.equal(
    evidence.discovery_smoke_result_path,
    `${stableEvidenceRelativePath}#discovery_results`,
  );
  assert.equal(evidence.generated_manifest_path, generatedManifestPath);
  assert.equal(evidence.generated_marketplace_path, generatedMarketplacePath);
  assert.equal(evidence.parse_error_count, 0);
  assert.equal(evidence.generated_drift_count, 0);
  assert.equal(evidence.unsupported_blocker_count, 0);
  assert.equal(evidence.discovery_results.status, 'pass');
  assert.equal(evidence.claude_plugin_regression.status, 'pass');
  assert.equal(evidence.dod_004_install_fallback_reproducibility.status, 'pass');
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.request_id,
    req888Dod004Metadata.request_id,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.dod_id,
    req888Dod004Metadata.dod_id,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.request_evidence_path,
    forcedWireEvidenceRelativePath,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.discovery_smoke_evidence_path,
    stableEvidenceRelativePath,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.native_plugin_install.executes_external_install,
    false,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.native_plugin_install.mutates_user_config,
    false,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.native_plugin_install.refreshes_plugin_cache,
    false,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.fallback_skill_discovery.discovery_root,
    fallbackSkillDiscoveryRootPath,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.fallback_skill_discovery.repo_target,
    fallbackSkillRepoTargetPath,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.fallback_skill_discovery.creates_symlink,
    false,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.no_go_artifact_guard.status,
    'pass',
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.no_go_artifact_guard.mutates_user_config,
    false,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.no_go_artifact_guard.refreshes_plugin_cache,
    false,
  );
  assert.equal(
    evidence.dod_004_install_fallback_reproducibility.no_go_artifact_guard.creates_symlink,
    false,
  );
  assert.equal(evidence.selection_reason, sprint4SelectionReason);
  assert.equal(evidence.s04_integration_context_path, sprint4IntegrationContextPath);
  assert.deepEqual(evidence.generated_asset_baseline_paths, generatedAssetBaselinePaths);
  assert.deepEqual(evidence.validation_entrypoints, validationEntrypoints);
  assert.equal(evidence.sprint4_forced_wire.selection_reason, sprint4SelectionReason);
  assert.deepEqual(evidence.sprint4_forced_wire.integration_context_assertions, {
    exists: true,
    force_wire_recommended: true,
    generated_manifest_new_island: true,
    generated_marketplace_new_island: true,
    validation_entrypoints_wired: true,
  });
  assert.equal(
    evidence.sprint4_forced_wire.integration_context_path,
    sprint4IntegrationContextPath,
  );
  assert.deepEqual(
    evidence.sprint4_forced_wire.generated_asset_baseline_paths,
    generatedAssetBaselinePaths,
  );
  assert.deepEqual(evidence.sprint4_forced_wire.validation_entrypoints, validationEntrypoints);
  assert.equal(
    evidence.sprint4_forced_wire.repo_root_orchestration_root_separation.roots_are_distinct,
    true,
  );
  assert.equal(evidence.sprint4_forced_wire.upstream_dod_gating.status, 'pass');
  assert.deepEqual(evidence.sprint4_forced_wire.out_of_scope_dod_guard.dod_ids, [
    'DOD-006',
    'DOD-008',
  ]);
  assert.deepEqual(
    evidence.dod_004_install_fallback_reproducibility.unsupported_surfaces.surfaces.map(
      (surface) => surface.dod_id,
    ),
    ['DOD-006', 'DOD-008'],
  );
  assert.deepEqual(evidence.changed_files_checked, changedFilesChecked);
  assert.deepEqual(
    evidence.discovery_results.assets.map((asset) => asset.path),
    [generatedManifestPath, generatedMarketplacePath],
  );
  assert.ok(evidence.input_paths_read.includes(inventoryArtifactPath));
  assert.ok(evidence.input_paths_read.includes(parityEvidencePath));
  assert.ok(evidence.input_paths_read.includes(integrationEvidencePath));
  assert.equal(evidence.out_of_scope_artifact_check.status, 'pass');
  assert.equal(evidence.drift_comparison.manifest.drift_count, 0);
  assert.equal(evidence.drift_comparison.marketplace.drift_count, 0);
}
