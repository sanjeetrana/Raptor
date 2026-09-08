/**
 * ZeroVault Public API
 */

export { createVault, unlockVault } from './vault/vault.js';
export {
  VaultError,
  VaultFormatError,
  VaultAuthError,
  VaultCorruptedError
} from './vault/errors.js';

export { VaultManager, VaultLockedError } from './vault/manager.js';

export * as security from './security/index.js';
export {
  base32Decode,
  base32Encode,
  generateHOTP,
  generateTOTP,
  verifyTOTP,
  parseOtpauthUri,
  generateOtpauthUri,
  calculateShannonEntropy,
  redactSecret,
  SECRET_DETECTOR_RULES,
  scanSecrets,
  redactText,
  generatePassword,
  generatePassphrase,
  generateBytes,
  generateHexKey,
  generateBase64Key,
  auditPassword,
  auditVaultSecrets,
  checkFilePermissions,
  secureFilePermissions,
  safeWriteFile,
  shredFile,
  hashFile,
  verifyFileIntegrity
} from './security/index.js';

