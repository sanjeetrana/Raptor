/**
 * errors.js — Custom Vault Error Classes
 *
 * Defines explicit error types so consumers can differentiate between
 * auth failures, format issues, and generic errors.
 */

/**
 * Base class for all vault errors.
 */
export class VaultError extends Error {
  constructor(message) {
    super(message);
    this.name = 'VaultError';
  }
}

/**
 * Thrown when the vault binary format is malformed or unsupported.
 */
export class VaultFormatError extends VaultError {
  constructor(message) {
    super(message);
    this.name = 'VaultFormatError';
  }
}

/**
 * Thrown when decryption or authentication fails (wrong password, tampered data).
 * Intentionally generic to avoid leaking failure modes.
 */
export class VaultAuthError extends VaultError {
  constructor(message = 'Authentication failed (wrong password or tampered vault)') {
    super(message);
    this.name = 'VaultAuthError';
  }
}

/**
 * Thrown when internal vault state is corrupted or unrecoverable.
 */
export class VaultCorruptedError extends VaultError {
  constructor(message) {
    super(message);
    this.name = 'VaultCorruptedError';
  }
}
