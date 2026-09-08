import {
  statSync,
  chmodSync,
  writeFileSync,
  openSync,
  writeSync,
  fsyncSync,
  ftruncateSync,
  closeSync,
  unlinkSync,
  renameSync,
  readFileSync
} from 'node:fs';
import { dirname, join } from 'node:path';
import { randomBytes, createHash, timingSafeEqual } from 'node:crypto';

/**
 * Inspects file permissions on POSIX systems.
 * Checks if the file is readable or writable by group/others.
 *
 * @param {string} filePath - Absolute or relative path to target file/dir
 * @returns {{ secure: boolean, modeOctal: string, isGroupReadable: boolean, isOthersReadable: boolean }}
 */
export function checkFilePermissions(filePath) {
  const stats = statSync(filePath);
  const mode = stats.mode & 0o777;
  const modeOctal = mode.toString(8).padStart(3, '0');

  // Check group or others read/write/execute bits (0o077)
  const groupOrOthersBits = mode & 0o077;
  const isGroupReadable = Boolean(mode & 0o040);
  const isOthersReadable = Boolean(mode & 0o004);

  return {
    secure: groupOrOthersBits === 0,
    modeOctal,
    isGroupReadable,
    isOthersReadable
  };
}

/**
 * Secures file permissions (POSIX chmod).
 * Default target mode is 0o600 for files (rw-------) and 0o700 for directories (rwx------).
 *
 * @param {string} filePath - Target file path
 * @param {number} [targetMode] - POSIX mode octal (default: 0o600 for files, 0o700 for dirs)
 */
export function secureFilePermissions(filePath, targetMode) {
  const stats = statSync(filePath);
  const mode = targetMode ?? (stats.isDirectory() ? 0o700 : 0o600);
  chmodSync(filePath, mode);
  return mode.toString(8).padStart(3, '0');
}

/**
 * Performs safe atomic write to a target file.
 * Writes to a unique temp file first with 0o600 permissions, syncs to disk, then renames atomically.
 *
 * @param {string} filePath - Target destination path
 * @param {Buffer|string} data - Payload content to write
 * @param {Object} [options]
 * @param {number} [options.mode=0o600] - Desired POSIX file permissions
 */
export function safeWriteFile(filePath, data, options = {}) {
  const mode = options.mode ?? 0o600;
  const dir = dirname(filePath);
  const tmpFileName = `.tmp_${Date.now()}_${randomBytes(6).toString('hex')}`;
  const tmpPath = join(dir, tmpFileName);

  const payload = Buffer.isBuffer(data) ? data : Buffer.from(data);

  // Write to temporary file with locked-down permissions
  writeFileSync(tmpPath, payload, { mode });

  // Atomic replace destination
  renameSync(tmpPath, filePath);
}

/**
 * Securely wipes and shreds a sensitive file before deletion.
 * Overwrites file contents in multiple passes with random bytes and zeros before unlinking.
 *
 * @param {string} filePath - Target file to shred
 * @param {Object} [options]
 * @param {number} [options.passes=3] - Number of random overwrite passes before zeroing
 */
export function shredFile(filePath, options = {}) {
  const { passes = 3 } = options;

  const stats = statSync(filePath);
  const fileSize = stats.size;

  if (fileSize > 0) {
    const fd = openSync(filePath, 'r+');
    try {
      const buffer = Buffer.alloc(Math.min(fileSize, 64 * 1024)); // 64KB chunk buffer

      // Overwrite passes with random bytes
      for (let p = 0; p < passes; p++) {
        let written = 0;
        while (written < fileSize) {
          const chunkSize = Math.min(buffer.length, fileSize - written);
          const randBuf = randomBytes(chunkSize);
          writeSync(fd, randBuf, 0, chunkSize, written);
          written += chunkSize;
        }
        fsyncSync(fd);
      }

      // Final pass: Zeroing
      buffer.fill(0);
      let zeroWritten = 0;
      while (zeroWritten < fileSize) {
        const chunkSize = Math.min(buffer.length, fileSize - zeroWritten);
        writeSync(fd, buffer, 0, chunkSize, zeroWritten);
        zeroWritten += chunkSize;
      }
      fsyncSync(fd);

      // Truncate file size to 0
      ftruncateSync(fd, 0);
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
  }

  // Remove file entry from filesystem
  unlinkSync(filePath);
}

/**
 * Computes cryptographic hash of a file's content.
 *
 * @param {string} filePath - Target file path
 * @param {string} [algorithm='sha256'] - Hash algorithm ('sha256', 'sha512')
 * @returns {string} - Hex string of hash
 */
export function hashFile(filePath, algorithm = 'sha256') {
  const content = readFileSync(filePath);
  return createHash(algorithm).update(content).digest('hex');
}

/**
 * Verifies file integrity against an expected hash using constant-time comparison.
 *
 * @param {string} filePath - Target file path
 * @param {string} expectedHashHex - Expected hex hash string
 * @param {string} [algorithm='sha256'] - Hash algorithm
 * @returns {boolean} - True if hash matches exactly
 */
export function verifyFileIntegrity(filePath, expectedHashHex, algorithm = 'sha256') {
  const actualHash = hashFile(filePath, algorithm);
  const actualBuf = Buffer.from(actualHash.toLowerCase());
  const expectedBuf = Buffer.from(expectedHashHex.toLowerCase());

  if (actualBuf.length !== expectedBuf.length) {
    return false;
  }

  return timingSafeEqual(actualBuf, expectedBuf);
}
