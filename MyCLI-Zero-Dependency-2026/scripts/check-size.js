#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const ignored = new Set(['node_modules', '.git', 'release', 'dist', 'logs', '.cache', 'coverage']);
const max = 100 * 1024 * 1024;
let total = 0;
let files = 0;

function walk(folder) {
  for (const item of fs.readdirSync(folder, { withFileTypes: true })) {
    if (ignored.has(item.name)) continue;
    const full = path.join(folder, item.name);
    if (item.isDirectory()) walk(full);
    else if (item.isFile()) { total += fs.statSync(full).size; files++; }
  }
}

walk(root);
console.log(`MyCLI source files: ${files}`);
console.log(`MyCLI source size: ${(total / 1024 / 1024).toFixed(2)} MB`);
if (total >= max) {
  console.error('FAIL: source folder is not under 100 MB. Remove generated artifacts or large assets.');
  process.exitCode = 1;
} else {
  console.log('PASS: source folder is under 100 MB.');
}
