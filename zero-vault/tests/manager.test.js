import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { VaultManager, VaultLockedError, VaultError } from '../src/index.js';

const getTempFile = () => path.join(os.tmpdir(), `test-vault-${Date.now()}-${Math.random()}.zvault`);

test('VaultManager - initialization and lifecycle', async (t) => {
  const filePath = getTempFile();
  const pwd = Buffer.from('my-master-password');
  
  const manager = new VaultManager(filePath);
  
  assert.strictEqual(manager.isUnlocked(), false);
  assert.throws(() => manager.listEntries(), VaultLockedError);

  // Initialize vault file
  await manager.initializeVault(pwd);
  assert.strictEqual(fs.existsSync(filePath), true, 'Vault file should exist after init');

  // Should still be locked after initialization
  assert.strictEqual(manager.isUnlocked(), false);

  // Unlock
  manager.unlock(pwd);
  assert.strictEqual(manager.isUnlocked(), true);

  // Lock
  manager.lock();
  assert.strictEqual(manager.isUnlocked(), false);
  assert.throws(() => manager.listEntries(), VaultLockedError);

  // Clean up
  fs.unlinkSync(filePath);
});

test('VaultManager - Credential CRUD operations', async (t) => {
  const filePath = getTempFile();
  const pwd = Buffer.from('test-password-123');
  const manager = new VaultManager(filePath);
  
  await manager.initializeVault(pwd);
  manager.unlock(pwd);

  // Create
  const id1 = manager.createEntry({
    service: 'github.com',
    username: 'user1',
    password: 'password123'
  });
  
  assert.strictEqual(typeof id1, 'string');

  // Read / List
  const list = manager.listEntries();
  assert.strictEqual(list.length, 1);
  assert.strictEqual(list[0].id, id1);
  assert.strictEqual(list[0].password, undefined, 'listEntries should omit passwords');

  const entry = manager.getEntry(id1);
  assert.strictEqual(entry.password, 'password123');

  // Update
  manager.updateEntry(id1, { password: 'new_password' });
  assert.strictEqual(manager.getEntry(id1).password, 'new_password');
  assert.strictEqual(manager.getEntry(id1).service, 'github.com', 'other fields remain untouched');

  // Lock and unlock to verify persistence
  manager.lock();
  const manager2 = new VaultManager(filePath);
  manager2.unlock(pwd);
  assert.strictEqual(manager2.listEntries().length, 1);
  assert.strictEqual(manager2.getEntry(id1).password, 'new_password', 'Updates were persisted to disk');

  // Delete
  manager2.deleteEntry(id1);
  assert.strictEqual(manager2.listEntries().length, 0);

  // Try fetching deleted
  assert.throws(() => manager2.getEntry(id1), VaultError);

  // Clean up
  fs.unlinkSync(filePath);
});

test('VaultManager - fails securely on invalid password', async (t) => {
  const filePath = getTempFile();
  const pwd = Buffer.from('correct-horse');
  const manager = new VaultManager(filePath);
  
  await manager.initializeVault(pwd);

  assert.throws(() => {
    manager.unlock(Buffer.from('wrong-battery'));
  }); // Should throw VaultAuthError but testing for general throw is fine
  
  assert.strictEqual(manager.isUnlocked(), false);
  
  fs.unlinkSync(filePath);
});
