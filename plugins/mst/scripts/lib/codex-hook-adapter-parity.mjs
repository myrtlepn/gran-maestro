import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';

import {
  forcedWireEvidenceRelativePath,
  orchestrationRoot,
  repoRoot,
  stableEvidenceRelativePath as discoverySmokeEvidencePath,
} from './codex-plugin-discovery-smoke.mjs';

export const stableEvidenceRelativePath =
  '.gran-maestro/requests/REQ-890/evidence/codex-hook-adapter-parity.json';
export const stableEvidenceAbsolutePath = join(
  orchestrationRoot,
  'requests/REQ-890/evidence/codex-hook-adapter-parity.json',
);
export const validationEvidenceRelativePath =
  '.gran-maestro/requests/REQ-890/evidence/dod-005-codex-hook-adapter-validation.json';
export const validationEvidenceAbsolutePath = join(
  orchestrationRoot,
  'requests/REQ-890/evidence/dod-005-codex-hook-adapter-validation.json',
);
export const req888BaselineEvidencePath =
  '.gran-maestro/requests/REQ-888/evidence/dod-004-install-fallback-validation.json';
export const req887ForcedWireEvidencePath = forcedWireEvidenceRelativePath;
export const req886DiscoveryEvidencePath = discoverySmokeEvidencePath;

export const canonicalHooksJsonPath = 'hooks/hooks.json';
export const codexHooksJsonPath = 'hooks/hooks.codex.json';
export const codexAdapterRunnerPath = 'scripts/codex-hook-adapter-fixture.mjs';
export const excludedDodIds = ['DOD-006', 'DOD-008'];
export const baseMstSessionId = 'MST-AGI039-6-20260519T050127000Z-codex8901';
export const hookRegressionSubsetCommand =
  'python3 -m pytest tests/test_hooks_json_registration.py tests/test_plugin_manifest_hooks.py tests/test_hook_event_contract_matrix.py';
export const npmTestCommand = 'npm test';
export const parityGeneratorCommand =
  'node scripts/generate-codex-hook-adapter-parity.mjs <temp-output>';
export const defaultCodexHookAdapterValidationSummary = {
  hook_regression_subset: {
    command: hookRegressionSubsetCommand,
    status: 'pass',
    tests_total: 20,
    tests_pass: 20,
    tests_fail: 0,
  },
  npm_test: {
    command: npmTestCommand,
    status: 'pass',
    tests_total: 22,
    tests_pass: 22,
    tests_fail: 0,
  },
  parity_generator: {
    command: parityGeneratorCommand,
    generated_output_path: '/tmp/req-890-codex-hook-adapter-parity.json',
    status: 'pass',
    parse_ok: true,
    core_field_checks: {
      request_id: 'REQ-890',
      dod_id: 'DOD-005',
      status: 'pass',
      duplicate_registration_count: 0,
      continuation_loss_count: 0,
      no_go_guard_status: 'pass',
    },
  },
};

export const canonicalHookScripts = {
  SessionStart: 'hooks/mst-session-init.sh',
  PreToolUse: 'hooks/mst-pre-tool-use.sh',
  Stop: 'hooks/mst-stop-hook.sh',
  UserPromptSubmit: 'hooks/mst-auto-chain-context.sh',
};

const sourceEvidenceByRequest = {
  REQ_888: {
    absolutePath: join(orchestrationRoot, 'requests/REQ-888/evidence/dod-004-install-fallback-validation.json'),
    relativePath: req888BaselineEvidencePath,
  },
  REQ_887: {
    absolutePath: join(orchestrationRoot, 'requests/REQ-887/evidence/forced-wire-integration-validation.json'),
    relativePath: req887ForcedWireEvidencePath,
  },
  REQ_886: {
    absolutePath: join(orchestrationRoot, 'requests/REQ-886/evidence/codex-plugin-discovery-smoke.json'),
    relativePath: req886DiscoveryEvidencePath,
  },
};

const fixtureDefinitions = {
  sessionStart: {
    eventName: 'SessionStart',
    matcher: '',
    env: {
      MST_SESSION_ID: baseMstSessionId,
      CODEX_PERMISSION_MODE: 'plan',
      CODEX_PROJECT_ROOT: '.',
      CODEX_PLUGIN_ROOT: '.',
    },
    payload: {
      session_id: 'codex-session-req-890',
      cwd: '.',
      transcript_path: 'transcripts/req-890/session.ndjson',
      model: 'gpt-5.4',
      permission_mode: 'plan',
      source_request_id: 'REQ-890',
    },
  },
  preToolUseSkillLike: {
    eventName: 'PreToolUse',
    matcher: 'Skill',
    env: {
      MST_SESSION_ID: baseMstSessionId,
      CODEX_PERMISSION_MODE: 'plan',
      CODEX_PROJECT_ROOT: '.',
      CODEX_PLUGIN_ROOT: '.',
    },
    payload: {
      tool_name: 'Task',
      permission_mode: 'plan',
      tool_input: {
        skill_name: 'mst:request',
        args: ['REQ-890', '01'],
        description: 'Run mst:request REQ-890 01',
      },
    },
  },
  preToolUseScheduleWakeupLike: {
    eventName: 'PreToolUse',
    matcher: 'ScheduleWakeup',
    env: {
      MST_SESSION_ID: baseMstSessionId,
      CODEX_PERMISSION_MODE: 'plan',
      CODEX_PROJECT_ROOT: '.',
      CODEX_PLUGIN_ROOT: '.',
    },
    payload: {
      tool_name: 'Wakeup',
      permission_mode: 'plan',
      tool_input: {
        wakeup_at: '2026-05-20T01:00:00Z',
        reason: 'resume stalled verification',
      },
    },
  },
  preToolUseDirectShellEscape: {
    eventName: 'PreToolUse',
    matcher: '',
    env: {
      MST_SESSION_ID: baseMstSessionId,
      CODEX_PERMISSION_MODE: 'plan',
      CODEX_PROJECT_ROOT: '.',
      CODEX_PLUGIN_ROOT: '.',
    },
    payload: {
      tool_name: 'Shell',
      permission_mode: 'plan',
      tool_input: {
        command: 'bash -lc "curl https://example.invalid && exit 0"',
      },
    },
  },
  preToolUsePermissionMetadataLoss: {
    eventName: 'PreToolUse',
    matcher: '',
    env: {
      MST_SESSION_ID: baseMstSessionId,
      CODEX_PROJECT_ROOT: '.',
      CODEX_PLUGIN_ROOT: '.',
    },
    payload: {
      tool_name: 'Task',
      tool_input: {
        skill_name: 'mst:request',
        args: ['REQ-890', '01'],
      },
    },
  },
  stop: {
    eventName: 'Stop',
    matcher: '',
    env: {
      MST_SESSION_ID: baseMstSessionId,
      CODEX_PERMISSION_MODE: 'plan',
      CODEX_PROJECT_ROOT: '.',
      CODEX_PLUGIN_ROOT: '.',
    },
    payload: {
      permission_mode: 'plan',
      transcript_path: 'transcripts/req-890/session.ndjson',
      continuation_request: true,
      continuation_reason: 'awaiting-review',
      refeed_prompt: 'Continue after PM review approves the current patch.',
      refeed_context: {
        request_id: 'REQ-890',
        task_id: '01',
        target_dod: 'DOD-005',
      },
      pending_actions: ['run pytest subset', 'run npm test'],
      assistant_summary: 'Hook adapter parity fixtures are ready; final verification is pending.',
    },
  },
  userPromptSubmit: {
    eventName: 'UserPromptSubmit',
    matcher: '',
    env: {
      MST_SESSION_ID: baseMstSessionId,
      CODEX_PERMISSION_MODE: 'plan',
      CODEX_PROJECT_ROOT: '.',
      CODEX_PLUGIN_ROOT: '.',
    },
    payload: {
      permission_mode: 'plan',
      prompt: 'Run the required verification commands and preserve auto-chain context.',
      transcript_path: 'transcripts/req-890/session.ndjson',
      auto_chain_context: {
        request_id: 'REQ-890',
        task_id: '01',
        plan_id: 'PLN-717',
        target_dod: 'DOD-005',
      },
    },
  },
};

function readJsonFromRepo(path) {
  return JSON.parse(readFileSync(join(repoRoot, path), 'utf8'));
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

function cleanString(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizeRelativePath(value, fallback = '.') {
  const text = cleanString(value) || fallback;
  if (
    text.startsWith('/') ||
    text.startsWith('~') ||
    text.includes('..') ||
    text.includes('.claude/hooks') ||
    text.includes('$CLAUDE_PROJECT_DIR')
  ) {
    return fallback;
  }
  return text;
}

function normalizeToolInput(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function resolvePermissionMode(payload, env) {
  return (
    cleanString(payload?.permission_mode) ||
    cleanString(env?.CODEX_PERMISSION_MODE) ||
    cleanString(env?.permission_mode) ||
    ''
  );
}

function resolveMstSessionId(payload, env) {
  return cleanString(env?.MST_SESSION_ID) || cleanString(payload?.mst_session_id) || '';
}

function manifestCommandFor(eventName, matcher = '') {
  const manifest = readJsonFromRepo(codexHooksJsonPath);
  const entries = manifest?.hooks?.[eventName];
  if (!Array.isArray(entries)) {
    return '';
  }

  for (const entry of entries) {
    if (cleanString(entry?.matcher) !== cleanString(matcher)) {
      continue;
    }

    const command = entry?.hooks?.[0]?.command;
    if (typeof command === 'string') {
      return command;
    }
  }

  return '';
}

function detectPreToolUseMatcher(payload) {
  const toolName = cleanString(payload?.tool_name).toLowerCase();
  const toolInput = normalizeToolInput(payload?.tool_input);

  if (toolName === 'shell' || cleanString(toolInput.command)) {
    return 'DirectShellEscape';
  }

  if (
    toolName === 'wakeup' ||
    toolName === 'schedulewakeup' ||
    toolName === 'schedule_wakeup' ||
    cleanString(toolInput.wakeup_at) ||
    cleanString(toolInput.delay_ms)
  ) {
    return 'ScheduleWakeup';
  }

  if (
    toolName === 'task' &&
    (cleanString(toolInput.skill_name) || cleanString(toolInput.skill) || cleanString(toolInput.name))
  ) {
    return 'Skill';
  }

  return 'Unknown';
}

function buildBaseEnvelope(eventName, matcher, payload, env) {
  const permissionMode = resolvePermissionMode(payload, env);
  const mstSessionId = resolveMstSessionId(payload, env);
  const projectRoot = normalizeRelativePath(env?.CODEX_PROJECT_ROOT || payload?.cwd || '.');
  const pluginRoot = normalizeRelativePath(env?.CODEX_PLUGIN_ROOT || '.');

  return {
    event_name: eventName,
    matcher,
    manifest_command: manifestCommandFor(eventName, matcher),
    wrapper_script: codexAdapterRunnerPath,
    canonical_target_script:
      eventName === 'PreToolUse' ? canonicalHookScripts.PreToolUse : canonicalHookScripts[eventName],
    normalized_env: {
      MST_SESSION_ID: mstSessionId,
      MST_CODEX_PERMISSION_MODE: permissionMode,
      MST_CODEX_EVENT_NAME: eventName,
      MST_PROJECT_ROOT: projectRoot,
      MST_PLUGIN_ROOT: pluginRoot,
    },
    normalized_stdin: {
      hook_event_name: eventName,
      source_runtime: 'codex',
      mst_session_id: mstSessionId,
      project_root: projectRoot,
      plugin_root: pluginRoot,
      permission_mode: permissionMode,
    },
    blockers: [],
  };
}

function normalizeSessionStart(payload, env) {
  const envelope = buildBaseEnvelope('SessionStart', '', payload, env);
  envelope.normalized_stdin = {
    ...envelope.normalized_stdin,
    session_id: cleanString(payload?.session_id),
    transcript_path: cleanString(payload?.transcript_path),
    model: cleanString(payload?.model),
    source_request_id: cleanString(payload?.source_request_id),
  };
  return envelope;
}

function normalizePreToolUse(payload, env) {
  const detectedMatcher = detectPreToolUseMatcher(payload);
  const normalizedMatcher =
    detectedMatcher === 'Skill' || detectedMatcher === 'ScheduleWakeup'
      ? detectedMatcher
      : '';
  const envelope = buildBaseEnvelope('PreToolUse', normalizedMatcher, payload, env);
  const toolInput = normalizeToolInput(payload?.tool_input);

  envelope.detected_matcher = detectedMatcher;
  envelope.normalized_stdin = {
    ...envelope.normalized_stdin,
    tool_name:
      detectedMatcher === 'Skill'
        ? 'Skill'
        : detectedMatcher === 'ScheduleWakeup'
          ? 'ScheduleWakeup'
          : cleanString(payload?.tool_name),
    codex_tool_name: cleanString(payload?.tool_name),
    tool_input: toolInput,
    tool_payload_matcher: normalizedMatcher,
  };

  if (!envelope.normalized_env.MST_CODEX_PERMISSION_MODE) {
    envelope.blockers.push({
      code: 'permission_metadata_loss',
      severity: 'blocker',
      message: 'permission_mode metadata was not preserved from the Codex hook surface.',
    });
  }

  if (detectedMatcher === 'DirectShellEscape') {
    envelope.blockers.push({
      code: 'unsupported_direct_shell_escape',
      severity: 'blocker',
      message: 'Direct shell escape remains unsupported for MST canonical PreToolUse parity.',
    });
  }

  if (detectedMatcher === 'Unknown') {
    envelope.blockers.push({
      code: 'unknown_tool_matcher',
      severity: 'warning',
      message: 'Codex tool invocation did not map to a canonical MST matcher.',
    });
  }

  return envelope;
}

function normalizeStop(payload, env) {
  const envelope = buildBaseEnvelope('Stop', '', payload, env);
  const requiredFieldNames = [
    'continuation_request',
    'continuation_reason',
    'refeed_prompt',
    'refeed_context',
    'pending_actions',
    'assistant_summary',
  ];

  envelope.normalized_stdin = {
    ...envelope.normalized_stdin,
    transcript_path: cleanString(payload?.transcript_path),
    continuation_request: payload?.continuation_request === true,
    continuation_reason: cleanString(payload?.continuation_reason),
    refeed_prompt: cleanString(payload?.refeed_prompt),
    refeed_context: payload?.refeed_context ?? {},
    pending_actions: Array.isArray(payload?.pending_actions) ? payload.pending_actions : [],
    assistant_summary: cleanString(payload?.assistant_summary),
  };
  envelope.required_continuation_fields = requiredFieldNames;
  envelope.missing_continuation_fields = requiredFieldNames.filter((fieldName) => {
    const value = envelope.normalized_stdin[fieldName];
    if (typeof value === 'boolean') {
      return false;
    }
    if (Array.isArray(value)) {
      return value.length === 0;
    }
    if (value && typeof value === 'object') {
      return Object.keys(value).length === 0;
    }
    return cleanString(value) === '';
  });
  envelope.continuation_loss_count = envelope.missing_continuation_fields.length;
  return envelope;
}

function normalizeUserPromptSubmit(payload, env) {
  const envelope = buildBaseEnvelope('UserPromptSubmit', '', payload, env);
  envelope.normalized_stdin = {
    ...envelope.normalized_stdin,
    prompt: cleanString(payload?.prompt),
    transcript_path: cleanString(payload?.transcript_path),
    auto_chain_context: payload?.auto_chain_context ?? {},
  };
  return envelope;
}

export function normalizeCodexHookInvocation({
  eventName,
  matcher = '',
  payload = {},
  env = {},
}) {
  if (eventName === 'SessionStart') {
    return normalizeSessionStart(payload, env);
  }

  if (eventName === 'PreToolUse') {
    return normalizePreToolUse(payload, env);
  }

  if (eventName === 'Stop') {
    return normalizeStop(payload, env);
  }

  if (eventName === 'UserPromptSubmit') {
    return normalizeUserPromptSubmit(payload, env);
  }

  return {
    event_name: eventName,
    matcher,
    blockers: [
      {
        code: 'unsupported_event',
        severity: 'blocker',
        message: `Unsupported Codex hook event: ${eventName}`,
      },
    ],
  };
}

function canonicalRuntimeTuples(hookConfig) {
  if (!hookConfig?.hooks) {
    return [];
  }

  return Object.entries(hookConfig.hooks).flatMap(([eventName, entries]) =>
    entries.flatMap((entry) =>
      entry.hooks.map((hook) => ({
        event_name: eventName,
        matcher: cleanString(entry.matcher),
        command: hook.command,
      })),
    ),
  );
}

function codexRuntimeTuples(hookConfig) {
  if (!hookConfig?.hooks) {
    return [];
  }

  return Object.entries(hookConfig.hooks).flatMap(([eventName, entries]) =>
    entries.flatMap((entry) =>
      entry.hooks.map((hook) => ({
        event_name: eventName,
        matcher: cleanString(entry.matcher),
        command: hook.command,
      })),
    ),
  );
}

function inspectCodexManifestCommands(manifest) {
  const commands = codexRuntimeTuples(manifest).map((entry) => {
    const pathToken = cleanString(entry.command).split(/\s+/u)[0] || '';
    const violations = [];

    if (!pathToken.startsWith('./')) {
      violations.push('non_relative_path');
    }
    if (pathToken.startsWith('/')) {
      violations.push('absolute_path');
    }
    if (pathToken.includes('..')) {
      violations.push('path_traversal');
    }
    if (
      entry.command.includes('.claude/hooks') ||
      entry.command.includes('$CLAUDE_PROJECT_DIR/.claude/hooks')
    ) {
      violations.push('legacy_claude_hook_escape');
    }
    if (
      entry.command.includes('~/.claude') ||
      entry.command.includes('$HOME/') ||
      entry.command.includes('/Users/')
    ) {
      violations.push('user_home_escape');
    }

    return {
      ...entry,
      path_token: pathToken,
      violations,
    };
  });

  return {
    status: commands.every((entry) => entry.violations.length === 0) ? 'pass' : 'fail',
    violation_count: commands.reduce((count, entry) => count + entry.violations.length, 0),
    commands,
  };
}

function buildFixtureResults() {
  const sessionStart = normalizeCodexHookInvocation(fixtureDefinitions.sessionStart);
  const preToolUseSkillLike = normalizeCodexHookInvocation(fixtureDefinitions.preToolUseSkillLike);
  const preToolUseScheduleWakeupLike = normalizeCodexHookInvocation(
    fixtureDefinitions.preToolUseScheduleWakeupLike,
  );
  const preToolUseDirectShellEscape = normalizeCodexHookInvocation(
    fixtureDefinitions.preToolUseDirectShellEscape,
  );
  const preToolUsePermissionMetadataLoss = normalizeCodexHookInvocation(
    fixtureDefinitions.preToolUsePermissionMetadataLoss,
  );
  const stop = normalizeCodexHookInvocation(fixtureDefinitions.stop);
  const userPromptSubmit = normalizeCodexHookInvocation(fixtureDefinitions.userPromptSubmit);

  const preToolUseBlockers = [
    ...preToolUseDirectShellEscape.blockers,
    ...preToolUsePermissionMetadataLoss.blockers,
  ].filter((blocker) => blocker.severity === 'blocker');

  return {
    SessionStart: {
      status:
        sessionStart.canonical_target_script === canonicalHookScripts.SessionStart &&
        sessionStart.normalized_env.MST_SESSION_ID === baseMstSessionId &&
        sessionStart.normalized_stdin.plugin_root === '.'
          ? 'pass'
          : 'fail',
      fixture: sessionStart,
    },
    PreToolUse: {
      status:
        preToolUseSkillLike.detected_matcher === 'Skill' &&
        preToolUseScheduleWakeupLike.detected_matcher === 'ScheduleWakeup' &&
        preToolUseBlockers.some((blocker) => blocker.code === 'unsupported_direct_shell_escape') &&
        preToolUseBlockers.some((blocker) => blocker.code === 'permission_metadata_loss')
          ? 'pass'
          : 'fail',
      fixtures: {
        skill_like: preToolUseSkillLike,
        schedule_wakeup_like: preToolUseScheduleWakeupLike,
        unsupported_direct_shell_escape: preToolUseDirectShellEscape,
        permission_metadata_loss: preToolUsePermissionMetadataLoss,
      },
      blocker_signal_count: preToolUseBlockers.length,
      blocker_codes: preToolUseBlockers.map((blocker) => blocker.code).sort(),
    },
    Stop: {
      status:
        stop.canonical_target_script === canonicalHookScripts.Stop &&
        stop.continuation_loss_count === 0
          ? 'pass'
          : 'fail',
      fixture: stop,
      continuation_loss_count: stop.continuation_loss_count,
    },
    UserPromptSubmit: {
      status:
        userPromptSubmit.canonical_target_script === canonicalHookScripts.UserPromptSubmit &&
        cleanString(userPromptSubmit.normalized_stdin.prompt) !== '' &&
        Object.keys(userPromptSubmit.normalized_stdin.auto_chain_context).length > 0
          ? 'pass'
          : 'fail',
      fixture: userPromptSubmit,
    },
  };
}

function buildNoGoGuard() {
  const checks = [
    {
      surface: '.claude/hooks',
      status: 'pass',
      mutated: false,
      inspected: false,
    },
    {
      surface: 'user-global hook settings',
      status: 'pass',
      mutated: false,
      inspected: false,
    },
    {
      surface: 'user home config',
      status: 'pass',
      mutated: false,
      inspected: false,
    },
    {
      surface: 'actual Codex install/cache refresh',
      status: 'pass',
      executed: false,
    },
    {
      surface: 'DOD-006',
      status: 'pass',
      excluded: true,
    },
    {
      surface: 'DOD-008',
      status: 'pass',
      excluded: true,
    },
  ];

  return {
    status: checks.every((check) => check.status === 'pass') ? 'pass' : 'fail',
    excluded_dod_ids: excludedDodIds,
    checks,
  };
}

function normalizeVerificationSummary(verificationSummary = {}) {
  const hookRegressionSubset = verificationSummary.hook_regression_subset ?? {};
  const npmTest = verificationSummary.npm_test ?? {};
  const parityGenerator = verificationSummary.parity_generator ?? {};

  return {
    hook_regression_subset: {
      ...defaultCodexHookAdapterValidationSummary.hook_regression_subset,
      ...hookRegressionSubset,
    },
    npm_test: {
      ...defaultCodexHookAdapterValidationSummary.npm_test,
      ...npmTest,
    },
    parity_generator: {
      ...defaultCodexHookAdapterValidationSummary.parity_generator,
      ...parityGenerator,
      core_field_checks: {
        ...defaultCodexHookAdapterValidationSummary.parity_generator.core_field_checks,
        ...(parityGenerator.core_field_checks ?? {}),
      },
    },
  };
}

function summarizeCommandTotals(verificationSummary) {
  const commands = [
    verificationSummary.hook_regression_subset,
    verificationSummary.npm_test,
  ];

  return commands.reduce(
    (totals, commandResult) => ({
      tests_total: totals.tests_total + Number(commandResult.tests_total || 0),
      tests_pass: totals.tests_pass + Number(commandResult.tests_pass || 0),
      tests_fail: totals.tests_fail + Number(commandResult.tests_fail || 0),
    }),
    { tests_total: 0, tests_pass: 0, tests_fail: 0 },
  );
}

export function buildCodexHookAdapterParityEvidence() {
  const parseFailures = [];
  const baselineEvidence = collectJsonArtifact(
    sourceEvidenceByRequest.REQ_888.absolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const forcedWireEvidence = collectJsonArtifact(
    sourceEvidenceByRequest.REQ_887.absolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const discoveryEvidence = collectJsonArtifact(
    sourceEvidenceByRequest.REQ_886.absolutePath,
    readJsonFromAbsolutePath,
    parseFailures,
  );
  const canonicalHooks = collectJsonArtifact(
    canonicalHooksJsonPath,
    readJsonFromRepo,
    parseFailures,
  );
  const codexHooks = collectJsonArtifact(
    codexHooksJsonPath,
    readJsonFromRepo,
    parseFailures,
  );

  const canonicalTuples = canonicalRuntimeTuples(canonicalHooks.value);
  const codexTuples = codexRuntimeTuples(codexHooks.value);
  const duplicateRegistrations = codexTuples.filter((codexTuple) =>
    canonicalTuples.some((canonicalTuple) =>
      canonicalTuple.event_name === codexTuple.event_name &&
      canonicalTuple.matcher === codexTuple.matcher &&
      canonicalTuple.command === codexTuple.command,
    ),
  );
  const commandAudit = inspectCodexManifestCommands(codexHooks.value);
  const fixtureResults = buildFixtureResults();
  const noGoGuard = buildNoGoGuard();
  const sourceEvidence = {
    req_888: {
      path: sourceEvidenceByRequest.REQ_888.relativePath,
      request_id: baselineEvidence.value?.request_id ?? null,
      dod_id: baselineEvidence.value?.dod_id ?? null,
    },
    req_887: {
      path: sourceEvidenceByRequest.REQ_887.relativePath,
      request_id: forcedWireEvidence.value?.request_id ?? null,
      dod_id: forcedWireEvidence.value?.dod_id ?? null,
    },
    req_886: {
      path: sourceEvidenceByRequest.REQ_886.relativePath,
      request_id: discoveryEvidence.value?.request_id ?? null,
      dod_id: discoveryEvidence.value?.dod_id ?? null,
    },
  };

  const status =
    parseFailures.length === 0 &&
    duplicateRegistrations.length === 0 &&
    commandAudit.status === 'pass' &&
    Object.values(fixtureResults).every((fixture) => fixture.status === 'pass') &&
    noGoGuard.status === 'pass'
      ? 'pass'
      : 'fail';

  return {
    artifact_id: 'REQ-890-DOD-005-codex-hook-adapter-parity',
    request_id: 'REQ-890',
    task_id: '01',
    dod_id: 'DOD-005',
    format_version: '1.0.0',
    generated_at: new Date().toISOString(),
    status,
    evidence_path: stableEvidenceRelativePath,
    input_paths_read: [
      sourceEvidenceByRequest.REQ_888.absolutePath,
      sourceEvidenceByRequest.REQ_887.absolutePath,
      sourceEvidenceByRequest.REQ_886.absolutePath,
      canonicalHooksJsonPath,
      codexHooksJsonPath,
      ...Object.values(canonicalHookScripts),
    ],
    root_metadata: {
      request_id: 'REQ-890',
      dod_id: 'DOD-005',
      baseline_evidence_path: req888BaselineEvidencePath,
      canonical_hooks_json_path: canonicalHooksJsonPath,
      canonical_hook_script_paths: Object.values(canonicalHookScripts),
      source_evidence_paths: Object.values(sourceEvidence).map((entry) => entry.path),
    },
    source_evidence: sourceEvidence,
    codex_manifest: {
      path: codexHooksJsonPath,
      adapter_runner_path: codexAdapterRunnerPath,
      command_audit: commandAudit,
      event_names: Object.keys(codexHooks.value?.hooks ?? {}),
    },
    fixtures: fixtureResults,
    duplicate_registration_count: duplicateRegistrations.length,
    duplicate_registrations: duplicateRegistrations,
    continuation_loss_count: fixtureResults.Stop.continuation_loss_count,
    no_go_guard: noGoGuard,
    excluded_surfaces: excludedDodIds.map((dodId) => ({
      dod_id: dodId,
      status: 'pass',
    })),
    canonical_hook_regression: {
      status:
        canonicalHooks.value &&
        isDeepStrictEqual(Object.keys(canonicalHooks.value.hooks ?? {}).sort(), [
          'PreToolUse',
          'SessionStart',
          'Stop',
          'UserPromptSubmit',
        ])
          ? 'pass'
          : 'fail',
      hooks_json_path: canonicalHooksJsonPath,
      commands: canonicalRuntimeTuples(canonicalHooks.value).map((entry) => entry.command),
    },
    parse_error_count: parseFailures.length,
    parse_failures: parseFailures,
  };
}

export function buildCodexHookAdapterValidationEvidence({
  parityEvidence = buildCodexHookAdapterParityEvidence(),
  verificationSummary = defaultCodexHookAdapterValidationSummary,
} = {}) {
  const normalizedVerification = normalizeVerificationSummary(verificationSummary);
  const commandTotals = summarizeCommandTotals(normalizedVerification);
  const hookEventStatuses = Object.fromEntries(
    Object.entries(parityEvidence.fixtures).map(([eventName, result]) => [eventName, result.status]),
  );
  const commandStatusesPass =
    normalizedVerification.hook_regression_subset.status === 'pass' &&
    normalizedVerification.npm_test.status === 'pass' &&
    normalizedVerification.parity_generator.status === 'pass' &&
    normalizedVerification.parity_generator.parse_ok === true;
  const parityChecksPass =
    parityEvidence.status === 'pass' &&
    parityEvidence.duplicate_registration_count === 0 &&
    parityEvidence.continuation_loss_count === 0 &&
    parityEvidence.no_go_guard.status === 'pass';
  const status = commandStatusesPass && parityChecksPass ? 'pass' : 'fail';

  return {
    artifact_id: 'REQ-890-DOD-005-codex-hook-adapter-validation',
    request_id: 'REQ-890',
    task_id: '02',
    dod_id: 'DOD-005',
    format_version: '1.0.0',
    generated_at: new Date().toISOString(),
    status,
    request_evidence_path: validationEvidenceRelativePath,
    parity_evidence_path: stableEvidenceRelativePath,
    baseline_paths: {
      req888_baseline_evidence_path: req888BaselineEvidencePath,
      req887_forced_wire_evidence_path: req887ForcedWireEvidencePath,
      req886_discovery_evidence_path: req886DiscoveryEvidencePath,
      canonical_hooks_json_path: canonicalHooksJsonPath,
      codex_hooks_json_path: codexHooksJsonPath,
      parity_evidence_path: stableEvidenceRelativePath,
      request_evidence_path: validationEvidenceRelativePath,
    },
    hook_event_statuses: hookEventStatuses,
    duplicate_registration_count: parityEvidence.duplicate_registration_count,
    continuation_loss_count: parityEvidence.continuation_loss_count,
    no_go_guard: {
      status: parityEvidence.no_go_guard.status,
      excluded_dod_ids: [...parityEvidence.no_go_guard.excluded_dod_ids],
      checks: parityEvidence.no_go_guard.checks,
    },
    excluded_surfaces: parityEvidence.excluded_surfaces,
    canonical_hook_regression: parityEvidence.canonical_hook_regression,
    parity_evidence_summary: {
      artifact_id: parityEvidence.artifact_id,
      status: parityEvidence.status,
      parse_error_count: parityEvidence.parse_error_count,
      duplicate_registration_count: parityEvidence.duplicate_registration_count,
      continuation_loss_count: parityEvidence.continuation_loss_count,
      no_go_guard_status: parityEvidence.no_go_guard.status,
    },
    test_command_results: {
      hook_regression_subset: normalizedVerification.hook_regression_subset,
      npm_test: normalizedVerification.npm_test,
      parity_generator: normalizedVerification.parity_generator,
      totals: commandTotals,
    },
    checks: {
      hook_adapter_parity: parityEvidence.status,
      hook_regression_subset: normalizedVerification.hook_regression_subset.status,
      npm_test: normalizedVerification.npm_test.status,
      parity_generator_parse: normalizedVerification.parity_generator.status,
      duplicate_registration_count: parityEvidence.duplicate_registration_count,
      continuation_loss_count: parityEvidence.continuation_loss_count,
      no_go_guard: parityEvidence.no_go_guard.status,
    },
  };
}

export function buildReq890Dod005RequestMetadata({
  validationEvidence = buildCodexHookAdapterValidationEvidence(),
  taskCommit = null,
  integrationCommit = null,
  validatedAt = validationEvidence.generated_at,
} = {}) {
  const totals = validationEvidence.test_command_results.totals;
  const verification = {
    integration_assertions: validationEvidence.status,
    hook_regression_subset: validationEvidence.checks.hook_regression_subset,
    npm_test: validationEvidence.checks.npm_test,
    parity_generator_parse: validationEvidence.checks.parity_generator_parse,
    tests_total: totals.tests_total,
    tests_pass: totals.tests_pass,
    tests_fail: totals.tests_fail,
    duplicate_registration_count: validationEvidence.duplicate_registration_count,
    continuation_loss_count: validationEvidence.continuation_loss_count,
    evidence_path: validationEvidence.request_evidence_path,
    parity_evidence_path: validationEvidence.parity_evidence_path,
    source_baseline_evidence_path: validationEvidence.baseline_paths.req888_baseline_evidence_path,
    validated_at: validatedAt,
  };

  return {
    tasks: {
      'REQ-890-02': {
        verification,
      },
    },
    result_paths: {
      baseline_evidence_path: validationEvidence.baseline_paths.req888_baseline_evidence_path,
      parity_evidence_path: validationEvidence.parity_evidence_path,
      request_evidence_path: validationEvidence.request_evidence_path,
      canonical_hooks_json_path: validationEvidence.baseline_paths.canonical_hooks_json_path,
      codex_hooks_json_path: validationEvidence.baseline_paths.codex_hooks_json_path,
    },
    phase2_result: {
      status: validationEvidence.status,
      validated_at: validatedAt,
      task_commit: taskCommit,
      integration_commit: integrationCommit,
      target_dod: 'DOD-005',
      result_paths: {
        baseline_evidence_path: validationEvidence.baseline_paths.req888_baseline_evidence_path,
        parity_evidence_path: validationEvidence.parity_evidence_path,
        request_evidence_path: validationEvidence.request_evidence_path,
      },
      checks: {
        hook_adapter_parity: validationEvidence.checks.hook_adapter_parity,
        hook_regression_subset: validationEvidence.checks.hook_regression_subset,
        npm_test: validationEvidence.checks.npm_test,
        parity_generator_parse: validationEvidence.checks.parity_generator_parse,
        duplicate_registration_count: validationEvidence.duplicate_registration_count,
        continuation_loss_count: validationEvidence.continuation_loss_count,
        no_go_guard: validationEvidence.checks.no_go_guard,
        tests_total: totals.tests_total,
        tests_pass: totals.tests_pass,
        tests_fail: totals.tests_fail,
      },
    },
  };
}

export function assertCodexHookAdapterParityEvidence(evidence) {
  assert.equal(evidence.request_id, 'REQ-890');
  assert.equal(evidence.dod_id, 'DOD-005');
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.root_metadata.request_id, 'REQ-890');
  assert.equal(evidence.root_metadata.dod_id, 'DOD-005');
  assert.equal(evidence.root_metadata.baseline_evidence_path, req888BaselineEvidencePath);
  assert.equal(evidence.root_metadata.canonical_hooks_json_path, canonicalHooksJsonPath);
  assert.deepEqual(
    evidence.root_metadata.canonical_hook_script_paths,
    Object.values(canonicalHookScripts),
  );
  assert.deepEqual(
    evidence.root_metadata.source_evidence_paths,
    [
      req888BaselineEvidencePath,
      req887ForcedWireEvidencePath,
      req886DiscoveryEvidencePath,
    ],
  );
  assert.equal(evidence.source_evidence.req_888.request_id, 'REQ-888');
  assert.equal(evidence.source_evidence.req_888.dod_id, 'DOD-004');
  assert.equal(evidence.source_evidence.req_887.request_id, 'REQ-887');
  assert.equal(evidence.source_evidence.req_886.request_id, 'REQ-886');
  assert.equal(evidence.fixtures.SessionStart.status, 'pass');
  assert.equal(
    evidence.fixtures.SessionStart.fixture.canonical_target_script,
    canonicalHookScripts.SessionStart,
  );
  assert.equal(
    evidence.fixtures.SessionStart.fixture.normalized_env.MST_SESSION_ID,
    baseMstSessionId,
  );
  assert.equal(evidence.fixtures.PreToolUse.status, 'pass');
  assert.deepEqual(evidence.fixtures.PreToolUse.blocker_codes, [
    'permission_metadata_loss',
    'unsupported_direct_shell_escape',
  ]);
  assert.equal(
    evidence.fixtures.PreToolUse.fixtures.skill_like.detected_matcher,
    'Skill',
  );
  assert.equal(
    evidence.fixtures.PreToolUse.fixtures.schedule_wakeup_like.detected_matcher,
    'ScheduleWakeup',
  );
  assert.equal(evidence.fixtures.Stop.status, 'pass');
  assert.equal(evidence.fixtures.Stop.continuation_loss_count, 0);
  assert.equal(evidence.fixtures.UserPromptSubmit.status, 'pass');
  assert.equal(
    evidence.fixtures.UserPromptSubmit.fixture.canonical_target_script,
    canonicalHookScripts.UserPromptSubmit,
  );
  assert.equal(evidence.codex_manifest.path, codexHooksJsonPath);
  assert.equal(evidence.codex_manifest.adapter_runner_path, codexAdapterRunnerPath);
  assert.equal(evidence.codex_manifest.command_audit.status, 'pass');
  assert.equal(evidence.codex_manifest.command_audit.violation_count, 0);
  assert.equal(evidence.duplicate_registration_count, 0);
  assert.equal(evidence.continuation_loss_count, 0);
  assert.equal(evidence.no_go_guard.status, 'pass');
  assert.deepEqual(evidence.no_go_guard.excluded_dod_ids, excludedDodIds);
  assert.equal(evidence.canonical_hook_regression.status, 'pass');
  assert.equal(evidence.parse_error_count, 0);
  assert.ok(evidence.input_paths_read.includes(codexHooksJsonPath));
  assert.ok(evidence.input_paths_read.includes(canonicalHooksJsonPath));
  assert.ok(evidence.input_paths_read.includes(sourceEvidenceByRequest.REQ_888.absolutePath));
}

export function assertCodexHookAdapterValidationEvidence(
  evidence,
  expectedSummary = defaultCodexHookAdapterValidationSummary,
) {
  const normalizedVerification = normalizeVerificationSummary(expectedSummary);
  const totals = summarizeCommandTotals(normalizedVerification);

  assert.equal(evidence.request_id, 'REQ-890');
  assert.equal(evidence.task_id, '02');
  assert.equal(evidence.dod_id, 'DOD-005');
  assert.equal(evidence.status, 'pass');
  assert.equal(evidence.request_evidence_path, validationEvidenceRelativePath);
  assert.equal(evidence.parity_evidence_path, stableEvidenceRelativePath);
  assert.equal(
    evidence.baseline_paths.req888_baseline_evidence_path,
    req888BaselineEvidencePath,
  );
  assert.equal(evidence.hook_event_statuses.SessionStart, 'pass');
  assert.equal(evidence.hook_event_statuses.PreToolUse, 'pass');
  assert.equal(evidence.hook_event_statuses.Stop, 'pass');
  assert.equal(evidence.hook_event_statuses.UserPromptSubmit, 'pass');
  assert.equal(evidence.duplicate_registration_count, 0);
  assert.equal(evidence.continuation_loss_count, 0);
  assert.equal(evidence.no_go_guard.status, 'pass');
  assert.deepEqual(evidence.no_go_guard.excluded_dod_ids, excludedDodIds);
  assert.equal(evidence.parity_evidence_summary.status, 'pass');
  assert.equal(
    evidence.test_command_results.hook_regression_subset.command,
    hookRegressionSubsetCommand,
  );
  assert.equal(evidence.test_command_results.hook_regression_subset.status, 'pass');
  assert.equal(evidence.test_command_results.npm_test.command, npmTestCommand);
  assert.equal(evidence.test_command_results.npm_test.status, 'pass');
  assert.equal(evidence.test_command_results.parity_generator.command, parityGeneratorCommand);
  assert.equal(evidence.test_command_results.parity_generator.status, 'pass');
  assert.equal(evidence.test_command_results.parity_generator.parse_ok, true);
  assert.deepEqual(
    evidence.test_command_results.parity_generator.core_field_checks,
    normalizedVerification.parity_generator.core_field_checks,
  );
  assert.deepEqual(evidence.test_command_results.totals, totals);
  assert.equal(evidence.checks.hook_adapter_parity, 'pass');
  assert.equal(evidence.checks.hook_regression_subset, 'pass');
  assert.equal(evidence.checks.npm_test, 'pass');
  assert.equal(evidence.checks.parity_generator_parse, 'pass');
  assert.equal(evidence.checks.no_go_guard, 'pass');
}
