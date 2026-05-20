import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import {
  buildDod012DocsReleaseIntegration,
  dod012RequestEvidenceAbsolutePath,
} from './lib/codex-plugin-discovery-smoke.mjs';

const outputPath = process.argv[2] || dod012RequestEvidenceAbsolutePath;
const evidence = buildDod012DocsReleaseIntegration();

try {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  process.stdout.write(`${outputPath}\n`);
} catch (error) {
  process.stderr.write(
    `Failed to write DOD-012 docs release integration evidence to ${outputPath}. ` +
      'Pass an explicit writable output path when running inside a sandbox.\n',
  );
  throw error;
}
