import { vaultState } from '../state.js';

function requireUnlocked(res) {
  const manager = vaultState.getManager();
  if (!manager || !manager.isUnlocked()) {
    res.json({ error: 'Vault is locked' }, 401);
    return null;
  }
  return manager;
}

export function registerVaultRoutes(router) {
  router.get('/api/vault/status', (req, res) => {
    const manager = vaultState.getManager();
    if (!manager || !manager.isUnlocked()) {
      return res.json({ locked: true, vaultPath: null });
    }
    res.json({ locked: false, vaultPath: manager.filePath });
  });

  router.post('/api/vault/create', async (req, res) => {
    const { password, vaultPath } = req.body;
    if (!password || !vaultPath) return res.json({ error: 'Missing password or vaultPath' }, 400);

    try {
      vaultState.initManager(vaultPath);
      const manager = vaultState.getManager();
      const pwdBuf = Buffer.from(password);
      await manager.initializeVault(pwdBuf);
      manager.unlock(pwdBuf);
      // Zero the local password buffer — manager retains its own internal copy
      pwdBuf.fill(0);
      res.json({ success: true, vaultPath });
    } catch {
      res.json({ error: 'Failed to create vault' }, 500);
    }
  });

  router.post('/api/vault/unlock', (req, res) => {
    const { password, vaultPath } = req.body;
    if (!password || !vaultPath) return res.json({ error: 'Missing password or vaultPath' }, 400);

    try {
      vaultState.initManager(vaultPath);
      const manager = vaultState.getManager();
      const pwdBuf = Buffer.from(password);
      manager.unlock(pwdBuf);
      // Zero the local password buffer — manager retains its own internal copy
      pwdBuf.fill(0);
      const itemCount = manager.listEntries().length;
      res.json({ success: true, vaultPath, itemCount });
    } catch {
      // Generic error — do not reveal whether the file exists, password was wrong, or vault is corrupted
      res.json({ error: 'Authentication failed or vault is corrupted' }, 401);
    }
  });

  router.post('/api/vault/lock', (req, res) => {
    vaultState.clearManager();
    res.json({ success: true, locked: true });
  });

  router.get('/api/entries', (req, res) => {
    const manager = requireUnlocked(res);
    if (!manager) return;
    try {
      res.json({ entries: manager.listEntries() });
    } catch {
      res.json({ error: 'Failed to list entries' }, 500);
    }
  });

  router.post('/api/entries', (req, res) => {
    const manager = requireUnlocked(res);
    if (!manager) return;
    try {
      const id = manager.createEntry(req.body);
      res.json({ success: true, id });
    } catch (err) {
      res.json({ error: err.message || 'Failed to create entry' }, 400);
    }
  });

  router.get('/api/entries/:id', (req, res) => {
    const manager = requireUnlocked(res);
    if (!manager) return;
    try {
      res.json({ entry: manager.getEntry(req.params.id) });
    } catch {
      res.json({ error: 'Entry not found' }, 404);
    }
  });

  router.put('/api/entries/:id', (req, res) => {
    const manager = requireUnlocked(res);
    if (!manager) return;
    try {
      manager.updateEntry(req.params.id, req.body);
      res.json({ success: true });
    } catch (err) {
      res.json({ error: err.message || 'Failed to update entry' }, 400);
    }
  });

  router.delete('/api/entries/:id', (req, res) => {
    const manager = requireUnlocked(res);
    if (!manager) return;
    try {
      manager.deleteEntry(req.params.id);
      res.json({ success: true });
    } catch {
      res.json({ error: 'Entry not found' }, 404);
    }
  });
}
