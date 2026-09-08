import test from 'node:test';
import assert from 'node:assert/strict';
import { createVault, unlockVault } from '../src/index.js';
import { VaultAuthError, VaultFormatError, VaultError } from '../src/index.js';
import { DEFAULT_PARAMS } from '../src/crypto/kdf.js';

// Speed up tests by lowering KDF cost
const TEST_PARAMS = { ...DEFAULT_PARAMS, passes: 1, memory: 1024 };

test('vault - create and unlock roundtrip', (t) => {
  const password = Buffer.from('my-master-password');
  const secrets = { api_key: 'sk_test_123', db_url: 'postgres://localhost' };

  const vault = createVault(password, secrets);
  assert.strictEqual(Buffer.isBuffer(vault), true);

  const unlocked = unlockVault(password, vault);
  assert.deepEqual(unlocked, secrets);
});

test('vault - throws VaultAuthError on wrong password', (t) => {
  const password = Buffer.from('password123');
  const vault = createVault(password, { secret: 'data' });

  assert.throws(() => {
    unlockVault(Buffer.from('wrong_password'), vault);
  }, VaultAuthError);
});

test('vault - throws VaultAuthError on tampered payload (HMAC mismatch)', (t) => {
  const password = Buffer.from('password123');
  const vault = createVault(password, { secret: 'data' });

  // Tamper with the last byte of ciphertext
  vault[vault.length - 1] ^= 1;

  assert.throws(() => {
    unlockVault(password, vault);
  }, VaultAuthError);
});

test('vault - throws VaultFormatError on malformed magic bytes', (t) => {
  const password = Buffer.from('password123');
  const vault = createVault(password, { secret: 'data' });

  // Tamper with MAGIC
  vault[0] = 0x00;

  assert.throws(() => {
    unlockVault(password, vault);
  }, VaultFormatError);
});

test('vault - input validation', (t) => {
  assert.throws(() => createVault(Buffer.from(''), {}), VaultError);
  assert.throws(() => createVault('not-buffer', {}), VaultError);
  assert.throws(() => unlockVault(Buffer.from(''), Buffer.alloc(10)), VaultError);
  assert.throws(() => unlockVault(Buffer.from('pass'), Buffer.alloc(10)), VaultFormatError); // Too small
});
