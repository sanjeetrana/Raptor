import { readFileSync, statSync, existsSync } from 'node:fs';
import { join, normalize, extname } from 'node:path';

const MIME_TYPES = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

export function serveStatic(req, res, publicDir) {
  let urlPath = req.url.split('?')[0];
  if (urlPath === '/') {
    urlPath = '/index.html';
  }

  // Prevent directory traversal
  const safePath = normalize(urlPath).replace(/^(\.\.(\/|\\|$))+/, '');
  const filePath = join(publicDir, safePath);

  // Check if file is strictly inside publicDir
  if (!filePath.startsWith(publicDir)) {
    res.writeHead(403);
    res.end('Forbidden');
    return true;
  }

  if (existsSync(filePath) && statSync(filePath).isFile()) {
    const ext = extname(filePath).toLowerCase();
    const mimeType = MIME_TYPES[ext] || 'application/octet-stream';
    
    try {
      const data = readFileSync(filePath);
      res.writeHead(200, {
        'Content-Type': mimeType,
        'Cache-Control': 'no-cache',
        'X-Content-Type-Options': 'nosniff'
      });
      res.end(data);
    } catch (err) {
      res.writeHead(500);
      res.end('Internal Server Error');
    }
    return true;
  }
  
  return false;
}
