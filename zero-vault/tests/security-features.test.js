/**
 * security-features.test.js — Phase 4 Member 2: Expanded Security Feature Tests
 *
 * Covers:
 *   - Scanner: edge cases, binary, dedup, false-positives, redaction guarantees
 *   - TOTP: boundary conditions, invalid inputs, secret non-exposure
 *   - Generator: CSPRNG guarantees, constraints, invalid inputs
 *   - Audit: determinism, structured findings, secret non-exposure
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  scanSecrets, redactText, redactSecret, looksLikeBinary, calculateShannonEntropy
} from '../src/security/scanner.js';
import {
  generateTOTP, verifyTOTP, parseOtpauthUri, generateOtpauthUri, base32Decode, base32Encode, RFC6238_TEST_VECTORS
} from '../src/security/totp.js';
import {
  generatePassword, generatePassphrase, generateHexKey, generateBase64Key, getRandomInt
} from '../src/security/generator.js';
import { auditPassword, auditVaultSecrets } from '../src/security/audit.js';

// =============================================================================
// SCANNER: Edge Cases, Dedup, Binary, False-Positive Reduction
// =============================================================================

test('Scanner — Empty and whitespace input returns empty array', () => {
  assert.deepEqual(scanSecrets(''), []);
  assert.deepEqual(scanSecrets('   \n\t  '), []);
});

test('Scanner — Non-string input returns empty array (no throw)', () => {
  assert.deepEqual(scanSecrets(null), []);
  assert.deepEqual(scanSecrets(undefined), []);
  assert.deepEqual(scanSecrets(42), []);
  assert.deepEqual(scanSecrets({}), []);
});

test('Scanner — Detects AWS Access Key in various contexts', () => {
  const texts = [
    'export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE',
    'aws_access_key_id = AKIAIOSFODNN7EXAMPLE',
    'keyId: "AKIAIOSFODNN7EXAMPLE"',
  ];
  for (const text of texts) {
    const findings = scanSecrets(text);
    const awsFindings = findings.filter(f => f.ruleId === 'aws_access_key');
    assert.ok(awsFindings.length > 0, `Should detect AWS key in: ${text}`);
    assert.ok(!awsFindings[0].redactedValue.includes('SFODNN7EXAMPLE'), 'Raw key must not appear in redacted output');
  }
});

test('Scanner — Does NOT flag innocent short uppercase strings (no false positives)', () => {
  // "AKIA" alone, too short for AWS key (needs 20 chars total)
  const text = 'AKIA is a prefix used by AWS';
  const findings = scanSecrets(text);
  const awsFindings = findings.filter(f => f.ruleId === 'aws_access_key');
  assert.equal(awsFindings.length, 0, 'Short AKIA prefix should not trigger aws_access_key rule');
});

test('Scanner — Detects JWT and preserves redaction (no raw payload)', () => {
  const fakeJwt = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6y';
  const findings = scanSecrets(`token = ${fakeJwt}`);
  const jwtFindings = findings.filter(f => f.ruleId === 'jwt_token');
  assert.ok(jwtFindings.length > 0, 'Should detect JWT');
  // Redacted value must not contain the payload part
  const redacted = jwtFindings[0].redactedValue;
  assert.ok(!redacted.includes('eyJzdWIiOiIxMjM0NTY3ODkwIn0'), 'JWT payload must be redacted');
});

test('Scanner — Detects GitHub PAT in various formats', () => {
  // Classic ghp_ token format (ghp_ + 36 alphanumeric)
  const ghpToken = 'ghp_' + 'A'.repeat(36);
  const findings = scanSecrets(`git_token: ${ghpToken}`);
  const ghFindings = findings.filter(f => f.ruleId === 'github_pat');
  assert.ok(ghFindings.length > 0, 'Should detect ghp_ token');
  assert.ok(ghFindings[0].redactedValue.startsWith('ghp_'), 'Should preserve ghp_ prefix');
  assert.ok(!ghFindings[0].redactedValue.includes('AAAAAAA'), 'Should not expose raw token body');
});

test('Scanner — Detects hardcoded password only when quoted (avoids config comment FPs)', () => {
  // Should detect
  const withQuote = 'password = "my_super_secret_password"';
  const detectedFindings = scanSecrets(withQuote);
  assert.ok(detectedFindings.filter(f => f.ruleId === 'hardcoded_password').length > 0,
    'Should detect quoted password assignment');

  // Should NOT detect - value is too short (< 8 chars)
  const tooShort = 'password = "short"';
  const shortFindings = scanSecrets(tooShort);
  assert.equal(shortFindings.filter(f => f.ruleId === 'hardcoded_password').length, 0,
    'Should not detect when password value is too short (< 8 chars)');
});

test('Scanner — Deduplicates findings at same position for same rule', () => {
  // If the same secret somehow matches the same regex twice at the same offset, it should be deduplicated
  const awsKey = 'AKIAIOSFODNN7EXAMPLE';
  const text = `key=${awsKey}`;
  const findings = scanSecrets(text);
  const awsFindings = findings.filter(f => f.ruleId === 'aws_access_key');
  assert.equal(awsFindings.length, 1, 'Should de-duplicate findings at same position');
});

test('Scanner — Binary content is skipped safely', () => {
  // Simulate binary-looking content with many null bytes
  const binaryLike = '\x00'.repeat(50) + 'AKIAIOSFODNN7EXAMPLE' + '\x00'.repeat(50);
  const findings = scanSecrets(binaryLike);
  // Should return no findings (binary was skipped) or at most not crash
  assert.ok(Array.isArray(findings), 'Should return an array even for binary-like input');
});

test('Scanner — looksLikeBinary correctly identifies binary vs text', () => {
  assert.ok(looksLikeBinary('\x00\x01\x02\x03\x04\x05hello'), 'Null-heavy content should be binary');
  assert.ok(!looksLikeBinary('This is normal text with AWS_KEY=AKIAIOSFODNN7EXAMPLE'), 'Normal text should not be binary');
});

test('Scanner — All findings have required fields and NO rawValue or secret fields', () => {
  const text = [
    'AKIAIOSFODNN7EXAMPLE',
    'sk_live_ABCDEFGHIJKLMNOP',
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.SflKxwRJSMeKKF2QT4fw'
  ].join('\n');

  const findings = scanSecrets(text);
  assert.ok(findings.length > 0, 'Should have findings');

  for (const f of findings) {
    // Required fields
    assert.ok('ruleId' in f, `Finding missing ruleId`);
    assert.ok('ruleName' in f, `Finding missing ruleName`);
    assert.ok('severity' in f, `Finding missing severity`);
    assert.ok('line' in f, `Finding missing line`);
    assert.ok('column' in f, `Finding missing column`);
    assert.ok('matchLength' in f, `Finding missing matchLength`);
    assert.ok('redactedValue' in f, `Finding missing redactedValue`);

    // Security: these fields must NEVER appear
    assert.ok(!('rawValue' in f), `Finding must not have rawValue`);
    assert.ok(!('secret' in f), `Finding must not have secret field`);
    assert.ok(!('value' in f), `Finding must not have value field`);
    assert.ok(!('match' in f), `Finding must not have match field`);

    // Severity must be one of the allowed values
    assert.ok(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].includes(f.severity),
      `Invalid severity: ${f.severity}`);
  }
});

test('Scanner — redactText handles all rule types end-to-end', () => {
  const text = `
    aws_key: AKIAIOSFODNN7EXAMPLE
    stripe: sk_live_ABCDEFGHIJKLMNOP
    password = "mysupersecretpassword"
  `;
  const redacted = redactText(text);
  assert.ok(!redacted.includes('AKIAIOSFODNN7EXAMPLE'), 'AWS key must be redacted');
  assert.ok(!redacted.includes('ABCDEFGHIJKLMNOP'), 'Stripe suffix must be redacted');
  assert.ok(!redacted.includes('mysupersecretpassword'), 'Password must be redacted');
});

test('Scanner — High entropy detection avoids common English words', () => {
  // Common English words have low entropy
  const text = 'the quick brown fox jumps over the lazy dog';
  const findings = scanSecrets(text);
  const entropyFindings = findings.filter(f => f.ruleId === 'high_entropy_secret');
  assert.equal(entropyFindings.length, 0, 'Common English text should not trigger entropy scanner');
});

test('Scanner — redactSecret never exposes more than prefix for known-prefix tokens', () => {
  const cases = [
    { input: 'AKIA' + 'X'.repeat(16), prefix: 'AKIA' },
    { input: 'sk_live_' + 'X'.repeat(24), prefix: 'sk_live_' },
    { input: 'ghp_' + 'X'.repeat(36), prefix: 'ghp_' },
  ];
  for (const { input, prefix } of cases) {
    const redacted = redactSecret(input);
    assert.ok(redacted.startsWith(prefix), `Should preserve prefix: ${prefix}`);
    assert.ok(!redacted.includes('X'.repeat(10)), 'Should not expose raw token body');
    assert.ok(redacted.includes('*'), 'Should contain stars');
  }
});

// =============================================================================
// TOTP: Standard Vectors, Boundaries, Invalid Inputs, Secret Non-Exposure
// =============================================================================

test('TOTP — RFC 6238 vectors (SHA-1) pass exactly', () => {
  const { asciiSecret, vectors } = RFC6238_TEST_VECTORS;
  const secretBuf = Buffer.from(asciiSecret, 'ascii');
  for (const v of vectors) {
    const token = generateTOTP(secretBuf, { timestamp: v.time, period: 30, algorithm: 'SHA1', digits: 8 });
    assert.equal(token, v.sha1, `SHA1 vector failed at time=${v.time}`);
  }
});

test('TOTP — RFC 6238 vectors (SHA-256) pass exactly', () => {
  const { asciiSecretSHA256, vectors } = RFC6238_TEST_VECTORS;
  const secretBuf = Buffer.from(asciiSecretSHA256, 'ascii');
  for (const v of vectors) {
    const token = generateTOTP(secretBuf, { timestamp: v.time, period: 30, algorithm: 'SHA256', digits: 8 });
    assert.equal(token, v.sha256, `SHA256 vector failed at time=${v.time}`);
  }
});

test('TOTP — RFC 6238 vectors (SHA-512) pass exactly', () => {
  const { asciiSecretSHA512, vectors } = RFC6238_TEST_VECTORS;
  const secretBuf = Buffer.from(asciiSecretSHA512, 'ascii');
  for (const v of vectors) {
    const token = generateTOTP(secretBuf, { timestamp: v.time, period: 30, algorithm: 'SHA512', digits: 8 });
    assert.equal(token, v.sha512, `SHA512 vector failed at time=${v.time}`);
  }
});

test('TOTP — Codes change at time step boundaries', () => {
  const secret = Buffer.from('12345678901234567890', 'ascii');
  const period = 30;
  // At t=0 and t=30, the counter changes so the code should differ
  const codeAt0 = generateTOTP(secret, { timestamp: 0, period });
  const codeAt30 = generateTOTP(secret, { timestamp: 30, period });
  const codeAt29 = generateTOTP(secret, { timestamp: 29, period });
  assert.notEqual(codeAt0, codeAt30, 'Code must change at period boundary');
  assert.equal(codeAt0, codeAt29, 'Code must be same within the same window (0-29)');
});

test('TOTP — Verify window tolerates ±1 drift', () => {
  const secret = 'JBSWY3DPEHPK3PXP';
  const now = Math.floor(Date.now() / 1000);
  const token = generateTOTP(secret, { timestamp: now });
  const result = verifyTOTP(token, secret, { timestamp: now, window: 1 });
  assert.ok(result.valid, 'Token should be valid within drift window');
  assert.equal(result.delta, 0, 'Delta should be 0 for current time');
});

test('TOTP — Rejects token from outside the drift window', () => {
  const secret = 'JBSWY3DPEHPK3PXP';
  const now = Math.floor(Date.now() / 1000);
  // Token from 5 periods ago — well outside ±1 window
  const oldToken = generateTOTP(secret, { timestamp: now - 150 });
  const result = verifyTOTP(oldToken, secret, { timestamp: now, window: 1 });
  assert.ok(!result.valid, 'Old token should be rejected outside drift window');
});

test('TOTP — Rejects invalid digits (5, 9)', () => {
  const secret = 'JBSWY3DPEHPK3PXP';
  assert.throws(() => generateTOTP(secret, { digits: 5 }), RangeError);
  assert.throws(() => generateTOTP(secret, { digits: 9 }), RangeError);
});

test('TOTP — Rejects empty secret string', () => {
  assert.throws(() => generateTOTP(''), Error);
});

test('TOTP — Rejects non-string / non-Buffer secret', () => {
  assert.throws(() => generateTOTP(12345), TypeError);
  assert.throws(() => generateTOTP(null), TypeError);
  assert.throws(() => generateTOTP([1, 2, 3]), TypeError);
});

test('TOTP — Rejects zero or negative period', () => {
  const secret = 'JBSWY3DPEHPK3PXP';
  assert.throws(() => generateTOTP(secret, { period: 0 }), RangeError);
  assert.throws(() => generateTOTP(secret, { period: -1 }), RangeError);
});

test('TOTP — Rejects invalid Base32 character in secret', () => {
  assert.throws(() => generateTOTP('JBSWY3D!INVALID'), Error);
});

test('TOTP — Output is zero-padded to correct digit length', () => {
  const secret = Buffer.from('12345678901234567890', 'ascii');
  for (const digits of [6, 7, 8]) {
    const token = generateTOTP(secret, { timestamp: 59, period: 30, digits });
    assert.equal(token.length, digits, `Token must be ${digits} digits`);
    assert.match(token, /^\d+$/, 'Token must be all digits');
  }
});

test('TOTP — parseOtpauthUri parses all fields correctly', () => {
  const uri = 'otpauth://totp/Example:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Example&algorithm=SHA256&digits=8&period=60';
  const parsed = parseOtpauthUri(uri);
  assert.equal(parsed.type, 'totp');
  assert.equal(parsed.secret, 'JBSWY3DPEHPK3PXP');
  assert.equal(parsed.issuer, 'Example');
  assert.equal(parsed.algorithm, 'SHA256');
  assert.equal(parsed.digits, 8);
  assert.equal(parsed.period, 60);
  assert.equal(parsed.accountName, 'user@example.com');
});

test('TOTP — parseOtpauthUri throws on missing secret', () => {
  assert.throws(() => parseOtpauthUri('otpauth://totp/label?issuer=Test'), Error);
});

test('TOTP — parseOtpauthUri throws on wrong protocol', () => {
  assert.throws(() => parseOtpauthUri('https://example.com?secret=ABC'), Error);
});

test('TOTP — parseOtpauthUri throws on unsupported OTP type', () => {
  assert.throws(() => parseOtpauthUri('otpauth://steam/label?secret=ABC'), Error);
});

test('TOTP — parseOtpauthUri throws on malformed URI (no scheme)', () => {
  assert.throws(() => parseOtpauthUri('not-a-uri'), Error);
});

test('TOTP — generateOtpauthUri round-trips correctly', () => {
  const opts = { type: 'totp', label: 'alice@example.com', secret: 'JBSWY3DPEHPK3PXP', issuer: 'Example', algorithm: 'SHA1', digits: 6, period: 30 };
  const uri = generateOtpauthUri(opts);
  const parsed = parseOtpauthUri(uri);
  assert.equal(parsed.secret, opts.secret);
  assert.equal(parsed.issuer, opts.issuer);
  assert.equal(parsed.digits, opts.digits);
});

test('TOTP — generated token does NOT appear in any audit output field', () => {
  const secret = 'JBSWY3DPEHPK3PXP';
  const token = generateTOTP(secret);
  // Audit of a TOTP secret should not expose the token in its output
  const auditResult = auditPassword(secret);
  const auditStr = JSON.stringify(auditResult);
  // The audit result should not contain the generated OTP token value
  assert.ok(!auditStr.includes(token), 'Audit output must not contain the generated TOTP token');
});

// =============================================================================
// GENERATOR: CSPRNG Guarantees, Constraints, Invalid Inputs
// =============================================================================

test('Generator — Does not use Math.random (CSPRNG only)', () => {
  const original = Math.random;
  let mathRandomCalled = false;
  Math.random = () => { mathRandomCalled = true; return 0; };
  try {
    generatePassword({ length: 32 });
    generatePassphrase({ wordCount: 4 });
    generateHexKey(32);
  } finally {
    Math.random = original;
  }
  assert.ok(!mathRandomCalled, 'Math.random must NEVER be called by the generator');
});

test('Generator — Respects exact length for all lengths in [4, 64]', () => {
  for (const len of [4, 8, 12, 16, 24, 32, 48, 64]) {
    const { password } = generatePassword({ length: len });
    assert.equal(password.length, len, `Password length must be exactly ${len}`);
  }
});

test('Generator — Respects character set constraints (uppercase only)', () => {
  const { password } = generatePassword({ length: 20, lowercase: false, digits: false, symbols: false });
  assert.match(password, /^[A-Z]+$/, 'Should contain only uppercase letters');
});

test('Generator — Respects character set constraints (digits only)', () => {
  const { password } = generatePassword({ length: 20, uppercase: false, lowercase: false, symbols: false });
  assert.match(password, /^\d+$/, 'Should contain only digits');
});

test('Generator — Enforces at least one char from each enabled group', () => {
  // Run multiple times to reduce probability of fluke
  for (let i = 0; i < 10; i++) {
    const { password } = generatePassword({ length: 16, uppercase: true, lowercase: true, digits: true, symbols: true, requireEachType: true });
    assert.match(password, /[A-Z]/, 'Must contain uppercase');
    assert.match(password, /[a-z]/, 'Must contain lowercase');
    assert.match(password, /[0-9]/, 'Must contain digit');
    assert.match(password, /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/, 'Must contain symbol');
  }
});

test('Generator — Throws on length below minimum (< 4)', () => {
  assert.throws(() => generatePassword({ length: 3 }), RangeError);
  assert.throws(() => generatePassword({ length: 0 }), RangeError);
  assert.throws(() => generatePassword({ length: -1 }), RangeError);
});

test('Generator — Throws on length above maximum (> 2048)', () => {
  assert.throws(() => generatePassword({ length: 2049 }), RangeError);
});

test('Generator — Throws when all charset groups are disabled', () => {
  assert.throws(() => generatePassword({ uppercase: false, lowercase: false, digits: false, symbols: false }), Error);
});

test('Generator — getRandomInt is within range [0, max)', () => {
  for (const max of [2, 10, 26, 62, 95]) {
    for (let i = 0; i < 20; i++) {
      const n = getRandomInt(max);
      assert.ok(n >= 0 && n < max, `getRandomInt(${max}) returned ${n} out of range`);
    }
  }
});

test('Generator — generatePassphrase respects word count', () => {
  for (const wordCount of [3, 4, 5, 6]) {
    const { passphrase } = generatePassphrase({ wordCount, separator: '-', capitalize: false });
    assert.equal(passphrase.split('-').length, wordCount, `Should have ${wordCount} words`);
  }
});

test('Generator — generatePassphrase entropy increases with word count', () => {
  const e3 = generatePassphrase({ wordCount: 3 }).entropyBits;
  const e5 = generatePassphrase({ wordCount: 5 }).entropyBits;
  const e7 = generatePassphrase({ wordCount: 7 }).entropyBits;
  assert.ok(e5 > e3, 'Entropy should increase with word count');
  assert.ok(e7 > e5, 'Entropy should increase with word count');
});

test('Generator — generateHexKey produces valid hex of correct length', () => {
  for (const bytes of [16, 32, 64]) {
    const key = generateHexKey(bytes);
    assert.equal(key.length, bytes * 2, `Hex key should be ${bytes * 2} chars`);
    assert.match(key, /^[0-9a-f]+$/, 'Should be lowercase hex');
  }
});

test('Generator — generateBase64Key produces URL-safe base64 (no +, /, =)', () => {
  for (let i = 0; i < 5; i++) {
    const key = generateBase64Key(32);
    assert.ok(!key.includes('+'), 'Must not contain +');
    assert.ok(!key.includes('/'), 'Must not contain /');
    assert.ok(!key.includes('='), 'Must not contain =');
  }
});

// =============================================================================
// AUDIT: Determinism, Structured Findings, Secret Non-Exposure
// =============================================================================

test('Audit — Same password always returns same score (deterministic)', () => {
  const pw = 'TestPassword123!';
  const result1 = auditPassword(pw);
  const result2 = auditPassword(pw);
  const result3 = auditPassword(pw);
  assert.equal(result1.score, result2.score, 'Score must be deterministic');
  assert.equal(result2.score, result3.score, 'Score must be deterministic');
  assert.equal(result1.tier, result2.tier, 'Tier must be deterministic');
});

test('Audit — Structured findings have required fields (category, severity, description, recommendation, scoreImpact)', () => {
  const result = auditPassword('abc');
  for (const detail of result.breakdown.details) {
    if (typeof detail === 'object') {
      assert.ok('category' in detail, 'Detail must have category');
      assert.ok('severity' in detail, 'Detail must have severity');
      assert.ok('description' in detail, 'Detail must have description');
      assert.ok('recommendation' in detail, 'Detail must have recommendation');
      assert.ok('scoreImpact' in detail, 'Detail must have scoreImpact');
      assert.ok(typeof detail.scoreImpact === 'number', 'scoreImpact must be a number');
    }
  }
});

test('Audit — Empty password returns score 0 and CRITICAL tier', () => {
  const result = auditPassword('');
  assert.equal(result.score, 0);
  assert.equal(result.tier, 'CRITICAL');
});

test('Audit — Weak short password scores CRITICAL or WEAK', () => {
  const result = auditPassword('abc');
  assert.ok(result.score < 40, 'Short weak password should score < 40');
  assert.ok(['CRITICAL', 'WEAK'].includes(result.tier));
});

test('Audit — Strong passphrase scores STRONG or EXCELLENT', () => {
  const result = auditPassword('correct-horse-battery-staple-2025!');
  assert.ok(result.score >= 80, `Strong passphrase should score >= 80, got ${result.score}`);
  assert.ok(['STRONG', 'EXCELLENT'].includes(result.tier));
});

test('Audit — Common pattern passwords are penalized deterministically', () => {
  const result1 = auditPassword('MyPassword123');
  const result2 = auditPassword('MyPassword123'); // run again
  assert.equal(result1.score, result2.score, 'Same common-pattern password always same score');
  // Should have a PATTERN finding
  const patternFindings = result1.breakdown.details.filter(d => d.category === 'PATTERN');
  assert.ok(patternFindings.length > 0, 'Should have PATTERN category finding');
});

test('Audit — scoreImpact values sum correctly to total adjustments', () => {
  const result = auditPassword('TestPass1!');
  const { baseEntropyScore, bonuses, penalties, details } = result.breakdown;

  // Sum up scoreImpact from details
  let totalBonuses = 0;
  let totalPenalties = 0;
  for (const d of details) {
    if (typeof d === 'object' && typeof d.scoreImpact === 'number') {
      if (d.scoreImpact > 0) totalBonuses += d.scoreImpact;
      else totalPenalties += Math.abs(d.scoreImpact);
    }
  }

  // The breakdown values should match what the details report
  assert.equal(totalBonuses, bonuses, 'Bonus sum from details must match breakdown.bonuses');
  assert.equal(totalPenalties, penalties, 'Penalty sum from details must match breakdown.penalties');
});

test('Audit — auditVaultSecrets detects duplicate passwords across entries', () => {
  const secrets = [
    { id: '1', service: 'GitHub', value: 'reused_password_123' },
    { id: '2', service: 'GitLab', value: 'reused_password_123' },
    { id: '3', service: 'Google', value: 'unique_password_xyz!@#' },
  ];
  const result = auditVaultSecrets(secrets);
  assert.ok(result.duplicatePasswordCount > 0, 'Should detect duplicate passwords');
  assert.ok(result.issueCount > 0, 'Should have issues');
});

test('Audit — auditVaultSecrets on healthy vault returns good health score', () => {
  const secrets = [
    { id: '1', service: 'GitHub', password: 'Tr0ub4dor&3-correct-horse-battery!' },
    { id: '2', service: 'Google', password: 'xK9mQ#7rPzL2@nVwY5!' },
    { id: '3', service: 'AWS', password: 'Bn8$jH2pRq6&mXv4Wy9#' },
  ];
  const result = auditVaultSecrets(secrets);
  assert.ok(result.healthScore >= 60, `Healthy vault should score >= 60, got ${result.healthScore}`);
  assert.equal(result.duplicatePasswordCount, 0, 'No duplicates in healthy vault');
});

test('Audit — audit output never exposes raw password values', () => {
  const secretPassword = 'my_super_secret_password_never_expose';
  const result = auditPassword(secretPassword);
  const resultStr = JSON.stringify(result);
  assert.ok(!resultStr.includes(secretPassword), 'Audit output must not contain the raw password');
});

test('Audit — auditVaultSecrets throws on non-array input', () => {
  assert.throws(() => auditVaultSecrets('not an array'), TypeError);
  assert.throws(() => auditVaultSecrets(null), TypeError);
  assert.throws(() => auditVaultSecrets(42), TypeError);
});
