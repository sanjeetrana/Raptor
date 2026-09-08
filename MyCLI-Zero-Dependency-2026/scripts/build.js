#!/usr/bin/env node
'use strict';
// Single documented build command: `npm run build` (or `node scripts/build.js`).
// Uses only node:fs, node:path, node:crypto, node:child_process — no bundler,
// no transpiler, since the project ships plain, already-runnable JS.
//
// Steps:
//   1. Syntax-check every .js file with `node --check` (stdlib Node itself).
//   2. Assemble a self-contained ./dist copy of the runtime files.
//   3. Print a deterministic SHA-256 manifest hash of ./dist so the same
//      source always produces the same hash (see the Reproducible Build
//      bonus section of README.md).

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const DIST = path.join(ROOT, 'dist');

const RUNTIME_ENTRIES = ['server.js', 'lib', 'public', 'data', 'package.json', 'README.md', 'STDLIB.md', 'LICENSE'];

function listJsFiles(dir, ignore = new Set(['node_modules', '.git', 'dist', 'release'])) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ignore.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...listJsFiles(full, ignore));
    else if (entry.isFile() && entry.name.endsWith('.js')) out.push(full);
  }
  return out;
}

function copyRecursive(src, dest) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src)) copyRecursive(path.join(src, entry), path.join(dest, entry));
  } else {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
  }
}

function hashDist(dir) {
  const files = [];
  (function walk(d) {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, entry.name);
      if (entry.isDirectory()) walk(full);
      else files.push(full);
    }
  })(dir);
  files.sort();
  const hash = crypto.createHash('sha256');
  for (const file of files) {
    hash.update(path.relative(dir, file).replace(/\\/g, '/'));
    hash.update(fs.readFileSync(file));
  }
  return hash.digest('hex');
}

function main() {
  console.log('== 1. Syntax check ==');
  const jsFiles = listJsFiles(ROOT);
  for (const file of jsFiles) {
    execFileSync(process.execPath, ['--check', file], { stdio: 'inherit' });
  }
  console.log(`PASS: ${jsFiles.length} JavaScript files parse cleanly.\n`);

  console.log('== 2. Assemble dist/ ==');
  fs.rmSync(DIST, { recursive: true, force: true });
  for (const entry of RUNTIME_ENTRIES) {
    const src = path.join(ROOT, entry);
    if (fs.existsSync(src)) copyRecursive(src, path.join(DIST, entry));
  }
  console.log(`Copied ${RUNTIME_ENTRIES.length} runtime entries into ${DIST}\n`);

  console.log('== 3. Deterministic manifest hash ==');
  const digest = hashDist(DIST);
  console.log(`SHA-256(dist): ${digest}`);
  fs.writeFileSync(path.join(ROOT, 'BUILD_HASH.txt'), `${digest}\n`);
  console.log('\nBuild complete. Run with: node server.js  (or) node dist/server.js');
}

main();
