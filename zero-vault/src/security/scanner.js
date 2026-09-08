/**
 * scanner.js — Secret Detection & Redaction Engine
 *
 * Detects secrets, credentials, and high-entropy strings in text content.
 * All outputs are redacted — raw secrets are NEVER returned in findings.
 *
 * Security guarantees:
 *   - redactedValue is always present; rawValue is NEVER included in findings
 *   - Duplicate findings (same ruleId + position) are de-duplicated
 *   - Binary content is safely handled (non-UTF-8 chunks are skipped)
 *   - Large inputs should be checked by caller (e.g. 5MB limit in routes)
 */

/**
 * Shannon Entropy calculation for a string.
 * High entropy indicates pseudorandom character distribution common in secrets/keys.
 *
 * @param {string} str - Input string
 * @returns {number} - Entropy in bits per character
 */
export function calculateShannonEntropy(str) {
  if (!str || str.length === 0) return 0;

  const frequencies = new Map();
  for (const char of str) {
    frequencies.set(char, (frequencies.get(char) || 0) + 1);
  }

  let entropy = 0;
  const len = str.length;
  for (const count of frequencies.values()) {
    const p = count / len;
    entropy -= p * Math.log2(p);
  }

  return entropy;
}

/**
 * Redacts a detected secret string.
 * Never exposes more than a few identifying prefix characters.
 *
 * @param {string} rawSecret - The secret string detected
 * @param {string} [ruleId] - Optional rule ID for context-aware redaction
 * @returns {string} - Redacted secret string
 */
export function redactSecret(rawSecret, ruleId = '') {
  if (!rawSecret) return '[REDACTED]';

  const len = rawSecret.length;

  if (ruleId === 'private_key') {
    return '-----BEGIN PRIVATE KEY-----\n[REDACTED PRIVATE KEY CONTENT]\n-----END PRIVATE KEY-----';
  }

  // Known-prefix tokens: show only the well-known prefix, redact the rest
  const knownPrefixes = [
    { prefix: 'AKIA', minLen: 5 },
    { prefix: 'sk_live_', minLen: 9 },
    { prefix: 'sk_test_', minLen: 9 },
    { prefix: 'ghp_', minLen: 5 },
    { prefix: 'gho_', minLen: 5 },
    { prefix: 'github_pat_', minLen: 12 },
    { prefix: 'eyJ', minLen: 4 },
    { prefix: 'xoxb-', minLen: 6 },
    { prefix: 'xoxp-', minLen: 6 },
    { prefix: 'Bearer ', minLen: 8 },
  ];

  for (const { prefix, minLen } of knownPrefixes) {
    if (rawSecret.startsWith(prefix) && len > minLen) {
      return prefix + '*'.repeat(Math.max(4, len - prefix.length));
    }
  }

  // Generic secret: never show more than first 4 chars of sufficient-length secrets
  if (len <= 4) return '*'.repeat(len);
  if (len <= 8) return rawSecret.slice(0, 2) + '*'.repeat(len - 2);

  return rawSecret.slice(0, 4) + '*'.repeat(len - 4);
}

/**
 * Built-in Secret Detection Rules
 *
 * Each rule has:
 *   - id: machine-readable identifier
 *   - name: human-readable name
 *   - severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
 *   - regex: detection pattern (always reset before use to avoid stateful issues)
 *   - group: capture group index containing the secret (1-indexed)
 *   - allowFalsePositiveCheck: optional function to validate a candidate match
 */
export const SECRET_DETECTOR_RULES = [
  {
    id: 'aws_access_key',
    name: 'AWS Access Key ID',
    severity: 'CRITICAL',
    // AWS Access Keys are exactly 20 chars: AKIA + 16 uppercase alphanumeric
    regex: /\b(AKIA[0-9A-Z]{16})\b/g,
    group: 1
  },
  {
    id: 'aws_secret_key',
    name: 'AWS Secret Access Key',
    severity: 'CRITICAL',
    // Context-keyed: must be preceded by known env var or key name
    regex: /(?:aws_secret(?:_access)?_key|aws[_-]key)\s*[:=]\s*['"]?([A-Za-z0-9/+=]{40})['"]?/gi,
    group: 1
  },
  {
    id: 'private_key',
    name: 'Private Key Block',
    severity: 'CRITICAL',
    regex: /(-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----)/g,
    group: 1
  },
  {
    id: 'stripe_api_key',
    name: 'Stripe Live Secret Key',
    severity: 'HIGH',
    // Stripe live keys: sk_live_ + at least 16 alphanumeric chars
    regex: /\b(sk_live_[0-9a-zA-Z]{16,56})\b/g,
    group: 1
  },
  {
    id: 'stripe_test_key',
    name: 'Stripe Test Secret Key',
    severity: 'MEDIUM',
    regex: /\b(sk_test_[0-9a-zA-Z]{16,56})\b/g,
    group: 1
  },
  {
    id: 'github_pat',
    name: 'GitHub Personal Access Token',
    severity: 'HIGH',
    // Classic ghp_ token (40 chars after prefix) or fine-grained github_pat_ (82+ chars after prefix)
    regex: /\b(ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})\b/g,
    group: 1
  },
  {
    id: 'jwt_token',
    name: 'JSON Web Token (JWT)',
    severity: 'MEDIUM',
    // JWT: 3 base64url segments separated by dots
    regex: /\b(eyJ[A-Za-z0-9_-]{4,}\.eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,})\b/g,
    group: 1
  },
  {
    id: 'slack_token',
    name: 'Slack Bot or User Token',
    severity: 'HIGH',
    regex: /\b(xox[bpas]-[0-9A-Za-z\-]{10,})\b/g,
    group: 1
  },
  {
    id: 'db_connection_string',
    name: 'Database Connection String with Credentials',
    severity: 'HIGH',
    // Must have a password component (user:pass@host)
    regex: /\b((?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis):\/\/[^\s"'<>:]+:[^\s"'<>@]{3,}@[^\s"'<>]+)\b/gi,
    group: 1
  },
  {
    id: 'env_secret',
    name: '.env File Secret Assignment',
    severity: 'HIGH',
    // Specific high-risk env var names only; value must be non-trivial (>=8 chars)
    regex: /^[ \t]*(?:AWS_SECRET_ACCESS_KEY|SECRET_KEY|API_KEY|PRIVATE_KEY|AUTH_TOKEN|DATABASE_URL|DB_PASSWORD)\s*=\s*(["']?.{8,}?["']?)[ \t]*$/gm,
    group: 1
  },
  {
    id: 'hardcoded_password',
    name: 'Hardcoded Password Assignment',
    severity: 'HIGH',
    // Only match when value is quoted string (reduces false positives on config comments)
    regex: /(?:password|passwd|pwd)\s*[:=]\s*['"]([^'"]{8,})['"](?!\w)/gi,
    group: 1
  }
];

/**
 * Check if a string looks like binary/non-text content.
 * Heuristic: if >10% of the first 512 bytes are null bytes or control chars, treat as binary.
 *
 * @param {string} text
 * @returns {boolean}
 */
export function looksLikeBinary(text) {
  const sample = text.slice(0, 512);
  let controlCount = 0;
  for (let i = 0; i < sample.length; i++) {
    const code = sample.charCodeAt(i);
    if (code === 0 || (code < 9 && code !== 0) || (code > 13 && code < 32)) {
      controlCount++;
    }
  }
  return controlCount / sample.length > 0.1;
}

/**
 * Scans a text string for sensitive secrets and credentials.
 *
 * @param {string} text - The input content to scan
 * @param {Object} [options]
 * @param {boolean} [options.entropyScan=true] - Whether to perform Shannon entropy scan
 * @param {number} [options.minEntropy=4.5] - Minimum Shannon entropy threshold (bits/char)
 * @param {number} [options.minEntropyLength=20] - Minimum string length for entropy check
 * @param {boolean} [options.skipBinary=true] - Skip binary-looking content
 * @returns {Array<Object>} - List of detected findings (redacted values only)
 */
export function scanSecrets(text, options = {}) {
  if (typeof text !== 'string' || text.length === 0) {
    return [];
  }

  const {
    entropyScan = true,
    minEntropy = 4.5,
    minEntropyLength = 20,
    skipBinary = true
  } = options;

  // Skip binary-looking content to prevent false positives and encoding errors
  if (skipBinary && looksLikeBinary(text)) {
    return [];
  }

  const findings = [];
  const lines = text.split('\n');
  // De-duplicate: track seen (ruleId, line, column) tuples
  const seenKeys = new Set();

  // Helper to compute line and column from character index
  function getPosition(index) {
    let currentLength = 0;
    for (let l = 0; l < lines.length; l++) {
      const lineLen = lines[l].length + 1; // +1 for newline
      if (index < currentLength + lineLen) {
        return { line: l + 1, column: index - currentLength + 1 };
      }
      currentLength += lineLen;
    }
    return { line: lines.length, column: 1 };
  }

  // Track matched ranges to avoid duplicate entropy alerts on already-matched tokens
  const matchedRanges = [];

  // 1. Rule-based pattern matching
  for (const rule of SECRET_DETECTOR_RULES) {
    // Always create a fresh regex to avoid shared state (lastIndex) bugs
    const regex = new RegExp(rule.regex.source, rule.regex.flags);
    let match;
    while ((match = regex.exec(text)) !== null) {
      const fullMatch = match[0];
      const secretValue = (rule.group && match[rule.group]) ? match[rule.group] : fullMatch;

      // Calculate the exact start position of secretValue within the full match
      const secretOffset = fullMatch.indexOf(secretValue);
      const startIndex = match.index + (secretOffset >= 0 ? secretOffset : 0);
      const endIndex = startIndex + secretValue.length;

      matchedRanges.push([startIndex, endIndex]);
      const pos = getPosition(startIndex);

      // De-duplicate by ruleId + line + column
      const dedupeKey = `${rule.id}:${pos.line}:${pos.column}`;
      if (seenKeys.has(dedupeKey)) continue;
      seenKeys.add(dedupeKey);

      findings.push({
        ruleId: rule.id,
        ruleName: rule.name,
        severity: rule.severity,
        line: pos.line,
        column: pos.column,
        matchLength: secretValue.length,
        redactedValue: redactSecret(secretValue, rule.id)
        // NOTE: rawValue / secretValue are intentionally NEVER included
      });
    }
  }

  // 2. High Shannon Entropy Scan
  if (entropyScan) {
    // Tokenize words: alphanumeric + common secret chars, at least minEntropyLength long
    const wordRegex = /[A-Za-z0-9_\-\+\/=]{20,}/g;
    let wordMatch;

    while ((wordMatch = wordRegex.exec(text)) !== null) {
      const candidate = wordMatch[0];
      const start = wordMatch.index;
      const end = start + candidate.length;

      if (candidate.length < minEntropyLength) continue;

      // Skip if already caught by a pattern rule
      const alreadyCaught = matchedRanges.some(
        ([rStart, rEnd]) => start >= rStart && end <= rEnd
      );
      if (alreadyCaught) continue;

      const entropy = calculateShannonEntropy(candidate);
      if (entropy >= minEntropy) {
        const pos = getPosition(start);
        const dedupeKey = `high_entropy_secret:${pos.line}:${pos.column}`;
        if (seenKeys.has(dedupeKey)) continue;
        seenKeys.add(dedupeKey);

        findings.push({
          ruleId: 'high_entropy_secret',
          ruleName: `High Entropy String (${entropy.toFixed(2)} bits/char)`,
          severity: 'MEDIUM',
          line: pos.line,
          column: pos.column,
          matchLength: candidate.length,
          entropy: Number(entropy.toFixed(2)),
          redactedValue: redactSecret(candidate, 'high_entropy_secret')
        });
      }
    }
  }

  return findings;
}

/**
 * Scans text and returns a fully redacted version.
 * All detected secrets are replaced in-place with redacted placeholders.
 *
 * @param {string} text - Input text containing potential secrets
 * @returns {string} - Text with all detected secrets replaced
 */
export function redactText(text) {
  if (typeof text !== 'string' || text.length === 0) {
    return text;
  }

  let result = text;

  for (const rule of SECRET_DETECTOR_RULES) {
    const regex = new RegExp(rule.regex.source, rule.regex.flags);
    result = result.replace(regex, (fullMatch, ...groups) => {
      // Find the actual captured group (first non-undefined capture)
      const secretGroup = groups.slice(0, rule.group || 1).find(g => g !== undefined);
      const secretToRedact = secretGroup || fullMatch;
      const redacted = redactSecret(secretToRedact, rule.id);
      // Replace only the secret part within the full match to preserve context
      return fullMatch.replace(secretToRedact, redacted);
    });
  }

  return result;
}
