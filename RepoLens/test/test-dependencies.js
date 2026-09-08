/**
 * Zero-Dependency Test Suite for RepoLens Dependency Analysis Engine
 * Run with: `node test/test-dependencies.js`
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const {
  extractImportSpecifiers,
  resolveImportPath,
  analyzeFileDependencies,
  buildDependencyGraph
} = require('../src/dependencies');

console.log('=== Running Static Dependency Analysis Tests ===');

// Setup temporary test fixture
const fixtureDir = path.join(__dirname, '__temp_dep_fixture__');

function setupFixture() {
  if (fs.existsSync(fixtureDir)) {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }

  fs.mkdirSync(path.join(fixtureDir, 'src', 'controllers'), { recursive: true });
  fs.mkdirSync(path.join(fixtureDir, 'src', 'models'), { recursive: true });
  fs.mkdirSync(path.join(fixtureDir, 'src', 'utils'), { recursive: true });

  // 1. Model file: user.js (has no dependencies)
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'models', 'user.js'),
    'module.exports = { User: class User {} };'
  );

  // 2. Utils file: helper.js (has no dependencies)
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'utils', 'helper.js'),
    'export const formatName = (name) => name.trim();'
  );

  // 3. Controller file: userController.js
  // Imports:
  // - ES named import: "../utils/helper.js"
  // - CommonJS relative require with extension-less path: "../models/user"
  // - External packages (must be ignored): "express", "lodash", "fs"
  // - Dynamic require (must be ignored): require(dynamicPath)
  // - Duplicate import (must be deduplicated): "../models/user"
  // - Missing import (must be ignored): "./does_not_exist"
  const userControllerContent = `
    const express = require('express');
    const lodash = require("lodash");
    const fs = require('fs');
    const dynamicModule = 'some_module';
    const dyn = require(dynamicModule);

    import { formatName } from "../utils/helper.js";
    const { User } = require('../models/user');
    const duplicateUser = require("../models/user");
    const missing = require("./does_not_exist");

    // Commented out import should be ignored:
    // const fake = require("./fake_controller");
  `;
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'controllers', 'userController.js'),
    userControllerContent
  );

  // 4. Routes file: userRoutes.js (imports userController with ES import)
  const userRoutesContent = `
    import userController from "./controllers/userController.js";
    import "./controllers/userController"; // duplicate / extension-less
    import express from 'express';
  `;
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'userRoutes.js'),
    userRoutesContent
  );
}

function cleanupFixture() {
  if (fs.existsSync(fixtureDir)) {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }
}

try {
  setupFixture();

  // Test 1: extractImportSpecifiers ignores external packages, comments, and dynamic requires
  const sampleCode = `
    import user from "./user.js";
    import { getUser } from './user.js';
    import "./setup.js";
    const auth = require("./auth");
    const { login } = require('./auth');
    const express = require('express');
    const path = require("path");
    const dynamic = require(foo);
    // const commented = require("./commented.js");
    /* import fake from "./fake.js"; */
  `;

  const extracted = extractImportSpecifiers(sampleCode);
  console.log('\n[Test 1] Extracted Specifiers:', extracted);

  assert.ok(extracted.includes('./user.js'), 'Should extract ES default/named import "./user.js"');
  assert.ok(extracted.includes('./setup.js'), 'Should extract ES side-effect import "./setup.js"');
  assert.ok(extracted.includes('./auth'), 'Should extract CommonJS require "./auth"');
  assert.strictEqual(extracted.filter(s => s === './user.js').length, 1, 'Should deduplicate "./user.js"');
  assert.strictEqual(extracted.filter(s => s === './auth').length, 1, 'Should deduplicate "./auth"');
  assert.ok(!extracted.includes('express'), 'Must ignore external package "express"');
  assert.ok(!extracted.includes('path'), 'Must ignore built-in module "path"');
  assert.ok(!extracted.includes('./commented.js'), 'Must ignore single-line commented import');
  assert.ok(!extracted.includes('./fake.js'), 'Must ignore multi-line commented import');
  console.log('✓ Test 1 Passed: Specifier extraction & filtering works accurately.');

  // Test 2: Extension-less resolution
  const controllerFile = path.join(fixtureDir, 'src', 'controllers', 'userController.js');
  const resolvedModel = resolveImportPath(controllerFile, '../models/user');
  assert.ok(resolvedModel !== null, 'Extension-less "../models/user" should resolve');
  assert.ok(resolvedModel.endsWith(path.join('src', 'models', 'user.js')), 'Should resolve to user.js');
  console.log('✓ Test 2 Passed: Extension-less import resolution works.');

  // Test 3: Missing imported file is ignored
  const missingResolved = resolveImportPath(controllerFile, './does_not_exist');
  assert.strictEqual(missingResolved, null, 'Non-existent file returns null');
  console.log('✓ Test 3 Passed: Missing imports safely return null.');

  // Test 4: analyzeFileDependencies for userController.js
  const controllerDeps = analyzeFileDependencies(controllerFile, { projectRoot: fixtureDir });
  console.log('\n[Test 4] userController.js dependencies:', controllerDeps);

  assert.strictEqual(controllerDeps.length, 2, 'Should have exactly 2 local dependencies');
  assert.ok(controllerDeps.includes('src/models/user.js'), 'Should include src/models/user.js');
  assert.ok(controllerDeps.includes('src/utils/helper.js'), 'Should include src/utils/helper.js');
  assert.ok(!controllerDeps.some(d => d.includes('express')), 'No express');
  assert.ok(!controllerDeps.some(d => d.includes('does_not_exist')), 'No non-existent file');
  console.log('✓ Test 4 Passed: File-level dependency analysis verified.');

  // Test 5: Full Project Dependency Graph
  const allFiles = [
    path.join(fixtureDir, 'src', 'userRoutes.js'),
    path.join(fixtureDir, 'src', 'controllers', 'userController.js'),
    path.join(fixtureDir, 'src', 'models', 'user.js'),
    path.join(fixtureDir, 'src', 'utils', 'helper.js')
  ];

  const graph = buildDependencyGraph(allFiles, { projectRoot: fixtureDir });
  console.log('\n[Test 5] Built Project Dependency Graph:\n', JSON.stringify(graph, null, 2));

  assert.deepStrictEqual(graph['src/userRoutes.js'], ['src/controllers/userController.js']);
  assert.deepStrictEqual(graph['src/controllers/userController.js'].sort(), ['src/models/user.js', 'src/utils/helper.js'].sort());
  assert.deepStrictEqual(graph['src/models/user.js'], []);
  assert.deepStrictEqual(graph['src/utils/helper.js'], []);
  console.log('✓ Test 5 Passed: Full dependency graph matches expected architecture structure.');

  console.log('\nAll static dependency tests passed successfully!');
} catch (err) {
  console.error('\n❌ Test failed:', err);
  process.exitCode = 1;
} finally {
  cleanupFixture();
}
