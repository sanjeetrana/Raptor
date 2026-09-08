/**
 * Zero-Dependency Test Suite for RepoLens JavaScript Source Analyzer
 * Run with: `node test/test-analyzer.js`
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { analyzeSource, analyzeCode } = require('../src/analyzer');

console.log('=== Running Source Analyzer Tests ===');

// Sample code covering various JavaScript constructs, comments, and spacing
const sampleCode = `
// TODO: Refactor this module later
// FIXME: Resolve edge cases in parser

class User {
  constructor(name) {
    this.name = name;
  }
}

class AdminService extends User {
  // admin methods
}

function getUsers() {
  return [];
}

async function fetchUserById(id) {
  return null;
}

const createUser = (data) => {
  return data;
};

const deleteUser = async (id) => {
  // todo: verify authorization
  return true;
};

const updateUser = function(id, data) {
  /* FIXME: validate input data */
  return data;
};

const inlineArrow = x => x * 2;
`;

// Test 1: Test analyzeCode with in-memory sample
const analysis = analyzeCode(sampleCode, 'src/example.js');
console.log('\n[Test 1] In-memory Analysis Output:', JSON.stringify(analysis, null, 2));

// Verify lines & blank lines
assert.strictEqual(analysis.path, 'src/example.js', 'Path should be preserved');
assert.strictEqual(typeof analysis.lines, 'number', 'Lines count should be a number');
assert.ok(analysis.lines > 0, 'Lines should be greater than 0');
assert.strictEqual(typeof analysis.blankLines, 'number', 'Blank lines count should be a number');
assert.ok(analysis.blankLines > 0, 'Should detect blank lines');
console.log(`✓ Line Counting Verified (${analysis.lines} lines, ${analysis.blankLines} blank lines)`);

// Verify TODO / FIXME detection (should be case-insensitive)
// TODOs: line 2 ("TODO:"), line 25 ("todo:")
// FIXMEs: line 3 ("FIXME:"), line 30 ("FIXME:")
assert.strictEqual(analysis.todos, 2, 'Should detect exactly 2 TODO occurrences');
assert.strictEqual(analysis.fixmes, 2, 'Should detect exactly 2 FIXME occurrences');
console.log(`✓ TODO/FIXME Counting Verified (${analysis.todos} todos, ${analysis.fixmes} fixmes)`);

// Verify Class Detection
assert.ok(analysis.classes.includes('User'), 'Should detect "User" class');
assert.ok(analysis.classes.includes('AdminService'), 'Should detect "AdminService" class');
assert.strictEqual(analysis.classes.length, 2, 'Should detect exactly 2 classes');
console.log(`✓ Class Detection Verified:`, analysis.classes);

// Verify Function Detection
const expectedFunctions = [
  'getUsers',
  'fetchUserById',
  'createUser',
  'deleteUser',
  'updateUser',
  'inlineArrow'
];

for (const fn of expectedFunctions) {
  assert.ok(
    analysis.functions.includes(fn),
    `Should detect function "${fn}". Detected functions: ${JSON.stringify(analysis.functions)}`
  );
}
assert.strictEqual(analysis.functions.length, expectedFunctions.length, 'Function count should match');
console.log(`✓ Function Detection Verified:`, analysis.functions);

// Test 2: File reading with analyzeSource
const tempFilePath = path.join(__dirname, '__temp_sample__.js');
try {
  fs.writeFileSync(tempFilePath, sampleCode);
  const fileAnalysis = analyzeSource(tempFilePath);

  assert.strictEqual(fileAnalysis.lines, analysis.lines);
  assert.strictEqual(fileAnalysis.todos, 2);
  assert.strictEqual(fileAnalysis.classes.length, 2);
  console.log('✓ Test 2 Passed: analyzeSource works seamlessly on physical disk files.');
} finally {
  if (fs.existsSync(tempFilePath)) {
    fs.unlinkSync(tempFilePath);
  }
}

// Test 3: Empty file handling
const emptyAnalysis = analyzeCode('', 'empty.js');
assert.strictEqual(emptyAnalysis.lines, 0);
assert.strictEqual(emptyAnalysis.blankLines, 0);
assert.strictEqual(emptyAnalysis.todos, 0);
assert.strictEqual(emptyAnalysis.fixmes, 0);
assert.deepStrictEqual(emptyAnalysis.functions, []);
assert.deepStrictEqual(emptyAnalysis.classes, []);
console.log('✓ Test 3 Passed: Empty file handled cleanly.');

console.log('\nAll analyzer tests passed successfully!');
