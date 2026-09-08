/**
 * Zero-Dependency Test Suite for RepoLens Scanner
 * Run with: `npm test` or `node test/test-scanner.js`
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { scanFiles } = require('../src/scanner');

console.log('=== Running Scanner Tests ===');

// Setup temporary test fixture directory
const testSandbox = path.join(__dirname, '__temp_fixture__');

function setupFixture() {
  if (fs.existsSync(testSandbox)) {
    fs.rmSync(testSandbox, { recursive: true, force: true });
  }

  // Create folder hierarchy
  fs.mkdirSync(path.join(testSandbox, 'src', 'utils'), { recursive: true });
  fs.mkdirSync(path.join(testSandbox, 'node_modules', 'dummy-pkg'), { recursive: true });
  fs.mkdirSync(path.join(testSandbox, '.git'), { recursive: true });

  // Create dummy files
  fs.writeFileSync(path.join(testSandbox, 'index.js'), '// entrypoint');
  fs.writeFileSync(path.join(testSandbox, 'src', 'app.js'), '// app logic');
  fs.writeFileSync(path.join(testSandbox, 'src', 'utils', 'helper.js'), '// helper');
  fs.writeFileSync(path.join(testSandbox, 'README.md'), '# Docs');
  fs.writeFileSync(path.join(testSandbox, 'src', 'styles.css'), '/* css */');
  fs.writeFileSync(path.join(testSandbox, 'node_modules', 'dummy-pkg', 'index.js'), '// ignore me');
  fs.writeFileSync(path.join(testSandbox, '.git', 'HEAD.js'), '// ignore me');
}

function cleanupFixture() {
  if (fs.existsSync(testSandbox)) {
    fs.rmSync(testSandbox, { recursive: true, force: true });
  }
}

try {
  setupFixture();

  // Test 1: Default scan should only find .js files outside ignored folders
  const results = scanFiles(testSandbox);
  console.log(`\n[Test 1] Found files:`, results);

  assert.strictEqual(results.length, 3, 'Should find exactly 3 .js files (index.js, app.js, helper.js)');
  assert.ok(results.some((f) => f.endsWith('/index.js')), 'Should include index.js');
  assert.ok(results.some((f) => f.endsWith('/src/app.js')), 'Should include src/app.js');
  assert.ok(results.some((f) => f.endsWith('/src/utils/helper.js')), 'Should include src/utils/helper.js');
  assert.ok(!results.some((f) => f.includes('node_modules')), 'Must not include files in node_modules');
  assert.ok(!results.some((f) => f.includes('.git')), 'Must not include files in .git');
  console.log('✓ Test 1 Passed: Recursive discovery and default ignore working correctly.');

  // Test 2: Custom extension filtering
  const mdAndCssFiles = scanFiles(testSandbox, { extensions: ['.md', '.css'] });
  assert.strictEqual(mdAndCssFiles.length, 2, 'Should find exactly 2 files for .md and .css extensions');
  console.log('✓ Test 2 Passed: Custom extensions filtering works.');

  // Test 3: Error handling for non-existent path
  assert.throws(
    () => scanFiles(path.join(testSandbox, 'does_not_exist')),
    /Path does not exist/,
    'Should throw error when path does not exist'
  );
  console.log('✓ Test 3 Passed: Error handling for non-existent path works.');

  console.log('\nAll tests passed successfully!');
} catch (error) {
  console.error('\n❌ Test failed:', error);
  process.exitCode = 1;
} finally {
  cleanupFixture();
}
