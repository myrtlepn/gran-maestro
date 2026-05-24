import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '..');
const manifestPath = join(repoRoot, '.codex-plugin', 'plugin.json');
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const marketplaceName = 'gran-maestro';
const pluginName = manifest.name;
const pluginSelector = `${pluginName}@${marketplaceName}`;
const tempRoot = mkdtempSync(join(tmpdir(), 'mst-codex-home.'));
const runtimeProjectRoot = join(tempRoot, 'runtime-project');
mkdirSync(join(runtimeProjectRoot, '.gran-maestro'), { recursive: true });
const keepTemp = process.argv.includes('--keep-temp');
const sourceIndex = process.argv.indexOf('--source');
const marketplaceSource = sourceIndex === -1
  ? repoRoot
  : process.argv[sourceIndex + 1];

if (sourceIndex !== -1 && !marketplaceSource) {
  process.stderr.write('--source requires a local path, owner/repo, HTTPS Git URL, or SSH Git URL\n');
  process.exit(2);
}

function runCodex(args) {
  const result = spawnSync('codex', args, {
    cwd: repoRoot,
    env: {
      ...process.env,
      CODEX_HOME: tempRoot,
    },
    encoding: 'utf8',
  });
  return {
    command: ['codex', ...args].join(' '),
    status: result.status,
    stdout: result.stdout,
    stderr: result.stderr,
  };
}

function commandPassed(result) {
  return result.status === 0;
}

function readJsonIfExists(path) {
  if (!existsSync(path)) {
    return null;
  }
  return JSON.parse(readFileSync(path, 'utf8'));
}

function listSkillNames(path) {
  if (!existsSync(path)) {
    return [];
  }
  return readdirSync(path, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith('.'))
    .map((entry) => entry.name)
    .sort();
}

const commands = [
  runCodex(['plugin', 'marketplace', 'add', marketplaceSource]),
  runCodex(['plugin', 'marketplace', 'list']),
  runCodex(['plugin', 'list', '--marketplace', marketplaceName]),
  runCodex(['plugin', 'add', pluginSelector]),
];

const installedRoot = join(
  tempRoot,
  'plugins',
  'cache',
  marketplaceName,
  pluginName,
  manifest.version,
);
const installedManifestPath = join(
  installedRoot,
  '.codex-plugin',
  'plugin.json',
);
const installedSkillsPath = join(
  installedRoot,
  'skills',
);
const installedScriptsPath = join(installedRoot, 'scripts', 'mst.py');
const installedEnforceTreePath = join(installedRoot, 'hooks', 'enforce-tree.json');
const installedHookHelperPath = join(installedRoot, 'hooks', 'lib', 'pre_tool_use_fast.py');
const installedHookHelperShardsPath = join(installedRoot, 'hooks', 'lib', 'pre_tool_use_fast_shards');
const installedConfigPath = join(tempRoot, 'config.toml');
const blockedClaudeSurfacePaths = [
  '.claude',
  '.claude-plugin',
  'hooks/hooks.json',
  'hooks/mst-auto-chain-context.sh',
  'hooks/mst-pre-tool-use.sh',
  'hooks/mst-session-init.sh',
  'hooks/mst-stop-hook.sh',
];
const marketplaceListOutput = commands[1]?.stdout ?? '';
const pluginListOutput = commands[2]?.stdout ?? '';
const pluginAddOutput = commands[3]?.stdout ?? '';
const installedManifest = readJsonIfExists(installedManifestPath);
const sourceSkillNames = listSkillNames(join(repoRoot, 'skills'));
const installedSkillNames = listSkillNames(installedSkillsPath);
const installedConfigToml = existsSync(installedConfigPath)
  ? readFileSync(installedConfigPath, 'utf8')
  : '';
const manifestMatchesSource =
  JSON.stringify(installedManifest) === JSON.stringify(manifest);
const skillsMatchSource =
  JSON.stringify(installedSkillNames) === JSON.stringify(sourceSkillNames);
const installedManifestHasHooks = Boolean(installedManifest?.hooks);
const presentBlockedClaudeSurfacePaths = blockedClaudeSurfacePaths.filter((path) => existsSync(join(installedRoot, path)));
const codexConfigTrustedClaudeHooks =
  installedConfigToml.includes(`${pluginSelector}:hooks/hooks.json`) ||
  installedConfigToml.includes('${CLAUDE_PLUGIN_ROOT}');
const installedMstTimestampCommand = spawnSync('python3', [installedScriptsPath, 'timestamp', 'now'], {
  cwd: runtimeProjectRoot,
  env: {
    ...process.env,
    CODEX_HOME: tempRoot,
  },
  encoding: 'utf8',
});
const installedMstTimestampPassed =
  installedMstTimestampCommand.status === 0 &&
  /^\d{4}-\d{2}-\d{2}T/.test(installedMstTimestampCommand.stdout.trim());

const evidence = {
  artifact_id: 'codex-plugin-local-install-smoke',
  status: commands.every(commandPassed) &&
    marketplaceListOutput.includes(marketplaceName) &&
    pluginListOutput.includes(pluginSelector) &&
    pluginAddOutput.includes(`Added plugin \`${pluginName}\``) &&
    existsSync(installedManifestPath) &&
    existsSync(installedSkillsPath) &&
    existsSync(installedScriptsPath) &&
    existsSync(installedEnforceTreePath) &&
    existsSync(installedHookHelperPath) &&
    existsSync(installedHookHelperShardsPath) &&
    manifestMatchesSource &&
    skillsMatchSource &&
    !installedManifestHasHooks &&
    presentBlockedClaudeSurfacePaths.length === 0 &&
    !codexConfigTrustedClaudeHooks &&
    installedMstTimestampPassed
    ? 'pass'
    : 'fail',
  repo_root: repoRoot,
  marketplace_source: marketplaceSource,
  codex_home: tempRoot,
  runtime_project_root: runtimeProjectRoot,
  mutates_user_codex_home: false,
  marketplace_name: marketplaceName,
  plugin_selector: pluginSelector,
  installed_root: installedRoot,
  installed_manifest_path: installedManifestPath,
  installed_skills_path: installedSkillsPath,
  installed_scripts_path: installedScriptsPath,
  installed_enforce_tree_path: installedEnforceTreePath,
  installed_hook_helper_path: installedHookHelperPath,
  installed_hook_helper_shards_path: installedHookHelperShardsPath,
  installed_mst_timestamp_command: {
    command: ['python3', installedScriptsPath, 'timestamp', 'now'].join(' '),
    status: installedMstTimestampCommand.status,
    stdout: installedMstTimestampCommand.stdout,
    stderr: installedMstTimestampCommand.stderr,
  },
  installed_mst_timestamp_passed: installedMstTimestampPassed,
  installed_manifest_matches_source: manifestMatchesSource,
  installed_manifest_has_hooks: installedManifestHasHooks,
  source_skill_count: sourceSkillNames.length,
  installed_skill_count: installedSkillNames.length,
  installed_skills_match_source: skillsMatchSource,
  missing_installed_skills: sourceSkillNames.filter((name) => !installedSkillNames.includes(name)),
  extra_installed_skills: installedSkillNames.filter((name) => !sourceSkillNames.includes(name)),
  blocked_claude_surface_paths: blockedClaudeSurfacePaths,
  present_blocked_claude_surface_paths: presentBlockedClaudeSurfacePaths,
  codex_config_path: installedConfigPath,
  codex_config_trusted_claude_hooks: codexConfigTrustedClaudeHooks,
  commands,
};

const outputIndex = process.argv.indexOf('--output');
if (outputIndex !== -1) {
  const outputPath = process.argv[outputIndex + 1];
  if (!outputPath) {
    process.stderr.write('--output requires a path\n');
    process.exitCode = 2;
  } else {
    writeFileSync(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  }
} else {
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
}

if (!keepTemp) {
  rmSync(tempRoot, { recursive: true, force: true });
}

if (evidence.status !== 'pass') {
  process.exitCode = 1;
}
