import fs from 'node:fs';
import path from 'node:path';

/**
 * Safely write a buffer to a file atomically.
 * Avoids destroying the original file if the write fails or is interrupted.
 *
 * @param {string} filePath - Target file path
 * @param {Buffer} data - Binary data to write
 */
export function atomicWriteSync(filePath, data) {
  const tmpPath = `${filePath}.${Date.now()}.tmp`;
  try {
    // Write to a temporary file first
    fs.writeFileSync(tmpPath, data, { mode: 0o600 }); // Restrict permissions (rw-------)
    // Atomically rename tmp file over target file
    fs.renameSync(tmpPath, filePath);
  } catch (err) {
    // Attempt cleanup if it fails
    if (fs.existsSync(tmpPath)) {
      try {
        fs.unlinkSync(tmpPath);
      } catch (cleanupErr) {
        // Ignore cleanup errors
      }
    }
    throw err;
  }
}

/**
 * Safely read a file, or return null if it does not exist.
 * 
 * @param {string} filePath 
 * @returns {Buffer | null}
 */
export function readFileSyncSafe(filePath) {
  try {
    return fs.readFileSync(filePath);
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
}
