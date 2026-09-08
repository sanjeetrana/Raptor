# Node.js Standard Library Usage

ZeroVault is strictly built with zero runtime dependencies. Below is the catalog of the Node.js standard library modules used in this project:

## `node:http`
- **Usage**: Local HTTP Server, request/response lifecycle.
- **Why**: Eliminates the need for Express/Fastify. Provides raw performance and complete control over the HTTP pipeline.

## `node:crypto`
- **Usage**: `createHmac`, `timingSafeEqual`, `randomBytes`, `createHash`, `pbkdf2Sync` / `argon2Sync` / `hkdfSync` (depending on platform support for KDFs), `createCipheriv`, `createDecipheriv`.
- **Why**: Core cryptographic primitives for AES-GCM encryption, HMAC authentication, TOTP generation, CSPRNG for passwords, and SHA256 hashing for file integrity.

## `node:fs`
- **Usage**: `readFileSync`, `writeFileSync`, `statSync`, `chmodSync`, `openSync`, `writeSync`, `fsyncSync`, `ftruncateSync`, `unlinkSync`, `renameSync`.
- **Why**: Required for reading/writing the `.zvault` file, serving static assets, inspecting permissions, and securely shredding files in multiple passes.

## `node:path`
- **Usage**: `join`, `normalize`, `extname`, `dirname`.
- **Why**: Safe path resolution to prevent directory traversal attacks in the static file server and secure file ops.

## `node:util`
- **Usage**: `parseArgs`.
- **Why**: Replaces `commander` or `yargs` for parsing CLI arguments securely and cleanly.

## `node:test` and `node:assert`
- **Usage**: `test`, `describe`, `it`, `strictEqual`, `throws`.
- **Why**: Replaces Jest/Mocha. Provides native, fast test running without any `node_modules` weight.
