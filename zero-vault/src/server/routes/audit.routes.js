import { vaultState } from '../state.js';
import { security } from '../../index.js';

export function registerAuditRoutes(router) {
  router.post('/api/audit/password', (req, res) => {
    try {
      const { password } = req.body;
      if (!password || typeof password !== 'string') return res.json({ error: 'Missing or invalid password field' }, 400);

      const auditResult = security.auditPassword(password);
      // Do not echo the password back in the response
      res.json({
        score: auditResult.score,
        tier: auditResult.tier,
        entropyBits: auditResult.entropyBits,
        length: auditResult.length,
        breakdown: auditResult.breakdown,
        remediations: auditResult.remediations
      });
    } catch (err) {
      res.json({ error: 'Failed to audit password' }, 500);
    }
  });

  router.get('/api/audit/vault', (req, res) => {
    try {
      const manager = vaultState.getManager();
      if (!manager || !manager.isUnlocked()) return res.json({ error: 'Vault is locked' }, 401);

      // Retrieve full credential data for strength/reuse analysis.
      // 'password' is mapped to 'value' to match the audit engine's expected schema.
      const entriesForAudit = manager.listEntries().map(summary => {
        const full = manager.getEntry(summary.id);
        return { id: full.id, title: full.service, value: full.password };
      });

      const auditResult = security.auditVaultSecrets(entriesForAudit);
      // Strip any fields that may have been populated with raw credential data
      res.json({
        healthScore: auditResult.healthScore,
        vaultStatus: auditResult.vaultStatus,
        itemsAudited: auditResult.itemsAudited,
        issueCount: auditResult.issueCount,
        duplicatePasswordCount: auditResult.duplicatePasswordCount,
        issues: auditResult.issues.map(issue => ({
          itemId: issue.itemId,
          severity: issue.severity,
          issue: issue.issue,
          remediations: issue.remediations
        }))
      });
    } catch (err) {
      res.json({ error: 'Failed to audit vault secrets' }, 500);
    }
  });
}
