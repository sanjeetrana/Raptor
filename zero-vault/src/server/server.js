import { createServer } from 'node:http';
import { join } from 'node:path';
import { Router } from './router.js';
import { serveStatic } from './static.js';
import { registerVaultRoutes } from './routes/vault.routes.js';
import { registerGeneratorRoutes } from './routes/generator.routes.js';
import { registerTotpRoutes } from './routes/totp.routes.js';
import { registerScannerRoutes } from './routes/scanner.routes.js';
import { registerAuditRoutes } from './routes/audit.routes.js';
import { registerFileRoutes } from './routes/file.routes.js';

const PUBLIC_DIR = join(process.cwd(), 'public');

export function startServer(port = 3000) {
  const router = new Router();

  registerVaultRoutes(router);
  registerGeneratorRoutes(router);
  registerTotpRoutes(router);
  registerScannerRoutes(router);
  registerAuditRoutes(router);
  registerFileRoutes(router);

  const server = createServer(async (req, res) => {
    if (req.url.startsWith('/api/')) {
      const handled = await router.handle(req, res);
      if (!handled) {
        res.writeHead(404, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'API route not found' }));
      }
      return;
    }

    const served = serveStatic(req, res, PUBLIC_DIR);
    if (!served) {
      // SPA fallback: serve index.html for navigation URLs (no file extension)
      if (req.method === 'GET' && !req.url.includes('.')) {
        serveStatic({ ...req, url: '/' }, res, PUBLIC_DIR);
      } else {
        res.writeHead(404);
        res.end('Not Found');
      }
    }
  });

  server.listen(port, () => {
    console.log(`ZeroVault running at http://localhost:${port}`);
  });

  return server;
}
