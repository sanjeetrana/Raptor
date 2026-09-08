/**
 * Zero-Dependency Test Suite for RepoLens Unified Project Pipeline
 * Run with: `node test/test-project.js`
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { analyzeProject } = require('../src/project');

console.log('=== Running Unified Project Pipeline Tests ===');

const fixtureDir = path.join(__dirname, '__temp_unified_project__');

function setupFixture() {
  if (fs.existsSync(fixtureDir)) {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }

  fs.mkdirSync(path.join(fixtureDir, 'src', 'controllers'), { recursive: true });
  fs.mkdirSync(path.join(fixtureDir, 'src', 'routes'), { recursive: true });
  fs.mkdirSync(path.join(fixtureDir, 'src', 'models'), { recursive: true });

  // 1. Model: User.js
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'models', 'User.js'),
    `class User {
  constructor(name) { this.name = name; }
}
module.exports = { User };`
  );

  // 2. Controller: userController.js (Imports User model)
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'controllers', 'userController.js'),
    `const { User } = require('../models/User');
// TODO: Implement user caching
// FIXME: Fix validation edge-case

function getUsers(req, res) { return []; }
function createUser(req, res) { return new User('alice'); }

module.exports = { getUsers, createUser };`
  );

  // 3. Route: userRoutes.js (Imports userController and declares routes)
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'routes', 'userRoutes.js'),
    `const router = require('express').Router();
const userCtrl = require('../controllers/userController');

router.get('/users', userCtrl.getUsers);
router.post('/users', userCtrl.createUser);
router.delete('/users/:id', (req, res) => res.send('deleted'));

module.exports = router;`
  );

  // 4. Server: app.js (Entry point: imports userRoutes)
  fs.writeFileSync(
    path.join(fixtureDir, 'app.js'),
    `const express = require('express');
const userRoutes = require('./src/routes/userRoutes');
const app = express();

app.get('/health', (req, res) => res.json({ status: 'ok' }));

function startServer(port) {
  return app.listen(port);
}

module.exports = { app, startServer };`
  );
}

function cleanupFixture() {
  if (fs.existsSync(fixtureDir)) {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }
}

try {
  setupFixture();

  // Test 1: Full pipeline execution on realistic project fixture
  const report = analyzeProject(fixtureDir);
  console.log('\n[Test 1] Generated Project Analysis Report:\n', JSON.stringify(report, null, 2));

  // 1.1 JSON serializability check
  const serialized = JSON.stringify(report);
  const reParsed = JSON.parse(serialized);
  assert.deepStrictEqual(reParsed, report, 'Report must be strictly JSON-serializable');
  console.log('✓ Test 1.1 Passed: Report is fully JSON-serializable.');

  // 1.2 Project metadata verification
  assert.strictEqual(typeof report.project.path, 'string');
  assert.strictEqual(report.project.fileCount, 4);
  console.log('✓ Test 1.2 Passed: Project file count & path verified.');

  // 1.3 Statistics verification
  assert.strictEqual(report.statistics.totalFiles, 4);
  assert.ok(report.statistics.totalLines > 20);
  assert.strictEqual(report.statistics.totalClasses, 1, 'Should find User class');
  assert.strictEqual(report.statistics.totalTodos, 1, 'Should find 1 TODO');
  assert.strictEqual(report.statistics.totalFixmes, 1, 'Should find 1 FIXME');
  assert.ok(report.statistics.totalFunctions >= 3, 'Should find functions');
  assert.ok(report.statistics.largestFile !== null);
  console.log('✓ Test 1.3 Passed: Project statistics verified.');

  // 1.4 Architecture verification
  assert.ok(report.architecture.entryPoints.includes('app.js'), 'app.js should be an entry point');
  assert.ok(report.architecture.leafModules.includes('src/models/User.js'), 'User.js should be a leaf module');
  assert.deepStrictEqual(report.architecture.circularDependencies, [], 'No circular dependencies');
  assert.strictEqual(report.architecture.dependencyCounts['app.js'], 1);
  console.log('✓ Test 1.4 Passed: Architecture analysis verified.');

  // 1.5 Recommendations verification
  assert.strictEqual(report.recommendations.length, 3, 'Should return top 3 starting recommendations');
  assert.strictEqual(report.recommendations[0].path, 'app.js', 'app.js entry point should be top recommendation');
  assert.ok(report.recommendations[0].reasons.includes('Entry point'));
  console.log('✓ Test 1.5 Passed: Starting recommendations verified.');

  // 1.6 Route Map verification
  assert.strictEqual(report.routes.length, 4, 'Should detect 4 routes across files');
  assert.ok(report.routes.some(r => r.method === 'GET' && r.path === '/users' && r.handler === 'userCtrl.getUsers'));
  assert.ok(report.routes.some(r => r.method === 'POST' && r.path === '/users' && r.handler === 'userCtrl.createUser'));
  assert.ok(report.routes.some(r => r.method === 'DELETE' && r.path === '/users/:id' && r.handler === 'anonymous'));
  assert.ok(report.routes.some(r => r.method === 'GET' && r.path === '/health' && r.handler === 'anonymous'));
  console.log('✓ Test 1.6 Passed: Route Map endpoints and handlers verified.');

  // Test 2: Empty Directory Handling
  const emptyFixtureDir = path.join(__dirname, '__temp_empty_project__');
  try {
    fs.mkdirSync(emptyFixtureDir, { recursive: true });
    const emptyReport = analyzeProject(emptyFixtureDir);

    assert.strictEqual(emptyReport.project.fileCount, 0);
    assert.strictEqual(emptyReport.statistics.totalFiles, 0);
    assert.deepStrictEqual(emptyReport.recommendations, []);
    assert.deepStrictEqual(emptyReport.routes, []);
    assert.deepStrictEqual(emptyReport.architecture.circularDependencies, []);
    console.log('✓ Test 2 Passed: Empty project directory handled cleanly.');
  } finally {
    if (fs.existsSync(emptyFixtureDir)) {
      fs.rmSync(emptyFixtureDir, { recursive: true, force: true });
    }
  }

  console.log('\nAll unified project pipeline tests passed successfully!');
} catch (err) {
  console.error('\n❌ Test failed:', err);
  process.exitCode = 1;
} finally {
  cleanupFixture();
}
