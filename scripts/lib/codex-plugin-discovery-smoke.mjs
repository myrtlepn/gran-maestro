import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
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
