/**
 * RepoLens - Unified Project Analysis Engine
 * Orchestrates all analysis components into a single project report.
 * Built using only Node.js standard library (zero external dependencies).
 */

const fs = require('fs');
const path = require('path');

const { scanFiles } = require('./scanner');
const { calculateProjectStats } = require('./statistics');
const { analyzeArchitecture } = require('./architecture');
const { recommendStartingFiles } = require('./start');
const { analyzeProjectRoutes } = require('./routes');
const { normalizePath } = require('./dependencies');

/**
 * Executes the complete RepoLens analysis pipeline on a target project directory.
 *
 * @param {string} projectPath - Path to the root directory of the project to analyze.
 * @param {Object} [options={}] - Configuration options.
 * @param {string[]} [options.extensions=['.js']] - File extensions to scan.
 * @param {string[]} [options.ignoreDirs] - Directories to ignore.
 * @param {number} [options.limit=3] - Number of starting recommendations to return.
 * @returns {Object} Comprehensive project analysis report.
 */
function analyzeProject(projectPath, options = {}) {
  // 1. Path validation
  if (!projectPath || typeof projectPath !== 'string') {
    throw new TypeError('analyzeProject requires a valid projectPath string');
  }

  const absoluteRoot = path.resolve(projectPath);

  if (!fs.existsSync(absoluteRoot)) {
    throw new Error(`Project path does not exist: "${projectPath}"`);
  }

  const stat = fs.statSync(absoluteRoot);
  if (!stat.isDirectory()) {
    throw new Error(`Project path is not a directory: "${projectPath}"`);
  }

  // 2. Discover project files
  const filePaths = scanFiles(absoluteRoot, {
    extensions: options.extensions,
    ignoreDirs: options.ignoreDirs
  });

  const normalizedRoot = normalizePath(absoluteRoot);
  const analysisOptions = {
    projectRoot: absoluteRoot,
    limit: options.limit
  };

  // 3. Compute statistics
  const statistics = calculateProjectStats(filePaths);

  // 4. Compute architecture (graph, entry points, leaves, cycles, most depended on)
  const architecture = analyzeArchitecture(filePaths, analysisOptions);

  // 5. Compute "Where Should I Start?" recommendations
  const recommendations = recommendStartingFiles(filePaths, analysisOptions);

  // 6. Compute Route Map
  const routes = analyzeProjectRoutes(filePaths, analysisOptions);

  // 7. Assemble unified, JSON-serializable report
  return {
    project: {
      path: normalizedRoot,
      fileCount: filePaths.length
    },
    statistics,
    architecture,
    recommendations,
    routes
  };
}

module.exports = {
  analyzeProject
};
