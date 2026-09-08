# Member 3: ZeroVault Core Integration API

This document details the public API contract for the Phase 2 `VaultManager`. This class manages the vault file persistence atomically, handles the locked/unlocked state, and manages Credential CRUD securely.

You do not need to understand the underlying cryptography (Argon2id, HKDF, AES-GCM). The `VaultManager` abstracts it completely.

## Import
```javascript
import { VaultManager, VaultLockedError, VaultAuthError, VaultFormatError } from './src/index.js';
```

## Lifecycle API

### `new VaultManager(filePath)`
Instantiates a vault manager pointing to a specific file. Does not read or write anything immediately.
- `filePath`: Absolute or relative path to the `.zvault` file.

### `await manager.initializeVault(password)`
Creates a completely new, empty vault on disk. **Will overwrite existing files.**
- `password`: `Buffer` — The master password.

### `manager.unlock(password)`
Unlocks the vault by reading it from disk and decrypting it into memory. Throws `VaultAuthError` on wrong password or if the file was tampered with.
- `password`: `Buffer` — The master password.

### `manager.lock()`
Secures the vault. Destroys the decrypted credentials in memory and explicitly zero-fills the master password buffer in memory. After this is called, any CRUD operation will throw a `VaultLockedError`.

### `manager.isUnlocked()`
Returns `true` if the vault is unlocked, `false` otherwise.

## Credential CRUD API

> **Note on Persistence**: All modifying operations (`createEntry`, `updateEntry`, `deleteEntry`) automatically and atomically write the updated encrypted vault back to disk. If the write fails, the previous vault file on disk is untouched, though the operation will throw an error.

### `manager.createEntry(data)`
Adds a new credential to the vault.
- `data`: Object containing `service` (required string), `username` (optional), `password` (optional), `notes` (optional).
- **Returns**: `String` (UUID of the new credential)

### `manager.listEntries()`
Lists all credentials in the vault.
- **Returns**: Array of summary objects: `[{ id, service, username, updatedAt }, ...]` (Note: `password` and `notes` are omitted for safety in listing).

### `manager.getEntry(id)`
Gets the full credential object, including passwords and notes.
- `id`: String UUID.
- **Returns**: Object (deep copy of the credential).

### `manager.updateEntry(id, updates)`
Updates fields on an existing credential.
- `id`: String UUID.
- `updates`: Object containing any of `service`, `username`, `password`, `notes`.

### `manager.deleteEntry(id)`
Deletes a credential permanently.
- `id`: String UUID.
