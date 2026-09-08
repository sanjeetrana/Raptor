/**
 * RepoLens - Master Test Runner
 * Executes all unit and integration test suites sequentially.
 */

const { execSync } = require('child_process');
const path = require('path');

const testSuites = [
  'test/test-scanner.js',
  'test/test-analyzer.js',
  'test/test-statistics.js',
  'test/test-dependencies.js',
  'test/test-architecture.js',
  'test/test-start.js',
  'test/test-routes.js',
  'test/test-project.js',
  'test/test-report.js'
];

console.log('==============================================');
console.log('   Running RepoLens Test Suite (Zero Deps)    ');
console.log('==============================================\n');

let passed = 0;

for (const suite of testSuites) {
  const fullPath = path.resolve(__dirname, '..', suite);
  console.log(`\n▶ [Executing] ${suite}...`);
  try {
    const output = execSync(`node "${fullPath}"`, {
      encoding: 'utf-8',
      stdio: 'pipe'
    });
    console.log(output.trim());
    passed++;
  } catch (err) {
    console.error(`\n❌ Test suite failed: ${suite}`);
    if (err.stdout) console.log(err.stdout);
    if (err.stderr) console.error(err.stderr);
    process.exit(1);
  }
}

console.log('\n==============================================');
console.log(`✅ All ${passed}/${testSuites.length} Test Suites Passed Successfully!`);
console.log('==============================================\n');
