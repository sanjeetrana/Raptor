import { calculateShannonEntropy, scanSecrets } from './scanner.js';
import { CHARSETS } from './generator.js';

/**
 * Common weak pattern regexes for password auditing
 */
/**
 * Common weak patterns for password auditing (deterministic, ordered)
 */
const COMMON_PATTERNS = [
  { regex: /12345/i,    label: '12345' },
  { regex: /qwerty/i,  label: 'qwerty' },
  { regex: /asdfgh/i,  label: 'asdfgh' },
  { regex: /password/i,label: 'password' },
  { regex: /admin/i,   label: 'admin' },
  { regex: /letmein/i, label: 'letmein' },
  { regex: /welcome/i, label: 'welcome' },
  { regex: /monkey/i,  label: 'monkey' },
  { regex: /abc123/i,  label: 'abc123' },
  { regex: /iloveyou/i,label: 'iloveyou' },
  { regex: /dragon/i,  label: 'dragon' },
];

/**
 * Audits a single password or secret string using a transparent scoring model.
 * All score calculations and deductions are explicitly documented and returned.
 *
 * @param {string} password - Input password string
 * @returns {Object} - Detailed audit report
 */
export function auditPassword(password) {
  if (typeof password !== 'string' || password.length === 0) {
    return {
      score: 0,
      tier: 'CRITICAL',
      entropyBits: 0,
      poolSize: 0,
      length: 0,
      breakdown: {
        baseEntropyScore: 0,
        bonuses: 0,
        penalties: 100,
        details: [
          {
            category: 'INPUT',
            severity: 'CRITICAL',
            description: 'Empty or non-string password provided',
            recommendation: 'Provide a non-empty password string',
            scoreImpact: -100
          }
        ]
      },
      remediations: ['Provide a non-empty password']
    };
  }

  const len = password.length;

  // 1. Determine active character sets and pool size
  let hasUpper = false;
  let hasLower = false;
  let hasDigit = false;
  let hasSymbol = false;

  for (const char of password) {
    if (CHARSETS.uppercase.includes(char)) hasUpper = true;
    else if (CHARSETS.lowercase.includes(char)) hasLower = true;
    else if (CHARSETS.digits.includes(char)) hasDigit = true;
    else hasSymbol = true;
  }

  let poolSize = 0;
  if (hasUpper) poolSize += CHARSETS.uppercase.length;
  if (hasLower) poolSize += CHARSETS.lowercase.length;
  if (hasDigit) poolSize += CHARSETS.digits.length;
  if (hasSymbol) poolSize += CHARSETS.symbols.length;
  if (poolSize === 0) poolSize = 1;

  // 2. Base Entropy Calculation (E = L * log2(N))
  // Use fixed-precision arithmetic for deterministic results
  const entropyBits = Number((len * Math.log2(poolSize)).toFixed(2));
  // Scale: 80 bits of entropy = 100 base score points
  const baseEntropyScore = Math.min(100, Math.round(entropyBits * 1.25));

  const details = []; // structured findings
  const remediations = [];
  let penalties = 0;
  let bonuses = 0;

  // 3. Length Auditing
  if (len < 8) {
    const impact = -30;
    penalties += Math.abs(impact);
    details.push({
      category: 'LENGTH',
      severity: 'CRITICAL',
      description: `Password is critically short (${len} characters)`,
      recommendation: 'Use at least 12 characters; 16+ is recommended',
      scoreImpact: impact
    });
    remediations.push('Increase password length to at least 12-16 characters.');
  } else if (len < 12) {
    const impact = -15;
    penalties += Math.abs(impact);
    details.push({
      category: 'LENGTH',
      severity: 'HIGH',
      description: `Password length is below modern standard (${len} characters)`,
      recommendation: 'Extend to 14+ characters for better brute-force resistance',
      scoreImpact: impact
    });
    remediations.push('Extend password to 14+ characters.');
  } else if (len >= 24) {
    const impact = +20;
    bonuses += impact;
    details.push({
      category: 'LENGTH',
      severity: 'INFO',
      description: `Excellent passphrase length (${len} characters)`,
      recommendation: 'No action required',
      scoreImpact: impact
    });
  } else if (len >= 16) {
    const impact = +10;
    bonuses += impact;
    details.push({
      category: 'LENGTH',
      severity: 'INFO',
      description: `Good password length (${len} characters)`,
      recommendation: 'No action required',
      scoreImpact: impact
    });
  }

  // 4. Character Diversity
  const activeGroupCount = (hasUpper ? 1 : 0) + (hasLower ? 1 : 0) + (hasDigit ? 1 : 0) + (hasSymbol ? 1 : 0);
  if (activeGroupCount < 3 && len < 20) {
    const missingCount = 4 - activeGroupCount;
    const impact = -(missingCount * 10);
    penalties += Math.abs(impact);
    details.push({
      category: 'DIVERSITY',
      severity: 'HIGH',
      description: `Low character diversity — uses only ${activeGroupCount}/4 character types`,
      recommendation: 'Mix uppercase, lowercase, digits, and symbols',
      scoreImpact: impact
    });
    remediations.push('Mix uppercase, lowercase, digits, and symbols.');
  }

  // 5. Common Pattern Check (deterministic: first match wins)
  for (const { regex, label } of COMMON_PATTERNS) {
    if (regex.test(password)) {
      const impact = -20;
      penalties += Math.abs(impact);
      details.push({
        category: 'PATTERN',
        severity: 'HIGH',
        description: `Contains predictable sequence or dictionary word: '${label}'`,
        recommendation: 'Avoid common words, keyboard patterns, and default passwords',
        scoreImpact: impact
      });
      remediations.push('Avoid common words, sequential keyboard patterns, and default passwords.');
      break; // Only penalize once for common patterns
    }
  }

  // 6. Repeating Character Runs
  const repeatMatch = password.match(/(.)\1{2,}/g);
  if (repeatMatch) {
    // Cap penalty at -20 regardless of how many runs exist
    const impact = -Math.min(20, repeatMatch.length * 10);
    penalties += Math.abs(impact);
    details.push({
      category: 'REPETITION',
      severity: 'MEDIUM',
      description: `Contains repeating character sequences: ${repeatMatch.map(r => `'${r[0]}'x${r.length}`).join(', ')}`,
      recommendation: 'Remove consecutive repeating characters',
      scoreImpact: impact
    });
    remediations.push('Remove consecutive repeating characters.');
  }

  // 7. Low Unique Character Ratio
  const uniqueCount = new Set(password).size;
  const uniqueRatio = uniqueCount / len;
  if (uniqueRatio < 0.5 && len >= 8) {
    const impact = -15;
    penalties += Math.abs(impact);
    details.push({
      category: 'REDUNDANCY',
      severity: 'MEDIUM',
      description: `High character redundancy — ${uniqueCount} unique chars out of ${len} total`,
      recommendation: 'Use a wider variety of characters throughout the password',
      scoreImpact: impact
    });
    remediations.push('Use a wider variety of characters throughout the password.');
  }

  // 8. Compute Final Score (deterministic: no floating-point accumulation)
  const rawScore = baseEntropyScore + bonuses - penalties;
  const finalScore = Math.max(0, Math.min(100, rawScore));

  // 9. Assign Risk Tier (deterministic thresholds)
  let tier;
  if (finalScore >= 90) tier = 'EXCELLENT';
  else if (finalScore >= 80) tier = 'STRONG';
  else if (finalScore >= 60) tier = 'MODERATE';
  else if (finalScore >= 40) tier = 'WEAK';
  else tier = 'CRITICAL';

  return {
    score: finalScore,
    tier,
    entropyBits,
    poolSize,
    length: len,
    breakdown: {
      baseEntropyScore,
      bonuses,
      penalties,
      details // array of {category, severity, description, recommendation, scoreImpact}
    },
    remediations
  };
}

/**
 * Audits an array of vault secret entries for security risks (e.g. duplicate passwords, weak secrets, unredacted exposed keys).
 *
 * @param {Array<Object>} secrets - Array of secret objects: { id, title, type, value, secretKey, totpSecret }
 * @returns {Object} - Comprehensive Vault Audit Report
 */
export function auditVaultSecrets(secrets = []) {
  if (!Array.isArray(secrets)) {
    throw new TypeError('Secrets parameter must be an array');
  }

  const passwordHashes = new Map();
  const duplicatePasswordIds = new Set();

  let totalScore = 0;
  const itemsAudited = secrets.length;
  const issues = [];

  for (const item of secrets) {
    const itemId = item.id || item.title || 'unknown_item';

    // Audit main password/value if present
    if (item.value && typeof item.value === 'string') {
      const pwdAudit = auditPassword(item.value);
      totalScore += pwdAudit.score;

      if (pwdAudit.tier === 'CRITICAL' || pwdAudit.tier === 'WEAK') {
        issues.push({
          itemId,
          title: item.title,
          severity: pwdAudit.tier,
          issue: `Weak secret/password detected (Score: ${pwdAudit.score}/100)`,
          remediations: pwdAudit.remediations
        });
      }

      // Check duplicate passwords
      if (passwordHashes.has(item.value)) {
        duplicatePasswordIds.add(itemId);
        duplicatePasswordIds.add(passwordHashes.get(item.value));
      } else {
        passwordHashes.set(item.value, itemId);
      }

      // Scan value for accidental hardcoded credentials or API keys
      const scannerFindings = scanSecrets(item.value);
      if (scannerFindings.length > 0) {
        issues.push({
          itemId,
          title: item.title,
          severity: 'HIGH',
          issue: `Value contains embedded unredacted secret (${scannerFindings[0].ruleName})`,
          remediations: ['Rotate the exposed key and store credentials in designated fields.']
        });
      }
    } else {
      totalScore += 80; // default baseline for non-password secrets
    }
  }

  // Report duplicate password issue
  if (duplicatePasswordIds.size > 0) {
    issues.push({
      itemId: Array.from(duplicatePasswordIds).join(', '),
      severity: 'HIGH',
      issue: `Duplicate passwords reused across ${duplicatePasswordIds.size} vault items`,
      remediations: ['Generate unique passwords for each account to prevent credential stuffing.']
    });
  }

  const averageHealthScore = itemsAudited > 0 ? Math.round(totalScore / itemsAudited) : 100;
  // Deduct overall health for duplicates
  const finalHealthScore = Math.max(0, averageHealthScore - (duplicatePasswordIds.size * 5));

  let vaultStatus;
  if (finalHealthScore >= 85) vaultStatus = 'HEALTHY';
  else if (finalHealthScore >= 70) vaultStatus = 'NEEDS_ATTENTION';
  else vaultStatus = 'AT_RISK';

  return {
    healthScore: finalHealthScore,
    vaultStatus,
    itemsAudited,
    issueCount: issues.length,
    duplicatePasswordCount: duplicatePasswordIds.size,
    issues
  };
}
