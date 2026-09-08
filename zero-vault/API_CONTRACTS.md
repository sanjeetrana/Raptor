# ZeroVault API Contracts & Integration Boundaries

This document outlines the API contracts designed by Member 3 for integration with the core Crypto/Vault Engine (Member 1) and Security Utilities (Member 2).

## 1. Vault Data Structures

The vault decrypts to a JSON payload matching this structure:

```typescript
interface VaultPayload {
  items: VaultSecretItem[];
}

interface VaultSecretItem {
  id: string; // UUID
  title: string;
  type: 'LOGIN' | 'SECURE_NOTE' | 'API_KEY' | 'CREDIT_CARD';
  
  // Login Type
  username?: string;
  value?: string; // Main password or secret key
  url?: string;
  totpSecret?: string; // Base32
  
  // Secure Note Type
  notes?: string;
  
  // Credit Card Type
  cardNumber?: string;
  cardExpiry?: string;
  cardCvv?: string;
}
```

## 2. Server API Endpoints

The `node:http` local server exposes the following REST API over JSON to the Vanilla Frontend.

### Vault
- `GET /api/vault/status`: `{ locked: boolean, vaultPath: string | null }`
- `POST /api/vault/create`: Request `{ password, vaultPath }`
- `POST /api/vault/unlock`: Request `{ password, vaultPath }`
- `POST /api/vault/lock`
- `GET /api/vault/items`: Response `{ items: VaultSecretItem[] }`
- `POST /api/vault/save`: Request `{ password, items: VaultSecretItem[] }`

### Security Utilities
- `POST /api/generator/password`: Request `{ length, uppercase, lowercase, digits, symbols, avoidAmbiguous }` -> Response `{ password, entropyBits, poolSize }`
- `POST /api/generator/passphrase`: Request `{ wordCount, separator, capitalize, includeNumber }` -> Response `{ passphrase, entropyBits }`
- `POST /api/totp/generate`: Request `{ secret, options? }` -> Response `{ token }`
- `POST /api/scanner/scan`: Request `{ text }` -> Response `{ findings: SecretScanResult[] }`
- `POST /api/audit/password`: Request `{ password }` -> Response `PasswordAuditResult`
- `POST /api/audit/vault`: Response `{ healthScore, vaultStatus, itemsAudited, issues }`
- `POST /api/file/permissions`: Request `{ filePath }` -> Response `{ secure, modeOctal }`
