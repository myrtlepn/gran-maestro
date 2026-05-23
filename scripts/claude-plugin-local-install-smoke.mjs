import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '..');
const claudeManifestPath = join(repoRoot, '.claude-plugin', 'plugin.json');
const codexManifestPath = join(repoRoot, '.codex-plugin', 'plugin.json');
const claudeManifest = JSON.parse(readFileSync(claudeManifestPath, 'utf8'));
const codexManifest = JSON.parse(readFileSync(codexManifestPath, 'utf8'));
const marketplaceName = 'gran-maestro';
const pluginName = claudeManifest.name;
const pluginSelector = `${pluginName}@${marketplaceName}`;
const tempRoot = mkdtempSync(join(tmpdir(), 'mst-claude-home.'));
const claudeConfigDir = join(tempRoot, '.claude');
const keepTemp = process.argv.includes('--keep-temp');
const sourceIndex = process.argv.indexOf('--source');
const marketplaceSource = sourceIndex === -1
  ? repoRoot
  : process.argv[sourceIndex + 1];

if (sourceIndex !== -1 && !marketplaceSource) {
  process.stderr.write('--source requires a local path, owner/repo, HTTPS Git URL, or SSH Git URL\n');
  process.exit(2);
}

function runClaude(args) {
  const result = spawnSync('claude', args, {
    cwd: repoRoot,
    env: {
      ...process.env,
      HOME: tempRoot,
      CLAUDE_CONFIG_DIR: claudeConfigDir,
      MST_CLAUDE_HOME: tempRoot,
    },
    encoding: 'utf8',
    timeout: 180_000,
  });
  return {
    command: ['claude', ...args].join(' '),
    status: result.status,
    signal: result.signal,
    stdout: result.stdout,
    stderr: result.stderr,
    timed_out: result.error?.code === 'ETIMEDOUT',
  };
}

function commandPassed(result) {
  return result.status === 0 && result.timed_out !== true;
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
  runClaude(['plugin', 'marketplace', 'add', marketplaceSource]),
  runClaude(['plugin', 'marketplace', 'list']),
  runClaude(['plugin', 'install', pluginSelector]),
];

const installedRoot = join(
  claudeConfigDir,
  'plugins',
  'cache',
  marketplaceName,
  pluginName,
  claudeManifest.version,
);
const installedClaudeManifestPath = join(installedRoot, '.claude-plugin', 'plugin.json');
const installedCodexManifestPath = join(installedRoot, '.codex-plugin', 'plugin.json');
const installedHooksPath = join(installedRoot, 'hooks', 'hooks.json');
const installedSkillsPath = join(installedRoot, 'skills');
const installedClaudeManifest = readJsonIfExists(installedClaudeManifestPath);
const installedCodexManifest = readJsonIfExists(installedCodexManifestPath);
const sourceSkillNames = listSkillNames(join(repoRoot, 'skills'));
const installedSkillNames = listSkillNames(installedSkillsPath);
const sourceAgentPaths = Array.isArray(claudeManifest.agents) ? claudeManifest.agents : [];
const installedAgentPaths = sourceAgentPaths.filter((agentPath) =>
  existsSync(join(installedRoot, agentPath)),
);
const claudeManifestMatchesSource =
  JSON.stringify(installedClaudeManifest) === JSON.stringify(claudeManifest);
const codexManifestMatchesSource =
  JSON.stringify(installedCodexManifest) === JSON.stringify(codexManifest);
const skillsMatchSource =
  JSON.stringify(installedSkillNames) === JSON.stringify(sourceSkillNames);
const hooksMatchSource =
  readFileSync(join(repoRoot, 'hooks', 'hooks.json'), 'utf8') ===
  (existsSync(installedHooksPath) ? readFileSync(installedHooksPath, 'utf8') : '');
const listOutput = commands[1]?.stdout ?? '';
const installOutput = commands[2]?.stdout ?? '';

const evidence = {
  artifact_id: 'claude-plugin-local-install-smoke',
  status: commands.every(commandPassed) &&
    listOutput.includes(marketplaceName) &&
    installOutput.includes(`Successfully installed plugin: ${pluginSelector}`) &&
    existsSync(installedClaudeManifestPath) &&
    existsSync(installedHooksPath) &&
    existsSync(installedSkillsPath) &&
    claudeManifestMatchesSource &&
    codexManifestMatchesSource &&
    hooksMatchSource &&
    skillsMatchSource &&
    installedAgentPaths.length === sourceAgentPaths.length
    ? 'pass'
    : 'fail',
  repo_root: repoRoot,
  marketplace_source: marketplaceSource,
  claude_home: tempRoot,
  claude_config_dir: claudeConfigDir,
  mutates_user_claude_home: false,
  marketplace_name: marketplaceName,
  plugin_selector: pluginSelector,
  installed_root: installedRoot,
  installed_claude_manifest_path: installedClaudeManifestPath,
  installed_codex_manifest_path: installedCodexManifestPath,
  installed_hooks_path: installedHooksPath,
  installed_skills_path: installedSkillsPath,
  installed_claude_manifest_matches_source: claudeManifestMatchesSource,
  installed_codex_manifest_matches_source: codexManifestMatchesSource,
  installed_hooks_match_source: hooksMatchSource,
  source_skill_count: sourceSkillNames.length,
  installed_skill_count: installedSkillNames.length,
  installed_skills_match_source: skillsMatchSource,
  missing_installed_skills: sourceSkillNames.filter((name) => !installedSkillNames.includes(name)),
  extra_installed_skills: installedSkillNames.filter((name) => !sourceSkillNames.includes(name)),
  source_agent_count: sourceAgentPaths.length,
  installed_agent_count: installedAgentPaths.length,
  missing_installed_agents: sourceAgentPaths.filter((agentPath) =>
    !installedAgentPaths.includes(agentPath),
  ),
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
