/**
 * random.js — CSPRNG wrappers
 *
 * Thin, validated wrappers around Node.js crypto.randomBytes.
 * Every random value used in ZeroVault (salts, IVs) flows through here,
 * making the source of randomness easy to audit.
 *
 * Security note:
 *   randomBytes() delegates to the OS CSPRNG (getrandom(2) / /dev/urandom).
 *   No user-space entropy mixing or custom PRNG is involved.
 */

import { randomBytes } from 'node:crypto';

/**
 * Generate a cryptographically random salt.
 * @param {number} [length=32] - Salt length in bytes (minimum 16).
 * @returns {Buffer}
 */
export function generateSalt(length = 32) {
  if (typeof length !== 'number' || !Number.isInteger(length) || length < 16) {
    throw new RangeError(`Salt length must be an integer of at least 16 bytes, got: ${length}`);
  }
  return randomBytes(length);
}

/**
 * Generate a cryptographically random IV (nonce) for AES-256-GCM.
 * @param {number} [length=12] - IV length in bytes (minimum 12 for GCM).
 * @returns {Buffer}
 */
export function generateIV(length = 12) {
  if (typeof length !== 'number' || !Number.isInteger(length) || length < 12) {
    throw new RangeError(`IV length must be an integer of at least 12 bytes, got: ${length}`);
  }
  return randomBytes(length);
}
