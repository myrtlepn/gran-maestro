import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
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
    dod_id: 'DOD-005',
    description: 'Codex hook wrapper artifacts remain out of scope for DOD-003.',
    assets: [
      'hooks/hooks.codex.json',
      '.codex-plugin/hooks.json',
      '.codex-plugin/hooks/',
      'hooks/codex-plugin-wrapper.sh',
      'scripts/generate-codex-hook-wrapper.mjs',
    ],
  },
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
    category: 'hook_wrapper',
    description: 'Codex hook wrapper artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: 'hooks/hooks.codex.json',
  },
  {
    category: 'hook_wrapper',
    description: 'Codex hook wrapper artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: '.codex-plugin/hooks.json',
  },
  {
    category: 'hook_wrapper',
    description: 'Codex hook wrapper artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: '.codex-plugin/hooks/',
  },
  {
    category: 'hook_wrapper',
    description: 'Codex hook wrapper artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: 'hooks/codex-plugin-wrapper.sh',
  },
  {
    category: 'hook_wrapper',
    description: 'Codex hook wrapper artifacts remain unimplemented for Sprint 5 DOD-004.',
    root: 'repo',
    path: 'scripts/generate-codex-hook-wrapper.mjs',
  },
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
    .filter((check) => ['DOD-005', 'DOD-006', 'DOD-008'].includes(check.dod_id))
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
      'Codex hook wrapper implementation is out of scope for DOD-003.',
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
    'DOD-005',
    'DOD-006',
    'DOD-008',
  ]);
  assert.deepEqual(
    evidence.dod_004_install_fallback_reproducibility.unsupported_surfaces.surfaces.map(
      (surface) => surface.dod_id,
    ),
    ['DOD-005', 'DOD-006', 'DOD-008'],
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
