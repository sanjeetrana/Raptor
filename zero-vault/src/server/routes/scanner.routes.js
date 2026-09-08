import * as security from '../../security/index.js';

// Maximum safe text input for scanner (5MB) to prevent DoS
const MAX_SCANNER_BYTES = 5 * 1024 * 1024;

export function registerScannerRoutes(router) {
  router.post('/api/scanner/scan', (req, res) => {
    try {
      const { text, options } = req.body;
      if (typeof text !== 'string') return res.json({ error: 'Missing or invalid text field' }, 400);

      // Guard against excessively large inputs
      if (Buffer.byteLength(text, 'utf8') > MAX_SCANNER_BYTES) {
        return res.json({ error: 'Input too large. Maximum allowed size is 5MB.' }, 413);
      }

      const findings = security.scanSecrets(text, options || {});

      // Explicitly verify no finding exposes a raw secret.
      // All findings must have a redactedValue field — never return rawValue.
      const safeFindings = findings.map(f => ({
        ruleId: f.ruleId,
        ruleName: f.ruleName,
        severity: f.severity,
        line: f.line,
        column: f.column,
        matchLength: f.matchLength,
        redactedValue: f.redactedValue,
        entropy: f.entropy  // Only present for high-entropy scan results
      }));

      res.json({ findings: safeFindings, totalCount: safeFindings.length });
    } catch (err) {
      res.json({ error: 'Scanner failed to process input safely' }, 500);
    }
  });

  router.post('/api/scanner/redact', (req, res) => {
    try {
      const { text } = req.body;
      if (typeof text !== 'string') return res.json({ error: 'Missing or invalid text field' }, 400);

      if (Buffer.byteLength(text, 'utf8') > MAX_SCANNER_BYTES) {
        return res.json({ error: 'Input too large. Maximum allowed size is 5MB.' }, 413);
      }

      const redacted = security.redactText(text);
      res.json({ redacted });
    } catch (err) {
      res.json({ error: 'Redaction failed' }, 500);
    }
  });
}
