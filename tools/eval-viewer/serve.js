#!/usr/bin/env node

/**
 * Dynamic eval result viewer for skill maintainers.
 *
 * Uses Vite for frontend (ES module imports of bpmn-js + icon renderer)
 * and Express middleware for the eval data API.
 *
 * Usage:
 *   node serve.js                                       # Browse all evals
 *   node serve.js ../../evals/camunda-bpmn/iteration-1  # Jump to specific iteration
 *
 * Opens http://localhost:3334 in the browser.
 */

import { readFileSync, readdirSync, existsSync, statSync } from 'fs';
import { join, basename, extname, resolve } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import { exec } from 'child_process';
import { createServer as createViteServer } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PORT = process.env.PORT || 3334;

const defaultEvalsRoot = resolve(join(__dirname, '..', '..', 'evals'));
let evalsRoot = defaultEvalsRoot;
let initialSkill = null;
let initialIteration = null;

// Parse the optional argument
if (process.argv[2]) {
  const arg = resolve(process.argv[2]);

  if (basename(arg).startsWith('iteration-') && existsSync(arg)) {
    const skillDir = dirname(arg);
    evalsRoot = dirname(skillDir);
    initialSkill = basename(skillDir);
    initialIteration = basename(arg);
  } else if (existsSync(arg)) {
    const children = readdirSync(arg).filter(n =>
      n.startsWith('iteration-') && statSync(join(arg, n)).isDirectory()
    );
    if (children.length > 0) {
      evalsRoot = dirname(arg);
      initialSkill = basename(arg);
    } else {
      evalsRoot = arg;
    }
  } else {
    evalsRoot = arg;
  }
}

if (!existsSync(evalsRoot)) {
  console.error(`Evals directory not found: ${evalsRoot}`);
  console.error(`Run some evals first, or pass a path: node serve.js <evals-dir>`);
  process.exit(1);
}

// --- Eval data scanning ---

function scanEvalsRoot() {
  const skills = [];
  const skillDirs = readdirSync(evalsRoot).filter(name => {
    const fullPath = join(evalsRoot, name);
    return statSync(fullPath).isDirectory() && !name.startsWith('.');
  });

  for (const skillName of skillDirs) {
    const skillDir = join(evalsRoot, skillName);
    const iterDirs = readdirSync(skillDir).filter(name => {
      const fullPath = join(skillDir, name);
      return statSync(fullPath).isDirectory() && name.startsWith('iteration-');
    }).sort((a, b) => {
      return parseInt(a.replace('iteration-', '')) - parseInt(b.replace('iteration-', ''));
    });

    const iterations = iterDirs.map(name => ({ name, path: join(skillDir, name) }));
    if (iterations.length > 0) {
      skills.push({ name: skillName, iterations });
    }
  }
  return skills;
}

function scanIteration(iterationPath) {
  const evals = [];
  const entries = readdirSync(iterationPath).filter(name => {
    const fullPath = join(iterationPath, name);
    return statSync(fullPath).isDirectory() && !name.startsWith('.');
  });

  for (const evalName of entries) {
    const evalDir = join(iterationPath, evalName);

    let metadata = { eval_name: evalName, prompt: '', assertions: [] };
    const metaPath = join(evalDir, 'eval_metadata.json');
    if (existsSync(metaPath)) {
      try { metadata = JSON.parse(readFileSync(metaPath, 'utf8')); } catch {}
    }

    const configs = [];
    const configDirs = readdirSync(evalDir).filter(name => {
      const fullPath = join(evalDir, name);
      return statSync(fullPath).isDirectory() && !name.startsWith('.');
    });

    for (const configName of configDirs) {
      const configDir = join(evalDir, configName);
      const outputsDir = join(configDir, 'outputs');

      const RENDERABLE = new Set(['.bpmn', '.dmn', '.form']);
      const SKIP = new Set(['.bpmnlintrc', '.gitkeep']);
      let outputFiles = [];
      if (existsSync(outputsDir)) {
        for (const file of readdirSync(outputsDir)) {
          if (file.startsWith('.') || SKIP.has(file)) continue;
          const ext = extname(file).toLowerCase();
          outputFiles.push({
            name: file, ext,
            type: ext === '.bpmn' ? 'bpmn' : ext === '.dmn' ? 'dmn' : ext === '.form' ? 'form' : 'text',
            path: join(outputsDir, file)
          });
        }
        outputFiles.sort((a, b) => {
          const aR = RENDERABLE.has(a.ext) ? 0 : 1;
          const bR = RENDERABLE.has(b.ext) ? 0 : 1;
          return aR - bR || a.name.localeCompare(b.name);
        });
      }

      let grading = null;
      const gradingPath = join(configDir, 'grading.json');
      if (existsSync(gradingPath)) {
        try { grading = JSON.parse(readFileSync(gradingPath, 'utf8')); } catch {}
      }

      let timing = null;
      const timingPath = join(configDir, 'timing.json');
      if (existsSync(timingPath)) {
        try { timing = JSON.parse(readFileSync(timingPath, 'utf8')); } catch {}
      }

      configs.push({ name: configName, label: configName.replace(/_/g, ' '), outputs: outputFiles, grading, timing });
    }

    evals.push({ name: evalName, metadata, configs });
  }
  return evals;
}

// --- Vite server with API middleware ---

async function startServer() {
  const vite = await createViteServer({
    root: __dirname,
    server: { port: PORT },
    plugins: [{
      name: 'eval-api',
      configureServer(server) {
        server.middlewares.use('/api/skills', (req, res) => {
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({
            skills: scanEvalsRoot(),
            initial: initialSkill ? { skill: initialSkill, iteration: initialIteration } : null
          }));
        });

        server.middlewares.use('/api/iteration', (req, res) => {
          // URL: /api/iteration/skill-name/iteration-N
          const parts = req.url.split('/').filter(Boolean);
          if (parts.length < 2) {
            res.statusCode = 400;
            return res.end('Usage: /api/iteration/:skill/:iteration');
          }
          const [skill, iteration] = parts;
          const iterPath = join(evalsRoot, skill, iteration);
          if (!existsSync(iterPath)) {
            res.statusCode = 404;
            return res.end(JSON.stringify({ error: 'Iteration not found' }));
          }
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({
            skill, iteration, directory: iterPath,
            evals: scanIteration(iterPath)
          }));
        });

        server.middlewares.use('/api/file', (req, res) => {
          const url = new URL(req.url, 'http://localhost');
          const filePath = url.searchParams.get('path');
          if (!filePath || !filePath.startsWith(evalsRoot)) {
            res.statusCode = 403;
            return res.end('Access denied');
          }
          if (!existsSync(filePath)) {
            res.statusCode = 404;
            return res.end('File not found');
          }
          const ext = extname(filePath).toLowerCase();
          const ct = ext === '.form' ? 'application/json'
            : (ext === '.bpmn' || ext === '.dmn') ? 'application/xml'
            : 'text/plain';
          res.setHeader('Content-Type', ct);
          res.end(readFileSync(filePath, 'utf8'));
        });
      }
    }]
  });

  await vite.listen();
  const url = `http://localhost:${PORT}`;
  console.log(`Eval Viewer running at ${url}`);
  console.log(`Evals root: ${evalsRoot}`);

  const skills = scanEvalsRoot();
  for (const s of skills) {
    console.log(`  ${s.name}: ${s.iterations.length} iteration(s)`);
  }

  const openCmd = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open';
  exec(`${openCmd} ${url}`);
}

startServer();
