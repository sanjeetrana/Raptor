import test from 'node:test';
import assert from 'node:assert/strict';
import { generateSalt, generateIV } from '../src/crypto/random.js';
import { deriveKey, DEFAULT_PARAMS } from '../src/crypto/kdf.js';
import { encrypt, decrypt } from '../src/crypto/aead.js';

test('random - generateSalt', (t) => {
  const salt = generateSalt();
  assert.strictEqual(Buffer.isBuffer(salt), true);
  assert.strictEqual(salt.length, 32);

  const custom = generateSalt(16);
  assert.strictEqual(custom.length, 16);

  assert.throws(() => generateSalt(15), RangeError);
  assert.throws(() => generateSalt('32'), RangeError);
});

test('random - generateIV', (t) => {
  const iv = generateIV();
  assert.strictEqual(Buffer.isBuffer(iv), true);
  assert.strictEqual(iv.length, 12);

  assert.throws(() => generateIV(11), RangeError);
});

test('kdf - deriveKey derives different keys for enc and mac', (t) => {
  const password = Buffer.from('test-password');
  const salt = generateSalt();
  
  const { encKey, macKey } = deriveKey(password, salt, { ...DEFAULT_PARAMS, passes: 1, memory: 1024 });
  
  assert.strictEqual(encKey.length, 32);
  assert.strictEqual(macKey.length, 32);
  assert.notDeepEqual(encKey, macKey, 'encKey and macKey must be domain separated');

  // Ensure password is zeroed
  assert.deepEqual(password, Buffer.from('test-password'), 'Original password buffer should NOT be zeroed by deriveKey');
});

test('aead - encrypt and decrypt roundtrip', (t) => {
  const key = generateSalt(32); // reuse random for key
  const iv = generateIV();
  const plaintext = Buffer.from('secret data');
  const aad = Buffer.from('header data');

  const { ciphertext, tag } = encrypt(key, iv, plaintext, aad);
  
  assert.strictEqual(tag.length, 16);
  assert.notDeepEqual(ciphertext, plaintext);

  const decrypted = decrypt(key, iv, ciphertext, tag, aad);
  assert.deepEqual(decrypted, plaintext);
});

test('aead - decrypt throws on wrong aad', (t) => {
  const key = generateSalt(32);
  const iv = generateIV();
  const plaintext = Buffer.from('secret data');
  const aad = Buffer.from('header data');

  const { ciphertext, tag } = encrypt(key, iv, plaintext, aad);
  
  const wrongAad = Buffer.from('tampered header data');
  assert.throws(() => {
    decrypt(key, iv, ciphertext, tag, wrongAad);
  });
});
