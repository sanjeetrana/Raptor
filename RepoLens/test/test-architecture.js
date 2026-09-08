/**
 * Zero-Dependency Test Suite for RepoLens Architecture Analysis Engine
 * Run with: `node test/test-architecture.js`
 */

const assert = require('assert');
const {
  analyzeArchitectureFromGraph,
  detectCircularDependencies,
  canonicalizeCycle
} = require('../src/architecture');

console.log('=== Running Architecture Analysis Tests ===');

// Test 1: Empty Input Handling
const emptyResult = analyzeArchitectureFromGraph({});
assert.deepStrictEqual(emptyResult.graph, {});
assert.deepStrictEqual(emptyResult.dependencyCounts, {});
assert.deepStrictEqual(emptyResult.dependentCounts, {});
assert.deepStrictEqual(emptyResult.entryPoints, []);
assert.deepStrictEqual(emptyResult.leafModules, []);
assert.deepStrictEqual(emptyResult.circularDependencies, []);
assert.deepStrictEqual(emptyResult.mostDependedOn, []);
console.log('✓ Test 1 Passed: Empty graph handled correctly.');

// Test 2: Standard Linear / Tree Architecture
// server.js -> routes.js -> controller.js -> db.js
// utils.js (imported by controller.js and routes.js)
const sampleGraph = {
  'server.js': ['routes.js'],
  'routes.js': ['controller.js', 'utils.js'],
  'controller.js': ['db.js', 'utils.js'],
  'db.js': [],
  'utils.js': []
};

const arch = analyzeArchitectureFromGraph(sampleGraph);
console.log('\n[Test 2] Linear Architecture Analysis Result:\n', JSON.stringify(arch, null, 2));

// Dependency counts (out-degree)
assert.strictEqual(arch.dependencyCounts['server.js'], 1);
assert.strictEqual(arch.dependencyCounts['routes.js'], 2);
assert.strictEqual(arch.dependencyCounts['controller.js'], 2);
assert.strictEqual(arch.dependencyCounts['db.js'], 0);
assert.strictEqual(arch.dependencyCounts['utils.js'], 0);
console.log('✓ Test 2.1: Dependency counts verified.');

// Dependent counts (in-degree)
assert.strictEqual(arch.dependentCounts['server.js'], 0);
assert.strictEqual(arch.dependentCounts['routes.js'], 1);
assert.strictEqual(arch.dependentCounts['controller.js'], 1);
assert.strictEqual(arch.dependentCounts['db.js'], 1);
assert.strictEqual(arch.dependentCounts['utils.js'], 2);
console.log('✓ Test 2.2: Dependent counts verified.');

// Entry points (in-degree === 0)
assert.deepStrictEqual(arch.entryPoints, ['server.js']);
console.log('✓ Test 2.3: Entry points detected accurately:', arch.entryPoints);

// Leaf modules (out-degree === 0)
assert.deepStrictEqual(arch.leafModules.sort(), ['db.js', 'utils.js'].sort());
console.log('✓ Test 2.4: Leaf modules detected accurately:', arch.leafModules);

// Most depended on sorting
assert.strictEqual(arch.mostDependedOn[0].path, 'utils.js');
assert.strictEqual(arch.mostDependedOn[0].dependents, 2);
console.log('✓ Test 2.5: Most depended on sorted accurately.');

// No cycles in linear graph
assert.strictEqual(arch.circularDependencies.length, 0);
console.log('✓ Test 2.6: No cycles detected in acyclic graph.');

// Test 3: Circular Dependency Detection
// A -> B -> C -> A
const cycleGraph = {
  'A.js': ['B.js'],
  'B.js': ['C.js'],
  'C.js': ['A.js']
};

const cycleArch = analyzeArchitectureFromGraph(cycleGraph);
console.log('\n[Test 3] Circular Dependencies Detected:', cycleArch.circularDependencies);

assert.strictEqual(cycleArch.circularDependencies.length, 1, 'Should detect exactly 1 cycle');
assert.deepStrictEqual(
  cycleArch.circularDependencies[0],
  ['A.js', 'B.js', 'C.js', 'A.js'],
  'Cycle path should be canonicalized to start and end with A.js'
);
console.log('✓ Test 3 Passed: Simple 3-node cycle detected.');

// Test 4: Cycle Canonicalization & Duplicate Rotation Prevention
const cycle1 = ['B.js', 'C.js', 'A.js', 'B.js'];
const cycle2 = ['C.js', 'A.js', 'B.js', 'C.js'];
const cycle3 = ['A.js', 'B.js', 'C.js', 'A.js'];

assert.deepStrictEqual(canonicalizeCycle(cycle1), ['A.js', 'B.js', 'C.js', 'A.js']);
assert.deepStrictEqual(canonicalizeCycle(cycle2), ['A.js', 'B.js', 'C.js', 'A.js']);
assert.deepStrictEqual(canonicalizeCycle(cycle3), ['A.js', 'B.js', 'C.js', 'A.js']);
console.log('✓ Test 4 Passed: Rotation deduplication & canonicalization verified.');

// Test 5: Multiple Independent Cycles
// Cycle 1: X -> Y -> X
// Cycle 2: M -> N -> O -> M
const multiCycleGraph = {
  'X.js': ['Y.js'],
  'Y.js': ['X.js'],
  'M.js': ['N.js'],
  'N.js': ['O.js'],
  'O.js': ['M.js'],
  'independent.js': []
};

const multiCycles = detectCircularDependencies(multiCycleGraph);
console.log('\n[Test 5] Multi-Cycle Output:', multiCycles);

assert.strictEqual(multiCycles.length, 2, 'Should find 2 distinct cycles');
assert.ok(multiCycles.some(c => c.join('->') === 'X.js->Y.js->X.js'));
assert.ok(multiCycles.some(c => c.join('->') === 'M.js->N.js->O.js->M.js'));
// Test 6: Entry point detection excludes test files
const { isTestFile } = require('../src/architecture');
assert.strictEqual(isTestFile('test/test-scanner.js'), true);
assert.strictEqual(isTestFile('tests/app.test.js'), true);
assert.strictEqual(isTestFile('__tests__/server.spec.js'), true);
assert.strictEqual(isTestFile('test-helper.js'), true);
assert.strictEqual(isTestFile('src/server.js'), false);
assert.strictEqual(isTestFile('index.js'), false);

const testExclusionGraph = {
  'server.js': ['src/app.js'],
  'src/app.js': [],
  'test/test-server.js': ['src/app.js'],
  'test/test-app.js': ['src/app.js']
};
const testExclusionArch = analyzeArchitectureFromGraph(testExclusionGraph);
// server.js, test/test-server.js, and test/test-app.js all have 0 dependents in this graph
// But only server.js should be classified as an application entry point
assert.deepStrictEqual(testExclusionArch.entryPoints, ['server.js']);
assert.ok(!testExclusionArch.entryPoints.includes('test/test-server.js'));
assert.ok(!testExclusionArch.entryPoints.includes('test/test-app.js'));
console.log('✓ Test 6 Passed: Test files excluded from entryPoints while application files are retained.');

console.log('\nAll architecture tests passed successfully!');
