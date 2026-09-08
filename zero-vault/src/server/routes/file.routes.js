import * as security from '../../security/index.js';

export function registerFileRoutes(router) {
  router.post('/api/file/permissions', (req, res) => {
    try {
      const { filePath } = req.body;
      if (!filePath) return res.json({ error: 'Missing filePath' }, 400);
      const perms = security.checkFilePermissions(filePath);
      res.json(perms);
    } catch (err) {
      res.json({ error: err.message }, 400);
    }
  });

  router.post('/api/file/secure', (req, res) => {
    try {
      const { filePath } = req.body;
      if (!filePath) return res.json({ error: 'Missing filePath' }, 400);
      const mode = security.secureFilePermissions(filePath);
      res.json({ success: true, mode });
    } catch (err) {
      res.json({ error: err.message }, 400);
    }
  });

  router.post('/api/file/hash', (req, res) => {
    try {
      const { filePath } = req.body;
      if (!filePath) return res.json({ error: 'Missing filePath' }, 400);
      const hash = security.hashFile(filePath);
      res.json({ hash });
    } catch (err) {
      res.json({ error: err.message }, 400);
    }
  });

  router.post('/api/file/verify', (req, res) => {
    try {
      const { filePath, expectedHash } = req.body;
      if (!filePath || !expectedHash) return res.json({ error: 'Missing filePath or expectedHash' }, 400);
      const valid = security.verifyFileIntegrity(filePath, expectedHash);
      res.json({ valid });
    } catch (err) {
      res.json({ error: err.message }, 400);
    }
  });

  router.post('/api/file/shred', (req, res) => {
    try {
      const { filePath } = req.body;
      if (!filePath) return res.json({ error: 'Missing filePath' }, 400);
      security.shredFile(filePath);
      res.json({ success: true });
    } catch (err) {
      res.json({ error: err.message }, 400);
    }
  });
}
