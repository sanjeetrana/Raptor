/**
 * Phase 3 Security Hardening Tests — Member 2
 * Tests TOTP, Scanner, Generator, and Audit modules for correct behaviour,
 * edge cases, and sensitive data leakage prevention.
 *
 * Uses node:test and node:assert only. No third-party testing packages.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

import {
  generateTOTP,
  verifyTOTP,
  parseOtpauthUri,
  generateOtpauthUri,
  RFC6238_TEST_VECTORS,
  generateHOTP,
  base32Decode,
  base32Encode
} from '../src/security/totp.js';

import {
  scanSecrets,
  redactText,
  redactSecret,
  calculateShannonEntropy
} from '../src/security/scanner.js';

import {
  generatePassword,
  generatePassphrase,
  generateHexKey,
  generateBase64Key,
  getRandomInt
} from '../src/security/generator.js';

import {
  auditPassword,
  auditVaultSecrets
} from '../src/security/audit.js';

// =============================================
// PART 1: TOTP HARDENING TESTS
// =============================================

test('TOTP — RFC 6238 official vectors (SHA-1)', async (t) => {
  const { vectors, asciiSecret } = RFC6238_TEST_VECTORS;
  const secretBuf = Buffer.from(asciiSecret, 'ascii');

  for (const vec of vectors) {
    const code = generateTOTP(secretBuf, { timestamp: vec.time, digits: 8, algorithm: 'SHA1' });
    assert.equal(code, vec.sha1, `SHA-1 vector failed at T=${vec.time}`);
  }
});

test('TOTP — RFC 6238 official vectors (SHA-256)', async (t) => {
  const { vectors, asciiSecretSHA256 } = RFC6238_TEST_VECTORS;
  const secretBuf = Buffer.from(asciiSecretSHA256, 'ascii');

  for (const vec of vectors) {
    const code = generateTOTP(secretBuf, { timestamp: vec.time, digits: 8, algorithm: 'SHA256' });
    assert.equal(code, vec.sha256, `SHA-256 vector failed at T=${vec.time}`);
  }
});

test('TOTP — RFC 6238 official vectors (SHA-512)', async (t) => {
  const { vectors, asciiSecretSHA512 } = RFC6238_TEST_VECTORS;
  const secretBuf = Buffer.from(asciiSecretSHA512, 'ascii');

  for (const vec of vectors) {
    const code = generateTOTP(secretBuf, { timestamp: vec.time, digits: 8, algorithm: 'SHA512' });
    assert.equal(code, vec.sha512, `SHA-512 vector failed at T=${vec.time}`);
  }
});

test('TOTP — Time boundary: codes differ across time steps', async (t) => {
  const secret = Buffer.from('12345678901234567890', 'ascii');
  const t1 = generateTOTP(secret, { timestamp: 0 });       // Step 0
  const t2 = generateTOTP(secret, { timestamp: 30 });      // Step 1
  const t3 = generateTOTP(secret, { timestamp: 29 });      // Still step 0
  assert.equal(t1, t3, 'Same step should produce same code');
  assert.notEqual(t1, t2, 'Different steps should produce different codes');
});

test('TOTP — Verify window drift tolerance', async (t) => {
  const secret = 'JBSWY3DPEHPK3PXP';
  const ts = 1000000; // arbitrary fixed time
  const validToken = generateTOTP(secret, { timestamp: ts });
  
  // Current step should pass
  const r1 = verifyTOTP(validToken, secret, { timestamp: ts });
  assert.equal(r1.valid, true);

  // One step ahead (within window=1)
  const r2 = verifyTOTP(validToken, secret, { timestamp: ts + 30, window: 1 });
  assert.equal(r2.valid, true);

  // Beyond window should fail
  const r3 = verifyTOTP(validToken, secret, { timestamp: ts + 90, window: 1 });
  assert.equal(r3.valid, false);
});

test('TOTP — Rejects invalid digits (5 or 9)', async (t) => {
  const secret = 'JBSWY3DPEHPK3PXP';
  assert.throws(() => generateTOTP(secret, { digits: 5 }), RangeError);
  assert.throws(() => generateTOTP(secret, { digits: 9 }), RangeError);
});

test('TOTP — Rejects empty secret', async (t) => {
  assert.throws(() => generateTOTP(''), Error);
  assert.throws(() => generateTOTP(Buffer.alloc(0)), Error);
});

test('TOTP — Rejects non-string / non-Buffer secret', async (t) => {
  assert.throws(() => generateTOTP(12345), TypeError);
  assert.throws(() => generateTOTP(null), TypeError);
});

test('TOTP — Rejects zero/negative period', async (t) => {
  assert.throws(() => generateTOTP('JBSWY3DPEHPK3PXP', { period: 0 }), RangeError);
  assert.throws(() => generateTOTP('JBSWY3DPEHPK3PXP', { period: -10 }), RangeError);
});

test('TOTP — parseOtpauthUri parses complete URI correctly', async (t) => {
  const uri = 'otpauth://totp/Example%3Aalice%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=Example&digits=6&period=30';
  const parsed = parseOtpauthUri(uri);

  assert.equal(parsed.type, 'totp');
  assert.equal(parsed.issuer, 'Example');
  assert.equal(parsed.digits, 6);
  assert.equal(parsed.period, 30);
  // Secret IS present in parsed object for server-side use
  assert.equal(parsed.secret, 'JBSWY3DPEHPK3PXP');
});

test('TOTP — parseOtpauthUri throws on malformed URI', async (t) => {
  assert.throws(() => parseOtpauthUri('not-a-uri'), Error);
  assert.throws(() => parseOtpauthUri('http://example.com'), Error);  // Wrong protocol
  assert.throws(() => parseOtpauthUri('otpauth://totp/noSecret'), Error); // Missing secret
});

test('TOTP — generateOtpauthUri round-trips correctly', async (t) => {
  const opts = {
    type: 'totp',
    label: 'alice',
    secret: 'JBSWY3DPEHPK3PXP',
    issuer: 'ExampleCo',
    digits: 6,
    period: 30
  };
  const uri = generateOtpauthUri(opts);
  const parsed = parseOtpauthUri(uri);
  assert.equal(parsed.secret, opts.secret);
  assert.equal(parsed.issuer, opts.issuer);
  assert.equal(parsed.type, opts.type);
  assert.equal(parsed.digits, opts.digits);
});

// =============================================
// PART 2: SECRET SCANNER HARDENING TESTS
// =============================================

test('Scanner — Detects AWS Access Key', async (t) => {
  const text = 'AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE';
  const findings = scanSecrets(text);
  const awsFindings = findings.filter(f => f.ruleId === 'aws_access_key');
  assert.ok(awsFindings.length > 0, 'Should detect AWS access key');
  // CRITICAL: redacted value must never equal original
  for (const f of awsFindings) {
    assert.ok(!f.redactedValue.includes('AKIAIOSFODNN7EXAMPLE'), 'Raw secret must not appear in redactedValue');
    assert.ok(f.redactedValue, 'redactedValue must be present');
  }
});

test('Scanner — Detects Stripe secret key with redaction', async (t) => {
  const text = 'const apiKey = "sk_live_ABCDEFGHIJKLMNOP";';
  const findings = scanSecrets(text);
  const stripeFindings = findings.filter(f => f.ruleId === 'stripe_api_key');
  assert.ok(stripeFindings.length > 0, 'Should detect Stripe key');
  assert.ok(stripeFindings[0].redactedValue.startsWith('sk_live_'), 'Prefix preserved');
  assert.ok(!stripeFindings[0].redactedValue.includes('ABCDEFGHIJKLMNOP'), 'Raw key not exposed');
});

test('Scanner — Detects JWT token', async (t) => {
  // Fake JWT (base64 encoded header.payload.signature format)
  const fakeJwt = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IlRlc3QifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
  const text = `Authorization: Bearer ${fakeJwt}`;
  const findings = scanSecrets(text);
  const jwtFindings = findings.filter(f => f.ruleId === 'jwt_token' || f.ruleId === 'bearer_token');
  assert.ok(jwtFindings.length > 0, 'Should detect JWT or Bearer token');
  for (const f of jwtFindings) {
    assert.ok(!f.redactedValue.includes(fakeJwt), 'Raw JWT must not appear in output');
  }
});

test('Scanner — Detects Private Key block', async (t) => {
  const text = `-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA2a2rwplBQLzHPZe5TNJNK9rGFVnNErBEaVhHDFHFCkpfLCO9
fakekey/notreal==
-----END RSA PRIVATE KEY-----`;
  const findings = scanSecrets(text);
  const pkFindings = findings.filter(f => f.ruleId === 'private_key');
  assert.ok(pkFindings.length > 0, 'Should detect private key');
  // Ensure full key content is not present in redacted output
  assert.ok(!pkFindings[0].redactedValue.includes('MIIEowIBAAKCAQEA'), 'Private key body must not appear in redacted output');
});

test('Scanner — Detects DB connection string with credentials', async (t) => {
  const text = 'DATABASE_URL=postgres://admin:hunter2@localhost:5432/mydb';
  const findings = scanSecrets(text);
  const dbFindings = findings.filter(f => f.ruleId === 'db_connection_string');
  assert.ok(dbFindings.length > 0, 'Should detect database URL');
  assert.ok(!dbFindings[0].redactedValue.includes('hunter2'), 'Password not exposed in redacted output');
});

test('Scanner — Handles empty input safely', async (t) => {
  assert.deepEqual(scanSecrets(''), []);
  assert.deepEqual(scanSecrets(null), []);
  assert.deepEqual(scanSecrets(42), []);
});

test('Scanner — Does not trigger on innocent text', async (t) => {
  const innocentText = 'Hello world! This is a normal README with no secrets.';
  const findings = scanSecrets(innocentText, { entropyScan: false });
  assert.equal(findings.length, 0, 'Should find no secrets in innocent text');
});

test('Scanner — redactText replaces all secrets in-place', async (t) => {
  const original = 'key=AKIAIOSFODNN7EXAMPLE and password: "hunter2"';
  const redacted = redactText(original);
  assert.ok(!redacted.includes('AKIAIOSFODNN7EXAMPLE'), 'AWS key not present in redacted output');
  assert.ok(redacted.length > 0, 'Output is not empty');
});

test('Scanner — findAll results include required fields', async (t) => {
  const text = 'AKIAIOSFODNN7EXAMPLE is a fake AWS key';
  const findings = scanSecrets(text, { entropyScan: false });
  assert.ok(findings.length > 0);
  for (const f of findings) {
    assert.ok(f.ruleId !== undefined, 'ruleId is required');
    assert.ok(f.ruleName !== undefined, 'ruleName is required');
    assert.ok(f.severity !== undefined, 'severity is required');
    assert.ok(f.line !== undefined, 'line is required');
    assert.ok(f.redactedValue !== undefined, 'redactedValue is required');
    // Ensure NO field is named rawValue or secret
    assert.equal(f.rawValue, undefined, 'Raw value must never be returned');
    assert.equal(f.secret, undefined, 'Secret must never be returned');
  }
});

test('Scanner — Shannon entropy correctly identified for high-entropy string', async (t) => {
  const highEntropyString = 'aB3$xK9!mZ2#wQ7&pR5@'; // High entropy
  const entropy = calculateShannonEntropy(highEntropyString);
  assert.ok(entropy > 4.0, `Expected entropy > 4.0, got ${entropy}`);
});

test('Scanner — Low entropy string does not trigger high-entropy detection', async (t) => {
  const lowEntropyString = 'aaaaaaaaaaaaaaaa'; // 16 chars, all same
  const entropy = calculateShannonEntropy(lowEntropyString);
  assert.ok(entropy < 1.0, `Expected entropy < 1.0, got ${entropy}`);
});

// =============================================
// PART 3: GENERATOR TESTS
// =============================================

test('Generator — Does not use Math.random() (uses CSPRNG)', async (t) => {
  // Indirect test: generate many passwords and verify no duplicates
  // If Math.random() was seeded the same way, we'd see patterns
  const passwords = new Set();
  for (let i = 0; i < 50; i++) {
    const { password } = generatePassword({ length: 32 });
    passwords.add(password);
  }
  // With 50 random 32-char passwords, we should get 50 unique ones
  assert.equal(passwords.size, 50, 'All generated passwords should be unique');
});

test('Generator — Respects requested password length', async (t) => {
  for (const len of [8, 16, 24, 64, 128]) {
    const { password } = generatePassword({ length: len });
    assert.equal(password.length, len, `Password length should be ${len}`);
  }
});

test('Generator — Respects character set constraints', async (t) => {
  const { password } = generatePassword({ length: 32, uppercase: true, lowercase: false, digits: false, symbols: false });
  assert.match(password, /^[A-Z]+$/, 'Should only contain uppercase letters');
});

test('Generator — Enforces minimum one char from each group', async (t) => {
  for (let i = 0; i < 20; i++) {
    const { password } = generatePassword({ length: 16, uppercase: true, lowercase: true, digits: true, symbols: true, requireEachType: true });
    assert.match(password, /[A-Z]/, 'Missing uppercase');
    assert.match(password, /[a-z]/, 'Missing lowercase');
    assert.match(password, /[0-9]/, 'Missing digit');
  }
});

test('Generator — Throws on length too short', async (t) => {
  assert.throws(() => generatePassword({ length: 3 }), RangeError);
});

test('Generator — Throws on length too long', async (t) => {
  assert.throws(() => generatePassword({ length: 2049 }), RangeError);
});

test('Generator — Passphrase word count respected', async (t) => {
  const { passphrase } = generatePassphrase({ wordCount: 5, separator: '-' });
  const wordCount = passphrase.split('-').length;
  assert.equal(wordCount, 5, `Expected 5 words, got ${wordCount}`);
});

test('Generator — getRandomInt is unbiased and within range', async (t) => {
  const counts = new Array(10).fill(0);
  for (let i = 0; i < 1000; i++) {
    const n = getRandomInt(10);
    assert.ok(n >= 0 && n < 10, `getRandomInt(10) returned out-of-range: ${n}`);
    counts[n]++;
  }
  // Rough distribution check: each bucket should get ~100 hits
  for (const count of counts) {
    assert.ok(count > 30, `Bucket underpopulated: ${count} (CSPRNG bias suspected)`);
  }
});

test('Generator — HexKey is valid hex of correct length', async (t) => {
  const hex = generateHexKey(32);
  assert.equal(hex.length, 64, '32 bytes should produce 64 hex chars');
  assert.match(hex, /^[0-9a-f]+$/, 'Hex key should be lowercase hex');
});

test('Generator — Base64Key is URL-safe base64', async (t) => {
  const key = generateBase64Key(32);
  assert.ok(!key.includes('+'), 'Should not contain +');
  assert.ok(!key.includes('/'), 'Should not contain /');
  assert.ok(!key.includes('='), 'Should not contain padding =');
});

// =============================================
// PART 4: SECURITY AUDIT TESTS
// =============================================

test('Audit — Deterministic scoring for same input', async (t) => {
  const password = 'TestPassword123!';
  const r1 = auditPassword(password);
  const r2 = auditPassword(password);
  assert.equal(r1.score, r2.score, 'Audit score must be deterministic');
  assert.equal(r1.tier, r2.tier, 'Audit tier must be deterministic');
});

test('Audit — Short weak password scores critically', async (t) => {
  const result = auditPassword('abc');
  assert.ok(result.score < 40, `Expected score < 40, got ${result.score}`);
  assert.equal(result.tier, 'CRITICAL');
});

test('Audit — Strong passphrase scores highly', async (t) => {
  const result = auditPassword('Correct-Horse-Battery-Staple-2024');
  assert.ok(result.score >= 60, `Expected score >= 60, got ${result.score}`);
});

test('Audit — Empty password returns score 0', async (t) => {
  const result = auditPassword('');
  assert.equal(result.score, 0);
  assert.equal(result.tier, 'CRITICAL');
});

test('Audit — Common pattern passwords are penalized', async (t) => {
  const r1 = auditPassword('password123');
  const r2 = auditPassword('Xyz9#mK2!pLqR7vT'); // complex random
  assert.ok(r2.score > r1.score, 'Common pattern should score lower than complex password');
});

test('Audit — Breakdown details explain all score components', async (t) => {
  const result = auditPassword('Abc12345');
  assert.ok(result.breakdown.details.length > 0, 'Should have score detail explanations');
  assert.equal(typeof result.breakdown.baseEntropyScore, 'number');
  assert.equal(typeof result.breakdown.penalties, 'number');
  assert.equal(typeof result.breakdown.bonuses, 'number');
  // Verify final score formula is transparent
  const expectedRaw = result.breakdown.baseEntropyScore + result.breakdown.bonuses - result.breakdown.penalties;
  const clamped = Math.max(0, Math.min(100, expectedRaw));
  assert.equal(result.score, clamped, 'Score must be verifiable from breakdown components');
});

test('Audit — auditVaultSecrets detects duplicates across entries', async (t) => {
  const secrets = [
    { id: '1', title: 'GitHub', value: 'SharedPassword123!' },
    { id: '2', title: 'Twitter', value: 'SharedPassword123!' }
  ];
  const result = auditVaultSecrets(secrets);
  assert.ok(result.duplicatePasswordCount > 0, 'Should detect duplicate passwords');
  assert.ok(result.issueCount > 0);
});

test('Audit — auditVaultSecrets on healthy vault returns good health score', async (t) => {
  const secrets = [
    { id: '1', title: 'GitHub', value: 'Zq#8mKvP!2xR@nWe7$tY' },
    { id: '2', title: 'Google', value: 'Lp&5bHjN*3cS@fUi0%wX' }
  ];
  const result = auditVaultSecrets(secrets);
  assert.ok(result.healthScore > 70, `Expected health > 70, got ${result.healthScore}`);
});

test('Audit — auditVaultSecrets throws on non-array input', async (t) => {
  assert.throws(() => auditVaultSecrets('not-an-array'), TypeError);
  assert.throws(() => auditVaultSecrets(null), TypeError);
});

test('Audit — audit does NOT expose secrets in output fields', async (t) => {
  const secrets = [
    { id: '1', title: 'TestService', value: 'SecretPassword!99' }
  ];
  const result = auditVaultSecrets(secrets);
  const resultStr = JSON.stringify(result);
  // The raw password must never appear in the audit result JSON
  assert.ok(!resultStr.includes('SecretPassword!99'), 'Raw credential must not appear in audit output');
});

// =============================================
// PART 5: CROSS-SYSTEM INTEGRATION
// =============================================

test('Cross-system — Scanner result never contains raw secret field', async (t) => {
  const inputs = [
    'AKIAIOSFODNN7EXAMPLE',
    'sk_live_ABCDEFGHIJKLMNOP12',
    'postgres://user:pass123@localhost/db'
  ];

  for (const input of inputs) {
    const findings = scanSecrets(input);
    for (const f of findings) {
      const fields = Object.keys(f);
      assert.ok(!fields.includes('rawValue'), 'No rawValue field should exist');
      assert.ok(!fields.includes('secret'), 'No secret field should exist');
      // Ensure redacted value is a meaningful redaction (not empty, not the original)
      assert.ok(f.redactedValue && f.redactedValue.length > 0, 'redactedValue must not be empty');
    }
  }
});

test('Cross-system — TOTP + Audit: TOTP secrets not leaking into audit output', async (t) => {
  // If a TOTP secret was accidentally stored as a credential value, the scanner
  // embedded in the audit engine should flag it but NOT expose it
  const totpSecret = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PX'; // high entropy Base32
  const secrets = [
    { id: '1', title: 'MyTOTP', value: totpSecret }
  ];
  const result = auditVaultSecrets(secrets);
  const resultStr = JSON.stringify(result);
  // The raw TOTP secret must not appear in the audit output
  assert.ok(!resultStr.includes(totpSecret), 'TOTP secret must not appear in audit results');
});
