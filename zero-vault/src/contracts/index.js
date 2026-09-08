/**
 * API Contracts & Integration Boundaries
 * Defines standard JSON schemas and data interfaces expected by the ZeroVault Frontend and CLI
 */

/**
 * @typedef {Object} PasswordAuditResult
 * @property {number} score - Score from 0 to 100
 * @property {'EXCELLENT'|'STRONG'|'MODERATE'|'WEAK'|'CRITICAL'} tier - Security level
 * @property {number} entropyBits - Entropy
 * @property {number} poolSize - Total distinct character pool size
 * @property {number} length - Password length
 * @property {Object} breakdown - Score deduction details
 * @property {string[]} remediations - Suggestions to improve
 */

/**
 * @typedef {Object} VaultSecretItem
 * @property {string} id - Unique UUID
 * @property {string} title - User-friendly title
 * @property {'LOGIN'|'SECURE_NOTE'|'API_KEY'|'CREDIT_CARD'} type - Item type
 * @property {string} [value] - Main secret or password
 * @property {string} [username] - Optional login username
 * @property {string} [url] - Optional login URL
 * @property {string} [notes] - Optional secure notes text
 * @property {string} [totpSecret] - Base32 TOTP secret
 * @property {string} [cardNumber] - Card details
 * @property {string} [cardExpiry] - Card expiry
 * @property {string} [cardCvv] - Card CVV
 */

/**
 * @typedef {Object} VaultPayload
 * @property {VaultSecretItem[]} items - Array of encrypted items
 */
