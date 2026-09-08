/**
 * RepoLens - "Where Should I Start?" Recommendation Engine
 * Built using only Node.js standard library (zero external dependencies).
 */

const path = require('path');
const { analyzeArchitecture } = require('./architecture');
const { analyzeSource } = require('./analyzer');
const { normalizePath } = require('./dependencies');

/**
 * Calculates the starting recommendation score and reasons for a file.
 *
 * @param {Object} params
 * @param {string} params.filePath - Normalized display path.
 * @param {number} params.dependentCount - Number of direct dependents.
 * @param {boolean} params.isEntryPoint - Whether the file is an entry point.
 * @param {Object} params.sourceReport - Analysis report from analyzer.js.
 * @returns {{ path: string, score: number, reasons: string[] }}
 */
function scoreFile({ filePath, dependentCount, isEntryPoint, sourceReport }) {
  const functionCount = (sourceReport.functions || []).length;
  const classCount = (sourceReport.classes || []).length;
  const todoCount = sourceReport.todos || 0;
  const fixmeCount = sourceReport.fixmes || 0;
  const lineCount = sourceReport.lines || 0;

  // Exact scoring formula
  const rawScore =
    (dependentCount * 5) +
    (isEntryPoint ? 20 : 0) +
    (functionCount * 2) +
    (classCount * 3) +
    (todoCount * 2) +
    (fixmeCount * 3) +
    (lineCount / 100);

  // Round to two decimal places
  const score = Number(rawScore.toFixed(2));

  // Build human-readable reasons (only including non-zero / applicable signals)
  const reasons = [];

  if (isEntryPoint) {
    reasons.push('Entry point');
  }

  if (dependentCount > 0) {
    reasons.push(`Used by ${dependentCount} file${dependentCount === 1 ? '' : 's'}`);
  }

  if (functionCount > 0) {
    reasons.push(`Contains ${functionCount} function${functionCount === 1 ? '' : 's'}`);
  }

  if (classCount > 0) {
    reasons.push(`Contains ${classCount} class${classCount === 1 ? '' : 'es'}`);
  }

  if (todoCount > 0) {
    reasons.push(`Contains ${todoCount} TODO${todoCount === 1 ? '' : 's'}`);
  }

  if (fixmeCount > 0) {
    reasons.push(`Contains ${fixmeCount} FIXME${fixmeCount === 1 ? '' : 's'}`);
  }

  return {
    path: filePath,
    score,
    reasons
  };
}

/**
 * Recommends the most critical starting files in a repository.
 *
 * @param {string[]} filePaths - List of JavaScript file paths.
 * @param {Object} [options={}] - Configuration options.
 * @param {number} [options.limit=3] - Maximum number of recommendations to return.
 * @param {string} [options.projectRoot] - Optional project root directory.
 * @returns {Array<{ path: string, score: number, reasons: string[] }>}
 */
function recommendStartingFiles(filePaths, options = {}) {
  if (!Array.isArray(filePaths) || filePaths.length === 0) {
    return [];
  }

  const limit = typeof options.limit === 'number' && options.limit >= 0 ? options.limit : 3;
  const rootDir = options.projectRoot ? path.resolve(options.projectRoot) : null;

  // 1. Run architecture analysis to extract dependentCounts and entryPoints
  const arch = analyzeArchitecture(filePaths, options);

  const recommendations = [];

  // 2. Score each file
  for (const filePath of filePaths) {
    const absolutePath = path.resolve(filePath);
    const normalizedKey = rootDir
      ? normalizePath(path.relative(rootDir, absolutePath))
      : normalizePath(filePath);

    const sourceReport = analyzeSource(absolutePath);
    const dependentCount = arch.dependentCounts[normalizedKey] || 0;
    const isEntryPoint = arch.entryPoints.includes(normalizedKey);

    const scored = scoreFile({
      filePath: normalizedKey,
      dependentCount,
      isEntryPoint,
      sourceReport
    });

    recommendations.push(scored);
  }

  // 3. Sort by score descending, then path ascending as a deterministic tie-breaker
  recommendations.sort((a, b) => {
    if (b.score !== a.score) {
      return b.score - a.score;
    }
    return a.path.localeCompare(b.path);
  });

  // 4. Return top recommendations according to limit
  return recommendations.slice(0, limit);
}

module.exports = {
  recommendStartingFiles,
  scoreFile
};
