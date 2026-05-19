import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  assertCodexPluginDiscoverySmokeEvidence,
  buildCodexPluginDiscoverySmokeEvidence,
  collectUnsupportedBlockers,
  fallbackSkillDiscoveryRootPath,
  fallbackSkillRepoTargetPath,
  fallbackSkillSymlinkPath,
  forcedWireEvidenceRelativePath,
  generatedAssetBaselinePaths,
  generatedManifestPath,
  generatedMarketplacePath,
  integrationEvidencePath,
  inventoryArtifactPath,
  orchestrationRoot,
  parityEvidencePath,
  req888Dod004Metadata,
  repoRoot as smokeRepoRoot,
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

function readRepoFile(path) {
  return readFileSync(join(repoRoot, path), 'utf8');
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
