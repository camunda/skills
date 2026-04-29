#!/usr/bin/env node

/**
 * Self-contained element template extraction script.
 * Installs @camunda/connectors-element-templates to a temp directory,
 * extracts the latest version of each template, and caches them
 * to ~/.camunda/element-templates/.
 *
 * Usage: node scripts/extract-templates.js [--force]
 *
 * The script is idempotent — subsequent runs skip extraction if
 * the cache already exists (unless --force is passed).
 */

import { readFileSync, writeFileSync, mkdirSync, rmSync, readdirSync, existsSync } from 'fs';
import { join } from 'path';
import { homedir, tmpdir } from 'os';
import { execSync } from 'child_process';

const PACKAGE_NAME = '@camunda/connectors-element-templates';
const PACKAGE_VERSION = '1.0.9';
const TARGET_DIR = join(homedir(), '.camunda', 'element-templates');
const TEMP_DIR = join(tmpdir(), 'camunda-et-cache');
const force = process.argv.includes('--force');

// Check if templates are already cached
if (existsSync(TARGET_DIR) && !force) {
  const existing = readdirSync(TARGET_DIR).filter(f => f.endsWith('.json'));
  if (existing.length > 0) {
    console.log(`Templates already cached at ${TARGET_DIR} (${existing.length} files). Use --force to re-extract.`);
    process.exit(0);
  }
}

console.log(`Installing ${PACKAGE_NAME}@${PACKAGE_VERSION} to temp directory...`);

// Install the npm package to a temp directory
mkdirSync(TEMP_DIR, { recursive: true });
try {
  execSync(`npm install ${PACKAGE_NAME}@${PACKAGE_VERSION} --prefix "${TEMP_DIR}" --no-save --silent`, {
    stdio: ['pipe', 'pipe', 'pipe']
  });
} catch (err) {
  console.error(`Failed to install ${PACKAGE_NAME}: ${err.message}`);
  process.exit(1);
}

const SOURCE_DIR = join(TEMP_DIR, 'node_modules', PACKAGE_NAME, 'src', 'element-templates');

if (!existsSync(SOURCE_DIR)) {
  console.error(`Source directory not found: ${SOURCE_DIR}`);
  process.exit(1);
}

// Create target directory
mkdirSync(TARGET_DIR, { recursive: true });

// Clear existing JSON files from target
if (existsSync(TARGET_DIR)) {
  const existingFiles = readdirSync(TARGET_DIR).filter(f => f.endsWith('.json'));
  for (const file of existingFiles) {
    rmSync(join(TARGET_DIR, file));
  }
}

// Read all JSON files from source
const files = readdirSync(SOURCE_DIR).filter(f => f.endsWith('.json'));

let extracted = 0;
let errors = 0;

for (const file of files) {
  try {
    const sourcePath = join(SOURCE_DIR, file);
    const targetPath = join(TARGET_DIR, file);

    const content = readFileSync(sourcePath, 'utf8');
    const templates = JSON.parse(content);

    if (!Array.isArray(templates) || templates.length === 0) {
      continue;
    }

    // Find the template with the highest version number
    const latestTemplate = templates.reduce((latest, current) => {
      const latestVersion = latest.version || 0;
      const currentVersion = current.version || 0;
      return currentVersion > latestVersion ? current : latest;
    });

    // Write as single object (not array)
    writeFileSync(targetPath, JSON.stringify(latestTemplate, null, 2) + '\n', 'utf8');
    extracted++;

  } catch (err) {
    console.error(`Error processing ${file}: ${err.message}`);
    errors++;
  }
}

console.log(`Extraction complete: ${extracted} templates extracted to ${TARGET_DIR}`);

if (errors > 0) {
  console.warn(`${errors} errors occurred during extraction.`);
  process.exit(1);
}
