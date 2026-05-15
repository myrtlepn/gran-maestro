import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));

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
