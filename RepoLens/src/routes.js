/**
 * RepoLens - Static Route Map Engine
 * Built using only Node.js standard library (zero external dependencies).
 */

const fs = require('fs');
const path = require('path');
const { normalizePath } = require('./dependencies');

// Supported standard HTTP routing methods
const SUPPORTED_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Parses the arguments following the route path to determine the final controller handler.
 *
 * @param {string} argsString - Raw string of arguments after the route path.
 * @returns {string} The identified handler name or "anonymous".
 */
function parseHandler(argsString) {
  if (!argsString || argsString.trim() === '') {
    return 'anonymous';
  }

  // Split arguments by top-level commas while respecting parentheses and brackets
  const args = [];
  let currentArg = '';
  let depth = 0;

  for (let i = 0; i < argsString.length; i++) {
    const char = argsString[i];
    if (char === '(' || char === '{' || char === '[') {
      depth++;
      currentArg += char;
    } else if (char === ')' || char === '}' || char === ']') {
      depth--;
      currentArg += char;
    } else if (char === ',' && depth === 0) {
      if (currentArg.trim()) {
        args.push(currentArg.trim());
      }
      currentArg = '';
    } else {
      currentArg += char;
    }
  }
  if (currentArg.trim()) {
    args.push(currentArg.trim());
  }

  if (args.length === 0) {
    return 'anonymous';
  }

  // The last argument is the final handler
  const finalArg = args[args.length - 1].trim();

  // Check if it is an anonymous function or arrow function
  // E.g.: (req, res) => ..., async (req, res) => ..., function(req, res) ..., async function() ...
  if (
    finalArg.includes('=>') ||
    /^async\s*\(/i.test(finalArg) ||
    /^\(/i.test(finalArg) ||
    /^function\b/i.test(finalArg) ||
    /^async\s+function\b/i.test(finalArg)
  ) {
    return 'anonymous';
  }

  // Check if it is a clean identifier or member expression: e.g. "getUser", "userController.getUser"
  const cleanIdentifierMatch = finalArg.match(/^([a-zA-Z_$][a-zA-Z0-9_$]*(?:\.[a-zA-Z_$][a-zA-Z0-9_$]*)*)/);
  if (cleanIdentifierMatch) {
    return cleanIdentifierMatch[1];
  }

  return 'anonymous';
}

/**
 * Extracts static Express-style HTTP route declarations from source code.
 *
 * @param {string} code - JavaScript source code.
 * @param {string} [filePath=""] - Source file path for metadata.
 * @returns {Array<{ method: string, path: string, handler: string, file: string }>} List of detected routes.
 */
function extractRoutes(code, filePath = '') {
  if (!code || typeof code !== 'string') {
    return [];
  }

  const normalizedFilePath = filePath ? normalizePath(filePath) : '';

  // 1. Strip comments to eliminate false positives in documentation
  const cleanCode = code
    .replace(/\/\*[\s\S]*?\*\//g, '') // multi-line comments
    .replace(/\/\/.*$/gm, '');          // single-line comments

  const routes = [];
  const seenRouteKeys = new Set();

  // 2. Match standard Express route patterns:
  // <identifier>.(get|post|put|patch|delete)(["'`]<path>["'`] , ...)
  const routeRegex = /(?:[a-zA-Z_$][a-zA-Z0-9_$]*)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*(['"`])([^'"`\r\n]+)\2\s*(?:,\s*([\s\S]*?))?\s*\)(?:\s*;|\s*$|\s*\n)/gim;

  let match;
  while ((match = routeRegex.exec(cleanCode)) !== null) {
    const rawMethod = match[1].toUpperCase();
    if (!SUPPORTED_METHODS.has(rawMethod)) {
      continue;
    }

    const routePath = match[3].trim();
    const argsString = match[4] || '';
    const handler = parseHandler(argsString);

    // Deduplicate identical routes within the same file (same method + path + handler)
    const dedupeKey = `${rawMethod}::${routePath}::${handler}`;
    if (!seenRouteKeys.has(dedupeKey)) {
      seenRouteKeys.add(dedupeKey);
      routes.push({
        method: rawMethod,
        path: routePath,
        handler: handler,
        file: normalizedFilePath
      });
    }
  }

  return routes;
}

/**
 * Reads a single JavaScript file and analyzes its routes.
 *
 * @param {string} filePath - Path to the file.
 * @param {Object} [options] - Options (e.g. { projectRoot }).
 * @returns {Array<Object>} List of routes found in this file.
 */
function analyzeRouteFile(filePath, options = {}) {
  const absolutePath = path.resolve(filePath);
  if (!fs.existsSync(absolutePath)) {
    throw new Error(`File does not exist: "${filePath}"`);
  }

  const rootDir = options.projectRoot ? path.resolve(options.projectRoot) : null;
  const displayPath = rootDir
    ? normalizePath(path.relative(rootDir, absolutePath))
    : normalizePath(filePath);

  const code = fs.readFileSync(absolutePath, 'utf-8');
  return extractRoutes(code, displayPath);
}

/**
 * Scans all provided project files and aggregates all detected HTTP routes into a single list.
 *
 * @param {string[]} filePaths - Array of JavaScript file paths.
 * @param {Object} [options] - Options (e.g. { projectRoot }).
 * @returns {Array<Object>} Combined list of all routes across the project.
 */
function analyzeProjectRoutes(filePaths, options = {}) {
  if (!Array.isArray(filePaths)) {
    throw new TypeError('analyzeProjectRoutes expects an array of file paths');
  }

  const allRoutes = [];

  for (const filePath of filePaths) {
    const routes = analyzeRouteFile(filePath, options);
    allRoutes.push(...routes);
  }

  return allRoutes;
}

module.exports = {
  extractRoutes,
  analyzeRouteFile,
  analyzeProjectRoutes,
  parseHandler
};
