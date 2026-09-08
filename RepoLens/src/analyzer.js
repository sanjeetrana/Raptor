/**
 * RepoLens - JavaScript Source Analyzer
 * Built using only Node.js standard library (zero external dependencies).
 */

const fs = require('fs');
const path = require('path');

/**
 * Analyzes JavaScript source code string and extracts metrics and structural declarations.
 *
 * @param {string} code - The source code content.
 * @param {string} [filePath=""] - The file path (for metadata in return object).
 * @returns {Object} Analysis report containing lines, blankLines, todos, fixmes, functions, classes.
 */
function analyzeCode(code, filePath = '') {
  // Normalize path format for consistent reporting
  const normalizedPath = filePath ? filePath.split(path.sep).join('/') : '';

  // 1. Line Counting
  // Handle empty file edge case
  if (code.length === 0) {
    return {
      path: normalizedPath,
      lines: 0,
      blankLines: 0,
      todos: 0,
      fixmes: 0,
      functions: [],
      classes: []
    };
  }

  // Split by newline (handling both CRLF and LF)
  const lineArray = code.split(/\r?\n/);
  const totalLines = lineArray.length;
  let blankLines = 0;

  for (const line of lineArray) {
    if (line.trim() === '') {
      blankLines++;
    }
  }

  // 2. Count TODO and FIXME occurrences
  // Using word boundary (\b) and case-insensitive flag (i) to match TODO / todo / FIXME / fixme
  const todoMatches = code.match(/\bTODO\b/gi);
  const fixmeMatches = code.match(/\bFIXME\b/gi);
  const todos = todoMatches ? todoMatches.length : 0;
  const fixmes = fixmeMatches ? fixmeMatches.length : 0;

  // 3. Prepare code for declaration extraction by stripping comments
  // This prevents false positives from comments that document code patterns (e.g. "// function example()")
  const codeWithoutComments = code
    .replace(/\/\*[\s\S]*?\*\//g, '') // strip multi-line comments
    .replace(/\/\/.*$/gm, '');          // strip single-line comments

  // 4. Extract Function Declarations
  // Matches:
  // - function name(...)
  // - async function name(...)
  // - const/let/var name = (...) => ...
  // - const/let/var name = async (...) => ...
  // - const/let/var name = function(...) ...
  // - const/let/var name = async function(...) ...
  const functions = new Set();

  // Pattern 1: Standard function declarations: (async )?function name(...)
  const standardFuncRegex = /(?:async\s+)?function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(/g;
  let match;
  while ((match = standardFuncRegex.exec(codeWithoutComments)) !== null) {
    functions.add(match[1]);
  }

  // Pattern 2: Function expressions / Arrow functions assigned to variables:
  const varFuncRegex = /(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s*)?(?:function(?:\s+[a-zA-Z_$][a-zA-Z0-9_$]*)?\s*\(|\([^)]*\)\s*=>|[a-zA-Z_$][a-zA-Z0-9_$]*\s*=>)/g;
  while ((match = varFuncRegex.exec(codeWithoutComments)) !== null) {
    functions.add(match[1]);
  }

  // 5. Extract Class Declarations
  // Matches: class Name { ... } or class Name extends ...
  const classes = new Set();
  const classRegex = /class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)/g;
  while ((match = classRegex.exec(codeWithoutComments)) !== null) {
    classes.add(match[1]);
  }

  return {
    path: normalizedPath,
    lines: totalLines,
    blankLines: blankLines,
    todos: todos,
    fixmes: fixmes,
    functions: Array.from(functions),
    classes: Array.from(classes)
  };
}

/**
 * Reads a JavaScript file from disk and analyzes its contents.
 *
 * @param {string} filePath - Path to the JavaScript file.
 * @returns {Object} Analysis result object.
 */
function analyzeSource(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`File does not exist: "${filePath}"`);
  }

  const content = fs.readFileSync(filePath, 'utf-8');
  return analyzeCode(content, filePath);
}

module.exports = {
  analyzeSource,
  analyzeCode
};
