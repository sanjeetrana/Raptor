import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { Router } from '../src/server/router.js';
import { registerVaultRoutes } from '../src/server/routes/vault.routes.js';
import { vaultState } from '../src/server/state.js';

const getTempFile = () => path.join(os.tmpdir(), `integration-${Date.now()}-${Math.random()}.zvault`);

// Helper to simulate a request to the Router
async function simulateRequest(router, method, url, body = {}) {
  let responseData = '';
  let statusCode = 200;

  const req = {
    method,
    url,
    on: (event, cb) => {
      if (event === 'data' && body && Object.keys(body).length > 0) {
        cb(Buffer.from(JSON.stringify(body)));
      }
      if (event === 'end') {
        cb();
      }
    }
  };
  
  const res = {
    writeHead: (code) => { statusCode = code; },
    end: (data) => { responseData = data; },
    json: (obj, code = 200) => {
      statusCode = code;
      responseData = JSON.stringify(obj);
    }
  };

  await router.handle(req, res);
  return { status: statusCode, body: responseData ? JSON.parse(responseData) : null };
}

test('API Integration - Complete Vault Lifecycle', async (t) => {
  const router = new Router();
  registerVaultRoutes(router);
  const vaultPath = getTempFile();
  const password = 'my-super-secret';
  let createdId = null;

  // 1. Check locked state initially
  let res = await simulateRequest(router, 'GET', '/api/vault/status');
  assert.equal(res.status, 200);
  assert.equal(res.body.locked, true);

  // 2. Access locked endpoints should fail safely
  res = await simulateRequest(router, 'GET', '/api/entries');
  assert.equal(res.status, 401);
  assert.equal(res.body.error, 'Vault is locked');

  // 3. Create vault
  res = await simulateRequest(router, 'POST', '/api/vault/create', { password, vaultPath });
  assert.equal(res.status, 200);
  assert.equal(res.body.success, true);
  
  // Status should be unlocked now
  res = await simulateRequest(router, 'GET', '/api/vault/status');
  assert.equal(res.body.locked, false);

  // 4. Add Credential
  res = await simulateRequest(router, 'POST', '/api/entries', { service: 'TestService', username: 'u1', password: 'p1' });
  assert.equal(res.status, 200);
  assert.equal(res.body.success, true);
  assert.ok(res.body.id);
  createdId = res.body.id;

  // 5. Read Credential
  res = await simulateRequest(router, 'GET', `/api/entries/${createdId}`);
  assert.equal(res.status, 200);
  assert.equal(res.body.entry.service, 'TestService');
  assert.equal(res.body.entry.password, 'p1');

  // 6. Update Credential
  res = await simulateRequest(router, 'PUT', `/api/entries/${createdId}`, { password: 'new-password' });
  assert.equal(res.status, 200);
  assert.equal(res.body.success, true);

  // 7. Lock Vault
  res = await simulateRequest(router, 'POST', '/api/vault/lock');
  assert.equal(res.status, 200);
  assert.equal(res.body.locked, true);

  // Status should be locked
  res = await simulateRequest(router, 'GET', '/api/vault/status');
  assert.equal(res.body.locked, true);

  // 8. Attempt access after lock (should be blocked)
  res = await simulateRequest(router, 'GET', `/api/entries/${createdId}`);
  assert.equal(res.status, 401);
  assert.equal(res.body.error, 'Vault is locked');

  // 9. Unlock Vault Again
  res = await simulateRequest(router, 'POST', '/api/vault/unlock', { password, vaultPath });
  assert.equal(res.status, 200);
  assert.equal(res.body.success, true);
  assert.equal(res.body.itemCount, 1);

  // 10. Delete Credential
  res = await simulateRequest(router, 'DELETE', `/api/entries/${createdId}`);
  assert.equal(res.status, 200);
  assert.equal(res.body.success, true);

  // Cleanup
  vaultState.clearManager();
  try { fs.unlinkSync(vaultPath); } catch (e) {}
});

test('API Integration - Fails safely on wrong password', async (t) => {
  const router = new Router();
  registerVaultRoutes(router);
  const vaultPath = getTempFile();

  // Create
  await simulateRequest(router, 'POST', '/api/vault/create', { password: 'correct', vaultPath });
  
  // Lock
  await simulateRequest(router, 'POST', '/api/vault/lock');
  
  // Unlock with wrong password
  const res = await simulateRequest(router, 'POST', '/api/vault/unlock', { password: 'wrong', vaultPath });
  assert.equal(res.status, 401);
  // Ensure error message is generic and doesn't leak secrets or paths
  assert.equal(res.body.error, 'Authentication failed or vault is corrupted');

  // Cleanup
  vaultState.clearManager();
  try { fs.unlinkSync(vaultPath); } catch (e) {}
});

test('API Integration - Graceful error on corrupted vault', async (t) => {
  const router = new Router();
  registerVaultRoutes(router);
  const vaultPath = getTempFile();

  // Write garbage
  fs.writeFileSync(vaultPath, Buffer.from('garbage data not a real vault'));

  // Unlock should fail gracefully without leaking stack trace
  const res = await simulateRequest(router, 'POST', '/api/vault/unlock', { password: 'any', vaultPath });
  assert.equal(res.status, 401);
  assert.equal(res.body.error, 'Authentication failed or vault is corrupted');

  try { fs.unlinkSync(vaultPath); } catch (e) {}
});
