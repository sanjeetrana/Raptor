/**
 * RepoLens - Static Import / Dependency Analysis Engine
 * Built using only Node.js standard library (zero external dependencies).
 */

const fs = require('fs');
const path = require('path');

/**
 * Normalizes a file path to use forward slashes for cross-platform consistency.
 *
 * @param {string} p - File path.
 * @returns {string} Normalized path.
 */
function normalizePath(p) {
  return p.split(path.sep).join('/');
}

/**
 * Extracts static relative import specifiers from JavaScript source code.
 *
 * @param {string} code - JavaScript source code string.
 * @returns {string[]} List of unique relative import specifiers (e.g., ['./user', '../utils/helper.js']).
 */
function extractImportSpecifiers(code) {
  if (!code || typeof code !== 'string') {
    return [];
  }

  // 1. Strip comments to avoid false matches in comments
  const cleanCode = code
    .replace(/\/\*[\s\S]*?\*\//g, '') // multi-line comments
    .replace(/\/\/.*$/gm, '');          // single-line comments

  const specifiers = new Set();

  // 2. Match ES Module imports and re-exports:
  // - import defaultMember from "./module"
  // - import { a, b } from "./module"
  // - import * as name from "./module"
  // - import "./side-effect"
  // - export { x } from "./module"
  // - export * from "./module"
  const esImportRegex = /(?:import\s+(?:[\w*\s{},$]+\s+from\s+)?|export\s+(?:[\w*\s{},$]+\s+from\s+)?)['"]([^'"]+)['"]/g;
  let match;
  while ((match = esImportRegex.exec(cleanCode)) !== null) {
    const specifier = match[1].trim();
    if (specifier.startsWith('./') || specifier.startsWith('../')) {
      specifiers.add(specifier);
    }
  }

  // 3. Match CommonJS require calls:
  // - require("./module")
  // - const mod = require('./module')
  // - const { func } = require("./module")
  // Note: Dynamic requires like require(someVar) will not match because quotes are required.
  const cjsRequireRegex = /\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
  while ((match = cjsRequireRegex.exec(cleanCode)) !== null) {
    const specifier = match[1].trim();
    if (specifier.startsWith('./') || specifier.startsWith('../')) {
      specifiers.add(specifier);
    }
  }

  return Array.from(specifiers);
}

/**
 * Resolves a relative import specifier to an existing target file on disk.
 * Handles extension-less imports (.js) and directory index files (index.js).
 *
 * @param {string} fromFilePath - Absolute or relative path to the importing file.
 * @param {string} importSpecifier - Relative import string (e.g., "./user" or "../utils/helper.js").
 * @returns {string|null} Resolved absolute file path, or null if the file does not exist.
 */
function resolveImportPath(fromFilePath, importSpecifier) {
  const fromDir = path.dirname(path.resolve(fromFilePath));
  const candidate = path.resolve(fromDir, importSpecifier);

  // 1. Direct file match (e.g., './user.js')
  if (fs.existsSync(candidate)) {
    try {
      const stat = fs.statSync(candidate);
      if (stat.isFile()) {
        return candidate;
      }
      if (stat.isDirectory()) {
        // Directory import -> look for index.js
        const indexFile = path.join(candidate, 'index.js');
        if (fs.existsSync(indexFile) && fs.statSync(indexFile).isFile()) {
          return indexFile;
        }
      }
    } catch {
      return null;
    }
  }

  // 2. Extension-less match (.js)
  const candidateWithJs = candidate + '.js';
  if (fs.existsSync(candidateWithJs)) {
    try {
      if (fs.statSync(candidateWithJs).isFile()) {
        return candidateWithJs;
      }
    } catch {
      return null;
    }
  }

  // 3. Extension-less match (.json)
  const candidateWithJson = candidate + '.json';
  if (fs.existsSync(candidateWithJson)) {
    try {
      if (fs.statSync(candidateWithJson).isFile()) {
        return candidateWithJson;
      }
    } catch {
      return null;
    }
  }

  // Target does not exist on disk
  return null;
}

/**
 * Analyzes static dependencies for a single file.
 *
 * @param {string} filePath - Path to the JavaScript file.
 * @param {Object} [options] - Configuration options.
 * @param {string} [options.projectRoot] - Root path to format dependencies as relative to project root.
 * @returns {string[]} Array of resolved imported file paths.
 */
function analyzeFileDependencies(filePath, options = {}) {
  const absolutePath = path.resolve(filePath);
  if (!fs.existsSync(absolutePath)) {
    throw new Error(`File does not exist: "${filePath}"`);
  }

  const code = fs.readFileSync(absolutePath, 'utf-8');
  const specifiers = extractImportSpecifiers(code);
  const resolvedDeps = new Set();
  const rootDir = options.projectRoot ? path.resolve(options.projectRoot) : null;

  for (const specifier of specifiers) {
    const resolvedAbsolute = resolveImportPath(absolutePath, specifier);
    if (resolvedAbsolute) {
      if (rootDir) {
        // Return relative to project root (e.g. "src/models/user.js")
        const relPath = path.relative(rootDir, resolvedAbsolute);
        resolvedDeps.add(normalizePath(relPath));
      } else {
        // Return normalized absolute path
        resolvedDeps.add(normalizePath(resolvedAbsolute));
      }
    }
  }

  return Array.from(resolvedDeps);
}

/**
 * Builds the full static dependency graph for a collection of project files.
 *
 * @param {string[]} filePaths - List of JavaScript file paths.
 * @param {Object} [options] - Configuration options.
 * @param {string} [options.projectRoot] - Optional project root directory.
 * @returns {Object.<string, string[]>} Map of { [sourceFile]: [importedFile1, importedFile2] }.
 */
function buildDependencyGraph(filePaths, options = {}) {
  if (!Array.isArray(filePaths)) {
    throw new TypeError('buildDependencyGraph expects an array of file paths');
  }

  const rootDir = options.projectRoot
    ? path.resolve(options.projectRoot)
    : (filePaths.length > 0 ? path.resolve(path.dirname(filePaths[0])) : null);

  const graph = {};

  for (const filePath of filePaths) {
    const absolutePath = path.resolve(filePath);
    const key = rootDir
      ? normalizePath(path.relative(rootDir, absolutePath))
      : normalizePath(filePath);

    const deps = analyzeFileDependencies(absolutePath, { projectRoot: rootDir });
    graph[key] = deps;
  }

  return graph;
}

module.exports = {
  extractImportSpecifiers,
  resolveImportPath,
  analyzeFileDependencies,
  buildDependencyGraph,
  normalizePath
};
