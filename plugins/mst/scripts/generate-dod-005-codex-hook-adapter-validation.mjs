import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import {
  buildCodexHookAdapterValidationEvidence,
  validationEvidenceAbsolutePath,
} from './lib/codex-hook-adapter-parity.mjs';

const outputPath = process.argv[2] || validationEvidenceAbsolutePath;
const verificationSummaryPath = process.argv[3];

const verificationSummary = verificationSummaryPath
  ? JSON.parse(readFileSync(verificationSummaryPath, 'utf8'))
  : undefined;
const evidence = buildCodexHookAdapterValidationEvidence({ verificationSummary });

try {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  process.stdout.write(`${outputPath}\n`);
} catch (error) {
  process.stderr.write(
    `Failed to write DOD-005 hook adapter validation evidence to ${outputPath}. ` +
      'Pass an explicit writable output path when running inside a sandbox.\n',
  );
  throw error;
}
