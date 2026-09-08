/**
 * format.js — Vault Binary Format Serialization
 *
 * Layout:
 *   [MAGIC]      8 bytes  — "ZV01\x00\x00\x00\x00"
 *   [VERSION]    2 bytes  — 0x0001 (uint16 BE)
 *   [KDF_ID]     1 byte   — 0x01 (Argon2id)
 *   [KDF_PARAMS] 18 bytes — passes(1), memory(4), parallelism(1), tagLength(1), reserved(11)
 *   [SALT]       32 bytes
 *   [IV]         12 bytes
 *   [HMAC]       32 bytes — Outer HMAC-SHA256 over everything before and after it
 *   [TAG]        16 bytes — GCM auth tag
 *   [CIPHERTEXT] variable — Encrypted JSON payload
 */

import { VaultFormatError } from './errors.js';

export const MAGIC = Buffer.from('ZV01\x00\x00\x00\x00', 'ascii');
export const VERSION = 1;
export const KDF_ID_ARGON2ID = 1;

const HEADER_LENGTH = 8 + 2 + 1 + 18 + 32 + 12; // 73 bytes
const MIN_VAULT_SIZE = HEADER_LENGTH + 32 + 16; // 121 bytes

/**
 * Encode vault fields into a single binary buffer.
 *
 * @param {object} p — passes, memory, parallelism, tagLength
 * @param {Buffer} salt
 * @param {Buffer} iv
 * @param {Buffer} hmac
 * @param {Buffer} tag
 * @param {Buffer} ciphertext
 * @returns {Buffer}
 */
export function encodeVault(p, salt, iv, hmac, tag, ciphertext) {
  const buf = Buffer.alloc(HEADER_LENGTH + 32 + 16 + ciphertext.length);
  let offset = 0;

  // MAGIC
  MAGIC.copy(buf, offset);
  offset += 8;

  // VERSION
  buf.writeUInt16BE(VERSION, offset);
  offset += 2;

  // KDF_ID
  buf.writeUInt8(KDF_ID_ARGON2ID, offset);
  offset += 1;

  // KDF_PARAMS (18 bytes)
  buf.writeUInt8(p.passes, offset);
  buf.writeUInt32BE(p.memory, offset + 1);
  buf.writeUInt8(p.parallelism, offset + 5);
  buf.writeUInt8(p.tagLength, offset + 6);
  // next 11 bytes remain 0 (reserved)
  offset += 18;

  // SALT
  salt.copy(buf, offset);
  offset += 32;

  // IV
  iv.copy(buf, offset);
  offset += 12;

  // HMAC (Outer signature)
  hmac.copy(buf, offset);
  offset += 32;

  // TAG
  tag.copy(buf, offset);
  offset += 16;

  // CIPHERTEXT
  ciphertext.copy(buf, offset);

  return buf;
}

/**
 * Decode a binary vault buffer into its constituent fields.
 *
 * @param {Buffer} buf
 * @returns {object} { kdfParams, salt, iv, hmac, tag, ciphertext, headerForAAD }
 */
export function decodeVault(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < MIN_VAULT_SIZE) {
    throw new VaultFormatError('Buffer too small to be a valid ZeroVault');
  }

  let offset = 0;

  // MAGIC
  const magic = buf.subarray(offset, offset + 8);
  if (!magic.equals(MAGIC)) {
    throw new VaultFormatError('Invalid vault magic bytes');
  }
  offset += 8;

  // VERSION
  const version = buf.readUInt16BE(offset);
  if (version !== VERSION) {
    throw new VaultFormatError(`Unsupported vault version: ${version}`);
  }
  offset += 2;

  // KDF_ID
  const kdfId = buf.readUInt8(offset);
  if (kdfId !== KDF_ID_ARGON2ID) {
    throw new VaultFormatError(`Unsupported KDF ID: ${kdfId}`);
  }
  offset += 1;

  // KDF_PARAMS
  const passes = buf.readUInt8(offset);
  const memory = buf.readUInt32BE(offset + 1);
  const parallelism = buf.readUInt8(offset + 5);
  const tagLength = buf.readUInt8(offset + 6);
  offset += 18;

  const kdfParams = { passes, memory, parallelism, tagLength };

  // SALT
  const salt = buf.subarray(offset, offset + 32);
  offset += 32;

  // IV
  const iv = buf.subarray(offset, offset + 12);
  offset += 12;

  // The AAD for AES-GCM is everything up to this point
  const headerForAAD = buf.subarray(0, offset);

  // HMAC
  const hmac = buf.subarray(offset, offset + 32);
  offset += 32;

  // TAG
  const tag = buf.subarray(offset, offset + 16);
  offset += 16;

  // CIPHERTEXT
  const ciphertext = buf.subarray(offset);

  return { kdfParams, salt, iv, hmac, tag, ciphertext, headerForAAD };
}

/**
 * Extract the exact byte segments covered by the outer HMAC.
 * The HMAC covers the header (AAD) and the encrypted payload (TAG + CIPHERTEXT).
 * It obviously excludes the HMAC field itself.
 */
export function getHmacPayload(headerForAAD, tag, ciphertext) {
  return Buffer.concat([headerForAAD, tag, ciphertext]);
}
