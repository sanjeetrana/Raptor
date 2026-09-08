/**
 * vault.js — Core Vault Operations
 *
 * Provides createVault and unlockVault — the only two public entry points
 * into the cryptographic vault subsystem.
 *
 * Security model:
 *   createVault: password → Argon2id+HKDF → AES-256-GCM encrypt → HMAC-SHA256 sign → binary blob
 *   unlockVault: binary blob → decode → HMAC verify (constant-time) → AES-GCM decrypt → JSON
 *
 * The master password and all derived key material are zero-filled after use.
 * Neither the password nor any key is returned, logged, or included in errors.
 */

import { createHmac, timingSafeEqual } from 'node:crypto';
import { generateSalt, generateIV } from '../crypto/random.js';
import { deriveKey, DEFAULT_PARAMS } from '../crypto/kdf.js';
import { encrypt, decrypt } from '../crypto/aead.js';
import { encodeVault, decodeVault, getHmacPayload } from './format.js';
import { VaultAuthError, VaultError, VaultCorruptedError } from './errors.js';

/**
 * Creates a new encrypted vault containing the given secrets.
 *
 * @param {Buffer} password — master password bytes
 * @param {object} secrets  — JSON-serializable secrets payload
 * @returns {Buffer}        — serialized `.zvault` binary
 */
export function createVault(password, secrets) {
  if (!Buffer.isBuffer(password) || password.length === 0) {
    throw new VaultError('Password must be a non-empty Buffer');
  }
  if (typeof secrets !== 'object' || secrets === null) {
    throw new VaultError('Secrets must be a non-null object');
  }

  const salt = generateSalt();
  const iv   = generateIV();

  const { encKey, macKey } = deriveKey(password, salt);

  const plaintext = Buffer.from(JSON.stringify(secrets), 'utf8');

  // Build a temporary header to extract the AAD bytes used by AES-GCM.
  // The AAD binds the header to the ciphertext so any header tampering fails authentication.
  const tempBuf      = encodeVault(DEFAULT_PARAMS, salt, iv, Buffer.alloc(32), Buffer.alloc(16), Buffer.alloc(0));
  const headerForAAD = decodeVault(tempBuf).headerForAAD;

  let ciphertext, tag;
  try {
    ({ ciphertext, tag } = encrypt(encKey, iv, plaintext, headerForAAD));
  } finally {
    encKey.fill(0);
    plaintext.fill(0);
  }

  const hmacPayload = getHmacPayload(headerForAAD, tag, ciphertext);
  let hmac;
  try {
    const h = createHmac('sha256', macKey);
    h.update(hmacPayload);
    hmac = h.digest();
  } finally {
    macKey.fill(0);
  }

  return encodeVault(DEFAULT_PARAMS, salt, iv, hmac, tag, ciphertext);
}

/**
 * Unlocks a vault and returns the parsed secrets.
 *
 * Authentication order: HMAC-SHA256 verify first (constant-time, fast rejection),
 * then AES-GCM decrypt. This prevents timing oracles and ensures wrong-password
 * errors are indistinguishable from tamper errors.
 *
 * @param {Buffer} password  — master password bytes
 * @param {Buffer} vaultData — serialized `.zvault` binary
 * @returns {object}         — decrypted secrets
 * @throws {VaultAuthError}   — wrong password or tampered data
 * @throws {VaultFormatError} — malformed binary format
 * @throws {VaultCorruptedError} — decrypted payload is not valid JSON
 */
export function unlockVault(password, vaultData) {
  if (!Buffer.isBuffer(password) || password.length === 0) {
    throw new VaultError('Password must be a non-empty Buffer');
  }

  const { kdfParams, salt, iv, hmac, tag, ciphertext, headerForAAD } = decodeVault(vaultData);

  const { encKey, macKey } = deriveKey(password, salt, kdfParams);

  try {
    // Verify outer HMAC before attempting decryption.
    // timingSafeEqual prevents timing-based password inference.
    const h = createHmac('sha256', macKey);
    h.update(getHmacPayload(headerForAAD, tag, ciphertext));
    const expectedHmac = h.digest();

    if (!timingSafeEqual(hmac, expectedHmac)) {
      throw new VaultAuthError('Authentication failed or vault is corrupted');
    }

    // Defense-in-depth: GCM tag verification catches ciphertext-only tampering
    // that somehow passed the outer HMAC (should be impossible, but belt-and-suspenders).
    let plaintext;
    try {
      plaintext = decrypt(encKey, iv, ciphertext, tag, headerForAAD);
    } catch {
      throw new VaultAuthError('Authentication failed or vault is corrupted');
    }

    try {
      return JSON.parse(plaintext.toString('utf8'));
    } catch {
      throw new VaultCorruptedError('Failed to parse decrypted payload as JSON');
    } finally {
      if (plaintext) plaintext.fill(0);
    }
  } finally {
    encKey.fill(0);
    macKey.fill(0);
  }
}
