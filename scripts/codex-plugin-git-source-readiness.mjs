import { spawnSync } from 'node:child_process';
import { existsSync, lstatSync, readFileSync, readdirSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '..');
const requiredPaths = [
  '.codex-plugin/plugin.json',
  '.agents/plugins/marketplace.json',
  'marketplace.json',
  'plugins/mst',
  'skills/on/SKILL.md',
  'skills/off/SKILL.md',
  'skills/_shared/SKILL.md',
  'scripts/codex-plugin-local-install-smoke.mjs',
  'tests/test_codex_plugin_manifest.py',
];

function git(args) {
  return spawnSync('git', args, {
    cwd: repoRoot,
    encoding: 'utf8',
  });
}

function isGitTracked(path) {
  return git(['ls-files', '--error-unmatch', '--', path]).status === 0;
}

function describePath(path) {
  const absolutePath = join(repoRoot, path);
  const exists = existsSync(absolutePath);
  const stat = exists ? lstatSync(absolutePath) : null;
  const isSymlink = Boolean(stat?.isSymbolicLink());
  return {
    path,
    exists,
    git_tracked: isGitTracked(path),
    is_symlink: isSymlink,
    realpath: exists ? realpathSync(absolutePath) : null,
  };
}

const pathChecks = requiredPaths.map(describePath);
const rootMarketplace = JSON.parse(readFileSync(join(repoRoot, 'marketplace.json'), 'utf8'));
const repoMarketplace = JSON.parse(readFileSync(join(repoRoot, '.agents/plugins/marketplace.json'), 'utf8'));
const manifest = JSON.parse(readFileSync(join(repoRoot, '.codex-plugin/plugin.json'), 'utf8'));
const pluginEntry = repoMarketplace.plugins?.[0] ?? {};
const projectionPathCheck = pathChecks.find((entry) => entry.path === 'plugins/mst');
const projectionRoot = join(repoRoot, 'plugins/mst');
const projectionManifestPath = join(projectionRoot, '.codex-plugin/plugin.json');
const projectionManifest = existsSync(projectionManifestPath)
  ? JSON.parse(readFileSync(projectionManifestPath, 'utf8'))
  : null;

function skillDirNames(root) {
  if (!existsSync(root)) {
    return [];
  }
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith('.'))
    .map((entry) => entry.name)
    .sort();
}

const sourceSkillNames = skillDirNames(join(repoRoot, 'skills'));
const projectionSkillNames = skillDirNames(join(projectionRoot, 'skills'));

const contractChecks = [
  {
    id: 'root_marketplace_mirrors_repo_marketplace',
    status: JSON.stringify(rootMarketplace) === JSON.stringify(repoMarketplace) ? 'pass' : 'fail',
  },
  {
    id: 'marketplace_points_to_repo_plugin_alias',
    status: pluginEntry.source?.source === 'local' && pluginEntry.source?.path === './plugins/mst'
      ? 'pass'
      : 'fail',
  },
  {
    id: 'plugin_projection_is_copy_directory',
    status: projectionPathCheck?.exists === true &&
      projectionPathCheck.is_symlink === false &&
      projectionPathCheck.realpath === projectionRoot &&
      existsSync(projectionManifestPath) &&
      !existsSync(join(projectionRoot, '.claude-plugin')) &&
      !existsSync(join(projectionRoot, '.claude'))
      ? 'pass'
      : 'fail',
  },
  {
    id: 'plugin_projection_manifest_matches_source',
    status: JSON.stringify(projectionManifest) === JSON.stringify(manifest)
      ? 'pass'
      : 'fail',
  },
  {
    id: 'plugin_projection_skills_match_source',
    status: JSON.stringify(projectionSkillNames) === JSON.stringify(sourceSkillNames)
      ? 'pass'
      : 'fail',
  },
  {
    id: 'codex_manifest_is_hookless',
    status: manifest.hooks === undefined && manifest.agents === undefined ? 'pass' : 'fail',
  },
  {
    id: 'codex_manifest_exposes_skills',
    status: manifest.skills === './skills/' ? 'pass' : 'fail',
  },
];

const evidence = {
  artifact_id: 'codex-plugin-git-source-readiness',
  status: pathChecks.every((entry) => entry.exists && entry.git_tracked) &&
    contractChecks.every((entry) => entry.status === 'pass')
    ? 'pass'
    : 'fail',
  repo_root: repoRoot,
  path_checks: pathChecks,
  contract_checks: contractChecks,
  untracked_required_paths: pathChecks
    .filter((entry) => entry.exists && !entry.git_tracked)
    .map((entry) => entry.path),
  missing_required_paths: pathChecks
    .filter((entry) => !entry.exists)
    .map((entry) => entry.path),
};

process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);

if (evidence.status !== 'pass') {
  process.exitCode = 1;
}
