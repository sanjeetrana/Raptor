/**
 * Zero-Dependency Test Suite for RepoLens Project Statistics Engine
 * Run with: `node test/test-statistics.js`
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { aggregateAnalysisResults, calculateProjectStats } = require('../src/statistics');

console.log('=== Running Project Statistics Tests ===');

// Test 1: Aggregate mock analysis reports
const mockReports = [
  {
    path: 'src/controllers/user.js',
    lines: 120,
    blankLines: 15,
    todos: 2,
    fixmes: 1,
    functions: ['getUser', 'createUser', 'deleteUser'],
    classes: ['UserController']
  },
  {
    path: 'src/services/auth.js',
    lines: 250, // largest file
    blankLines: 30,
    todos: 3,
    fixmes: 0,
    functions: ['login', 'generateToken', 'verifyToken', 'logout'],
    classes: ['AuthService']
  },
  {
    path: 'src/utils/helpers.js',
    lines: 45,
    blankLines: 5,
    todos: 0,
    fixmes: 1,
    functions: ['formatDate', 'sanitizeInput'],
    classes: []
  }
];

const stats = aggregateAnalysisResults(mockReports);
console.log('\n[Test 1] Aggregated Stats Output:\n', JSON.stringify(stats, null, 2));

assert.strictEqual(stats.totalFiles, 3, 'Total files should be 3');
assert.strictEqual(stats.totalLines, 120 + 250 + 45, 'Total lines should sum to 415');
assert.strictEqual(stats.totalBlankLines, 15 + 30 + 5, 'Total blank lines should sum to 50');
assert.strictEqual(stats.totalFunctions, 3 + 4 + 2, 'Total functions should sum to 9');
assert.strictEqual(stats.totalClasses, 1 + 1 + 0, 'Total classes should sum to 2');
assert.strictEqual(stats.totalTodos, 2 + 3 + 0, 'Total todos should sum to 5');
assert.strictEqual(stats.totalFixmes, 1 + 0 + 1, 'Total fixmes should sum to 2');
assert.deepStrictEqual(
  stats.largestFile,
  { path: 'src/services/auth.js', lines: 250 },
  'Largest file should be correctly identified'
);
console.log('✓ Test 1 Passed: Aggregation of individual file reports is accurate.');

// Test 2: Edge case with empty list of files
const emptyStats = aggregateAnalysisResults([]);
assert.strictEqual(emptyStats.totalFiles, 0);
assert.strictEqual(emptyStats.totalLines, 0);
assert.strictEqual(emptyStats.totalBlankLines, 0);
assert.strictEqual(emptyStats.totalFunctions, 0);
assert.strictEqual(emptyStats.totalClasses, 0);
assert.strictEqual(emptyStats.totalTodos, 0);
assert.strictEqual(emptyStats.totalFixmes, 0);
assert.strictEqual(emptyStats.largestFile, null);
console.log('✓ Test 2 Passed: Empty list yields safe default stats object.');

// Test 3: Integration test with physical files on disk via calculateProjectStats
const tempDir = path.join(__dirname, '__temp_stats_fixture__');
try {
  fs.mkdirSync(tempDir, { recursive: true });

  const fileA = path.join(tempDir, 'fileA.js');
  const fileB = path.join(tempDir, 'fileB.js');

  fs.writeFileSync(
    fileA,
    '// TODO: test\nfunction a() {}\nfunction b() {}\n' // 4 lines, 2 functions, 1 todo
  );
  fs.writeFileSync(
    fileB,
    'class MyClass {}\n// FIXME: fix\n\nconst c = () => {};\n' // 5 lines, 1 class, 1 function, 1 fixme, 1 blank
  );

  const projectStats = calculateProjectStats([fileA, fileB]);
  console.log('\n[Test 3] End-to-end Project Stats on Temp Files:\n', JSON.stringify(projectStats, null, 2));

  assert.strictEqual(projectStats.totalFiles, 2);
  assert.strictEqual(projectStats.totalLines, 9);
  assert.strictEqual(projectStats.totalBlankLines, 3);
  assert.strictEqual(projectStats.totalFunctions, 3);
  assert.strictEqual(projectStats.totalClasses, 1);
  assert.strictEqual(projectStats.totalTodos, 1);
  assert.strictEqual(projectStats.totalFixmes, 1);
  assert.strictEqual(projectStats.largestFile.lines, 5);
  console.log('✓ Test 3 Passed: calculateProjectStats works end-to-end with analyzer.');
} finally {
  if (fs.existsSync(tempDir)) {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

console.log('\nAll project statistics tests passed successfully!');
