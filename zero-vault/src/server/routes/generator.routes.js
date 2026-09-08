import * as security from '../../security/index.js';

export function registerGeneratorRoutes(router) {
  router.post('/api/generator/password', (req, res) => {
    try {
      const options = req.body || {};
      const result = security.generatePassword(options);
      res.json(result);
    } catch (err) {
      res.json({ error: err.message }, 400);
    }
  });

  router.post('/api/generator/passphrase', (req, res) => {
    try {
      const options = req.body || {};
      const result = security.generatePassphrase(options);
      res.json(result);
    } catch (err) {
      res.json({ error: err.message }, 400);
    }
  });

  router.post('/api/generator/keys', (req, res) => {
    try {
      const { byteLength = 32 } = req.body || {};
      res.json({
        hex: security.generateHexKey(byteLength),
        base64: security.generateBase64Key(byteLength)
      });
    } catch (err) {
      res.json({ error: err.message }, 400);
    }
  });
}
