#!/usr/bin/env node

/**
 * BPMN auto-layout script. Recalculates all DI coordinates.
 *
 * Usage:
 *   node auto-layout.js <file.bpmn>              # reads file, prints to stdout
 *   cat file.bpmn | node auto-layout.js           # reads stdin, prints to stdout
 *   node auto-layout.js <file.bpmn> -o out.bpmn   # writes to output file
 *
 * Warning: this recalculates ALL positions and destroys any manual layout.
 * Use only as a reset when coordinates are badly broken.
 *
 * Requires: npx-compatible environment (Node.js 18+).
 * The bpmn-auto-layout package is installed on demand to a temp directory.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { execSync } from 'child_process';
import { tmpdir } from 'os';
import { join } from 'path';

const PACKAGE = 'bpmn-auto-layout';
const VERSION = '1.0.1';
const CACHE_DIR = join(tmpdir(), 'camunda-auto-layout-cache');

// Ensure the package is available
const pkgPath = join(CACHE_DIR, 'node_modules', PACKAGE);
if (!existsSync(pkgPath)) {
  mkdirSync(CACHE_DIR, { recursive: true });
  execSync(`npm install ${PACKAGE}@${VERSION} --prefix "${CACHE_DIR}" --no-save --silent`, {
    stdio: ['pipe', 'pipe', 'pipe']
  });
}

const { layoutProcess } = await import(join(pkgPath, 'index.js'));

// Parse arguments
const args = process.argv.slice(2);
let outputFile = null;
const fileArgs = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '-o' && args[i + 1]) {
    outputFile = args[++i];
  } else {
    fileArgs.push(args[i]);
  }
}

// Read input
let xml;
const isStdin = !process.stdin.isTTY;

if (isStdin) {
  xml = await new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => data += chunk);
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
} else if (fileArgs.length > 0 && existsSync(fileArgs[0])) {
  xml = readFileSync(fileArgs[0], 'utf8');
} else {
  console.error('Usage: node auto-layout.js <file.bpmn> [-o output.bpmn]');
  console.error('       cat file.bpmn | node auto-layout.js');
  process.exit(1);
}

// Layout and output
const result = await layoutProcess(xml);

if (outputFile) {
  writeFileSync(outputFile, result, 'utf8');
  console.error(`Wrote layouted BPMN to ${outputFile}`);
} else {
  process.stdout.write(result);
}
