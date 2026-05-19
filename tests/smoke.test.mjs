import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  assertCodexSkillAgentProjectionValidationEvidence,
  assertCodexPluginDiscoverySmokeEvidence,
  assertCodexRoleMappingEvidence,
  assertCodexSkillProjectionEvidence,
  buildCodexSkillAgentProjectionValidationEvidence,
  buildCodexPluginDiscoverySmokeEvidence,
  buildCodexRoleMappingEvidence,
  buildCodexSkillProjectionEvidence,
  collectUnsupportedBlockers,
  coreMstSkillNames,
  defaultCodexSkillAgentProjectionValidationSummary,
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
