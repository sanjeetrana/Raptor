/**
 * kdf.js — Password-Based Key Derivation
 *
 * Uses Argon2id (Node.js 25 built-in) as the primary KDF, then expands the
 * master key with HKDF-SHA256 into two domain-separated sub-keys.
 *
 * Key derivation pipeline:
 *
 *   password + salt
 *       │
 *       ▼
 *   argon2id (memory-hard, side-channel-resistant)
 *       │
 *       ▼
 *   masterKey (32 bytes, never stored or returned)
 *       │
 *       ├─ HKDF(sha256, masterKey, salt, "zerovault-enc-v1") → encKey (32 bytes)
 *       └─ HKDF(sha256, masterKey, salt, "zerovault-mac-v1") → macKey (32 bytes)
 *
 * Security decisions:
 *   - Argon2id: OWASP's recommended password hashing algorithm. Combines the
 *     data-independent memory access of Argon2i (side-channel resistance) with
 *     the GPU resistance of Argon2d. RFC 9106 standardized.
 *   - HKDF expansion: Prevents encKey and macKey from being related even if
 *     the argon2id output has any structural weaknesses.
 *   - Password is copied internally and zeroed after KDF completes.
 *   - masterKey is zeroed immediately after sub-key derivation.
 *
 * Limitations:
 *   - Node.js does not expose mlock(2)/VirtualLock for memory page pinning.
 *     Key material may theoretically be paged to disk on memory pressure.
 *     This is a platform limitation, not a design flaw.
 *   - argon2Sync is used intentionally (test + vault operations are already
 *     sequential). An async variant can be added without API changes.
 */

import { argon2Sync, hkdfSync } from 'node:crypto';

/**
 * Default Argon2id parameters.
 *
 * Rationale:
 *   passes=3       — OWASP minimum time-cost for interactive logins
 *   memory=65536   — 64 MiB; significant GPU/ASIC cost
 *   parallelism=4  — matches typical quad-core availability
 *   tagLength=32   — 256-bit master key before HKDF expansion
 *
 * These are deliberately conservative for a hackathon context.
 * Production usage should benchmark and tune for ≥500ms on target hardware.
 */
export const DEFAULT_PARAMS = Object.freeze({
  passes: 3,
  memory: 65536,   // KiB
  parallelism: 4,
  tagLength: 32,
});

// HKDF info strings — domain-separate the two sub-keys
const ENC_INFO = Buffer.from('zerovault-enc-v1', 'utf8');
const MAC_INFO = Buffer.from('zerovault-mac-v1', 'utf8');

/**
 * Expand a master key into two domain-separated sub-keys via HKDF-SHA256.
 * @param {Buffer} masterKey
 * @param {Buffer} salt
 * @returns {{ encKey: Buffer, macKey: Buffer }}
 */
function deriveSubKeys(masterKey, salt) {
  const encKey = Buffer.from(hkdfSync('sha256', masterKey, salt, ENC_INFO, 32));
  const macKey = Buffer.from(hkdfSync('sha256', masterKey, salt, MAC_INFO, 32));
  return { encKey, macKey };
}

/**
 * Derive encryption and MAC keys from a password and salt using Argon2id + HKDF.
 *
 * The caller's password buffer is NOT zeroed — an internal copy is made and
 * zeroed. The caller is responsible for zeroing their own password buffer if
 * they want defense-in-depth.
 *
 * @param {Buffer} password   — password bytes (non-empty Buffer)
 * @param {Buffer} salt       — random salt (minimum 16 bytes; use generateSalt())
 * @param {object} [params]   — KDF parameters, merged with DEFAULT_PARAMS
 * @returns {{ encKey: Buffer, macKey: Buffer }}
 */
export function deriveKey(password, salt, params = {}) {
  if (!Buffer.isBuffer(password) || password.length === 0) {
    throw new TypeError('password must be a non-empty Buffer');
  }
  if (!Buffer.isBuffer(salt) || salt.length < 16) {
    throw new TypeError('salt must be a Buffer of at least 16 bytes');
  }

  const p = { ...DEFAULT_PARAMS, ...params };

  // Work on an internal copy so the caller's buffer is unmodified
  const pwCopy = Buffer.allocUnsafe(password.length);
  password.copy(pwCopy);

  let masterKey;
  try {
    masterKey = Buffer.from(
      argon2Sync('argon2id', {
        message:     pwCopy,
        nonce:       salt,
        passes:      p.passes,
        memory:      p.memory,
        parallelism: p.parallelism,
        tagLength:   p.tagLength,
      })
    );
  } finally {
    // Zero the local password copy regardless of success or failure
    pwCopy.fill(0);
  }

  const subKeys = deriveSubKeys(masterKey, salt);

  // Zero the master key — sub-keys are all we need from here on
  masterKey.fill(0);

  return subKeys;
}
