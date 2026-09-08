# 🔐 ZeroVault

> **A completely zero-dependency, encrypted secret vault, security scanner, and 2FA authenticator — built strictly using the Node.js standard library and vanilla web technologies.**

[![Node.js](https://img.shields.io/badge/Node.js-%3E%3D25.0.0-brightgreen)](https://nodejs.org)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-blue)](package.json)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 🚀 Quick Start (Hackathon Reviewers)

```bash
# Clone & run — no npm install needed (zero dependencies!)
git clone <repo-url>
cd zero-vault
npm start
```

Then open **[Zero Vault – Live Deployment](https://zero-vault-production.up.railway.app)** in your browser.

### 🔑 Demo Credentials

| Field | Value |
|---|---|
| **Master Password** | `ZeroVault@2025` |
| **Vault File** | `my.zvault` (pre-seeded, included in repo) |
| **Demo TOTP Secret** | `JBSWY3DPEHPK3PXP` |

> **To unlock the demo vault:**
> 1. Open zero-vault-production.up.railway.app
> 2. In the vault path field, enter: `my.zvault`
> 3. Enter the master password: `ZeroVault@2025`
> 4. Click **Unlock** — you'll see pre-loaded secrets instantly

---

## ✨ Features

### 🔒 Encrypted Secret Vault
- **AES-256-GCM** authenticated encryption for all stored secrets
- **HMAC-SHA256** outer signature — wrong password is rejected in constant time before any decryption attempt
- **Argon2id** key derivation — master password is never stored or used directly as a key
- **HKDF-SHA256** splits derived key material into two independent 256-bit keys: one for encryption, one for MAC
- Atomic file writes using `.tmp` + `rename` — power loss cannot corrupt your vault
- Master password buffer is zeroed in memory (`buf.fill(0)`) immediately after use

### 🔑 CSPRNG Secret Generator
Generate cryptographically secure credentials in one click:
- **Password** — configurable length, uppercase, lowercase, digits, symbols
- **Passphrase** — Diceware-style word list, high entropy, human-memorable
- **Hex Key** — 256-bit random hex key (e.g., for API signing)
- **Base64 Key** — 256-bit random Base64 key (e.g., for JWT secrets)

### 🛡️ Secret Scanner
- Detects **AWS Access Keys** (`AKIA...`)
- Detects **GitHub Personal Access Tokens** (`ghp_...`, `github_pat_...`)
- Detects **Stripe API Keys** (`sk_live_...`, `pk_live_...`)
- Detects **Generic high-entropy strings** (Shannon entropy analysis)
- Supports **text redaction** — replaces found secrets with `[REDACTED]`
- Input size guarded at **5MB** to prevent DoS

### 🔐 TOTP / 2FA Authenticator
- Generate **RFC 6238-compliant** TOTP tokens from any Base32 secret
- Verify tokens with configurable time window (`delta`)
- Parse and generate standard `otpauth://` URIs (compatible with Google Authenticator, Authy, etc.)
- Secrets are **never echoed back** in API responses

### 📊 Password Audit Engine
Transparent, deterministic scoring model (0–100):
- **Entropy bits** calculated as `L × log₂(N)` (length × character pool)
- Penalties for: short length, low diversity, common patterns (`password`, `admin`, `qwerty`...), repeating characters, high redundancy
- Bonuses for: 16+ character length, 24+ character passphrases
- Returns tier: `EXCELLENT` / `STRONG` / `MODERATE` / `WEAK` / `CRITICAL`
- **Vault-wide audit** — detects duplicate passwords across entries, scans values for accidentally hardcoded secrets

### 📁 File Protection
- **Inspect** — check file permission bits and identify overly-permissive access
- **Secure** — lock a file down to `0o600` (owner read/write only)
- **Hash** — compute SHA-256 digest of any file
- **Shred** — multi-pass overwrite before deletion to prevent recovery

---

## 🏗️ Architecture

```
zero-vault/
├── bin/
│   └── zerovault.js          # CLI entrypoint
├── src/
│   ├── index.js              # Public API exports (VaultManager, crypto primitives)
│   ├── cli/
│   │   └── index.js          # CLI command router (serve, generate, totp, scan, audit, file)
│   ├── crypto/               # Vault encryption core
│   │   ├── kdf.js            # Argon2id + HKDF key derivation
│   │   ├── aes.js            # AES-256-GCM encrypt/decrypt
│   │   └── hmac.js           # HMAC-SHA256 outer signature
│   ├── vault/                # VaultManager — CRUD on encrypted entries
│   ├── security/
│   │   ├── scanner.js        # Secret detection + entropy analysis
│   │   ├── generator.js      # CSPRNG password/passphrase/key generation
│   │   ├── totp.js           # RFC 6238 TOTP implementation
│   │   ├── audit.js          # Password & vault health auditing
│   │   └── file.js           # File permission inspection and shredding
│   └── server/
│       ├── server.js         # Native node:http server
│       ├── router.js         # Custom URL router (no Express)
│       ├── state.js          # Singleton VaultManager session state
│       └── routes/           # Route handlers per feature module
│           ├── vault.routes.js
│           ├── generator.routes.js
│           ├── scanner.routes.js
│           ├── totp.routes.js
│           ├── audit.routes.js
│           └── file.routes.js
├── public/                   # Vanilla HTML5 + CSS3 + ES6 frontend (no build step)
│   ├── index.html
│   ├── css/
│   └── js/
└── tests/                    # Node.js built-in test runner
```

**Core principle:** Zero npm dependencies. Every module used is from `node:` built-ins — `node:http`, `node:crypto`, `node:fs`, `node:path`, `node:util`.

---

## 🔐 Security Architecture

### Key Derivation Chain

```
Master Password
       │
       ▼
  Argon2id (salt: 32 random bytes, time: 3, mem: 64MB, parallel: 4)
       │
       ▼
  HKDF-SHA256
       ├──► encKey (256-bit)  →  AES-256-GCM encryption
       └──► macKey (256-bit)  →  HMAC-SHA256 outer signature
```

### Vault Binary Format (`.zvault`)

| Field      | Size     | Description                                |
|------------|----------|--------------------------------------------|
| MAGIC      | 4 bytes  | ASCII "ZVLT"                               |
| VERSION    | 1 byte   | 0x01                                       |
| KDF_ID     | 1 byte   | 0x01 = Argon2id                            |
| KDF_PARAMS | 12 bytes | time, memory, parallelism                  |
| SALT       | 32 bytes | Random per vault creation                  |
| IV         | 12 bytes | Random per write                           |
| HMAC       | 32 bytes | Outer signature (Header + Tag + Ciphertext)|
| TAG        | 16 bytes | AES-GCM authentication tag                 |
| CIPHERTEXT | variable | AES-256-GCM encrypted JSON payload         |

### Security Properties

| Property | Implementation |
|---|---|
| Authenticated Encryption | AES-256-GCM (detects ciphertext tampering) |
| Wrong Password Rejection | Constant-time `crypto.timingSafeEqual` HMAC check |
| Key Stretching | Argon2id (memory-hard, GPU/ASIC resistant) |
| Memory Safety | Key buffers zeroed with `buf.fill(0)` after use |
| Atomic Writes | `.tmp` file + `fs.renameSync` (crash-safe) |
| Secret Leakage Prevention | API never returns raw secrets in responses |

### Known Limitations (Honest Disclosure)
- Node.js runs in V8 user-land — `mlock()` is unavailable; keys could theoretically be paged to disk by the OS
- V8 strings returned by `JSON.parse` are immutable and cannot be zeroed before GC collects them
- ZeroVault **does not** protect against: malware on the host, compromised OS, advanced memory dumps, or hardware keyloggers
- If your machine is fully compromised, no in-process secret manager can protect you

---

## 🖥️ CLI Reference

```bash
# Start the web UI server
node bin/zerovault.js serve [--port 3000]

# Generate credentials
node bin/zerovault.js generate password       # Secure random password
node bin/zerovault.js generate passphrase     # Diceware-style passphrase
node bin/zerovault.js generate key            # 256-bit Hex + Base64 key

# TOTP / 2FA
node bin/zerovault.js totp JBSWY3DPEHPK3PXP  # Generate current TOTP token

# Secret Scanner
node bin/zerovault.js scan "AKIAIOSFODNN7EXAMPLE"  # Scan text for secrets

# Password Auditor
node bin/zerovault.js audit "mysecretpassword"     # Get strength score + report

# File Protection
node bin/zerovault.js file inspect ./secrets.txt   # Check permissions
node bin/zerovault.js file secure  ./secrets.txt   # Lock to 0o600
node bin/zerovault.js file hash    ./secrets.txt   # SHA-256 digest
node bin/zerovault.js file shred   ./secrets.txt   # Multi-pass secure delete
```

---

## 🌐 REST API Reference

All endpoints served at `http://localhost:3000`.

### Vault
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/vault/status` | Check if vault is locked/unlocked |
| `POST` | `/api/vault/create` | Create a new vault file |
| `POST` | `/api/vault/unlock` | Unlock vault with master password |
| `POST` | `/api/vault/lock` | Lock vault and zero keys from memory |

### Secret Entries
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/entries` | List all entries (vault must be unlocked) |
| `POST` | `/api/entries` | Create a new secret entry |
| `GET` | `/api/entries/:id` | Get a specific entry |
| `PUT` | `/api/entries/:id` | Update an entry |
| `DELETE` | `/api/entries/:id` | Delete an entry |

### Generator
| Method | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/api/generator/password` | `{ length, symbols, ... }` | Generate password |
| `POST` | `/api/generator/passphrase` | `{ wordCount, separator }` | Generate passphrase |
| `POST` | `/api/generator/keys` | `{ byteLength }` | Generate hex + base64 key |

### Scanner
| Method | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/api/scanner/scan` | `{ text }` | Scan for exposed secrets |
| `POST` | `/api/scanner/redact` | `{ text }` | Auto-redact secrets in text |

### TOTP
| Method | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/api/totp/generate` | `{ secret }` | Generate current TOTP token |
| `POST` | `/api/totp/verify` | `{ token, secret }` | Verify a TOTP token |
| `POST` | `/api/totp/parse-uri` | `{ uri }` | Parse `otpauth://` URI |
| `POST` | `/api/totp/generate-uri` | `{ label, secret, issuer }` | Generate `otpauth://` URI |

### Audit
| Method | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/api/audit/password` | `{ password }` | Score a single password |
| `POST` | `/api/audit/vault` | `{ entries }` | Audit entire vault health |

### File Protection
| Method | Endpoint | Body | Description |
|---|---|---|---|
| `POST` | `/api/file/inspect` | `{ filePath }` | Inspect file permissions |
| `POST` | `/api/file/secure` | `{ filePath }` | Set permissions to `0o600` |
| `POST` | `/api/file/hash` | `{ filePath }` | SHA-256 hash of file |
| `POST` | `/api/file/shred` | `{ filePath }` | Multi-pass secure delete |

---

## 🧪 Testing

```bash
# Run all tests (Node.js built-in test runner)
npm test

# Verbose spec output
npm run test:verbose
```

Tests cover: vault encryption round-trips, TOTP generation & verification, scanner pattern matching, password audit scoring, and HTTP router logic.

---

## 🛠️ Scripts

```bash
npm start             # Start web server on port 3000
npm run cli           # Alias for the CLI entrypoint
npm test              # Run test suite
npm run test:verbose  # Run tests with spec reporter
```

---

## 🧱 Technology Stack

| Layer | Technology |
|---|---|
| Runtime | Node.js ≥ 25.0.0 |
| HTTP Server | `node:http` (no Express) |
| Cryptography | `node:crypto` (AES-GCM, HMAC, HKDF, Argon2id) |
| Frontend | Vanilla HTML5, CSS3, ES6 (no React, no build step) |
| Testing | `node:test` built-in test runner |
| **npm dependencies** | **0** |

---

## 👥 Team

Built for **[Zero Dependency | 72-Hour Hackathon]** — demonstrating that production-grade security tooling requires no third-party packages, only deep knowledge of cryptographic fundamentals and the Node.js standard library.

---

## 📄 License

MIT
