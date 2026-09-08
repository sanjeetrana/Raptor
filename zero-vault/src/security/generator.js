import { randomBytes } from 'node:crypto';

// Standard Character Sets
export const CHARSETS = {
  uppercase: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
  lowercase: 'abcdefghijklmnopqrstuvwxyz',
  digits: '0123456789',
  symbols: '!@#$%^&*()_+-=[]{}|;:,.<>?'
};

// Ambiguous characters often misread (O, 0, I, 1, l, Z, 2, S, 5)
export const AMBIGUOUS_CHARS = new Set(['O', '0', 'I', '1', 'l', 'Z', '2', 'S', '5']);

// Built-in wordpool for CSPRNG Passphrase Generation (100 distinct clean words)
export const DEFAULT_WORDLIST = [
  'anchor', 'beacon', 'breeze', 'bridge', 'castle', 'cipher', 'cobalt', 'crater',
  'crystal', 'dragon', 'echo', 'ember', 'falcon', 'forest', 'fossil', 'galaxy',
  'glacier', 'granite', 'harbor', 'island', 'jungle', 'knight', 'lagoon', 'lantern',
  'legacy', 'legend', 'magnet', 'marble', 'matrix', 'meadow', 'meteor', 'mirage',
  'monarch', 'nebula', 'oasis', 'ocean', 'orchid', 'orbit', 'palace', 'panther',
  'phoenix', 'planet', 'portal', 'prism', 'pyramid', 'quartz', 'radar', 'radius',
  'raven', 'record', 'relief', 'ripple', 'river', 'rocket', 'safari', 'shadow',
  'shield', 'signal', 'silence', 'silver', 'solar', 'spark', 'sphere', 'spirit',
  'spring', 'square', 'star', 'status', 'storm', 'stream', 'summit', 'sunset',
  'symbol', 'target', 'temple', 'timber', 'titan', 'topaz', 'torpedo', 'tower',
  'trench', 'trophy', 'tundra', 'tunnel', 'valley', 'vector', 'velvet', 'vessel',
  'vortex', 'walnut', 'whisper', 'willow', 'winter', 'wisdom', 'wizard', 'zenith'
];

/**
 * CSPRNG Unbiased Rejection Sampling to pick an index from 0 to maxExclusive - 1.
 * Prevents modulo bias when maxExclusive does not evenly divide 256.
 *
 * @param {number} maxExclusive - Upper bound (exclusive)
 * @returns {number} - Cryptographically random index in [0, maxExclusive - 1]
 */
export function getRandomInt(maxExclusive) {
  if (maxExclusive <= 0) {
    throw new RangeError('maxExclusive must be positive');
  }
  if (maxExclusive === 1) return 0;

  // Max threshold byte value that evenly divides maxExclusive
  const limit = Math.floor(256 / maxExclusive) * maxExclusive;

  while (true) {
    const buf = randomBytes(1);
    const value = buf[0];
    if (value < limit) {
      return value % maxExclusive;
    }
  }
}

/**
 * CSPRNG Fisher-Yates In-Place Array Shuffle.
 *
 * @param {Array} array - Array to shuffle
 * @returns {Array} - Shuffled array
 */
export function shuffleArray(array) {
  for (let i = array.length - 1; i > 0; i--) {
    const j = getRandomInt(i + 1);
    const temp = array[i];
    array[i] = array[j];
    array[j] = temp;
  }
  return array;
}

/**
 * Calculates exact bit entropy for a given length and pool size.
 * Formula: Entropy (bits) = Length * log2(PoolSize)
 *
 * @param {number} length - Password length
 * @param {number} poolSize - Total distinct characters in pool
 * @returns {number} - Entropy in bits
 */
export function calculateEntropyBits(length, poolSize) {
  if (length <= 0 || poolSize <= 0) return 0;
  return Number((length * Math.log2(poolSize)).toFixed(2));
}

/**
 * Generates a cryptographically secure random password with flexible options.
 *
 * @param {Object} [options]
 * @param {number} [options.length=16] - Password length (4 to 2048)
 * @param {boolean} [options.uppercase=true] - Include A-Z
 * @param {boolean} [options.lowercase=true] - Include a-z
 * @param {boolean} [options.digits=true] - Include 0-9
 * @param {boolean} [options.symbols=true] - Include special characters
 * @param {boolean} [options.avoidAmbiguous=false] - Exclude ambiguous characters (O, 0, I, 1, etc.)
 * @param {boolean} [options.requireEachType=true] - Ensure at least 1 char from each selected group
 * @param {string} [options.customCharset] - Custom character set override
 * @returns {{ password: string, entropyBits: number, poolSize: number }}
 */
export function generatePassword(options = {}) {
  const {
    length = 16,
    uppercase = true,
    lowercase = true,
    digits = true,
    symbols = true,
    avoidAmbiguous = false,
    requireEachType = true,
    customCharset
  } = options;

  if (length < 4 || length > 2048) {
    throw new RangeError('Password length must be between 4 and 2048');
  }

  let finalPool = '';
  const selectedGroups = [];

  if (customCharset) {
    let pool = customCharset;
    if (avoidAmbiguous) {
      pool = [...pool].filter((c) => !AMBIGUOUS_CHARS.has(c)).join('');
    }
    if (pool.length === 0) {
      throw new Error('Custom charset is empty after applying options');
    }
    finalPool = pool;
    selectedGroups.push(pool);
  } else {
    const groups = [
      { enabled: uppercase, set: CHARSETS.uppercase },
      { enabled: lowercase, set: CHARSETS.lowercase },
      { enabled: digits, set: CHARSETS.digits },
      { enabled: symbols, set: CHARSETS.symbols }
    ];

    for (const group of groups) {
      if (group.enabled) {
        let setStr = group.set;
        if (avoidAmbiguous) {
          setStr = [...setStr].filter((c) => !AMBIGUOUS_CHARS.has(c)).join('');
        }
        if (setStr.length > 0) {
          selectedGroups.push(setStr);
          finalPool += setStr;
        }
      }
    }
  }

  if (finalPool.length === 0) {
    throw new Error('At least one character set must be enabled');
  }

  // Remove duplicate characters from finalPool for accurate entropy pool calculation
  const uniquePool = Array.from(new Set(finalPool)).join('');
  const poolSize = uniquePool.length;

  const resultChars = [];

  // Guarantee at least 1 character from each selected group if required
  if (requireEachType && selectedGroups.length > 1 && length >= selectedGroups.length) {
    for (const groupSet of selectedGroups) {
      const idx = getRandomInt(groupSet.length);
      resultChars.push(groupSet[idx]);
    }
  }

  // Fill remaining length from full pool using CSPRNG
  while (resultChars.length < length) {
    const idx = getRandomInt(uniquePool.length);
    resultChars.push(uniquePool[idx]);
  }

  // CSPRNG shuffle to break predictable group ordering
  shuffleArray(resultChars);

  const password = resultChars.join('');
  const entropyBits = calculateEntropyBits(length, poolSize);

  return {
    password,
    entropyBits,
    poolSize
  };
}

/**
 * Generates a Diceware-style passphrase using a CSPRNG wordpool.
 *
 * @param {Object} [options]
 * @param {number} [options.wordCount=4] - Number of words (3 to 20)
 * @param {string} [options.separator='-'] - Word separator character
 * @param {boolean} [options.capitalize=true] - Capitalize first letter of each word
 * @param {boolean} [options.includeNumber=false] - Append CSPRNG random number to end
 * @param {Array<string>} [options.wordlist] - Custom word list array
 * @returns {{ passphrase: string, entropyBits: number }}
 */
export function generatePassphrase(options = {}) {
  const {
    wordCount = 4,
    separator = '-',
    capitalize = true,
    includeNumber = false,
    wordlist = DEFAULT_WORDLIST
  } = options;

  if (wordCount < 3 || wordCount > 20) {
    throw new RangeError('Word count must be between 3 and 20');
  }
  if (!Array.isArray(wordlist) || wordlist.length === 0) {
    throw new Error('Wordlist must be a non-empty array');
  }

  const selectedWords = [];
  for (let i = 0; i < wordCount; i++) {
    const wordIdx = getRandomInt(wordlist.length);
    let word = wordlist[wordIdx];
    if (capitalize) {
      word = word.charAt(0).toUpperCase() + word.slice(1);
    }
    selectedWords.push(word);
  }

  let passphrase = selectedWords.join(separator);

  let numPoolSize = 1;
  if (includeNumber) {
    const num = getRandomInt(100);
    passphrase += `${separator}${num}`;
    numPoolSize = 100;
  }

  // Entropy = log2(wordlistSize ^ wordCount * numPoolSize)
  const totalPossibilities = Math.pow(wordlist.length, wordCount) * numPoolSize;
  const entropyBits = Number(Math.log2(totalPossibilities).toFixed(2));

  return {
    passphrase,
    entropyBits
  };
}

/**
 * Generates CSPRNG random bytes buffer.
 *
 * @param {number} length - Number of bytes
 * @returns {Buffer}
 */
export function generateBytes(length = 32) {
  if (length <= 0) throw new RangeError('Length must be positive');
  return randomBytes(length);
}

/**
 * Generates a hex-encoded CSPRNG secret key.
 *
 * @param {number} [byteLength=32] - Secret key length in bytes
 * @returns {string} - Hex string (2x byteLength characters)
 */
export function generateHexKey(byteLength = 32) {
  return generateBytes(byteLength).toString('hex');
}

/**
 * Generates a Base64URL-encoded CSPRNG secret key.
 *
 * @param {number} [byteLength=32] - Secret key length in bytes
 * @returns {string} - Base64URL string
 */
export function generateBase64Key(byteLength = 32) {
  return generateBytes(byteLength)
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}
