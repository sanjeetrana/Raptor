/**
 * Zero-Dependency Test Suite for RepoLens "Where Should I Start?" Engine
 * Run with: `node test/test-start.js`
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { recommendStartingFiles, scoreFile } = require('../src/start');

console.log('=== Running "Where Should I Start?" Tests ===');

// Test 1: scoreFile unit test with exact manual arithmetic
const mockSourceReport = {
  path: 'src/controllers/user.js',
  lines: 350,
  blankLines: 40,
  todos: 2,
  fixmes: 1,
  functions: ['getUsers', 'createUser', 'deleteUser'], // 3 functions
  classes: ['UserController']                          // 1 class
};

// Expected calculation:
// dependentCount (8) * 5 = 40
// isEntryPoint (false) = 0
// functionCount (3) * 2 = 6
// classCount (1) * 3 = 3
// todoCount (2) * 2 = 4
// fixmeCount (1) * 3 = 3
// lineCount (350) / 100 = 3.5
// Total = 40 + 0 + 6 + 3 + 4 + 3 + 3.5 = 59.5
const unitScored = scoreFile({
  filePath: 'src/controllers/user.js',
  dependentCount: 8,
  isEntryPoint: false,
  sourceReport: mockSourceReport
});

console.log('\n[Test 1] Unit Scored Output:\n', JSON.stringify(unitScored, null, 2));

assert.strictEqual(unitScored.score, 59.5, 'Score arithmetic must be exact');
assert.deepStrictEqual(unitScored.reasons, [
  'Used by 8 files',
  'Contains 3 functions',
  'Contains 1 class',
  'Contains 2 TODOs',
  'Contains 1 FIXME'
], 'Reasons must match formatted rules');
console.log('✓ Test 1 Passed: Exact score arithmetic and reason generation verified.');

// Test 2: Entry point scoring
const entryScored = scoreFile({
  filePath: 'server.js',
  dependentCount: 0,
  isEntryPoint: true,
  sourceReport: {
    lines: 100,
    todos: 0,
    fixmes: 0,
    functions: ['startServer'],
    classes: []
  }
});
// 0*5 + 20 + 1*2 + 0*3 + 0*2 + 0*3 + 100/100 = 20 + 2 + 1 = 23
assert.strictEqual(entryScored.score, 23);
assert.deepStrictEqual(entryScored.reasons, [
  'Entry point',
  'Contains 1 function'
], 'Entry point reason present, 0-dependents not mentioned');
console.log('✓ Test 2 Passed: Entry-point bonus (+20) and clean reasons verified.');

// Test 3: Empty project handling
const emptyRecommendations = recommendStartingFiles([]);
assert.deepStrictEqual(emptyRecommendations, []);
console.log('✓ Test 3 Passed: Empty file list returns empty recommendations.');

// Test 4: End-to-End Integration on Physical Project Fixture
const fixtureDir = path.join(__dirname, '__temp_start_fixture__');

function setupFixture() {
  if (fs.existsSync(fixtureDir)) {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }

  fs.mkdirSync(path.join(fixtureDir, 'src', 'controllers'), { recursive: true });
  fs.mkdirSync(path.join(fixtureDir, 'src', 'db'), { recursive: true });

  // 1. server.js (Entry point: 0 dependents, imports routes)
  fs.writeFileSync(
    path.join(fixtureDir, 'server.js'),
    `const routes = require('./routes');\nfunction start() {}\nstart();\n`
  );

  // 2. routes.js (Imported by server.js, imports controller)
  fs.writeFileSync(
    path.join(fixtureDir, 'routes.js'),
    `const userCtrl = require('./src/controllers/user');\nfunction setupRoutes() {}\n`
  );

  // 3. src/controllers/user.js (Imported by routes.js, imports db.js)
  // Has 2 functions, 1 TODO, 1 FIXME
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'controllers', 'user.js'),
    `const db = require('../db/database');\n// TODO: add validation\n// FIXME: fix leak\nfunction getUser() {}\nfunction saveUser() {}\n`
  );

  // 4. src/db/database.js (Core leaf module imported by controller: 1 dependent)
  // Has 1 class, 2 functions
  fs.writeFileSync(
    path.join(fixtureDir, 'src', 'db', 'database.js'),
    `class Database {}\nfunction connect() {}\nfunction query() {}\nmodule.exports = { Database };\n`
  );
}

function cleanupFixture() {
  if (fs.existsSync(fixtureDir)) {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }
}

try {
  setupFixture();

  const filePaths = [
    path.join(fixtureDir, 'server.js'),
    path.join(fixtureDir, 'routes.js'),
    path.join(fixtureDir, 'src', 'controllers', 'user.js'),
    path.join(fixtureDir, 'src', 'db', 'database.js')
  ];

  // Test 4.1: Default Limit (Top 3)
  const top3 = recommendStartingFiles(filePaths, { projectRoot: fixtureDir });
  console.log('\n[Test 4.1] Top 3 Recommendations:\n', JSON.stringify(top3, null, 2));

  assert.strictEqual(top3.length, 3, 'Should return exactly 3 recommendations by default');

  // Verify descending order
  assert.ok(top3[0].score >= top3[1].score);
  assert.ok(top3[1].score >= top3[2].score);
  console.log('✓ Test 4.1 Passed: Default top 3 returned and sorted descending.');

  // Test 4.2: Custom Limit (limit: 2)
  const top2 = recommendStartingFiles(filePaths, { projectRoot: fixtureDir, limit: 2 });
  assert.strictEqual(top2.length, 2, 'Custom limit should return 2 recommendations');
  console.log('✓ Test 4.2 Passed: Custom limit respected.');

  // Test 4.3: Custom Limit (limit: 10) on 4 files
  const topAll = recommendStartingFiles(filePaths, { projectRoot: fixtureDir, limit: 10 });
  assert.strictEqual(topAll.length, 4, 'Returns all 4 files when limit exceeds total files');
  console.log('✓ Test 4.3 Passed: Handles limit greater than file count.');

  console.log('\nAll "Where Should I Start?" tests passed successfully!');
} catch (err) {
  console.error('\n❌ Test failed:', err);
  process.exitCode = 1;
} finally {
  cleanupFixture();
}
