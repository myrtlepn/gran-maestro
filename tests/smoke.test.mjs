import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  assertCodexSkillAgentProjectionValidationEvidence,
  assertDod008CoreWorkflowSmokeHarness,
  assertDod008LifecycleSmokeArtifacts,
  assertDod008WorkflowArtifactParityValidation,
  assertDod008WorkflowE2EValidationEvidence,
  assertDod008WorkflowSchemaContract,
  assertDod009ClaudePluginRegressionMatrix,
  assertDod007RequestEvidence,
  assertCodexPluginDiscoverySmokeEvidence,
  assertCodexRoleMappingEvidence,
  assertCodexSkillProjectionEvidence,
  buildCodexSkillAgentProjectionValidationEvidence,
  buildDod008CoreWorkflowSmokeHarness,
  buildDod008LifecycleSmokeArtifacts,
  buildDod008LifecycleSmokeValidation,
  buildDod008WorkflowArtifactParityValidation,
  buildDod008WorkflowE2EValidationEvidence,
  buildDod008WorkflowSchemaContract,
  buildDod009ClaudePluginRegressionMatrix,
  scanDod008ScenarioSchemaMetadata,
  scanDod008RequestEvidenceMetadata,
  scanDod009RegressionMatrixMetadata,
  buildDod007RequestEvidence,
  buildCodexPluginDiscoverySmokeEvidence,
  buildCodexRoleMappingEvidence,
  buildCodexSkillProjectionEvidence,
  collectUnsupportedBlockers,
  coreMstSkillNames,
  defaultCodexSkillAgentProjectionValidationSummary,
  defaultDod008WorkflowE2EValidationSummary,
  defaultDod007RequestEvidenceVerificationSummary,
  dod008CoreWorkflowSmokeArtifactTypes,
  dod008CoreWorkflowSmokeScenarioPaths,
  dod008CoreWorkflowSmokeSessionId,
  dod008WorkflowArtifactParityTypes,
  dod008AcceptanceRuntimeSurfaceIds,
  dod008ArtifactSchemaRequiredFieldsByType,
  dod008ExcludedSurfaceIds,
  dod008LifecycleSmokeArtifactTypes,
  dod008NoGoMetadataGuardCriteria,
  dod008WorkflowE2EValidationEvidenceRelativePath,
  dod008WorkflowScenarioPaths,
  dod009ExcludedSurfaceIds,
  dod009MatrixSurfacePaths,
  dod007ExcludedSurfaceIds,
  dod007RequestEvidenceRelativePath,
  req894RequestMetadataRelativePath,
  excludedDodIds as skillProjectionExcludedDodIds,
  fallbackSkillDiscoveryRootPath,
  fallbackSkillRepoTargetPath,
  fallbackSkillSymlinkPath,
  forcedWireEvidenceRelativePath,
  skillProjectionEvidenceRelativePath,
  roleMappingEvidenceRelativePath,
  generatedAssetBaselinePaths,
  generatedManifestPath,
  generatedMarketplacePath,
  integrationEvidencePath,
  inventoryArtifactPath,
  orchestrationRoot,
  parityEvidencePath,
  req888Dod004Metadata,
  req891RequestMetadataRelativePath,
  req893RequestMetadataRelativePath,
  requiredAgentRoleNames,
  repoRoot as smokeRepoRoot,
  skillAgentProjectionValidationEvidenceRelativePath,
  sprint4IntegrationContextPath,
  sprint4SelectionReason,
  stableEvidenceRelativePath,
  userConfigPathLiteral,
  validationEntrypoints,
} from '../scripts/lib/codex-plugin-discovery-smoke.mjs';
import {
  assertCodexHookAdapterParityEvidence,
  assertCodexHookAdapterValidationEvidence,
  buildCodexHookAdapterParityEvidence,
  buildCodexHookAdapterValidationEvidence,
  buildReq890Dod005RequestMetadata,
  canonicalHookScripts,
  defaultCodexHookAdapterValidationSummary,
  excludedDodIds as hookAdapterExcludedDodIds,
  req888BaselineEvidencePath,
  stableEvidenceRelativePath as hookAdapterEvidencePath,
  validationEvidenceRelativePath as hookAdapterValidationEvidencePath,
} from '../scripts/lib/codex-hook-adapter-parity.mjs';

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const req890ValidationSummary = {
  ...defaultCodexHookAdapterValidationSummary,
  parity_generator: {
    ...defaultCodexHookAdapterValidationSummary.parity_generator,
    generated_output_path: '/tmp/req-890-codex-hook-adapter-parity.test.json',
  },
};
const req891ValidationSummary = {
  ...defaultCodexSkillAgentProjectionValidationSummary,
  skill_projection_generator: {
    ...defaultCodexSkillAgentProjectionValidationSummary.skill_projection_generator,
    generated_output_path: '/tmp/req-891-skill-projection.test.json',
  },
  role_mapping_generator: {
    ...defaultCodexSkillAgentProjectionValidationSummary.role_mapping_generator,
    generated_output_path: '/tmp/req-891-role-mapping.test.json',
  },
  npm_test: {
    ...defaultCodexSkillAgentProjectionValidationSummary.npm_test,
    tests_total: 30,
    tests_pass: 30,
    tests_fail: 0,
  },
};
const req893ValidationSummary = {
  ...defaultDod007RequestEvidenceVerificationSummary,
  focused_verify_command: {
    ...defaultDod007RequestEvidenceVerificationSummary.focused_verify_command,
    tests_total: 25,
    tests_pass: 25,
    tests_fail: 0,
    summary: '25 passed in 31.42s',
  },
  state_transition_integrity: {
    ...defaultDod007RequestEvidenceVerificationSummary.state_transition_integrity,
    tests_total: 8,
    tests_pass: 8,
    tests_fail: 0,
    summary: '8 passed in 1.82s',
  },
  continuation_contract: {
    ...defaultDod007RequestEvidenceVerificationSummary.continuation_contract,
    tests_total: 6,
    tests_pass: 6,
    tests_fail: 0,
    summary: '6 passed',
  },
  auto_continuation_contract: {
    ...defaultDod007RequestEvidenceVerificationSummary.auto_continuation_contract,
    tests_total: 7,
    tests_pass: 7,
    tests_fail: 0,
    summary: '7 passed in 20.65s',
  },
  run_wrapper_session_contract: {
    ...defaultDod007RequestEvidenceVerificationSummary.run_wrapper_session_contract,
    tests_total: 10,
    tests_pass: 10,
    tests_fail: 0,
    summary: '10 passed in 9.13s',
  },
  npm_test: {
    ...defaultDod007RequestEvidenceVerificationSummary.npm_test,
    tests_total: 42,
    tests_pass: 42,
    tests_fail: 0,
    summary: '42 passed',
  },
};
const req894ValidationSummary = {
  ...defaultDod008WorkflowE2EValidationSummary,
  focused_workflow_validation: {
    ...defaultDod008WorkflowE2EValidationSummary.focused_workflow_validation,
    tests_total: 16,
    tests_pass: 16,
    tests_fail: 0,
    summary: '16 DOD-008 workflow checks passed in 742ms',
  },
  schema_contract: {
    ...defaultDod008WorkflowE2EValidationSummary.schema_contract,
    tests_total: 5,
    tests_pass: 5,
    tests_fail: 0,
    summary: '5 schema checks passed',
  },
  core_workflow_harness: {
    ...defaultDod008WorkflowE2EValidationSummary.core_workflow_harness,
    tests_total: 3,
    tests_pass: 3,
    tests_fail: 0,
    summary: '3 core workflow checks passed',
  },
  lifecycle_smoke: {
    ...defaultDod008WorkflowE2EValidationSummary.lifecycle_smoke,
    tests_total: 4,
    tests_pass: 4,
    tests_fail: 0,
    summary: '4 lifecycle checks passed',
  },
  artifact_parity: {
    ...defaultDod008WorkflowE2EValidationSummary.artifact_parity,
    tests_total: 4,
    tests_pass: 4,
    tests_fail: 0,
    summary: '4 parity checks passed',
  },
  npm_test: {
    ...defaultDod008WorkflowE2EValidationSummary.npm_test,
    tests_total: 57,
    tests_pass: 57,
    tests_fail: 0,
    summary: '57 passed',
  },
};

function readRepoFile(path) {
  return readFileSync(join(repoRoot, path), 'utf8');
}

function assertMetadataPathIsScoped(path) {
  assert.equal(typeof path, 'string');
  assert.ok(path.length > 0);
  assert.doesNotMatch(path, /^[A-Za-z]:[\\/]/u);
  assert.doesNotMatch(path, /^(?:\/|\\\\)/u);
  assert.doesNotMatch(path, /(^|\/)\.\.(?:\/|$)/u);
  assert.doesNotMatch(path, /\\/u);
  assert.doesNotMatch(path, /^~\//u);
  assert.doesNotMatch(path, /\$HOME|\$\{HOME\}/u);
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

function assertNoForbiddenSkillProjectionEvidenceLiterals(evidence, forbiddenLiterals = []) {
  const stringLeaves = collectStringLeaves(evidence);
  const defaultForbiddenLiterals = [
    repoRoot,
    orchestrationRoot,
    '/tmp/evidence.json',
    '/tmp/',
    '/private/',
    'C:\\\\',
    '~/',
    '$HOME',
    '${HOME}',
    'ln -s',
    'codex plugins install',
    'codex plugins refresh',
    'codex plugins reload',
  ];

  for (const stringValue of stringLeaves) {
    assert.doesNotMatch(stringValue, /(^|[\\/])\.\.(?:[\\/]|$)/u);
    assert.doesNotMatch(stringValue, /%2e%2e/iu);
    assert.doesNotMatch(stringValue, /^~\//u);
    assert.doesNotMatch(stringValue, /\$HOME|\$\{HOME\}/u);
  }

  for (const literal of [...defaultForbiddenLiterals, ...forbiddenLiterals]) {
    assert.ok(
      stringLeaves.every((stringValue) => !stringValue.includes(literal)),
      `Forbidden literal found in skill projection evidence: ${literal}`,
    );
  }
}

function assertNoForbiddenRoleMappingEvidenceLiterals(evidence, forbiddenLiterals = []) {
  assertNoForbiddenSkillProjectionEvidenceLiterals(evidence, [
    '~/.codex/config.toml',
    '~/.agents/skills',
    'danger-full-access',
    'full-access',
    'codex plugins install',
    'codex plugins refresh',
    'codex plugins reload',
    'ln -s',
    'chmod ',
    'chown ',
    'curl ',
    '| bash',
    ...forbiddenLiterals,
  ]);
}

function assertNoForbiddenDod007EvidenceLiterals(evidence, forbiddenLiterals = []) {
  const stringLeaves = collectStringLeaves(evidence);
  const forbiddenDefaults = [
    repoRoot,
    orchestrationRoot,
    '/Users/',
    '/private/',
    '~/',
    '$HOME',
    '${HOME}',
    '~/.codex',
    '~/.agents',
    '.claude/hooks',
    'ln -s',
    'codex plugins install',
    'codex plugins refresh',
    'codex plugins reload',
    'cache refresh',
    ...forbiddenLiterals,
  ];

  for (const stringValue of stringLeaves) {
    assert.doesNotMatch(stringValue, /(^|[\\/])\.\.(?:[\\/]|$)/u);
    assert.doesNotMatch(stringValue, /%2e%2e/iu);
    assert.doesNotMatch(stringValue, /^[A-Za-z]:[\\/]/u);
  }

  for (const literal of forbiddenDefaults) {
    assert.ok(
      stringLeaves.every((stringValue) => !stringValue.includes(literal)),
      `Forbidden literal found in DOD-007 evidence: ${literal}`,
    );
  }
}

function assertNoForbiddenDod008ContractLiterals(contract) {
  const stringLeaves = collectStringLeaves(contract);
  const forbiddenDefaults = [
    '/Users/',
    '~/',
    '$HOME',
    '${HOME}',
    '~/.codex',
    '~/.agents',
    '.claude/hooks',
    'traversal',
    'codex plugins install',
    'codex plugins refresh',
    'codex plugins reload',
    'external install',
    'cache refresh',
    'reload',
    'ln -s',
    'symlink',
  ];

  for (const stringValue of stringLeaves) {
    assert.doesNotMatch(stringValue, /(^|[\\/])\.\.(?:[\\/]|$)/u);
    assert.doesNotMatch(stringValue, /%2e%2e/iu);
    assert.doesNotMatch(stringValue, /^[A-Za-z]:[\\/]/u);
  }

  for (const literal of forbiddenDefaults) {
    assert.ok(
      stringLeaves.every((stringValue) =>
        !stringValue.toLowerCase().includes(literal.toLowerCase()),
      ),
      `Forbidden literal found in DOD-008 contract metadata: ${literal}`,
    );
  }
}

function assertNoForbiddenDod008EvidenceLiterals(evidence, forbiddenLiterals = []) {
  const stringLeaves = collectStringLeaves(evidence);
  const forbiddenDefaults = [
    repoRoot,
    orchestrationRoot,
    '/Users/',
    '/private/',
    '~/',
    '$HOME',
    '${HOME}',
    '~/.codex',
    '~/.agents',
    '.claude/hooks',
    'symlink',
    'install',
    'cache refresh',
    'reload',
    ...forbiddenLiterals,
  ];

  for (const stringValue of stringLeaves) {
    assert.doesNotMatch(stringValue, /(^|[\\/])\.\.(?:[\\/]|$)/u);
    assert.doesNotMatch(stringValue, /%2e%2e/iu);
    assert.doesNotMatch(stringValue, /^[A-Za-z]:[\\/]/u);
  }

  for (const literal of forbiddenDefaults) {
    assert.ok(
      stringLeaves.every((stringValue) =>
        !stringValue.toLowerCase().includes(literal.toLowerCase()),
      ),
      `Forbidden literal found in DOD-008 evidence: ${literal}`,
    );
  }

  assert.deepEqual(scanDod008RequestEvidenceMetadata(evidence), {
    status: 'pass',
    scanned_string_count: scanDod008RequestEvidenceMetadata(evidence).scanned_string_count,
    violation_count: 0,
    violations: [],
  });
}

function assertNoForbiddenDod009ContractLiterals(contract, forbiddenLiterals = []) {
  const stringLeaves = collectStringLeaves(contract);
  const forbiddenDefaults = [
    repoRoot,
    orchestrationRoot,
    '/Users/',
    '/private/',
    '/home/',
    '~/',
    '$HOME',
    '${HOME}',
    '~/.codex',
    '.claude/hooks',
    'codex plugins install',
    'codex plugins refresh',
    'codex plugins reload',
    'cache refresh',
    'external install',
    'ln -s',
    ...forbiddenLiterals,
  ];

  for (const stringValue of stringLeaves) {
    assert.doesNotMatch(stringValue, /(^|[\\/])\.\.(?:[\\/]|$)/u);
    assert.doesNotMatch(stringValue, /%2e%2e/iu);
    assert.doesNotMatch(stringValue, /^[A-Za-z]:[\\/]/u);
  }

  for (const literal of forbiddenDefaults) {
    assert.ok(
      stringLeaves.every((stringValue) =>
        !stringValue.toLowerCase().includes(literal.toLowerCase()),
      ),
      `Forbidden literal found in DOD-009 contract metadata: ${literal}`,
    );
  }
}

test('smoke test runner executes deterministically', () => {
  assert.equal(1 + 1, 2);
});

test('manifest versions remain synchronized across packages', () => {
  const versions = [
    JSON.parse(readRepoFile('package.json')).version,
    JSON.parse(readRepoFile('.claude-plugin/plugin.json')).version,
    JSON.parse(readRepoFile('.claude-plugin/marketplace.json')).plugins[0].version,
    JSON.parse(readRepoFile('extension/manifest.json')).version,
    JSON.parse(readRepoFile('extension/package.json')).version,
  ];

  assert.equal(new Set(versions).size, 1);
});

test('plugin manifest agents exactly match agents markdown files', () => {
  const plugin = JSON.parse(readRepoFile('.claude-plugin/plugin.json'));
  const actualAgents = readdirSync(join(repoRoot, 'agents'))
    .filter((name) => name.endsWith('.md'))
    .map((name) => `./agents/${name}`)
    .sort();

  assert.deepEqual([...plugin.agents].sort(), actualAgents);
});

test('plugin manifest uses canonical hooks registration', () => {
  const plugin = JSON.parse(readRepoFile('.claude-plugin/plugin.json'));
  const hooks = JSON.parse(readRepoFile('hooks/hooks.json'));

  assert.equal(plugin.hooks, './hooks/hooks.json');
  assert.ok(hooks.hooks);

  const commands = Object.values(hooks.hooks).flatMap((entries) =>
    entries.flatMap((entry) => entry.hooks.map((hook) => hook.command)),
  );

  assert.deepEqual(
    [...new Set(commands)].sort(),
    [
      '${CLAUDE_PLUGIN_ROOT}/hooks/mst-auto-chain-context.sh',
      '${CLAUDE_PLUGIN_ROOT}/hooks/mst-pre-tool-use.sh',
      '${CLAUDE_PLUGIN_ROOT}/hooks/mst-session-init.sh',
      '${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh',
    ],
  );
});

test('codex plugin discovery smoke finds generated assets without parse errors', () => {
  const evidence = buildCodexPluginDiscoverySmokeEvidence();

  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.discovery_results.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assert.deepEqual(evidence.discovery_results.assets, [
    {
      path: generatedManifestPath,
      exists: true,
      parse_ok: true,
      error: null,
    },
    {
      path: generatedMarketplacePath,
      exists: true,
      parse_ok: true,
      error: null,
    },
  ]);
});

test('codex plugin discovery smoke records stable evidence metadata and zero drift', () => {
  const evidence = buildCodexPluginDiscoverySmokeEvidence();

  assertCodexPluginDiscoverySmokeEvidence(evidence);
  assert.equal(evidence.root_metadata.repo_root, smokeRepoRoot);
  assert.equal(evidence.root_metadata.repository_asset_root, smokeRepoRoot);
  assert.equal(evidence.root_metadata.orchestration_root, orchestrationRoot);
  assert.equal(evidence.root_metadata.orchestration_evidence_root, orchestrationRoot);
  assert.ok(orchestrationRoot.endsWith('.gran-maestro'));
  assert.deepEqual(
    evidence.input_paths_read.slice(0, 4),
    [
      inventoryArtifactPath,
      evidence.source_artifact_paths.inventory_validation_path,
      parityEvidencePath,
      integrationEvidencePath,
    ],
  );
  assert.equal(evidence.validation_evidence_path, stableEvidenceRelativePath);
  assert.equal(
    evidence.discovery_smoke_result_path,
    `${stableEvidenceRelativePath}#discovery_results`,
  );
});

test('codex plugin discovery smoke records Sprint 4 forced wire observability', () => {
  const evidence = buildCodexPluginDiscoverySmokeEvidence();

  assert.equal(evidence.selection_reason, sprint4SelectionReason);
  assert.equal(evidence.s04_integration_context_path, sprint4IntegrationContextPath);
  assert.deepEqual(evidence.generated_asset_baseline_paths, generatedAssetBaselinePaths);
  assert.deepEqual(evidence.validation_entrypoints, validationEntrypoints);
  assert.equal(evidence.sprint4_forced_wire.selection_reason, sprint4SelectionReason);
  assert.equal(
    evidence.sprint4_forced_wire.integration_context_path,
    sprint4IntegrationContextPath,
  );
  assert.ok(evidence.input_paths_read.includes(sprint4IntegrationContextPath));
  assert.deepEqual(
    evidence.sprint4_forced_wire.generated_asset_baseline_paths,
    generatedAssetBaselinePaths,
  );
  assert.deepEqual(evidence.sprint4_forced_wire.validation_entrypoints, validationEntrypoints);
  assert.deepEqual(evidence.sprint4_forced_wire.out_of_scope_dod_guard.dod_ids, [
    'DOD-006',
    'DOD-008',
  ]);
  assert.equal(evidence.sprint4_forced_wire.out_of_scope_dod_guard.status, 'pass');
});

test('codex plugin discovery smoke records DOD-004 install and fallback reproducibility metadata', () => {
  const evidence = buildCodexPluginDiscoverySmokeEvidence();
  const dod004 = evidence.dod_004_install_fallback_reproducibility;

  assert.equal(dod004.dod_id, req888Dod004Metadata.dod_id);
  assert.equal(dod004.request_id, req888Dod004Metadata.request_id);
  assert.equal(dod004.task_id, req888Dod004Metadata.task_id);
  assert.equal(dod004.request_evidence_path, forcedWireEvidenceRelativePath);
  assert.equal(dod004.discovery_smoke_evidence_path, stableEvidenceRelativePath);
  assert.equal(dod004.generated_manifest_path, generatedManifestPath);
  assert.equal(dod004.generated_marketplace_path, generatedMarketplacePath);

  assert.equal(dod004.native_plugin_install.mode, 'metadata-only');
  assert.deepEqual(
    dod004.native_plugin_install.source_references.map((source) => source.type),
    ['local', 'marketplace'],
  );
  assert.deepEqual(
    dod004.native_plugin_install.verification_steps.map((step) => step.phase),
    ['install', 'enable', 'reload'],
  );
  assert.ok(
    dod004.native_plugin_install.verification_steps.some((step) =>
      step.references.includes(userConfigPathLiteral),
    ),
  );
  assert.equal(dod004.native_plugin_install.executes_external_install, false);
  assert.equal(dod004.native_plugin_install.mutates_user_config, false);
  assert.equal(dod004.native_plugin_install.refreshes_plugin_cache, false);

  assert.equal(dod004.fallback_skill_discovery.mode, 'metadata-only');
  assert.equal(dod004.fallback_skill_discovery.discovery_root, fallbackSkillDiscoveryRootPath);
  assert.equal(dod004.fallback_skill_discovery.repo_target, fallbackSkillRepoTargetPath);
  assert.equal(dod004.fallback_skill_discovery.symlink_path, fallbackSkillSymlinkPath);
  assert.match(dod004.fallback_skill_discovery.symlink_behavior, /skills\//);
  assert.equal(dod004.fallback_skill_discovery.creates_symlink, false);
  assert.equal(dod004.fallback_skill_discovery.mutates_user_config, false);

  assert.equal(dod004.unsupported_surfaces.status, 'pass');
  assert.deepEqual(
    dod004.unsupported_surfaces.surfaces.map((surface) => surface.dod_id),
    ['DOD-006', 'DOD-008'],
  );
  assert.equal(dod004.no_go_artifact_guard.status, 'pass');
  assert.equal(dod004.no_go_artifact_guard.mutates_user_config, false);
  assert.equal(dod004.no_go_artifact_guard.refreshes_plugin_cache, false);
  assert.equal(dod004.no_go_artifact_guard.creates_symlink, false);
});

test('codex plugin discovery smoke generator writes parseable stable evidence shape', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'codex-plugin-discovery-smoke-'));
  const outputPath = join(tempDir, 'evidence.json');

  try {
    const result = spawnSync(
      process.execPath,
      ['scripts/generate-codex-plugin-discovery-smoke.mjs', outputPath],
      {
        cwd: repoRoot,
        encoding: 'utf8',
      },
    );

    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), outputPath);

    const evidence = JSON.parse(readFileSync(outputPath, 'utf8'));
    assertCodexPluginDiscoverySmokeEvidence(evidence);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test('codex plugin discovery smoke gates upstream DOD validation status', () => {
  const passingBlockers = collectUnsupportedBlockers({
    inventoryValidation: {
      coverage: {
        expected_component_count: 2,
        actual_component_count: 2,
        missing_component_count: 0,
        coverage_percent: 100,
      },
      checks: [{ status: 'pass' }],
    },
    parityEvidence: {
      parse_error_count: 0,
      generated_drift_count: 0,
      unsupported_blocker_count: 0,
    },
    integrationEvidence: {
      status: 'pass',
      dod_002_blocker: false,
      parity_evidence_counts: {
        parse_error_count: 0,
        generated_drift_count: 0,
        unsupported_blocker_count: 0,
      },
    },
    outOfScopeArtifactCheck: { status: 'pass' },
  });
  assert.deepEqual(passingBlockers, []);

  const failingBlockers = collectUnsupportedBlockers({
    inventoryValidation: {
      coverage: {
        expected_component_count: 2,
        actual_component_count: 1,
        missing_component_count: 1,
        coverage_percent: 50,
      },
      checks: [{ status: 'pass' }, { status: 'fail' }],
    },
    parityEvidence: {
      parse_error_count: 1,
      generated_drift_count: 1,
      unsupported_blocker_count: 1,
    },
    integrationEvidence: {
      status: 'fail',
      dod_002_blocker: true,
      parity_evidence_counts: {
        parse_error_count: 1,
        generated_drift_count: 1,
        unsupported_blocker_count: 1,
      },
    },
    outOfScopeArtifactCheck: { status: 'fail' },
  });

  assert.match(failingBlockers.join('\n'), /DOD-001 inventory validation coverage/);
  assert.match(failingBlockers.join('\n'), /DOD-001 inventory validation checks/);
  assert.match(failingBlockers.join('\n'), /DOD-002 parity evidence parse_error_count/);
  assert.match(failingBlockers.join('\n'), /DOD-002 parity evidence generated_drift_count/);
  assert.match(failingBlockers.join('\n'), /DOD-002 parity evidence unsupported_blocker_count/);
  assert.match(failingBlockers.join('\n'), /DOD-002 integration evidence status/);
  assert.match(failingBlockers.join('\n'), /DOD-002 integration evidence reported a blocker/);
  assert.match(failingBlockers.join('\n'), /DOD-002 integration parity evidence parse_error_count/);
  assert.match(failingBlockers.join('\n'), /DOD-002 integration parity evidence generated_drift_count/);
  assert.match(failingBlockers.join('\n'), /DOD-002 integration parity evidence unsupported_blocker_count/);
  assert.match(failingBlockers.join('\n'), /Out-of-scope DOD artifacts/);
});

test('codex plugin discovery smoke preserves DOD-003 scope exclusions', () => {
  const evidence = buildCodexPluginDiscoverySmokeEvidence();

  assert.match(evidence.scope_exclusions.join('\n'), /hook wrapper/i);
  assert.match(evidence.scope_exclusions.join('\n'), /runtime projection/i);
  assert.match(evidence.scope_exclusions.join('\n'), /workflow E2E parity/i);
  assert.equal(evidence.out_of_scope_artifact_check.status, 'pass');
  assert.ok(
    evidence.out_of_scope_artifact_check.checks.every((check) =>
      check.assets.every((asset) => asset.exists === false),
    ),
  );
});

test('codex plugin discovery smoke no-go artifact guard stays repo-scoped and pass', () => {
  const evidence = buildCodexPluginDiscoverySmokeEvidence();
  const guard = evidence.dod_004_install_fallback_reproducibility.no_go_artifact_guard;

  assert.equal(guard.status, 'pass');
  assert.ok(guard.assets.every((asset) => asset.exists === false));
  assert.ok(
    guard.assets.some(
      (asset) =>
        asset.path === 'requests/REQ-886/evidence/codex-workflow-e2e-parity.json' &&
        asset.root === 'orchestration',
    ),
  );
});

test('codex skill projection evidence inventories every source skill with validated records', () => {
  const evidence = buildCodexSkillProjectionEvidence();
  const actualSkillPaths = readdirSync(join(repoRoot, 'skills'), { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => `skills/${entry.name}/SKILL.md`)
    .filter((path) => {
      try {
        readRepoFile(path);
        return true;
      } catch {
        return false;
      }
    })
    .sort();

  assertCodexSkillProjectionEvidence(evidence);
  evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
  assert.deepEqual(evidence.source_skill_inventory.skill_paths, actualSkillPaths);
  assert.equal(
    evidence.coverage.validated_projection_count,
    evidence.source_skill_inventory.source_skill_count,
  );
  assert.ok(
    evidence.projection_records.every((record) =>
      record.source_path === record.projected_path &&
      record.parse_status === 'pass' &&
      /^[a-f0-9]{64}$/u.test(record.source_digest),
    ),
  );
  assertNoForbiddenSkillProjectionEvidenceLiterals(evidence);
});

test('codex skill projection evidence builds core MST smoke metadata without runtime side effects', () => {
  const evidence = buildCodexSkillProjectionEvidence();
  const coreSmoke = evidence.core_skill_smoke;

  assert.equal(coreSmoke.status, 'pass');
  assert.deepEqual(coreSmoke.core_skill_names, coreMstSkillNames);
  assert.deepEqual(
    coreSmoke.records.map((record) => record.skill_name),
    coreMstSkillNames,
  );
  assert.ok(
    coreSmoke.records.every((record) =>
      record.invocation_metadata.mode === 'metadata-only' &&
      typeof record.invocation_metadata.command_id === 'string' &&
      record.invocation_metadata.command_id.length > 0,
    ),
  );
  assert.equal(coreSmoke.runtime_side_effects.created_request_count, 0);
  assert.equal(coreSmoke.runtime_side_effects.advanced_request_count, 0);
  assert.equal(coreSmoke.runtime_side_effects.request_state_transition_count, 0);
  assert.equal(coreSmoke.runtime_side_effects.hook_execution_count, 0);
  assert.equal(coreSmoke.runtime_side_effects.session_execution_count, 0);
  assert.equal(coreSmoke.runtime_side_effects.workflow_execution_count, 0);
});

test('codex skill projection evidence rejects repository escape and install fixtures', () => {
  const evidence = buildCodexSkillProjectionEvidence();
  const failedPathCodes = evidence.no_go_guard.path_fixtures
    .filter((fixture) => fixture.status === 'fail')
    .map((fixture) => fixture.code)
    .sort();
  const failedCommandCodes = evidence.no_go_guard.command_fixtures
    .filter((fixture) => fixture.status === 'fail')
    .map((fixture) => fixture.code)
    .sort();

  assert.equal(evidence.no_go_guard.status, 'pass');
  assert.deepEqual(failedPathCodes, [
    'absolute_host_path',
    'absolute_host_path',
    'encoded_traversal',
    'env_expansion',
    'env_expansion',
    'home_expansion',
    'path_traversal',
    'path_traversal',
  ]);
  assert.deepEqual(failedCommandCodes, [
    'cache_refresh',
    'external_install',
    'symlink_creation',
  ]);
  assert.deepEqual(
    evidence.no_go_guard.path_fixtures.map((fixture) => fixture.fixture_id),
    [
      'repo_relative_skill_path',
      'parent_traversal_posix',
      'parent_traversal_windows',
      'encoded_parent_traversal',
      'tilde_home_expansion',
      'env_home_expansion',
      'env_home_braced_expansion',
      'absolute_posix_path',
      'absolute_windows_path',
    ],
  );
  assert.deepEqual(
    evidence.no_go_guard.command_fixtures.map((fixture) => fixture.fixture_id),
    ['relative_generator_cli', 'symlink_cli', 'install_cli', 'refresh_cli'],
  );
  assertNoForbiddenSkillProjectionEvidenceLiterals(evidence);
});

test('codex skill projection generator writes parseable request-level evidence shape', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'codex-skill-projection-'));
  const outputPath = join(tempDir, 'evidence.json');

  try {
    const result = spawnSync(
      process.execPath,
      ['scripts/generate-codex-skill-projection-smoke.mjs', outputPath],
      {
        cwd: repoRoot,
        encoding: 'utf8',
      },
    );

    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), outputPath);

    const evidence = JSON.parse(readFileSync(outputPath, 'utf8'));
    assertCodexSkillProjectionEvidence(evidence);
    assert.equal(evidence.request_evidence_path, skillProjectionEvidenceRelativePath);
    evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
    assertNoForbiddenSkillProjectionEvidenceLiterals(evidence, [tempDir, outputPath]);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test('codex skill projection evidence preserves DOD-007 and DOD-008 excluded boundaries', () => {
  const evidence = buildCodexSkillProjectionEvidence();

  assert.deepEqual(evidence.excluded_surfaces.map((surface) => surface.dod_id), skillProjectionExcludedDodIds);
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.status === 'pass'));
  assert.equal(evidence.baseline_evidence.status, 'pass');
  assert.equal(evidence.baseline_evidence.request_id, 'REQ-890');
  assert.equal(evidence.baseline_evidence.dod_id, 'DOD-005');
});

test('codex role mapping evidence inventories every canonical agent role with full coverage', () => {
  const evidence = buildCodexRoleMappingEvidence();
  const actualAgentPaths = readdirSync(join(repoRoot, 'agents'), { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.md'))
    .map((entry) => `agents/${entry.name}`)
    .sort();

  assertCodexRoleMappingEvidence(evidence);
  evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
  assert.deepEqual(evidence.source_agent_inventory.agent_paths, actualAgentPaths);
  assert.deepEqual(evidence.role_coverage.required_roles, requiredAgentRoleNames);
  assert.deepEqual(
    evidence.role_coverage.mapped_roles,
    [...requiredAgentRoleNames].sort(),
  );
  assert.equal(evidence.role_coverage.coverage_percent, 100);
  assert.equal(evidence.role_coverage.missing_role_count, 0);
  assert.equal(evidence.role_coverage.extra_role_count, 0);
  assert.ok(
    evidence.role_mapping_records.every((record) =>
      record.source_path === `agents/${record.role_name}.md` &&
      record.manifest_path === `./agents/${record.role_name}.md` &&
      record.codex_mapping.mapping_mode === 'metadata-only' &&
      record.codex_mapping.routing_surface === `/prompts:${record.role_name}` &&
      /^[a-f0-9]{64}$/u.test(record.source_digest),
    ),
  );
  assertNoForbiddenRoleMappingEvidenceLiterals(evidence);
});

test('codex role mapping evidence enforces exact Claude manifest parity without codex-only paths', () => {
  const evidence = buildCodexRoleMappingEvidence();
  const sourceManifest = JSON.parse(readRepoFile('.claude-plugin/plugin.json'));
  const expectedAgents = readdirSync(join(repoRoot, 'agents'))
    .filter((name) => name.endsWith('.md'))
    .map((name) => `./agents/${name}`)
    .sort();

  assert.equal(evidence.claude_manifest_parity.status, 'pass');
  assert.deepEqual(evidence.claude_manifest_parity.expected_agents, expectedAgents);
  assert.deepEqual(evidence.claude_manifest_parity.manifest_agents, [...sourceManifest.agents].sort());
  assert.equal(evidence.claude_manifest_parity.missing_agent_count, 0);
  assert.equal(evidence.claude_manifest_parity.extra_agent_count, 0);
  assert.equal(evidence.claude_manifest_parity.forbidden_projection_path_count, 0);
  assert.deepEqual(evidence.claude_manifest_parity.forbidden_projection_paths, []);
});

test('codex role mapping evidence aligns codex plugin marketplace and T01/T02 coverage metadata', () => {
  const evidence = buildCodexRoleMappingEvidence();
  const consistency = evidence.cross_file_consistency;

  assert.equal(consistency.status, 'pass');
  assert.equal(consistency.plugin_identity.status, 'pass');
  assert.ok(consistency.plugin_identity.checks.every((check) => check.status === 'pass'));
  assert.equal(consistency.repository_relative_paths.status, 'pass');
  assert.ok(consistency.repository_relative_paths.checks.every((check) => check.status === 'pass'));
  assert.equal(consistency.skill_inventory_coverage.status, 'pass');
  assert.equal(consistency.skill_inventory_coverage.missing_skill_count, 0);
  assert.equal(consistency.skill_inventory_coverage.extra_skill_count, 0);
  assert.equal(consistency.skill_inventory_coverage.drift_count, 0);
  assert.equal(consistency.agent_role_coverage.status, 'pass');
  assert.equal(consistency.agent_role_coverage.missing_role_count, 0);
  assert.equal(consistency.agent_role_coverage.extra_role_count, 0);
  assert.equal(consistency.agent_role_coverage.manifest_missing_agent_count, 0);
  assert.equal(consistency.agent_role_coverage.manifest_extra_agent_count, 0);
  assert.equal(
    evidence.source_dependencies.skill_projection_evidence_path,
    skillProjectionEvidenceRelativePath,
  );
  assert.equal(evidence.request_evidence_path, roleMappingEvidenceRelativePath);
});

test('codex role mapping privilege guard rejects escalation fixtures via allowlist schema', () => {
  const evidence = buildCodexRoleMappingEvidence();
  const guard = evidence.privilege_guard;
  const fixtureMap = new Map(
    guard.deny_fixture_rejections.fixtures.map((fixture) => [fixture.fixture_id, fixture]),
  );

  assert.equal(guard.status, 'pass');
  assert.equal(guard.schema_basis, 'allowlist');
  assert.equal(guard.skill_metadata_schema.status, 'pass');
  assert.equal(guard.role_metadata_schema.status, 'pass');
  assert.deepEqual(guard.regression_signal_counts, {
    bypass_permissions: 0,
    sandbox_disable: 0,
    arbitrary_command_fields: 0,
    user_home_mutation: 0,
    plugin_cache_refresh: 0,
    codex_external_install: 0,
    chmod_chown: 0,
    curl_bash: 0,
  });
  assert.equal(guard.deny_fixture_rejections.status, 'pass');
  assert.deepEqual(
    guard.deny_fixture_rejections.fixtures.map((fixture) => fixture.fixture_id),
    [
      'bypass_permissions_camelcase',
      'sandbox_disable_mode',
      'arbitrary_command_field',
      'user_home_mutation_path',
      'plugin_cache_refresh_field',
      'codex_external_install_field',
      'chmod_field',
      'chown_field',
      'curl_bash_shell_command',
      'symlink_creation_field',
    ],
  );
  assert.ok(guard.deny_fixture_rejections.fixtures.every((fixture) => fixture.matched_expected));
  assert.ok(fixtureMap.get('bypass_permissions_camelcase').violation_codes.includes('permission_bypass_key'));
  assert.ok(fixtureMap.get('sandbox_disable_mode').violation_codes.includes('sandbox_disable_key'));
  assert.ok(fixtureMap.get('arbitrary_command_field').violation_codes.includes('arbitrary_command_key'));
  assert.ok(fixtureMap.get('user_home_mutation_path').violation_codes.includes('home_expansion'));
  assert.ok(fixtureMap.get('plugin_cache_refresh_field').violation_codes.includes('plugin_cache_refresh_key'));
  assert.ok(fixtureMap.get('codex_external_install_field').violation_codes.includes('external_install_key'));
  assert.ok(fixtureMap.get('chmod_field').violation_codes.includes('chmod_chown_key'));
  assert.ok(fixtureMap.get('chown_field').violation_codes.includes('chmod_chown_key'));
  assert.ok(fixtureMap.get('curl_bash_shell_command').violation_codes.includes('arbitrary_command_key'));
  assert.ok(fixtureMap.get('symlink_creation_field').violation_codes.includes('user_home_mutation_key'));
  assertNoForbiddenRoleMappingEvidenceLiterals(evidence);
});

test('codex role mapping generator writes parseable request-level evidence shape', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'codex-role-mapping-'));
  const outputPath = join(tempDir, 'evidence.json');

  try {
    const result = spawnSync(
      process.execPath,
      ['scripts/generate-codex-role-mapping-smoke.mjs', outputPath],
      {
        cwd: repoRoot,
        encoding: 'utf8',
      },
    );

    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), outputPath);

    const evidence = JSON.parse(readFileSync(outputPath, 'utf8'));
    assertCodexRoleMappingEvidence(evidence);
    assert.equal(evidence.request_evidence_path, roleMappingEvidenceRelativePath);
    evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
    assertNoForbiddenRoleMappingEvidenceLiterals(evidence, [tempDir, outputPath]);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test('codex skill-agent projection validation evidence records REQ-891 request-level linkage', () => {
  const evidence = buildCodexSkillAgentProjectionValidationEvidence({
    verificationSummary: req891ValidationSummary,
  });

  assertCodexSkillAgentProjectionValidationEvidence(evidence, req891ValidationSummary);
  evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
  assert.equal(
    evidence.request_evidence_path,
    skillAgentProjectionValidationEvidenceRelativePath,
  );
  assert.equal(evidence.request_metadata_snapshot.path, req891RequestMetadataRelativePath);
  assert.equal(evidence.source_commit.status, 'pass');
  assert.deepEqual(
    evidence.source_commit.tasks.map((task) => task.task_id),
    ['REQ-891-01', 'REQ-891-02'],
  );
  assert.deepEqual(evidence.source_commit.tasks.map((task) => task.source_commit), [
    '2f5c3da',
    '5a6d3f5',
  ]);
  assert.equal(evidence.t01_evidence_summary.evidence_path, skillProjectionEvidenceRelativePath);
  assert.equal(evidence.t02_evidence_summary.evidence_path, roleMappingEvidenceRelativePath);
  assert.equal(evidence.t01_evidence_summary.self_check.command_count, 3);
  assert.equal(evidence.t02_evidence_summary.self_check.command_count, 4);
  assert.ok(!('commands' in evidence.t01_evidence_summary.self_check));
  assert.ok(!('commands' in evidence.t02_evidence_summary.self_check));
  assert.equal(evidence.t02_evidence_summary.privilege_regression_count, 0);
  assert.equal(evidence.dod_005_baseline_summary.parse_ok, true);
  assert.equal(evidence.dod_005_baseline_summary.test_command_totals.tests_fail, 0);
  assert.equal(evidence.evidence_lifecycle.missing_required_artifact_paths.length, 0);
  assertNoForbiddenRoleMappingEvidenceLiterals(evidence);
});

test('codex skill-agent projection validation evidence lifecycle gates pass on generators tests and artifact paths', () => {
  const passingEvidence = buildCodexSkillAgentProjectionValidationEvidence({
    verificationSummary: req891ValidationSummary,
  });
  assert.equal(passingEvidence.status, 'pass');
  assert.equal(passingEvidence.evidence_lifecycle.status, 'pass');

  const failingGeneratorEvidence = buildCodexSkillAgentProjectionValidationEvidence({
    verificationSummary: {
      ...req891ValidationSummary,
      role_mapping_generator: {
        ...req891ValidationSummary.role_mapping_generator,
        status: 'fail',
        parse_ok: false,
      },
    },
  });
  assert.equal(failingGeneratorEvidence.status, 'fail');
  assert.equal(failingGeneratorEvidence.evidence_lifecycle.status, 'fail');
  assert.equal(
    failingGeneratorEvidence.evidence_lifecycle.implementation_artifact_generation_pass,
    false,
  );

  const missingPathEvidence = buildCodexSkillAgentProjectionValidationEvidence({
    verificationSummary: {
      ...req891ValidationSummary,
      skill_projection_generator: {
        ...req891ValidationSummary.skill_projection_generator,
        generated_artifact_path: '/tmp/req-891-skill-projection.test.json',
      },
    },
  });
  assert.equal(missingPathEvidence.status, 'fail');
  assert.equal(missingPathEvidence.evidence_lifecycle.required_artifact_paths_present, false);
  assert.ok(
    missingPathEvidence.evidence_lifecycle.missing_required_artifact_paths.includes(
      'skill_projection_generator_artifact_path',
    ),
  );
  assert.equal(
    missingPathEvidence.test_command_results.skill_projection_generator.generated_output_path,
    null,
  );

  const failingTestEvidence = buildCodexSkillAgentProjectionValidationEvidence({
    verificationSummary: {
      ...req891ValidationSummary,
      npm_test: {
        ...req891ValidationSummary.npm_test,
        status: 'fail',
        tests_fail: 1,
      },
    },
  });
  assert.equal(failingTestEvidence.status, 'fail');
  assert.equal(failingTestEvidence.evidence_lifecycle.tests_pass, false);
});

test('codex skill-agent projection validation generator writes parseable request-level evidence shape', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'codex-skill-agent-projection-validation-'));
  const outputPath = join(tempDir, 'evidence.json');
  const verificationPath = join(tempDir, 'verification-summary.json');

  try {
    writeFileSync(`${verificationPath}`, `${JSON.stringify(req891ValidationSummary, null, 2)}\n`, 'utf8');

    const result = spawnSync(
      process.execPath,
      [
        'scripts/generate-dod-006-codex-skill-agent-projection-validation.mjs',
        outputPath,
        verificationPath,
      ],
      {
        cwd: repoRoot,
        encoding: 'utf8',
      },
    );

    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), outputPath);

    const evidence = JSON.parse(readFileSync(outputPath, 'utf8'));
    assertCodexSkillAgentProjectionValidationEvidence(evidence, req891ValidationSummary);
    evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
    assert.equal(
      evidence.request_evidence_path,
      skillAgentProjectionValidationEvidenceRelativePath,
    );
    assert.equal(evidence.test_command_results.skill_projection_generator.generated_output_path, null);
    assert.equal(evidence.test_command_results.role_mapping_generator.generated_output_path, null);
    assert.equal(evidence.t02_evidence_summary.privilege_regression_count, 0);
    assert.ok(!('commands' in evidence.t01_evidence_summary.self_check));
    assert.ok(!('commands' in evidence.t02_evidence_summary.self_check));
    assertNoForbiddenRoleMappingEvidenceLiterals(evidence, [tempDir, outputPath, verificationPath]);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test('DOD-008 workflow schema contract includes representative scenario paths', () => {
  const contract = buildDod008WorkflowSchemaContract();

  assertDod008WorkflowSchemaContract(contract);
  assert.deepEqual(dod008WorkflowScenarioPaths, [
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
  ]);
  assert.deepEqual(
    contract.scenario_contract.map((scenario) => scenario.representative_path),
    dod008WorkflowScenarioPaths,
  );
  assertNoForbiddenDod008ContractLiterals(contract.scenario_contract);
});

test('DOD-008 artifact schema contract defines non-empty required fields', () => {
  const contract = buildDod008WorkflowSchemaContract();
  const schemaByType = new Map(
    contract.artifact_schema_contract.map((schema) => [schema.artifact_type, schema]),
  );

  assert.deepEqual(
    [...schemaByType.keys()],
    [
      'objective',
      'request',
      'spec',
      'task',
      'trace',
      'review',
      'accept',
      'recover',
      'cleanup',
      'dashboard',
      'settings',
    ],
  );

  for (const [artifactType, requiredFields] of Object.entries(dod008ArtifactSchemaRequiredFieldsByType)) {
    const schema = schemaByType.get(artifactType);
    assert.ok(schema, `${artifactType} schema`);
    assert.deepEqual(schema.required_fields, requiredFields);
    assert.ok(requiredFields.length > 0, `${artifactType} required fields`);
    assert.ok(requiredFields.every((field) => typeof field === 'string' && field.length > 0));
  }

  assertNoForbiddenDod008ContractLiterals(contract.artifact_schema_contract);
});

test('DOD-008 lifecycle smoke artifacts validate against required schema fields', () => {
  const artifacts = buildDod008LifecycleSmokeArtifacts();
  const validation = buildDod008LifecycleSmokeValidation(artifacts);
  const contract = buildDod008WorkflowSchemaContract();

  assertDod008LifecycleSmokeArtifacts(artifacts);
  assert.deepEqual(dod008LifecycleSmokeArtifactTypes, [
    'recover',
    'cleanup',
    'dashboard',
    'settings',
  ]);
  assert.equal(validation.status, 'pass');
  assert.deepEqual(validation.artifact_types, dod008LifecycleSmokeArtifactTypes);
  assert.deepEqual(validation.missing_artifact_types, []);
  assert.deepEqual(validation.missing_required_fields, []);
  assert.deepEqual(contract.lifecycle_smoke_artifacts, artifacts);
  assert.deepEqual(contract.lifecycle_smoke_validation, validation);
  assertNoForbiddenDod008ContractLiterals(artifacts);
});

test('DOD-008 recover and cleanup smoke artifacts preserve lifecycle safety fields', () => {
  const artifacts = buildDod008LifecycleSmokeArtifacts();
  const byType = new Map(artifacts.map((artifact) => [artifact.artifact_type, artifact]));
  const recover = byType.get('recover');
  const cleanup = byType.get('cleanup');

  assert.equal(recover.canonical_session_identity.mst_session_id, recover.mst_session_id);
  assert.equal(recover.canonical_session_identity.lookup_key, recover.mst_session_id);
  assert.equal(recover.canonical_session_identity.partition_key, recover.mst_session_id);
  assert.equal(recover.recovery_judgement.primary_action, 'resume_session');
  assert.equal(recover.recovery_judgement.reason, 'resume_ready');
  assert.ok(
    recover.recovery_judgement.affected_resources.some(
      (resource) => resource.kind === 'mst_session_id',
    ),
  );

  assert.equal(cleanup.report.orphan_session_count, 0);
  assert.equal(cleanup.report.planned_cleanup_count, 0);
  assert.equal(cleanup.request_artifacts_preserved.status, 'pass');
  assert.equal(cleanup.request_artifacts_preserved.mutated_path_count, 0);
  assert.ok(
    cleanup.request_artifacts_preserved.checked_paths.every((path) =>
      path.startsWith('.gran-maestro/requests/REQ-894/'),
    ),
  );
});

test('DOD-008 dashboard and settings smoke artifacts cover route/config shapes', () => {
  const artifacts = buildDod008LifecycleSmokeArtifacts();
  const byType = new Map(artifacts.map((artifact) => [artifact.artifact_type, artifact]));
  const dashboard = byType.get('dashboard');
  const settings = byType.get('settings');

  assert.equal(dashboard.health.route, '/api/health');
  assert.equal(dashboard.health.ok, true);
  assert.equal(dashboard.overview.active_items.shape.items, 'array');
  assert.equal(dashboard.overview.active_items.shape.has_more, 'boolean');
  assert.equal(dashboard.overview.next_steps.shape.items, 'array');
  assert.equal(dashboard.overview.pulse.shape.active, 'number');
  assert.equal(dashboard.overview.pulse.shape.blocked, 'number');

  assert.equal(settings.config.config_route.route, '/api/config');
  assert.deepEqual(Object.keys(settings.config.config_route.shape), [
    'merged',
    'overrides',
    'defaults',
  ]);
  assert.equal(settings.config.defaults_route.route, '/api/config/defaults');
  assert.equal(settings.config.mode_route.shape.active, 'boolean');
  assert.equal(settings.effective_values.workflow_default_agent, 'codex-dev');
});

test('DOD-008 no-go metadata guard scans scenario and schema contract metadata', () => {
  const contract = buildDod008WorkflowSchemaContract();
  const scannedMetadata = {
    scenario_contract: contract.scenario_contract,
    artifact_schema_contract: contract.artifact_schema_contract,
    no_go_metadata_guard: contract.no_go_metadata_guard,
    lifecycle_smoke_artifacts: contract.lifecycle_smoke_artifacts,
  };

  assert.deepEqual(
    contract.no_go_metadata_guard.criteria.map((criterion) => criterion.criterion_id),
    dod008NoGoMetadataGuardCriteria.map((criterion) => criterion.criterion_id),
  );
  assert.equal(contract.forbidden_metadata_scan.status, 'pass');
  assert.equal(contract.forbidden_metadata_scan.violation_count, 0);
  assert.deepEqual(scanDod008ScenarioSchemaMetadata(scannedMetadata), {
    status: 'pass',
    scanned_string_count: scanDod008ScenarioSchemaMetadata(scannedMetadata).scanned_string_count,
    violation_count: 0,
    violations: [],
  });
  assertNoForbiddenDod008ContractLiterals(scannedMetadata);

  for (const forbiddenValue of [
    '/Users/example/project',
    '~/example',
    '$HOME/example',
    '~/.codex/config.toml',
    '~/.agents/skills',
    '.claude/hooks',
    '../escape',
    '%2e%2e/escape',
    'traversal',
    'codex plugins install example',
    'codex plugins refresh',
    'codex plugins reload',
    'external install',
    'cache refresh',
    'reload plugin index',
    'ln -s source target',
    'symlink mutation',
  ]) {
    const scan = scanDod008ScenarioSchemaMetadata({
      scenario_contract: [{ representative_path: forbiddenValue }],
      artifact_schema_contract: [],
    });
    assert.equal(scan.status, 'fail', forbiddenValue);
    assert.ok(scan.violation_count > 0, forbiddenValue);
  }
});

test('DOD-008 manual-readable exports keep downstream DOD surfaces excluded', () => {
  const contract = buildDod008WorkflowSchemaContract();

  assert.deepEqual(dod008AcceptanceRuntimeSurfaceIds, ['DOD-008']);
  assert.deepEqual(dod008ExcludedSurfaceIds, [
    'DOD-009',
    'DOD-010',
    'DOD-011',
    'DOD-012',
    'DOD-013',
  ]);
  assert.deepEqual(
    contract.manual_readable_exports.excluded_surface_ids,
    dod008ExcludedSurfaceIds,
  );
  assert.deepEqual(
    contract.manual_readable_exports.acceptance_runtime_surface_ids,
    dod008AcceptanceRuntimeSurfaceIds,
  );
  assert.equal(
    dod008ExcludedSurfaceIds.some((surfaceId) =>
      dod008AcceptanceRuntimeSurfaceIds.includes(surfaceId),
    ),
    false,
  );
  assert.ok(contract.excluded_surfaces.every((surface) => surface.implementation_count === 0));
  assert.ok(contract.excluded_surfaces.every((surface) => surface.runtime_invocation_count === 0));
  assert.ok(contract.excluded_surfaces.every((surface) => surface.acceptance_gate_count === 0));
  assertNoForbiddenDod008ContractLiterals(contract.manual_readable_exports);
});

test('DOD-008 core workflow smoke harness reproduces request through accept artifact shapes', () => {
  const harness = buildDod008CoreWorkflowSmokeHarness();

  assertDod008CoreWorkflowSmokeHarness(harness);
  assert.deepEqual(
    harness.scenario_records.map((scenario) => scenario.representative_path),
    dod008CoreWorkflowSmokeScenarioPaths,
  );
  assert.deepEqual(Object.keys(harness.artifacts), dod008CoreWorkflowSmokeArtifactTypes);
  for (const validation of harness.artifact_validations) {
    assert.deepEqual(
      validation.required_fields,
      dod008ArtifactSchemaRequiredFieldsByType[validation.artifact_type],
    );
    assert.deepEqual(validation.missing_fields, []);
    assert.deepEqual(validation.empty_fields, []);
    assert.deepEqual(validation.session_violations, []);
  }
  assertNoForbiddenDod008ContractLiterals({
    scenario_records: harness.scenario_records,
    artifacts: harness.artifacts,
    command_metadata: harness.command_metadata,
  });
});

test('DOD-008 core workflow smoke harness preserves canonical MST session boundaries', () => {
  const harness = buildDod008CoreWorkflowSmokeHarness();
  const session = harness.session_metadata;

  assert.equal(session.env.MST_SESSION_ID, dod008CoreWorkflowSmokeSessionId);
  assert.equal(session.context.mst_session_id, dod008CoreWorkflowSmokeSessionId);
  assert.equal(session.env.MST_SESSION_ID, session.context.mst_session_id);
  assert.deepEqual(session.canonical_sources, ['MST_SESSION_ID', 'mst_session_id']);
  assert.equal(session.legacy_diagnostics.diagnostic_only, true);
  assert.equal(session.legacy_diagnostics.canonical_source_count, 0);
  assert.equal(session.boundary_checks.legacy_only_identity_rejected, true);
  assert.ok(
    dod008CoreWorkflowSmokeArtifactTypes.every(
      (artifactType) =>
        harness.artifacts[artifactType].state_session.env.MST_SESSION_ID ===
        harness.artifacts[artifactType].state_session.context.mst_session_id,
    ),
  );
});

test('DOD-008 core workflow smoke harness command metadata is fixture-only', () => {
  const harness = buildDod008CoreWorkflowSmokeHarness();

  assert.deepEqual(harness.command_metadata.map((entry) => entry.command), [
    'node --test tests/smoke.test.mjs',
  ]);
  assert.ok(harness.command_metadata.every((entry) => entry.mode === 'deterministic-fixture'));
  assert.equal(harness.side_effect_summary.repository_local_only, true);
  assert.equal(harness.side_effect_summary.fixture_only, true);
  assert.equal(harness.side_effect_summary.mutates_user_home, false);
  assert.equal(harness.side_effect_summary.edits_hook_config, false);
  assert.equal(harness.side_effect_summary.executes_codex_install, false);
  assert.equal(harness.side_effect_summary.refreshes_codex_cache, false);
  assert.equal(harness.side_effect_summary.runs_real_implementation, false);
  assert.equal(harness.forbidden_metadata_scan.status, 'pass');
  assert.equal(harness.forbidden_metadata_scan.violation_count, 0);
  assertNoForbiddenDod008ContractLiterals(harness.command_metadata);
});

test('DOD-008 workflow artifact parity validates Claude canonical and Codex fixture shapes', () => {
  const validation = buildDod008WorkflowArtifactParityValidation();

  assertDod008WorkflowArtifactParityValidation(validation);
  assert.deepEqual(
    validation.required_field_parity.checked_artifact_types,
    dod008WorkflowArtifactParityTypes,
  );
  for (const diff of validation.required_field_parity.artifact_diffs) {
    assert.deepEqual(
      diff.claude_required_fields,
      dod008ArtifactSchemaRequiredFieldsByType[diff.artifact_type],
    );
    assert.deepEqual(diff.codex_required_fields, diff.claude_required_fields);
    assert.deepEqual(diff.missing_required_fields, []);
    assert.deepEqual(diff.extra_required_fields, []);
  }
  assertNoForbiddenDod008ContractLiterals(validation);
});

test('DOD-008 workflow parity reports human-readable missing and extra required-field blockers', () => {
  const badRequestRequiredFields = [
    ...dod008ArtifactSchemaRequiredFieldsByType.request.filter((field) => field !== 'status'),
    'codex_only_required',
  ];
  const validation = buildDod008WorkflowArtifactParityValidation({
    codexRequiredFieldsByType: {
      request: badRequestRequiredFields,
    },
  });

  assert.equal(validation.status, 'fail');
  assert.equal(validation.required_field_parity.status, 'fail');
  assert.equal(validation.required_field_parity.missing_blocker_count, 1);
  assert.equal(validation.required_field_parity.extra_blocker_count, 1);
  assert.equal(validation.blocker_summary.blocker_count, 2);
  assert.deepEqual(
    validation.required_field_parity.blockers.map((blocker) => ({
      surface_id: blocker.surface_id,
      artifact_type: blocker.artifact_type,
      artifact_field: blocker.artifact_field,
      diff_type: blocker.diff_type,
    })),
    [
      {
        surface_id: 'DOD-008',
        artifact_type: 'request',
        artifact_field: 'status',
        diff_type: 'missing_required_field',
      },
      {
        surface_id: 'DOD-008',
        artifact_type: 'request',
        artifact_field: 'codex_only_required',
        diff_type: 'extra_required_field',
      },
    ],
  );
  assert.match(validation.blocker_summary.human_readable.join('\n'), /DOD-008 request\.status/);
  assert.match(
    validation.blocker_summary.human_readable.join('\n'),
    /DOD-008 request\.codex_only_required/,
  );
});

test('DOD-008 workflow parity validates session identity, recovery, and orphan-session boundaries', () => {
  const validation = buildDod008WorkflowArtifactParityValidation();

  assert.equal(validation.boundary_checks.status, 'pass');
  assert.equal(validation.boundary_checks.session_identity.status, 'pass');
  assert.deepEqual(
    validation.boundary_checks.session_identity.checked_artifact_types,
    dod008CoreWorkflowSmokeArtifactTypes,
  );
  assert.equal(validation.boundary_checks.session_identity.blocker_count, 0);
  assert.equal(validation.boundary_checks.recovery.status, 'pass');
  assert.equal(validation.boundary_checks.recovery.artifact_type, 'recover');
  assert.equal(validation.boundary_checks.recovery.blocker_count, 0);
  assert.equal(validation.boundary_checks.orphan_session.status, 'pass');
  assert.equal(validation.boundary_checks.orphan_session.artifact_type, 'cleanup');
  assert.equal(validation.boundary_checks.orphan_session.orphan_session_count, 0);
  assert.equal(validation.boundary_checks.orphan_session.blocker_count, 0);
});

test('DOD-008 workflow parity keeps excluded DOD surfaces at zero implementation/runtime/acceptance counts', () => {
  const validation = buildDod008WorkflowArtifactParityValidation();

  assert.deepEqual(validation.excluded_surface_guard.surface_ids, [
    'DOD-009',
    'DOD-010',
    'DOD-011',
    'DOD-012',
    'DOD-013',
  ]);
  assert.equal(validation.excluded_surface_guard.status, 'pass');
  for (const surface of validation.excluded_surface_guard.surfaces) {
    assert.equal(surface.implementation_count, 0, `${surface.surface_id} implementation_count`);
    assert.equal(surface.runtime_invocation_count, 0, `${surface.surface_id} runtime_invocation_count`);
    assert.equal(surface.acceptance_gate_count, 0, `${surface.surface_id} acceptance_gate_count`);
  }
});

test('DOD-007 request evidence records REQ-893 linkage and contract summaries', () => {
  const evidence = buildDod007RequestEvidence({
    verificationSummary: req893ValidationSummary,
  });

  assertDod007RequestEvidence(evidence, req893ValidationSummary);
  evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
  assert.equal(evidence.request_evidence_path, dod007RequestEvidenceRelativePath);
  assert.equal(evidence.request_metadata_snapshot.path, req893RequestMetadataRelativePath);
  assert.equal(evidence.request_metadata_snapshot.request_id, 'REQ-893');
  assert.equal(evidence.request_metadata_snapshot.agi_id, 'AGI-039');
  assert.equal(evidence.request_metadata_snapshot.sprint, 8);
  assert.equal(evidence.request_metadata_snapshot.dod_id, 'DOD-007');
  assert.equal(evidence.request_metadata_snapshot.plan_id, 'PLN-720');
  assert.deepEqual(
    evidence.source_commit.tasks.map((task) => task.source_commit),
    [
      'f73bf3916fd9b661a093b6e096963f1d66c918d6',
      '4e26b50b0d749142f1c11e41f806c7cc70eb7762',
      '471e6f50f6dce193c465cd07031df8e27ddfe590',
      '50649a02dce132aa2dedcf21df938fe570f1539f',
    ],
  );
  assert.equal(evidence.state_contract_summary.status, 'pass');
  assert.equal(evidence.continuation_contract_summary.status, 'pass');
  assert.equal(evidence.wrapper_contract_summary.status, 'pass');
  assertNoForbiddenDod007EvidenceLiterals(evidence);
});

test('DOD-007 request evidence status gates on supplied focused verify summaries', () => {
  const passingEvidence = buildDod007RequestEvidence({
    verificationSummary: req893ValidationSummary,
  });
  assert.equal(passingEvidence.status, 'pass');

  const missingSummaryEvidence = buildDod007RequestEvidence();
  assert.equal(missingSummaryEvidence.status, 'fail');
  assert.equal(missingSummaryEvidence.evidence_lifecycle.verification_summary_supplied, false);

  const failingFocusedVerifyEvidence = buildDod007RequestEvidence({
    verificationSummary: {
      ...req893ValidationSummary,
      focused_verify_command: {
        ...req893ValidationSummary.focused_verify_command,
        status: 'fail',
        tests_pass: 24,
        tests_fail: 1,
      },
    },
  });
  assert.equal(failingFocusedVerifyEvidence.status, 'fail');
  assert.equal(failingFocusedVerifyEvidence.evidence_lifecycle.focused_verify_pass, false);

  const failingContractEvidence = buildDod007RequestEvidence({
    verificationSummary: {
      ...req893ValidationSummary,
      run_wrapper_session_contract: {
        ...req893ValidationSummary.run_wrapper_session_contract,
        status: 'fail',
        tests_pass: 9,
        tests_fail: 1,
      },
    },
  });
  assert.equal(failingContractEvidence.status, 'fail');
  assert.equal(failingContractEvidence.evidence_lifecycle.contract_summaries_pass, false);
});

test('DOD-007 request evidence preserves excluded surfaces with zero counts', () => {
  const evidence = buildDod007RequestEvidence({
    verificationSummary: req893ValidationSummary,
  });

  assert.deepEqual(
    evidence.excluded_surfaces.map((surface) => surface.surface_id),
    dod007ExcludedSurfaceIds,
  );
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.status === 'pass'));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.implementation_count === 0));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.runtime_invocation_count === 0));
  assert.ok(evidence.excluded_surfaces.every((surface) => surface.acceptance_gate_count === 0));
});

test('DOD-007 request evidence generator writes parseable request-level evidence shape', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'dod-007-request-evidence-'));
  const outputPath = join(tempDir, 'evidence.json');
  const verificationPath = join(tempDir, 'verification-summary.json');

  try {
    writeFileSync(`${verificationPath}`, `${JSON.stringify(req893ValidationSummary, null, 2)}\n`, 'utf8');

    const result = spawnSync(
      process.execPath,
      [
        'scripts/generate-dod-007-request-evidence.mjs',
        outputPath,
        verificationPath,
      ],
      {
        cwd: repoRoot,
        encoding: 'utf8',
      },
    );

    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), outputPath);

    const evidence = JSON.parse(readFileSync(outputPath, 'utf8'));
    assertDod007RequestEvidence(evidence, req893ValidationSummary);
    evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
    assert.equal(evidence.test_command_results.generator.generated_output_path, null);
    assertNoForbiddenDod007EvidenceLiterals(evidence, [tempDir, outputPath, verificationPath]);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test('DOD-008 workflow E2E evidence records request linkage scenarios schemas and commands', () => {
  const evidence = buildDod008WorkflowE2EValidationEvidence({
    verificationSummary: req894ValidationSummary,
  });

  assertDod008WorkflowE2EValidationEvidence(evidence, req894ValidationSummary);
  evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
  assert.equal(evidence.request_evidence_path, dod008WorkflowE2EValidationEvidenceRelativePath);
  assert.equal(evidence.request_metadata_snapshot.path, req894RequestMetadataRelativePath);
  assert.deepEqual(evidence.workflow_scenarios.scenario_paths, dod008WorkflowScenarioPaths);
  assert.equal(evidence.schema_results.workflow_schema_contract.status, 'pass');
  assert.equal(evidence.schema_results.core_workflow_harness.status, 'pass');
  assert.equal(evidence.schema_results.lifecycle_smoke_validation.status, 'pass');
  assert.equal(evidence.schema_results.artifact_parity_validation.status, 'pass');
  assert.equal(evidence.test_command_results.focused_workflow_validation.status, 'pass');
  assert.equal(evidence.test_command_results.schema_contract.status, 'pass');
  assert.equal(evidence.test_command_results.core_workflow_harness.status, 'pass');
  assert.equal(evidence.test_command_results.lifecycle_smoke.status, 'pass');
  assert.equal(evidence.test_command_results.artifact_parity.status, 'pass');
  assert.equal(evidence.test_command_results.npm_test.status, 'pass');
  assertNoForbiddenDod008EvidenceLiterals(evidence);
});

test('DOD-008 workflow E2E evidence preserves failed focused summaries without pass status', () => {
  const failingSummary = {
    ...req894ValidationSummary,
    focused_workflow_validation: {
      ...req894ValidationSummary.focused_workflow_validation,
      status: 'fail',
      tests_pass: 15,
      tests_fail: 1,
      summary: '15 passed, 1 failed: artifact parity blocker preserved',
    },
  };
  const evidence = buildDod008WorkflowE2EValidationEvidence({
    verificationSummary: failingSummary,
  });

  assert.equal(evidence.status, 'fail');
  assert.equal(evidence.evidence_lifecycle.focused_workflow_validation_pass, false);
  assert.equal(evidence.focused_workflow_validation_summary.status, 'fail');
  assert.equal(
    evidence.focused_workflow_validation_summary.focused_workflow_validation.summary,
    '15 passed, 1 failed: artifact parity blocker preserved',
  );
  assert.equal(
    evidence.test_command_results.focused_workflow_validation.summary,
    '15 passed, 1 failed: artifact parity blocker preserved',
  );
  assertNoForbiddenDod008EvidenceLiterals(evidence);
});

test('DOD-008 workflow E2E generator writes parseable request-level evidence shape', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'dod-008-workflow-e2e-'));
  const outputPath = join(tempDir, 'evidence.json');
  const verificationPath = join(tempDir, 'verification-summary.json');

  try {
    writeFileSync(`${verificationPath}`, `${JSON.stringify(req894ValidationSummary, null, 2)}\n`, 'utf8');

    const result = spawnSync(
      process.execPath,
      [
        'scripts/generate-dod-008-workflow-e2e-validation.mjs',
        outputPath,
        verificationPath,
      ],
      {
        cwd: repoRoot,
        encoding: 'utf8',
      },
    );

    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), outputPath);

    const evidence = JSON.parse(readFileSync(outputPath, 'utf8'));
    assertDod008WorkflowE2EValidationEvidence(evidence, req894ValidationSummary);
    evidence.input_paths_read.forEach(assertMetadataPathIsScoped);
    assert.equal(evidence.test_command_results.generator.generated_output_path, null);
    assertNoForbiddenDod008EvidenceLiterals(evidence, [tempDir, outputPath, verificationPath]);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test('DOD-008 generated workflow E2E artifact metadata has no forbidden literals', () => {
  const evidence = JSON.parse(readRepoFile(dod008WorkflowE2EValidationEvidenceRelativePath));

  assertDod008WorkflowE2EValidationEvidence(evidence, req894ValidationSummary);
  assertNoForbiddenDod008EvidenceLiterals(evidence);
});

test('DOD-009 Claude plugin regression matrix records canonical source surfaces', () => {
  const contract = buildDod009ClaudePluginRegressionMatrix();

  assertDod009ClaudePluginRegressionMatrix(contract);
  assert.deepEqual(dod009MatrixSurfacePaths, [
    '.claude-plugin/plugin.json',
    'package.json',
    '.claude-plugin/marketplace.json',
    'extension/manifest.json',
    'extension/package.json',
    'hooks/hooks.json',
    'skills/',
    'agents/',
  ]);
  assert.deepEqual(
    contract.matrix_surfaces.map((surface) => surface.canonical_source_path),
    dod009MatrixSurfacePaths,
  );
  assert.ok(
    contract.matrix_surfaces.every((surface) => surface.verification_scope === 'claude-canonical-source'),
  );
  assertNoForbiddenDod009ContractLiterals(contract.matrix_surfaces);
});

test('DOD-009 Claude plugin regression matrix validates version agents skills and hooks contracts', () => {
  const contract = buildDod009ClaudePluginRegressionMatrix();

  assert.equal(contract.contract_checks.version_sync.status, 'pass');
  assert.deepEqual(contract.contract_checks.version_sync.checked_paths, [
    'package.json',
    '.claude-plugin/plugin.json',
    '.claude-plugin/marketplace.json',
    'extension/manifest.json',
    'extension/package.json',
  ]);
  assert.equal(contract.contract_checks.version_sync.unique_version_count, 1);
  assert.equal(contract.contract_checks.agents_parity.status, 'pass');
  assert.equal(contract.contract_checks.agents_parity.missing_manifest_entries.length, 0);
  assert.equal(contract.contract_checks.agents_parity.extra_manifest_entries.length, 0);
  assert.equal(contract.contract_checks.skills_directory_registration.status, 'pass');
  assert.equal(contract.contract_checks.skills_directory_registration.manifest_skills_pointer, './skills/');
  assert.ok(contract.contract_checks.skills_directory_registration.skill_file_count > 0);
  assert.equal(contract.contract_checks.hooks_pointer.status, 'pass');
  assert.equal(contract.contract_checks.hooks_pointer.manifest_hooks_pointer, './hooks/hooks.json');
  assert.equal(contract.contract_checks.hooks_registration.status, 'pass');
  assert.deepEqual(contract.contract_checks.hooks_registration.command_paths, [
    '${CLAUDE_PLUGIN_ROOT}/hooks/mst-auto-chain-context.sh',
    '${CLAUDE_PLUGIN_ROOT}/hooks/mst-pre-tool-use.sh',
    '${CLAUDE_PLUGIN_ROOT}/hooks/mst-session-init.sh',
    '${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh',
  ]);
  assert.equal(contract.blocker_summary.status, 'pass');
  assert.deepEqual(contract.blocker_summary.human_readable, []);
});

test('DOD-009 no-go metadata guard rejects user-home and external mutation literals', () => {
  const contract = buildDod009ClaudePluginRegressionMatrix();
  const scannedMetadata = {
    matrix_surfaces: contract.matrix_surfaces,
    contract_checks: contract.contract_checks,
    no_go_metadata_guard: contract.no_go_metadata_guard,
    manual_readable_exports: contract.manual_readable_exports,
  };

  assert.equal(contract.forbidden_metadata_scan.status, 'pass');
  assert.equal(contract.forbidden_metadata_scan.violation_count, 0);
  assert.deepEqual(scanDod009RegressionMatrixMetadata(scannedMetadata), {
    status: 'pass',
    scanned_string_count: scanDod009RegressionMatrixMetadata(scannedMetadata).scanned_string_count,
    violation_count: 0,
    violations: [],
  });

  for (const forbiddenValue of [
    '/Users/example/.codex/config.toml',
    '~/project',
    '$HOME/project',
    '~/.codex/config.toml',
    '.claude/hooks/mst-stop-hook.sh',
    '../escape',
    '%2e%2e/escape',
    'codex plugins install mst',
    'codex plugins refresh',
    'codex plugins reload',
    'external install request',
    'cache refresh command',
    'ln -s skills ~/.agents/skills/gran-maestro',
  ]) {
    const scan = scanDod009RegressionMatrixMetadata({
      matrix_surfaces: [{ canonical_source_path: forbiddenValue }],
    });
    assert.equal(scan.status, 'fail', forbiddenValue);
    assert.ok(scan.violation_count > 0, forbiddenValue);
  }

  assertNoForbiddenDod009ContractLiterals(scannedMetadata);
});

test('DOD-009 excluded surfaces stay zero-count and blocker summary stays human-readable', () => {
  const contract = buildDod009ClaudePluginRegressionMatrix();
  const failingContract = buildDod009ClaudePluginRegressionMatrix({
    versionOverrides: {
      'extension/package.json': '9.9.9',
    },
  });

  assert.deepEqual(dod009ExcludedSurfaceIds, ['DOD-010', 'DOD-011', 'DOD-012', 'DOD-013']);
  assert.deepEqual(
    contract.manual_readable_exports.excluded_surface_ids,
    dod009ExcludedSurfaceIds,
  );
  assert.ok(contract.excluded_surfaces.every((surface) => surface.implementation_count === 0));
  assert.ok(contract.excluded_surfaces.every((surface) => surface.runtime_invocation_count === 0));
  assert.ok(contract.excluded_surfaces.every((surface) => surface.acceptance_gate_count === 0));
  assert.equal(failingContract.status, 'fail');
  assert.equal(failingContract.contract_checks.version_sync.status, 'fail');
  assert.ok(Array.isArray(failingContract.blocker_summary.human_readable));
  assert.ok(failingContract.blocker_summary.human_readable.length > 0);
  assert.match(
    failingContract.blocker_summary.human_readable.join('\n'),
    /extension\/package\.json/,
  );
});

test('codex hook adapter parity evidence records DOD-005 metadata and baseline references', () => {
  const evidence = buildCodexHookAdapterParityEvidence();

  assertCodexHookAdapterParityEvidence(evidence);
  assert.equal(evidence.evidence_path, hookAdapterEvidencePath);
  assert.equal(evidence.root_metadata.baseline_evidence_path, req888BaselineEvidencePath);
  assert.deepEqual(
    evidence.root_metadata.canonical_hook_script_paths,
    Object.values(canonicalHookScripts),
  );
});

test('codex hook adapter parity fixtures normalize the four target events', () => {
  const evidence = buildCodexHookAdapterParityEvidence();

  assert.equal(evidence.fixtures.SessionStart.fixture.normalized_stdin.hook_event_name, 'SessionStart');
  assert.equal(evidence.fixtures.SessionStart.fixture.normalized_env.MST_PROJECT_ROOT, '.');

  assert.equal(evidence.fixtures.PreToolUse.fixtures.skill_like.detected_matcher, 'Skill');
  assert.equal(
    evidence.fixtures.PreToolUse.fixtures.schedule_wakeup_like.detected_matcher,
    'ScheduleWakeup',
  );
  assert.deepEqual(evidence.fixtures.PreToolUse.blocker_codes, [
    'permission_metadata_loss',
    'unsupported_direct_shell_escape',
  ]);

  assert.equal(evidence.fixtures.Stop.continuation_loss_count, 0);
  assert.equal(
    evidence.fixtures.Stop.fixture.normalized_stdin.refeed_context.target_dod,
    'DOD-005',
  );

  assert.equal(
    evidence.fixtures.UserPromptSubmit.fixture.normalized_stdin.auto_chain_context.plan_id,
    'PLN-717',
  );
});

test('codex hook adapter manifest stays duplicate-free and plugin-root relative', () => {
  const evidence = buildCodexHookAdapterParityEvidence();

  assert.equal(evidence.codex_manifest.command_audit.status, 'pass');
  assert.equal(evidence.codex_manifest.command_audit.violation_count, 0);
  assert.equal(evidence.duplicate_registration_count, 0);
  assert.deepEqual(
    evidence.codex_manifest.command_audit.commands.map((entry) => entry.path_token),
    [
      './scripts/codex-hook-adapter-fixture.mjs',
      './scripts/codex-hook-adapter-fixture.mjs',
      './scripts/codex-hook-adapter-fixture.mjs',
      './scripts/codex-hook-adapter-fixture.mjs',
      './scripts/codex-hook-adapter-fixture.mjs',
    ],
  );
  assert.equal(evidence.no_go_guard.status, 'pass');
  assert.deepEqual(evidence.no_go_guard.excluded_dod_ids, hookAdapterExcludedDodIds);
});

test('codex hook adapter parity generator writes parseable evidence shape', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'codex-hook-adapter-parity-'));
  const outputPath = join(tempDir, 'evidence.json');

  try {
    const result = spawnSync(
      process.execPath,
      ['scripts/generate-codex-hook-adapter-parity.mjs', outputPath],
      {
        cwd: repoRoot,
        encoding: 'utf8',
      },
    );

    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), outputPath);

    const evidence = JSON.parse(readFileSync(outputPath, 'utf8'));
    assertCodexHookAdapterParityEvidence(evidence);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test('codex hook adapter validation evidence records command summaries and DOD-005 pass signals', () => {
  const parityEvidence = buildCodexHookAdapterParityEvidence();
  const validationEvidence = buildCodexHookAdapterValidationEvidence({
    parityEvidence,
    verificationSummary: req890ValidationSummary,
  });

  assertCodexHookAdapterValidationEvidence(validationEvidence, req890ValidationSummary);
  assert.equal(validationEvidence.request_evidence_path, hookAdapterValidationEvidencePath);
  assert.equal(validationEvidence.parity_evidence_path, hookAdapterEvidencePath);
  assert.equal(validationEvidence.duplicate_registration_count, 0);
  assert.equal(validationEvidence.continuation_loss_count, 0);
  assert.equal(validationEvidence.no_go_guard.status, 'pass');
});

test('REQ-890 request metadata snapshot stays aligned with DOD-005 validation evidence', () => {
  const validationEvidence = buildCodexHookAdapterValidationEvidence({
    verificationSummary: req890ValidationSummary,
  });
  const metadata = buildReq890Dod005RequestMetadata({
    validationEvidence,
    taskCommit: 'bbbe542',
    integrationCommit: '54f547e',
    validatedAt: '2026-05-19T05:42:00.000Z',
  });

  assert.equal(
    metadata.tasks['REQ-890-02'].verification.evidence_path,
    hookAdapterValidationEvidencePath,
  );
  assert.equal(
    metadata.tasks['REQ-890-02'].verification.parity_evidence_path,
    hookAdapterEvidencePath,
  );
  assert.equal(metadata.tasks['REQ-890-02'].verification.tests_total, 42);
  assert.equal(metadata.tasks['REQ-890-02'].verification.tests_pass, 42);
  assert.equal(metadata.tasks['REQ-890-02'].verification.tests_fail, 0);
  assert.equal(metadata.tasks['REQ-890-02'].verification.duplicate_registration_count, 0);
  assert.equal(metadata.tasks['REQ-890-02'].verification.continuation_loss_count, 0);
  assert.equal(metadata.phase2_result.status, 'pass');
  assert.equal(metadata.phase2_result.checks.hook_adapter_parity, 'pass');
  assert.equal(metadata.phase2_result.checks.hook_regression_subset, 'pass');
  assert.equal(metadata.phase2_result.checks.npm_test, 'pass');
  assert.equal(metadata.phase2_result.checks.parity_generator_parse, 'pass');
  assert.equal(metadata.result_paths.request_evidence_path, hookAdapterValidationEvidencePath);
  assert.equal(metadata.result_paths.parity_evidence_path, hookAdapterEvidencePath);
  assert.equal(metadata.result_paths.baseline_evidence_path, req888BaselineEvidencePath);
});

test('codex hook adapter validation generator writes parseable request-level evidence shape', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'codex-hook-adapter-validation-'));
  const outputPath = join(tempDir, 'evidence.json');
  const verificationPath = join(tempDir, 'verification-summary.json');

  try {
    writeFileSync(`${verificationPath}`, `${JSON.stringify(req890ValidationSummary, null, 2)}\n`, 'utf8');

    const result = spawnSync(
      process.execPath,
      [
        'scripts/generate-dod-005-codex-hook-adapter-validation.mjs',
        outputPath,
        verificationPath,
      ],
      {
        cwd: repoRoot,
        encoding: 'utf8',
      },
    );

    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), outputPath);

    const evidence = JSON.parse(readFileSync(outputPath, 'utf8'));
    assertCodexHookAdapterValidationEvidence(evidence, req890ValidationSummary);
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
});

test('AskUserQuestion contract requires meaningful labels and preview details', () => {
  const planSkill = readRepoFile('skills/plan/SKILL.md');

  assert.match(planSkill, /content-decision explicit option label은 bare/);
  assert.match(planSkill, /A\. \{의미 요약\}/);
  assert.match(planSkill, /UI가 자동 추가하므로.*explicit option을 수동으로 넣지 않는다/);
  assert.match(planSkill, /`description` 또는 `preview` 필드/);
  assert.match(planSkill, /## 장점[\s\S]*## 단점[\s\S]*## PM 추천 의견/);
});

test('AskUserQuestion visual comparison sample includes a text wireframe', () => {
  const planSkill = readRepoFile('skills/plan/SKILL.md');

  assert.match(planSkill, /visual-comparison single-select/);
  assert.match(planSkill, /preview: \|[\s\S]*대시보드[\s\S]*┌[\s\S]*│[\s\S]*└/);
  assert.match(planSkill, /화면명이나 컴포넌트명을 포함/);
});

test('AskUserQuestion multiSelect samples keep detail in descriptions', () => {
  const planSkill = readRepoFile('skills/plan/SKILL.md');
  const stitchSkill = readRepoFile('skills/stitch/SKILL.md');

  assert.match(planSkill, /`multiSelect: true`에서는 preview가 표시되지 않으므로/);
  assert.match(planSkill, /\[장점\][\s\S]*\[단점\][\s\S]*\[적합\]/);
  assert.match(stitchSkill, /`"A\. \{스타일명1\}"`/);
  assert.match(stitchSkill, /각 option\.description에는 `\[장점\]`, `\[단점\]`, `\[적합\]`/);
});
