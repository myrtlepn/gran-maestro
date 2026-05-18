import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '..', '..');

function findProjectRoot(startDir) {
  let currentDir = startDir;

  while (true) {
    if (
      existsSync(join(currentDir, '.gran-maestro')) &&
      existsSync(join(currentDir, 'package.json'))
    ) {
      return currentDir;
    }

    const parentDir = dirname(currentDir);
    if (parentDir === currentDir) {
      throw new Error(`Could not locate project root for ${startDir}`);
    }

    currentDir = parentDir;
  }
}

export const projectRoot = findProjectRoot(repoRoot);
export const orchestrationRoot = join(projectRoot, '.gran-maestro');

export const stableEvidenceRelativePath =
  '.gran-maestro/requests/REQ-886/evidence/codex-plugin-discovery-smoke.json';
export const stableEvidenceAbsolutePath = join(projectRoot, stableEvidenceRelativePath);

export const generatedManifestPath = '.codex-plugin/plugin.json';
export const generatedMarketplacePath = '.agents/plugins/marketplace.json';
export const sourceManifestPath = '.claude-plugin/plugin.json';
export const sourceMarketplacePath = '.claude-plugin/marketplace.json';
export const sourceHookConfigPath = 'hooks/hooks.json';

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
      '.gran-maestro/requests/REQ-886/evidence/codex-workflow-e2e-parity.json',
    ],
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

function buildOutOfScopeArtifactCheck() {
  const checks = outOfScopeArtifactCandidates.map((check) => {
    const assets = check.assets.map((path) => ({
      path,
      exists: existsSync(join(projectRoot, path)),
    }));

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

  const unsupportedBlockers = [];

  if ((inventoryArtifact.value?.coverage?.missing_component_count ?? 0) !== 0) {
    unsupportedBlockers.push('DOD-001 inventory coverage is incomplete.');
  }

  if ((parityEvidence.value?.unsupported_blocker_count ?? 0) !== 0) {
    unsupportedBlockers.push('DOD-002 parity evidence reported unsupported blockers.');
  }

  if ((integrationEvidence.value?.parity_evidence_counts?.unsupported_blocker_count ?? 0) !== 0) {
    unsupportedBlockers.push('DOD-002 integration evidence reported unsupported blockers.');
  }

  if (outOfScopeArtifactCheck.status !== 'pass') {
    unsupportedBlockers.push('Out-of-scope DOD artifacts were detected.');
  }

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
    input_paths_read: [
      inventoryArtifactPath,
      inventoryValidationPath,
      parityEvidencePath,
      integrationEvidencePath,
      sourceManifestPath,
      sourceMarketplacePath,
      sourceHookConfigPath,
      generatedManifestPath,
      generatedMarketplacePath,
    ],
    generated_manifest_path: generatedManifestPath,
    generated_marketplace_path: generatedMarketplacePath,
    parse_error_count: parseFailures.length,
    generated_drift_count: manifestComparison.drift_count + marketplaceComparison.drift_count,
    unsupported_blocker_count: unsupportedBlockers.length,
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
