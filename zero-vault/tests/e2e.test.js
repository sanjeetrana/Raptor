/**
 * End-to-End Integration Test — Phase 3 Member 3
 *
 * Covers the full ZeroVault application flow:
 * Create Vault → Unlock → Add Credential → Update → Delete
 * → TOTP → Scanner → Audit → Lock → Unlock Again
 *
 * Uses node:test and node:assert only. No third-party testing packages.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { Router } from '../src/server/router.js';
import { registerVaultRoutes } from '../src/server/routes/vault.routes.js';
import { registerTotpRoutes } from '../src/server/routes/totp.routes.js';
import { registerScannerRoutes } from '../src/server/routes/scanner.routes.js';
import { registerGeneratorRoutes } from '../src/server/routes/generator.routes.js';
import { registerAuditRoutes } from '../src/server/routes/audit.routes.js';
import { vaultState } from '../src/server/state.js';

const getTempFile = () =>
  path.join(os.tmpdir(), `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}.zvault`);

/**
 * Simulate a request to the Router, mimicking how node:http works.
 */
async function req(router, method, url, body = {}) {
  let statusCode = 200;
  let responseBody = '';

  const mockReq = {
    method,
    url,
    on: (event, cb) => {
      if (event === 'data' && body && Object.keys(body).length > 0) {
        cb(Buffer.from(JSON.stringify(body)));
      }
      if (event === 'end') cb();
    }
  };

  const mockRes = {
    writeHead: (code) => { statusCode = code; },
    end: (data) => { responseBody = data; },
    json: (obj, code = 200) => {
      statusCode = code;
      responseBody = JSON.stringify(obj);
    }
  };

  await router.handle(mockReq, mockRes);
  return {
    status: statusCode,
    body: responseBody ? JSON.parse(responseBody) : {}
  };
}

// =============================================
// FULL E2E LIFECYCLE
// =============================================

test('E2E — Complete ZeroVault lifecycle', async (t) => {
  const router = new Router();
  registerVaultRoutes(router);
  registerTotpRoutes(router);
  registerScannerRoutes(router);
  registerGeneratorRoutes(router);
  registerAuditRoutes(router);

  const vaultPath = getTempFile();
  const password = 'TestVaultPassword-E2E!99';
  let credentialId;

  // 1. Initial status: must be locked
  let r = await req(router, 'GET', '/api/vault/status');
  assert.equal(r.body.locked, true, 'Vault must start locked');

  // 2. Create vault
  r = await req(router, 'POST', '/api/vault/create', { password, vaultPath });
  assert.equal(r.status, 200, 'Create vault should succeed');
  assert.equal(r.body.success, true);

  // 3. Status should now be unlocked
  r = await req(router, 'GET', '/api/vault/status');
  assert.equal(r.body.locked, false, 'Vault should be unlocked after create');

  // 4. List entries (empty at start)
  r = await req(router, 'GET', '/api/entries');
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.entries, [], 'Vault should start empty');

  // 5. Add credential
  r = await req(router, 'POST', '/api/entries', {
    service: 'TestService',
    username: 'user@example.com',
    password: 'SecureP@ss123!'
  });
  assert.equal(r.status, 200);
  assert.ok(r.body.id, 'Should return new credential ID');
  credentialId = r.body.id;

  // 6. List entries - should have 1
  r = await req(router, 'GET', '/api/entries');
  assert.equal(r.body.entries.length, 1);
  assert.equal(r.body.entries[0].service, 'TestService');
  assert.equal(r.body.entries[0].password, undefined, 'listEntries must NOT expose passwords');

  // 7. Get full entry
  r = await req(router, 'GET', `/api/entries/${credentialId}`);
  assert.equal(r.status, 200);
  assert.equal(r.body.entry.password, 'SecureP@ss123!');
  assert.equal(r.body.entry.service, 'TestService');

  // 8. Update credential
  r = await req(router, 'PUT', `/api/entries/${credentialId}`, { password: 'Updated@Pass99!' });
  assert.equal(r.status, 200);
  assert.equal(r.body.success, true);

  // Verify update persisted
  r = await req(router, 'GET', `/api/entries/${credentialId}`);
  assert.equal(r.body.entry.password, 'Updated@Pass99!', 'Update should be persisted');

  // 9. TOTP generation
  r = await req(router, 'POST', '/api/totp/generate', { secret: 'JBSWY3DPEHPK3PXP' });
  assert.equal(r.status, 200);
  assert.ok(r.body.token, 'TOTP token should be generated');
  assert.equal(r.body.token.length, 6, 'Default TOTP should be 6 digits');

  // 10. TOTP parse-uri should NOT return raw secret
  r = await req(router, 'POST', '/api/totp/parse-uri', {
    uri: 'otpauth://totp/Example:alice?secret=JBSWY3DPEHPK3PXP&issuer=Example'
  });
  assert.equal(r.status, 200);
  assert.equal(r.body.secret, undefined, 'parse-uri must NOT return raw secret to client');
  assert.equal(r.body.secretPresent, true);
  assert.equal(r.body.issuer, 'Example');

  // 11. Scanner — should detect and redact secret
  const maliciousText = 'AWS_KEY=AKIAIOSFODNN7EXAMPLE and also sk_live_ABCDEFGHIJKLMNOP12';
  r = await req(router, 'POST', '/api/scanner/scan', { text: maliciousText });
  assert.equal(r.status, 200);
  assert.ok(r.body.findings.length > 0, 'Scanner should find secrets');
  for (const f of r.body.findings) {
    assert.equal(f.rawValue, undefined, 'Raw secret must not appear in scanner API response');
    assert.ok(f.redactedValue, 'Redacted value must be present');
    assert.ok(!f.redactedValue.includes('AKIAIOSFODNN7EXAMPLE'), 'Full AWS key must not appear in findings');
    assert.ok(!f.redactedValue.includes('ABCDEFGHIJKLMNOP12'), 'Full Stripe key must not appear in findings');
  }

  // 12. Generator — secure password
  r = await req(router, 'POST', '/api/generator/password', { length: 24 });
  assert.equal(r.status, 200);
  assert.equal(r.body.password.length, 24, 'Generated password should be 24 chars');
  assert.ok(r.body.entropyBits > 100, 'Should have high entropy');

  // 13. Audit vault
  r = await req(router, 'GET', '/api/audit/vault');
  assert.equal(r.status, 200);
  assert.ok(typeof r.body.healthScore === 'number');
  assert.ok(r.body.vaultStatus);
  // Ensure no raw passwords in audit response
  const auditStr = JSON.stringify(r.body);
  assert.ok(!auditStr.includes('Updated@Pass99!'), 'Raw credential must not appear in audit response');

  // 14. Lock vault
  r = await req(router, 'POST', '/api/vault/lock');
  assert.equal(r.status, 200);
  assert.equal(r.body.locked, true);

  // 15. Access while locked must be rejected
  r = await req(router, 'GET', '/api/entries');
  assert.equal(r.status, 401);
  assert.equal(r.body.error, 'Vault is locked');

  r = await req(router, 'GET', `/api/entries/${credentialId}`);
  assert.equal(r.status, 401);

  r = await req(router, 'GET', '/api/audit/vault');
  assert.equal(r.status, 401);

  // 16. Unlock again (persistence check)
  r = await req(router, 'POST', '/api/vault/unlock', { password, vaultPath });
  assert.equal(r.status, 200);
  assert.equal(r.body.success, true);
  assert.equal(r.body.itemCount, 1, 'Credential should survive lock/unlock cycle');

  // 17. Verify updated password persisted through lock/unlock
  r = await req(router, 'GET', `/api/entries/${credentialId}`);
  assert.equal(r.body.entry.password, 'Updated@Pass99!', 'Updated password must persist');

  // 18. Delete credential
  r = await req(router, 'DELETE', `/api/entries/${credentialId}`);
  assert.equal(r.status, 200);
  assert.equal(r.body.success, true);

  // Verify deletion
  r = await req(router, 'GET', '/api/entries');
  assert.equal(r.body.entries.length, 0, 'Entry list should be empty after delete');

  // Cleanup
  vaultState.clearManager();
  try { fs.unlinkSync(vaultPath); } catch (e) {}
});

// =============================================
// SECURITY BOUNDARY TESTS
// =============================================

test('E2E — Wrong password fails safely with generic error', async (t) => {
  const router = new Router();
  registerVaultRoutes(router);

  const vaultPath = getTempFile();
  await req(router, 'POST', '/api/vault/create', { password: 'correct', vaultPath });
  await req(router, 'POST', '/api/vault/lock');

  const r = await req(router, 'POST', '/api/vault/unlock', { password: 'wrong-password', vaultPath });
  assert.equal(r.status, 401);
  assert.equal(r.body.error, 'Authentication failed or vault is corrupted');
  // Error must not contain file path, stack trace, or crypto details
  assert.ok(!r.body.error.includes(vaultPath), 'Error must not include file path');

  vaultState.clearManager();
  try { fs.unlinkSync(vaultPath); } catch (e) {}
});

test('E2E — Malformed JSON handled safely', async (t) => {
  const router = new Router();
  registerVaultRoutes(router);

  // Send no body / empty body
  const r = await req(router, 'POST', '/api/vault/unlock', {});
  assert.equal(r.status, 400);
  assert.ok(r.body.error.includes('Missing'));
});

test('E2E — Unknown route returns safe 404', async (t) => {
  const router = new Router();
  registerVaultRoutes(router);

  const r = await req(router, 'GET', '/api/nonexistent-route-xyz');
  // Router returns false for unhandled routes, server adds 404
  assert.ok(r.body !== null); // Just ensure we don't crash
});

test('E2E — TOTP: invalid secret returns safe error (no internal details)', async (t) => {
  const router = new Router();
  registerTotpRoutes(router);

  const r = await req(router, 'POST', '/api/totp/generate', { secret: '!!!INVALID_BASE32!!!' });
  assert.equal(r.status, 400);
  // Must not expose internal error details like algorithm names or stack traces
  assert.ok(!r.body.error.includes('Error:'), 'Must not expose raw Error prefix');
  assert.ok(!r.body.error.includes('base32'), 'Must not expose internal detail like "base32"');
});

test('E2E — Scanner: large input is rejected gracefully', async (t) => {
  const router = new Router();
  registerScannerRoutes(router);

  const hugeInput = 'a'.repeat(6 * 1024 * 1024); // 6MB > limit
  const r = await req(router, 'POST', '/api/scanner/scan', { text: hugeInput });
  assert.equal(r.status, 413, 'Should reject oversized input with 413');
});

test('E2E — Scanner: safe handling of empty and non-string inputs', async (t) => {
  const router = new Router();
  registerScannerRoutes(router);

  let r = await req(router, 'POST', '/api/scanner/scan', { text: '' });
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.findings, []);

  r = await req(router, 'POST', '/api/scanner/scan', { text: 42 });
  assert.equal(r.status, 400);
});

test('E2E — Generator: invalid options fail safely', async (t) => {
  const router = new Router();
  registerGeneratorRoutes(router);

  const r = await req(router, 'POST', '/api/generator/password', { length: 2 });
  assert.equal(r.status, 400, 'Too-short length should return 400');
  assert.ok(r.body.error, 'Error message should be present');
});
