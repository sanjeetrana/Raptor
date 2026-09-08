import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { existsSync, writeFileSync, unlinkSync } from 'node:fs';

import {
  base32Decode,
  base32Encode,
  generateHOTP,
  generateTOTP,
  verifyTOTP,
  parseOtpauthUri,
  generateOtpauthUri,
  RFC6238_TEST_VECTORS
} from '../src/security/totp.js';

import {
  calculateShannonEntropy,
  redactSecret,
  scanSecrets,
  redactText
} from '../src/security/scanner.js';

import {
  getRandomInt,
  calculateEntropyBits,
  generatePassword,
  generatePassphrase,
  generateHexKey,
  generateBase64Key,
  CHARSETS
} from '../src/security/generator.js';

import {
  auditPassword,
  auditVaultSecrets
} from '../src/security/audit.js';

import {
  checkFilePermissions,
  secureFilePermissions,
  safeWriteFile,
  shredFile,
  hashFile,
  verifyFileIntegrity
} from '../src/security/file-protection.js';

describe('Security Subsystem — TOTP / 2FA (RFC 6238 & RFC 4226)', () => {
  it('should encode and decode Base32 strings (RFC 4648)', () => {
    const rawText = 'Hello World!';
    const buf = Buffer.from(rawText);
    const encoded = base32Encode(buf);
    assert.equal(typeof encoded, 'string');

    const decoded = base32Decode(encoded);
    assert.equal(decoded.toString(), rawText);
  });

  it('should pass RFC 6238 official test vectors for SHA-1', () => {
    const secret = Buffer.from('12345678901234567890');

    for (const vec of RFC6238_TEST_VECTORS.vectors) {
      const token = generateTOTP(secret, {
        timestamp: vec.time,
        algorithm: 'SHA1',
        digits: 8
      });
      assert.equal(token, vec.sha1, `Failed RFC 6238 SHA1 test vector at t=${vec.time}`);
    }
  });

  it('should pass RFC 6238 official test vectors for SHA-256', () => {
    const secret = Buffer.from('12345678901234567890123456789012');

    for (const vec of RFC6238_TEST_VECTORS.vectors) {
      const token = generateTOTP(secret, {
        timestamp: vec.time,
        algorithm: 'SHA256',
        digits: 8
      });
      assert.equal(token, vec.sha256, `Failed RFC 6238 SHA256 test vector at t=${vec.time}`);
    }
  });

  it('should pass RFC 6238 official test vectors for SHA-512', () => {
    const secret = Buffer.from('1234567890123456789012345678901234567890123456789012345678901234');

    for (const vec of RFC6238_TEST_VECTORS.vectors) {
      const token = generateTOTP(secret, {
        timestamp: vec.time,
        algorithm: 'SHA512',
        digits: 8
      });
      assert.equal(token, vec.sha512, `Failed RFC 6238 SHA512 test vector at t=${vec.time}`);
    }
  });

  it('should verify TOTP token within time drift window', () => {
    const secret = 'JBSWY3DPEHPK3PXP';
    const now = 1700000000;
    const token = generateTOTP(secret, { timestamp: now });

    // Exact time
    const resExact = verifyTOTP(token, secret, { timestamp: now, window: 1 });
    assert.equal(resExact.valid, true);
    assert.equal(resExact.delta, 0);

    // Drifting -30 seconds (1 step behind)
    const resPast = verifyTOTP(token, secret, { timestamp: now + 30, window: 1 });
    assert.equal(resPast.valid, true);
    assert.equal(resPast.delta, -1);

    // Invalid token check
    const resInvalid = verifyTOTP('000000', secret, { timestamp: now, window: 1 });
    assert.equal(resInvalid.valid, false);
  });

  it('should parse and generate valid otpauth:// URIs', () => {
    const uriStr = 'otpauth://totp/Example:alice@google.com?secret=JBSWY3DPEHPK3PXP&issuer=Example&algorithm=SHA256&digits=6&period=30';
    const parsed = parseOtpauthUri(uriStr);

    assert.equal(parsed.type, 'totp');
    assert.equal(parsed.issuer, 'Example');
    assert.equal(parsed.accountName, 'alice@google.com');
    assert.equal(parsed.secret, 'JBSWY3DPEHPK3PXP');
    assert.equal(parsed.algorithm, 'SHA256');

    const regenerated = generateOtpauthUri({
      type: 'totp',
      label: 'alice@google.com',
      secret: 'JBSWY3DPEHPK3PXP',
      issuer: 'Example',
      algorithm: 'SHA256'
    });
    assert.ok(regenerated.startsWith('otpauth://totp/Example%3Aalice%40google.com'));
    assert.ok(regenerated.includes('secret=JBSWY3DPEHPK3PXP'));
  });
});

describe('Security Subsystem — Secret Scanner', () => {
  it('should detect AWS Access Keys and API keys', () => {
    const stripeKey = 'sk_' + 'live_51MzX1234567890abcdefghijklmnopqrst';
    const ghpKey = 'ghp_' + '1234567890abcdefghijklmnopqrstuvwxyz';
    const sampleText = `
      # Config file
      AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
      aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
      STRIPE_KEY=${stripeKey}
      GITHUB_TOKEN=${ghpKey}
    `;

    const findings = scanSecrets(sampleText);
    assert.ok(findings.length >= 4);

    const awsFinding = findings.find((f) => f.ruleId === 'aws_access_key');
    assert.ok(awsFinding);
    assert.equal(awsFinding.redactedValue, 'AKIA****************');

    const stripeFinding = findings.find((f) => f.ruleId === 'stripe_api_key');
    assert.ok(stripeFinding);
    assert.ok(stripeFinding.redactedValue.startsWith('sk_live_'));
  });

  it('should detect Private Keys and JWT tokens', () => {
    const jwtSample = 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
    const findings = scanSecrets(jwtSample);

    assert.ok(findings.some((f) => f.ruleId === 'jwt_token' || f.ruleId === 'bearer_token'));
  });

  it('should redact sensitive content completely without leaking secrets', () => {
    const stripeKey = 'sk_' + 'live_51MzX1234567890abcdef';
    const secretContent = `AWS_KEY=AKIAIOSFODNN7EXAMPLE and STRIPE=${stripeKey}`;
    const redacted = redactText(secretContent);

    assert.ok(!redacted.includes('AKIAIOSFODNN7EXAMPLE'));
    assert.ok(!redacted.includes(stripeKey));
    assert.ok(redacted.includes('AKIA****************'));
  });

  it('should calculate Shannon entropy accurately', () => {
    const lowEntropy = 'aaaaaaaaaaaaaaaa';
    const highEntropy = '8f4a9b2c1d0e3f7a8b9c0d1e2f3a4b5c';

    assert.ok(calculateShannonEntropy(lowEntropy) < 1.0);
    assert.ok(calculateShannonEntropy(highEntropy) > 3.5);
  });
});

describe('Security Subsystem — CSPRNG Generator', () => {
  it('should generate unbiased random integers', () => {
    for (let i = 0; i < 50; i++) {
      const val = getRandomInt(10);
      assert.ok(val >= 0 && val < 10);
    }
  });

  it('should generate secure passwords adhering to length & character options', () => {
    const options = {
      length: 20,
      uppercase: true,
      lowercase: true,
      digits: true,
      symbols: true,
      avoidAmbiguous: true,
      requireEachType: true
    };

    const res = generatePassword(options);
    assert.equal(res.password.length, 20);
    assert.ok(res.entropyBits > 100);

    // Check ambiguous exclusion
    for (const char of res.password) {
      assert.ok(!['O', '0', 'I', '1', 'l', 'Z', '2', 'S', '5'].includes(char));
    }
  });

  it('should generate passphrases with entropy calculation', () => {
    const res = generatePassphrase({
      wordCount: 5,
      separator: '-',
      capitalize: true,
      includeNumber: true
    });

    const parts = res.passphrase.split('-');
    assert.equal(parts.length, 6); // 5 words + 1 trailing number
    assert.ok(res.entropyBits > 30);
  });

  it('should generate CSPRNG hex and Base64 keys', () => {
    const hexKey = generateHexKey(16);
    assert.equal(hexKey.length, 32);

    const b64Key = generateBase64Key(32);
    assert.ok(b64Key.length >= 40);
  });
});

describe('Security Subsystem — Security Audit', () => {
  it('should penalize weak/short passwords and reward passphrases', () => {
    const weakAudit = auditPassword('12345');
    assert.equal(weakAudit.tier, 'CRITICAL');
    assert.ok(weakAudit.score < 40);

    const strongAudit = auditPassword('Correct-Horse-Battery-Staple-2026!');
    assert.equal(strongAudit.tier, 'EXCELLENT');
    assert.ok(strongAudit.score >= 90);
  });

  it('should audit collection of vault secrets and detect duplicates', () => {
    const secrets = [
      { id: '1', title: 'Gmail', value: 'SameSecret123!' },
      { id: '2', title: 'GitHub', value: 'SameSecret123!' }, // duplicate password
      { id: '3', title: 'AWS', value: 'AKIAIOSFODNN7EXAMPLE' } // exposed credential in value
    ];

    const auditRes = auditVaultSecrets(secrets);
    assert.equal(auditRes.duplicatePasswordCount, 2);
    assert.ok(auditRes.issues.length >= 2);
  });
});

describe('Security Subsystem — File Protection Foundation', () => {
  const testFile = join(tmpdir(), `zerovault_test_${Date.now()}.dat`);

  after(() => {
    if (existsSync(testFile)) {
      unlinkSync(testFile);
    }
  });

  it('should safely write file atomically and check permissions', () => {
    const content = Buffer.from('Sensitive Vault Data Payload');
    safeWriteFile(testFile, content, { mode: 0o600 });

    assert.ok(existsSync(testFile));

    const perm = checkFilePermissions(testFile);
    assert.equal(perm.secure, true);
    assert.equal(perm.modeOctal, '600');

    const isIntact = verifyFileIntegrity(testFile, hashFile(testFile));
    assert.equal(isIntact, true);
  });

  it('should shred sensitive file securely', () => {
    const shredTarget = join(tmpdir(), `shred_me_${Date.now()}.dat`);
    writeFileSync(shredTarget, 'TOP SECRET DATA DO NOT LEAK');

    assert.ok(existsSync(shredTarget));

    shredFile(shredTarget, { passes: 2 });
    assert.equal(existsSync(shredTarget), false);
  });
});
