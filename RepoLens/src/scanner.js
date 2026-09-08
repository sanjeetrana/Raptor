/**
 * RepoLens - Recursive File Scanner
 * Built using only Node.js standard library (zero external dependencies).
 */

const fs = require('fs');
const path = require('path');

// Default directories to skip during scanning to avoid unnecessary overhead and infinite loops.
const DEFAULT_IGNORED_DIRS = new Set([
  'node_modules',
  '.git',
  '.svn',
  '.hg',
  'dist',
  'build',
  'coverage',
  '.next',
  '.cache'
]);

/**
 * Recursively scans a directory and collects file paths matching target extensions.
 *
 * @param {string} dirPath - The absolute or relative root path of the project to scan.
 * @param {Object} [options] - Scanner configuration options.
 * @param {string[]} [options.extensions=['.js']] - Array of file extensions to include (e.g., ['.js']).
 * @param {string[]} [options.ignoreDirs] - Directory names to skip during recursive scan.
 * @returns {string[]} List of matching file paths (normalized with forward slashes).
 */
function scanFiles(dirPath, options = {}) {
  // 1. Resolve to an absolute path to avoid ambiguity with relative paths.
  const absoluteRoot = path.resolve(dirPath);

  // 2. Validate that the target path exists and is actually a directory.
  if (!fs.existsSync(absoluteRoot)) {
    throw new Error(`Path does not exist: "${dirPath}"`);
  }

  const stat = fs.statSync(absoluteRoot);
  if (!stat.isDirectory()) {
    throw new Error(`Path is not a directory: "${dirPath}"`);
  }

  // 3. Configure file extensions and directory ignores.
  // Default to ['.js'] per requirements.
  const allowedExtensions = new Set(
    (options.extensions || ['.js']).map((ext) =>
      ext.startsWith('.') ? ext.toLowerCase() : `.${ext.toLowerCase()}`
    )
  );

  const ignoredDirs = new Set([
    ...DEFAULT_IGNORED_DIRS,
    ...(options.ignoreDirs || [])
  ]);

  const collectedFiles = [];

  /**
   * Helper function for recursive traversal.
   * We use `fs.readdirSync` with `{ withFileTypes: true }` because `Dirent` objects
   * tell us immediately if an entry is a file or directory without needing separate `fs.stat` calls.
   */
  function walk(currentDir) {
    let entries;
    try {
      entries = fs.readdirSync(currentDir, { withFileTypes: true });
    } catch (err) {
      // Gracefully handle permission errors or unreadable directories.
      console.warn(`[RepoLens Scanner] Could not read directory: ${currentDir} (${err.message})`);
      return;
    }

    for (const entry of entries) {
      const entryName = entry.name;
      const fullPath = path.join(currentDir, entryName);

      if (entry.isDirectory()) {
        // Skip ignored directories (like node_modules and .git)
        if (ignoredDirs.has(entryName)) {
          continue;
        }
        // Recursively step into child directories
        walk(fullPath);
      } else if (entry.isFile()) {
        const ext = path.extname(entryName).toLowerCase();
        if (allowedExtensions.has(ext)) {
          // Normalize paths to forward slashes for consistent output across Windows and POSIX
          const normalizedPath = fullPath.split(path.sep).join('/');
          collectedFiles.push(normalizedPath);
        }
      }
    }
  }

  walk(absoluteRoot);
  return collectedFiles;
}

module.exports = {
  scanFiles,
  DEFAULT_IGNORED_DIRS
};
