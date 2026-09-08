/**
 * RepoLens - Architecture Analysis Engine
 * Built using only Node.js standard library (zero external dependencies).
 */

const { buildDependencyGraph } = require('./dependencies');

/**
 * Checks if a given file path corresponds to a test, fixture, or benchmark file.
 * Test files should not be classified as application entry points.
 *
 * @param {string} filePath - Normalized file path.
 * @returns {boolean} True if the file matches common test/benchmark patterns.
 */
function isTestFile(filePath) {
  if (!filePath || typeof filePath !== 'string') return false;

  const normalized = filePath.split('\\').join('/').toLowerCase();
  const basename = normalized.split('/').pop() || '';

  // Folder patterns: /test/, /tests/, /__tests__/, /fixtures/, /benchmarks/
  if (
    normalized.includes('/test/') ||
    normalized.startsWith('test/') ||
    normalized.includes('/tests/') ||
    normalized.startsWith('tests/') ||
    normalized.includes('/__tests__/') ||
    normalized.startsWith('__tests__/') ||
    normalized.includes('/fixtures/') ||
    normalized.startsWith('fixtures/')
  ) {
    return true;
  }

  // Filename patterns: test-*.js, test_*.js, *.test.js, *.spec.js
  if (
    basename.startsWith('test-') ||
    basename.startsWith('test_') ||
    basename.endsWith('.test.js') ||
    basename.endsWith('.spec.js')
  ) {
    return true;
  }

  return false;
}

/**
 * Canonicalizes a cycle array to prevent duplicate reports caused by rotation.
 * E.g., ['B.js', 'C.js', 'A.js', 'B.js'] -> ['A.js', 'B.js', 'C.js', 'A.js']
 *
 * @param {string[]} cycle - Array of nodes representing a cycle ending at the start node.
 * @returns {string[]} Canonicalized cycle array.
 */
function canonicalizeCycle(cycle) {
  if (cycle.length <= 1) return cycle;

  // The cycle nodes without the trailing duplicate
  const nodes = cycle.slice(0, -1);
  if (nodes.length === 0) return cycle;

  // Find index of lexicographically smallest node
  let minIndex = 0;
  for (let i = 1; i < nodes.length; i++) {
    if (nodes[i] < nodes[minIndex]) {
      minIndex = i;
    }
  }

  // Rotate array so minIndex is at position 0
  const rotated = [...nodes.slice(minIndex), ...nodes.slice(0, minIndex)];
  // Close the cycle
  rotated.push(rotated[0]);
  return rotated;
}

/**
 * Detects all unique circular dependency cycles in a graph using DFS.
 *
 * @param {Object.<string, string[]>} graph - Dependency graph.
 * @returns {Array<string[]>} List of unique cycles.
 */
function detectCircularDependencies(graph) {
  const visited = new Set();
  const recursionStack = new Set();
  const currentPath = [];
  const foundCycles = [];
  const seenCycleKeys = new Set();

  function dfs(node) {
    visited.add(node);
    recursionStack.add(node);
    currentPath.push(node);

    const neighbors = graph[node] || [];

    for (const neighbor of neighbors) {
      if (recursionStack.has(neighbor)) {
        // Cycle detected: slice from the first occurrence of neighbor to current
        const cycleStartIndex = currentPath.indexOf(neighbor);
        if (cycleStartIndex !== -1) {
          const rawCycle = currentPath.slice(cycleStartIndex);
          rawCycle.push(neighbor);

          const canonical = canonicalizeCycle(rawCycle);
          const key = canonical.join(' -> ');

          if (!seenCycleKeys.has(key)) {
            seenCycleKeys.add(key);
            foundCycles.push(canonical);
          }
        }
      } else if (!visited.has(neighbor)) {
        // If neighbor is part of the graph, visit it
        if (graph[neighbor] !== undefined) {
          dfs(neighbor);
        }
      }
    }

    currentPath.pop();
    recursionStack.delete(node);
  }

  for (const node of Object.keys(graph)) {
    if (!visited.has(node)) {
      dfs(node);
    }
  }

  return foundCycles;
}

/**
 * Analyzes architectural properties from an existing dependency graph.
 *
 * @param {Object.<string, string[]>} graph - Dependency graph.
 * @returns {Object} Architecture analysis report.
 */
function analyzeArchitectureFromGraph(graph) {
  const allFiles = Object.keys(graph);

  const dependencyCounts = {};
  const dependentCounts = {};

  // 1. Initialize counts for every scanned file
  for (const file of allFiles) {
    dependencyCounts[file] = 0;
    dependentCounts[file] = 0;
  }

  // 2. Compute dependencyCounts and dependentCounts
  for (const file of allFiles) {
    const deps = graph[file] || [];
    dependencyCounts[file] = deps.length;

    for (const importedFile of deps) {
      if (dependentCounts[importedFile] !== undefined) {
        dependentCounts[importedFile]++;
      } else {
        // If imported file is tracked, increment, else register it
        dependentCounts[importedFile] = 1;
      }
    }
  }

  // 3. Entry Points: Non-test files that no other scanned file directly imports (in-degree = 0)
  const entryPoints = allFiles.filter((file) => dependentCounts[file] === 0 && !isTestFile(file));

  // 4. Leaf Modules: Files that import no other local file (out-degree = 0)
  const leafModules = allFiles.filter((file) => dependencyCounts[file] === 0);

  // 5. Most Depended On: Files sorted by number of direct dependents descending
  const mostDependedOn = allFiles
    .map((file) => ({
      path: file,
      dependents: dependentCounts[file] || 0
    }))
    .sort((a, b) => {
      if (b.dependents !== a.dependents) {
        return b.dependents - a.dependents; // Highest dependents first
      }
      return a.path.localeCompare(b.path); // Deterministic tie-break
    });

  // 6. Circular Dependencies
  const circularDependencies = detectCircularDependencies(graph);

  return {
    graph,
    dependencyCounts,
    dependentCounts,
    entryPoints,
    leafModules,
    circularDependencies,
    mostDependedOn
  };
}

/**
 * Builds the dependency graph for the given file paths and performs full architectural analysis.
 *
 * @param {string[]} filePaths - Array of JavaScript file paths.
 * @param {Object} [options] - Configuration options passed to buildDependencyGraph.
 * @returns {Object} Full architectural analysis.
 */
function analyzeArchitecture(filePaths, options = {}) {
  if (!Array.isArray(filePaths)) {
    throw new TypeError('analyzeArchitecture expects an array of file paths');
  }

  // 1. Build graph using existing dependency analyzer
  const graph = buildDependencyGraph(filePaths, options);

  // 2. Perform graph and metric analysis
  return analyzeArchitectureFromGraph(graph);
}

module.exports = {
  analyzeArchitecture,
  analyzeArchitectureFromGraph,
  detectCircularDependencies,
  canonicalizeCycle,
  isTestFile
};
