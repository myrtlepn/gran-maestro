import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import {
  buildCodexHookAdapterParityEvidence,
  stableEvidenceAbsolutePath,
} from './lib/codex-hook-adapter-parity.mjs';

const outputPath = process.argv[2] || stableEvidenceAbsolutePath;
const evidence = buildCodexHookAdapterParityEvidence();

try {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  process.stdout.write(`${outputPath}\n`);
} catch (error) {
  process.stderr.write(
    `Failed to write DOD-005 hook adapter parity evidence to ${outputPath}. ` +
      'Pass an explicit writable output path when running inside a sandbox.\n',
  );
  throw error;
}
