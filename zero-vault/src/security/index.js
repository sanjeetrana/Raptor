/**
 * Security Utilities Subsystem Public Interface (Member 2)
 */

export {
  base32Decode,
  base32Encode,
  generateHOTP,
  generateTOTP,
  verifyTOTP,
  parseOtpauthUri,
  generateOtpauthUri,
  RFC6238_TEST_VECTORS
} from './totp.js';

export {
  calculateShannonEntropy,
  redactSecret,
  SECRET_DETECTOR_RULES,
  scanSecrets,
  redactText
} from './scanner.js';

export {
  CHARSETS,
  AMBIGUOUS_CHARS,
  DEFAULT_WORDLIST,
  getRandomInt,
  shuffleArray,
  calculateEntropyBits,
  generatePassword,
  generatePassphrase,
  generateBytes,
  generateHexKey,
  generateBase64Key
} from './generator.js';

export {
  auditPassword,
  auditVaultSecrets
} from './audit.js';

export {
  checkFilePermissions,
  secureFilePermissions,
  safeWriteFile,
  shredFile,
  hashFile,
  verifyFileIntegrity
} from './file-protection.js';
