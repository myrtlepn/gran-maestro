import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import {
  buildCodexSkillAgentProjectionValidationEvidence,
  skillAgentProjectionValidationEvidenceAbsolutePath,
} from './lib/codex-plugin-discovery-smoke.mjs';

const outputPath = process.argv[2] || skillAgentProjectionValidationEvidenceAbsolutePath;
const verificationSummaryPath = process.argv[3];

const verificationSummary = verificationSummaryPath
  ? JSON.parse(readFileSync(verificationSummaryPath, 'utf8'))
  : undefined;
const evidence = buildCodexSkillAgentProjectionValidationEvidence({ verificationSummary });

try {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  process.stdout.write(`${outputPath}\n`);
} catch (error) {
  process.stderr.write(
    `Failed to write DOD-006 skill/agent projection validation evidence to ${outputPath}. ` +
      'Pass an explicit writable output path when running inside a sandbox.\n',
  );
  throw error;
}
