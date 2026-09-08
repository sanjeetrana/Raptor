# ZeroVault Security Model

## Claims

ZeroVault provides authenticated encryption for JSON payloads with zero external dependencies, leveraging only the Node.js standard library.

1. **Confidentiality:** Payloads are encrypted using AES-256-GCM.
2. **Integrity & Authenticity:** 
   - A GCM auth tag protects the ciphertext and the vault header (via AAD).
   - An outer HMAC-SHA256 signature protects the entire file format, providing a fast, constant-time "wrong password" rejection before decryption is attempted.
3. **Key Derivation:** Argon2id is used as the primary KDF. This provides resistance against GPU/ASIC cracking and side-channel attacks.
4. **Key Separation:** The Argon2id output is never used directly as a cipher key. It is expanded via HKDF-SHA256 into two distinct, domain-separated keys: one for encryption, one for the HMAC.

## Known Limitations & Honest Disclosures

1. **No Memory Pinning & String Immutability:** Node.js does not expose OS-level memory locking (e.g., `mlock(2)` or `VirtualLock`). Consequently, sensitive key material or plaintext *could* be paged to disk by the OS under memory pressure. Furthermore, while we actively zero-fill Node.js `Buffer` objects (`buf.fill(0)`) immediately after their cryptographic use, V8 strings (e.g. from `JSON.parse`) are immutable and cannot be securely erased. They remain in memory until garbage collected. This is a platform limitation of running in user-land V8, not a flaw in the cryptography logic.
   - **VaultManager Lifecycle**: The stateful `VaultManager` must retain the master password in memory while the vault is `unlocked()` to facilitate transparent, atomic saves on CRUD operations. When `lock()` is called, the credential payload is dropped (relying on GC) and the master password buffer is explicitly zero-filled (`buf.fill(0)`).
2. **Side-Channel Timing on Decryption:** While the outer HMAC verification uses constant-time comparison (`timingSafeEqual`), the subsequent AES-GCM decryption in V8/OpenSSL may still theoretically have minute timing variations on failure, though GCM tag mismatches are handled gracefully.
3. **No Key Rotation (Yet):** Phase 1 does not support in-place password rotation.
4. **Synchronous KDF:** `argon2Sync` is used for simplicity in Phase 1. It blocks the event loop.

## Cryptographic Primitives

| Operation | Algorithm | Source |
|---|---|---|
| KDF | Argon2id | `node:crypto.argon2Sync` |
| Key Expansion | HKDF-SHA256 | `node:crypto.hkdfSync` |
| Encryption | AES-256-GCM | `node:crypto.createCipheriv` |
| MAC (Outer) | HMAC-SHA256 | `node:crypto.createHmac` |
| CSPRNG | OS TRNG | `node:crypto.randomBytes` |
