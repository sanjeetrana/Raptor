/**
 * Zero-Dependency Test Suite for RepoLens HTML Report Generator
 * Run with: `node test/test-report.js`
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { generateHtmlReport, writeHtmlReport } = require('../src/report');

console.log('=== Running Static HTML Report Tests ===');

const mockReport = {
  project: {
    path: 'D:/Projects/sample-app',
    fileCount: 5
  },
  statistics: {
    totalFiles: 5,
    totalLines: 450,
    totalBlankLines: 60,
    totalFunctions: 12,
    totalClasses: 2,
    totalTodos: 3,
    totalFixmes: 1,
    largestFile: {
      path: 'src/services/auth.js',
      lines: 180
    }
  },
  architecture: {
    graph: {
      'server.js': ['src/routes.js'],
      'src/routes.js': ['src/services/auth.js'],
      'src/services/auth.js': []
    },
    dependencyCounts: {
      'server.js': 1,
      'src/routes.js': 1,
      'src/services/auth.js': 0
    },
    dependentCounts: {
      'server.js': 0,
      'src/routes.js': 1,
      'src/services/auth.js': 1
    },
    entryPoints: ['server.js'],
    leafModules: ['src/services/auth.js'],
    circularDependencies: [],
    mostDependedOn: [
      { path: 'src/services/auth.js', dependents: 1 },
      { path: 'src/routes.js', dependents: 1 }
    ]
  },
  recommendations: [
    {
      path: 'server.js',
      score: 35.4,
      reasons: ['Entry point', 'Contains 2 functions']
    },
    {
      path: 'src/services/auth.js',
      score: 22.8,
      reasons: ['Used by 1 file', 'Contains 1 class']
    }
  ],
  routes: [
    {
      method: 'POST',
      path: '/api/login',
      handler: 'authController.login',
      file: 'src/routes.js'
    },
    {
      method: 'GET',
      path: '/api/users',
      handler: 'getUsers',
      file: 'src/routes.js'
    }
  ]
};

// Test 1: generateHtmlReport returns valid HTML string
const html = generateHtmlReport(mockReport, { title: 'Test Report Title' });
assert.strictEqual(typeof html, 'string', 'Report should be a string');
console.log('✓ Test 1 Passed: HTML returned as string.');

// Test 2: Report title appears
assert.ok(html.includes('Test Report Title'), 'Title must be present in HTML');
console.log('✓ Test 2 Passed: Custom title appears in document.');

// Test 3: Project statistics appear
assert.ok(html.includes('450'), 'Total lines must appear');
assert.ok(html.includes('src/services/auth.js'), 'Largest file must appear');
assert.ok(html.includes('180 lines'), 'Largest file line count must appear');
console.log('✓ Test 3 Passed: Statistics appear correctly in rendered output.');

// Test 4: Recommendations appear
assert.ok(html.includes('#1'), 'Recommendation rank #1 must appear');
assert.ok(html.includes('35.40'), 'Recommendation score must appear');
assert.ok(html.includes('Entry point'), 'Reason "Entry point" must appear');
console.log('✓ Test 4 Passed: Recommendations appear correctly.');

// Test 5: Architecture information appears
assert.ok(html.includes('server.js'), 'Entry point server.js must appear');
assert.ok(html.includes('src/services/auth.js'), 'Leaf module must appear');
console.log('✓ Test 5 Passed: Architecture information appears.');

// Test 6: Routes appear
assert.ok(html.includes('/api/login'), 'Route path /api/login must appear');
assert.ok(html.includes('authController.login'), 'Handler name must appear');
assert.ok(html.includes('badge-post'), 'POST badge class must appear');
console.log('✓ Test 6 Passed: Route table rendered correctly.');

// Test 7: Circular dependency info appears
assert.ok(html.includes('No circular dependencies detected'), 'Clean state for no cycles must appear');

// Test 7.2: Report with cycles
const reportWithCycles = {
  ...mockReport,
  architecture: {
    ...mockReport.architecture,
    circularDependencies: [['A.js', 'B.js', 'A.js']]
  }
};
const htmlWithCycles = generateHtmlReport(reportWithCycles);
assert.ok(htmlWithCycles.includes('Circular Dependencies Detected'), 'Cycles warning must appear');
assert.ok(htmlWithCycles.includes('A.js &rarr; B.js &rarr; A.js'), 'Cycle path must appear');
console.log('✓ Test 7 Passed: Circular dependency information handled cleanly.');

// Test 8: Raw JSON section exists
assert.ok(html.includes('<details class="raw-json-details">'), 'Details element must exist');
assert.ok(html.includes('View Raw JSON Report'), 'Summary title must exist');
console.log('✓ Test 8 Passed: Raw JSON collapsible section exists.');

// Test 9: HTML contains embedded <style>
assert.ok(html.includes('<style>'), '<style> tag must be present');
assert.ok(html.includes('</style>'), '</style> tag must be present');
console.log('✓ Test 9 Passed: Embedded CSS stylesheet verified.');

// Test 10: HTML does not reference external CDN libraries
assert.ok(!html.includes('http://'), 'No external http:// resources');
assert.ok(!html.includes('https://'), 'No external https:// resources');
assert.ok(!html.includes('cdn.'), 'No CDN references');
assert.ok(!html.includes('unpkg.com'), 'No unpkg references');
assert.ok(!html.includes('cdnjs'), 'No cdnjs references');
console.log('✓ Test 10 Passed: 100% self-contained zero-dependency HTML confirmed.');

// Test 11: writeHtmlReport creates the expected file and cleans up
const tempHtmlPath = path.join(__dirname, '__temp_report__.html');
try {
  const writtenPath = writeHtmlReport(mockReport, tempHtmlPath);
  assert.strictEqual(fs.existsSync(tempHtmlPath), true);
  const fileContent = fs.readFileSync(writtenPath, 'utf-8');
  assert.ok(fileContent.includes('RepoLens'));
  console.log('✓ Test 11 Passed: writeHtmlReport successfully writes file to disk.');
} finally {
  if (fs.existsSync(tempHtmlPath)) {
    fs.unlinkSync(tempHtmlPath);
  }
}

console.log('\nAll static HTML report tests passed successfully!');
