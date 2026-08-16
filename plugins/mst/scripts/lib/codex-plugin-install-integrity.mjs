import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

export const representativePluginFiles = Object.freeze([
  'skills/debug/SKILL.md',
  'skills/request/SKILL.md',
  'skills/_shared/session-bootstrap.md',
  'scripts/mst_cmds/session_shards/part_001.py',
  'scripts/mst_cmds/session_shards/part_002.py',
  'src/core/cli-adapter.ts',
  'agents/pm-conductor.md',
]);

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

export function compareRepresentativePluginFiles(
  sourceRoot,
  installedRoot,
  relativePaths = representativePluginFiles,
) {
  const files = relativePaths.map((relativePath) => {
    const sourcePath = join(sourceRoot, relativePath);
    const installedPath = join(installedRoot, relativePath);
    const sourceExists = existsSync(sourcePath);
    const installedExists = existsSync(installedPath);
    const sourceBytes = sourceExists ? readFileSync(sourcePath) : null;
    const installedBytes = installedExists ? readFileSync(installedPath) : null;
    const sourceSha256 = sourceBytes === null ? null : sha256(sourceBytes);
    const installedSha256 = installedBytes === null ? null : sha256(installedBytes);
    const hashesMatch =
      sourceSha256 !== null &&
      installedSha256 !== null &&
      sourceSha256 === installedSha256;
    const bytesMatch =
      sourceBytes !== null &&
      installedBytes !== null &&
      sourceBytes.equals(installedBytes);

    return {
      path: relativePath,
      source_exists: sourceExists,
      installed_exists: installedExists,
      source_sha256: sourceSha256,
      installed_sha256: installedSha256,
      hashes_match: hashesMatch,
      bytes_match: bytesMatch,
    };
  });
  const mismatches = files
    .filter((entry) => !entry.hashes_match || !entry.bytes_match)
    .map((entry) => entry.path);

  return {
    matches: mismatches.length === 0,
    mismatches,
    files,
  };
}
