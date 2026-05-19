#!/usr/bin/env node

import {
  normalizeCodexHookInvocation,
} from './lib/codex-hook-adapter-parity.mjs';

function readStdin() {
  return new Promise((resolve) => {
    let raw = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      raw += chunk;
    });
    process.stdin.on('end', () => {
      resolve(raw);
    });
    process.stdin.on('error', () => {
      resolve('');
    });
  });
}

function parsePayload(raw) {
  if (!raw.trim()) {
    return {};
  }

  try {
    return JSON.parse(raw);
  } catch {
    return {
      raw_stdin: raw,
      parse_error: 'invalid_json',
    };
  }
}

const [eventName = '', matcher = ''] = process.argv.slice(2);
const stdinRaw = await readStdin();
const payload = parsePayload(stdinRaw);
const normalized = normalizeCodexHookInvocation({
  eventName,
  matcher,
  payload,
  env: process.env,
});

process.stdout.write(`${JSON.stringify(normalized, null, 2)}\n`);
process.exit(
  normalized.blockers.some((blocker) => blocker.severity === 'blocker') ? 2 : 0,
);
