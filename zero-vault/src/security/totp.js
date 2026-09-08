import { createHmac, timingSafeEqual } from 'node:crypto';

/**
 * Base32 RFC 4648 Alphabet
 */
const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

/**
 * Decodes a Base32 string into a Buffer.
 * Supports optional padding and space/hyphen removal.
 *
 * @param {string} input - Base32 encoded string
 * @returns {Buffer} - Decoded binary buffer
 */
export function base32Decode(input) {
  if (typeof input !== 'string') {
    throw new TypeError('Base32 input must be a string');
  }

  // Clean input: uppercase, strip spaces, hyphens, and padding '='
  const cleanInput = input.toUpperCase().replace(/[\s=\-]/g, '');

  if (cleanInput.length === 0) {
    return Buffer.alloc(0);
  }

  let bits = 0;
  let value = 0;
  const output = [];

  for (let i = 0; i < cleanInput.length; i++) {
    const char = cleanInput[i];
    const index = BASE32_ALPHABET.indexOf(char);
    if (index === -1) {
      throw new Error(`Invalid Base32 character encountered: '${char}'`);
    }

    value = (value << 5) | index;
    bits += 5;

    if (bits >= 8) {
      output.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }

  return Buffer.from(output);
}

/**
 * Encodes a Buffer or Uint8Array into a Base32 string (RFC 4648).
 *
 * @param {Buffer|Uint8Array} buffer - Data to encode
 * @param {boolean} [padding=true] - Whether to include '=' padding
 * @returns {string} - Base32 encoded string
 */
export function base32Encode(buffer, padding = true) {
  const buf = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer);
  let bits = 0;
  let value = 0;
  let output = '';

  for (let i = 0; i < buf.length; i++) {
    value = (value << 8) | buf[i];
    bits += 8;

    while (bits >= 5) {
      output += BASE32_ALPHABET[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }

  if (bits > 0) {
    output += BASE32_ALPHABET[(value << (5 - bits)) & 31];
  }

  if (padding) {
    while (output.length % 8 !== 0) {
      output += '=';
    }
  }

  return output;
}

/**
 * Generates an HOTP (HMAC-Based One-Time Password) per RFC 4226.
 *
 * @param {string|Buffer} secret - Secret key (Base32 string or raw Buffer)
 * @param {number|bigint} counter - Moving factor counter
 * @param {Object} [options]
 * @param {string} [options.algorithm='SHA1'] - HMAC algorithm ('SHA1', 'SHA256', 'SHA512')
 * @param {number} [options.digits=6] - OTP length (6 to 8)
 * @returns {string} - Formatted OTP string
 */
export function generateHOTP(secret, counter, options = {}) {
  const { algorithm = 'SHA1', digits = 6 } = options;

  if (digits < 6 || digits > 8) {
    throw new RangeError('OTP digits must be between 6 and 8');
  }

  // Parse secret key
  let secretBuffer;
  if (Buffer.isBuffer(secret)) {
    secretBuffer = secret;
  } else if (typeof secret === 'string') {
    secretBuffer = base32Decode(secret);
  } else {
    throw new TypeError('Secret must be a Base32 string or Buffer');
  }

  if (secretBuffer.length === 0) {
    throw new Error('Secret key cannot be empty');
  }

  // Convert counter to 8-byte big-endian buffer
  const countBuf = Buffer.alloc(8);
  const countBigInt = BigInt(counter);
  countBuf.writeBigInt64BE(countBigInt, 0);

  // Compute HMAC
  const hmacAlgo = algorithm.toLowerCase().replace('-', '');
  const hmac = createHmac(hmacAlgo, secretBuffer);
  hmac.update(countBuf);
  const hash = hmac.digest();

  // Dynamic Truncation per RFC 4226 Section 5.3
  const offset = hash[hash.length - 1] & 0x0f;
  const binary =
    (((hash[offset] & 0x7f) << 24) |
    ((hash[offset + 1] & 0xff) << 16) |
    ((hash[offset + 2] & 0xff) << 8) |
    (hash[offset + 3] & 0xff)) >>> 0;

  const otp = binary % Math.pow(10, digits);
  return String(otp).padStart(digits, '0');
}

/**
 * Generates a TOTP (Time-Based One-Time Password) per RFC 6238.
 *
 * @param {string|Buffer} secret - Secret key (Base32 string or raw Buffer)
 * @param {Object} [options]
 * @param {number} [options.timestamp] - Unix timestamp in seconds (default: current time)
 * @param {number} [options.period=30] - Time step X in seconds (default: 30)
 * @param {number} [options.t0=0] - Epoch time T0 in seconds (default: 0)
 * @param {string} [options.algorithm='SHA1'] - HMAC algorithm ('SHA1', 'SHA256', 'SHA512')
 * @param {number} [options.digits=6] - OTP length (6 to 8)
 * @returns {string} - Formatted OTP string
 */
export function generateTOTP(secret, options = {}) {
  const {
    timestamp = Math.floor(Date.now() / 1000),
    period = 30,
    t0 = 0,
    algorithm = 'SHA1',
    digits = 6
  } = options;

  if (period <= 0) {
    throw new RangeError('TOTP period must be a positive integer');
  }

  const counter = Math.floor((timestamp - t0) / period);
  return generateHOTP(secret, counter, { algorithm, digits });
}

/**
 * Verifies a TOTP token against a secret with time-window drift tolerance.
 * Uses constant-time string comparison to prevent timing side-channels.
 *
 * @param {string} token - The OTP token provided by the user
 * @param {string|Buffer} secret - The Base32 or Buffer secret key
 * @param {Object} [options]
 * @param {number} [options.timestamp] - Unix timestamp in seconds (default: current time)
 * @param {number} [options.window=1] - Number of time steps to check before/after (default: 1)
 * @param {number} [options.period=30] - Time step in seconds
 * @param {string} [options.algorithm='SHA1'] - HMAC algorithm
 * @param {number} [options.digits=6] - OTP digits
 * @returns {{ valid: boolean, delta: number|null }} - Result object
 */
export function verifyTOTP(token, secret, options = {}) {
  if (typeof token !== 'string') {
    return { valid: false, delta: null };
  }

  const {
    timestamp = Math.floor(Date.now() / 1000),
    window = 1,
    period = 30,
    algorithm = 'SHA1',
    digits = token.length
  } = options;

  const normalizedToken = token.trim();
  const tokenBuf = Buffer.from(normalizedToken);

  for (let delta = -window; delta <= window; delta++) {
    const stepTimestamp = timestamp + delta * period;
    const expectedToken = generateTOTP(secret, {
      timestamp: stepTimestamp,
      period,
      algorithm,
      digits
    });
    const expectedBuf = Buffer.from(expectedToken);

    if (
      tokenBuf.length === expectedBuf.length &&
      timingSafeEqual(tokenBuf, expectedBuf)
    ) {
      return { valid: true, delta };
    }
  }

  return { valid: false, delta: null };
}

/**
 * Parses an otpauth:// URI (key uri format).
 *
 * @param {string} uriString - URI like otpauth://totp/Example:alice@google.com?secret=JBSWY3DPEHPK3PXP&issuer=Example
 * @returns {Object} - Parsed URI properties
 */
export function parseOtpauthUri(uriString) {
  let url;
  try {
    url = new URL(uriString);
  } catch {
    throw new Error('Invalid URI format');
  }

  if (url.protocol !== 'otpauth:') {
    throw new Error(`Unsupported protocol '${url.protocol}'. Expected 'otpauth:'`);
  }

  const type = url.hostname.toLowerCase();
  if (type !== 'totp' && type !== 'hotp') {
    throw new Error(`Unsupported OTP type '${type}'. Expected 'totp' or 'hotp'`);
  }

  const rawPath = decodeURIComponent(url.pathname.replace(/^\//, ''));
  let label = rawPath;
  let issuerFromLabel = '';
  let accountName = rawPath;

  if (rawPath.includes(':')) {
    const parts = rawPath.split(':');
    issuerFromLabel = parts[0].trim();
    accountName = parts.slice(1).join(':').trim();
  }

  const searchParams = url.searchParams;
  const secret = searchParams.get('secret');
  if (!secret) {
    throw new Error("Missing mandatory 'secret' query parameter");
  }

  const issuer = searchParams.get('issuer') || issuerFromLabel;
  const algorithm = (searchParams.get('algorithm') || 'SHA1').toUpperCase();
  const digits = searchParams.get('digits') ? parseInt(searchParams.get('digits'), 10) : 6;
  const period = searchParams.get('period') ? parseInt(searchParams.get('period'), 10) : 30;
  const counter = searchParams.get('counter') ? parseInt(searchParams.get('counter'), 10) : 0;

  return {
    type,
    label,
    accountName,
    secret,
    issuer,
    algorithm,
    digits,
    period,
    counter
  };
}

/**
 * Generates an otpauth:// URI string.
 *
 * @param {Object} options
 * @param {'totp'|'hotp'} [options.type='totp'] - OTP Type
 * @param {string} options.label - Account name / label
 * @param {string} options.secret - Base32 secret string
 * @param {string} [options.issuer] - Service / issuer name
 * @param {string} [options.algorithm='SHA1'] - HMAC algorithm
 * @param {number} [options.digits=6] - OTP digits
 * @param {number} [options.period=30] - TOTP period
 * @param {number} [options.counter=0] - HOTP counter
 * @returns {string} - otpauth:// URI
 */
export function generateOtpauthUri(options) {
  const {
    type = 'totp',
    label,
    secret,
    issuer,
    algorithm = 'SHA1',
    digits = 6,
    period = 30,
    counter = 0
  } = options;

  if (!label) throw new Error('Label is required');
  if (!secret) throw new Error('Secret is required');

  const fullLabel = issuer ? `${issuer}:${label}` : label;
  const encodedLabel = encodeURIComponent(fullLabel);
  const searchParams = new URLSearchParams();

  searchParams.set('secret', secret);
  if (issuer) searchParams.set('issuer', issuer);
  if (algorithm !== 'SHA1') searchParams.set('algorithm', algorithm);
  if (digits !== 6) searchParams.set('digits', String(digits));

  if (type === 'totp') {
    if (period !== 30) searchParams.set('period', String(period));
  } else if (type === 'hotp') {
    searchParams.set('counter', String(counter));
  }

  return `otpauth://${type}/${encodedLabel}?${searchParams.toString()}`;
}

/**
 * RFC 6238 Official Test Vectors for verification.
 * Standard RFC 6238 Secret: ASCII "12345678901234567890" (20 bytes)
 * Base32 representation: "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
 */
export const RFC6238_TEST_VECTORS = {
  asciiSecret: '12345678901234567890',
  asciiSecretSHA256: '12345678901234567890123456789012',
  asciiSecretSHA512: '1234567890123456789012345678901234567890123456789012345678901234',
  base32Secret: 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', // 20 bytes
  vectors: [
    { time: 59, sha1: '94287082', sha256: '46119246', sha512: '90693936' },
    { time: 1111111109, sha1: '07081804', sha256: '68084774', sha512: '25091201' },
    { time: 1111111111, sha1: '14050471', sha256: '67062674', sha512: '99943326' },
    { time: 1234567890, sha1: '89005924', sha256: '91819424', sha512: '93441116' },
    { time: 2000000000, sha1: '69279037', sha256: '90698825', sha512: '38618901' },
    { time: 20000000000, sha1: '65353130', sha256: '77737706', sha512: '47863826' }
  ]
};
