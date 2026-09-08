/**
 * RepoLens - Project Statistics Engine
 * Built using only Node.js standard library (zero external dependencies).
 */

const { analyzeSource } = require('./analyzer');

/**
 * Aggregates an array of individual file analysis reports into a single project statistics summary.
 *
 * @param {Array<Object>} reports - Array of analysis objects from analyzer.js.
 * @returns {Object} Combined project statistics.
 */
function aggregateAnalysisResults(reports) {
  const stats = {
    totalFiles: reports.length,
    totalLines: 0,
    totalBlankLines: 0,
    totalFunctions: 0,
    totalClasses: 0,
    totalTodos: 0,
    totalFixmes: 0,
    largestFile: null
  };

  if (reports.length === 0) {
    return stats;
  }

  let largest = {
    path: '',
    lines: -1
  };

  for (const report of reports) {
    stats.totalLines += report.lines || 0;
    stats.totalBlankLines += report.blankLines || 0;
    stats.totalFunctions += (report.functions ? report.functions.length : 0);
    stats.totalClasses += (report.classes ? report.classes.length : 0);
    stats.totalTodos += report.todos || 0;
    stats.totalFixmes += report.fixmes || 0;

    // Track the file with the highest number of lines
    if (report.lines > largest.lines) {
      largest = {
        path: report.path,
        lines: report.lines
      };
    }
  }

  stats.largestFile = largest.lines >= 0 ? largest : null;

  return stats;
}

/**
 * Receives an array of JavaScript file paths, analyzes each with `analyzeSource()`,
 * and computes the project-level statistics.
 *
 * @param {string[]} filePaths - Array of file paths to analyze.
 * @returns {Object} Project statistics summary.
 */
function calculateProjectStats(filePaths) {
  if (!Array.isArray(filePaths)) {
    throw new TypeError('calculateProjectStats expects an array of file paths');
  }

  // 1. Analyze each file path using the existing source analyzer
  const reports = filePaths.map((filePath) => analyzeSource(filePath));

  // 2. Aggregate the individual reports into project-wide metrics
  return aggregateAnalysisResults(reports);
}

module.exports = {
  calculateProjectStats,
  aggregateAnalysisResults
};
