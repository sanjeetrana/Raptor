/**
 * aead.js — Authenticated Encryption with Associated Data
 *
 * Wraps Node.js AES-256-GCM for authenticated encryption.
 *
 * Why AES-256-GCM:
 *   - Single-primitive AEAD: one operation provides confidentiality AND
 *     integrity. No need to combine a cipher + separate MAC manually.
 *   - 256-bit key: future-proof against quantum (Grover's algorithm halves
 *     effective key length, leaving 128-bit security post-quantum).
 *   - GCM: NIST-standardized, hardware-accelerated (AES-NI) on modern CPUs.
 *   - 12-byte IV: optimal for GCM (96-bit nonces avoid counter-overflow risk
 *     that exists with non-96-bit nonces per NIST SP 800-38D).
 *   - 16-byte auth tag: full 128-bit GCM tag (maximum length).
 *
 * AAD (Additional Authenticated Data):
 *   The vault header (MAGIC, VERSION, KDF_ID, KDF_PARAMS, SALT, IV) is passed
 *   as AAD. GCM authenticates it without encrypting it, so any header
 *   tampering causes decryption to fail with a tag mismatch.
 *
 * What this module does NOT do:
 *   - No custom cipher implementation.
 *   - No manual mode (CBC, CTR, etc.) without a MAC.
 *   - No ECB mode.
 */

import { createCipheriv, createDecipheriv } from 'node:crypto';

const ALGORITHM   = 'aes-256-gcm';
const KEY_LENGTH  = 32; // bytes (256 bits)
const IV_LENGTH   = 12; // bytes (96 bits — optimal for GCM)
const TAG_LENGTH  = 16; // bytes (128 bits — maximum GCM tag length)

/**
 * Encrypt plaintext with AES-256-GCM.
 *
 * @param {Buffer} encKey    — 32-byte encryption key
 * @param {Buffer} iv        — 12-byte random IV (never reuse with same key)
 * @param {Buffer} plaintext — data to encrypt
 * @param {Buffer} aad       — additional authenticated data (authenticated but not encrypted)
 * @returns {{ ciphertext: Buffer, tag: Buffer }}
 */
export function encrypt(encKey, iv, plaintext, aad) {
  if (!Buffer.isBuffer(encKey) || encKey.length !== KEY_LENGTH) {
    throw new TypeError(`encKey must be a ${KEY_LENGTH}-byte Buffer`);
  }
  if (!Buffer.isBuffer(iv) || iv.length !== IV_LENGTH) {
    throw new TypeError(`iv must be a ${IV_LENGTH}-byte Buffer`);
  }
  if (!Buffer.isBuffer(plaintext)) {
    throw new TypeError('plaintext must be a Buffer');
  }
  if (!Buffer.isBuffer(aad)) {
    throw new TypeError('aad must be a Buffer');
  }

  const cipher = createCipheriv(ALGORITHM, encKey, iv, { authTagLength: TAG_LENGTH });
  cipher.setAAD(aad, { plaintextLength: plaintext.length });

  const chunks = [cipher.update(plaintext)];
  chunks.push(cipher.final());
  const ciphertext = Buffer.concat(chunks);
  const tag = cipher.getAuthTag();

  return { ciphertext, tag };
}

/**
 * Decrypt ciphertext with AES-256-GCM.
 *
 * Throws if authentication fails (wrong key, tampered ciphertext, wrong tag,
 * or tampered AAD). The error is intentionally generic — do not leak which
 * field caused the failure.
 *
 * @param {Buffer} encKey     — 32-byte encryption key
 * @param {Buffer} iv         — 12-byte IV (must match the one used for encrypt)
 * @param {Buffer} ciphertext — encrypted bytes
 * @param {Buffer} tag        — 16-byte GCM authentication tag
 * @param {Buffer} aad        — additional authenticated data (must match encrypt)
 * @returns {Buffer} plaintext
 * @throws if authentication or decryption fails
 */
export function decrypt(encKey, iv, ciphertext, tag, aad) {
  if (!Buffer.isBuffer(encKey) || encKey.length !== KEY_LENGTH) {
    throw new TypeError(`encKey must be a ${KEY_LENGTH}-byte Buffer`);
  }
  if (!Buffer.isBuffer(iv) || iv.length !== IV_LENGTH) {
    throw new TypeError(`iv must be a ${IV_LENGTH}-byte Buffer`);
  }
  if (!Buffer.isBuffer(ciphertext)) {
    throw new TypeError('ciphertext must be a Buffer');
  }
  if (!Buffer.isBuffer(tag) || tag.length !== TAG_LENGTH) {
    throw new TypeError(`tag must be a ${TAG_LENGTH}-byte Buffer`);
  }
  if (!Buffer.isBuffer(aad)) {
    throw new TypeError('aad must be a Buffer');
  }

  const decipher = createDecipheriv(ALGORITHM, encKey, iv, { authTagLength: TAG_LENGTH });
  decipher.setAAD(aad, { plaintextLength: ciphertext.length });
  decipher.setAuthTag(tag);

  const chunks = [decipher.update(ciphertext)];
  // .final() throws ERR_CRYPTO_GCM_AUTH_TAG_MISMATCH if authentication fails
  chunks.push(decipher.final());

  return Buffer.concat(chunks);
}
