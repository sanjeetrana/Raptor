export class Router {
  constructor() {
    this.routes = {
      GET: [],
      POST: [],
      PUT: [],
      DELETE: [],
      OPTIONS: []
    };
  }

  addRoute(method, path, handler) {
    const paramNames = [];
    const regexPath = path.replace(/:([a-zA-Z0-9_]+)/g, (_, paramName) => {
      paramNames.push(paramName);
      return '([^/]+)';
    });
    const regex = new RegExp(`^${regexPath}$`);
    this.routes[method].push({ regex, paramNames, handler });
  }

  get(path, handler) { this.addRoute('GET', path, handler); }
  post(path, handler) { this.addRoute('POST', path, handler); }
  put(path, handler) { this.addRoute('PUT', path, handler); }
  delete(path, handler) { this.addRoute('DELETE', path, handler); }
  options(path, handler) { this.addRoute('OPTIONS', path, handler); }

  async handle(req, res) {
    const { method, url } = req;
    const [path, queryString] = url.split('?');
    
    // CORS Preflight
    if (method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      });
      res.end();
      return true;
    }

    const routeList = this.routes[method] || [];
    for (const route of routeList) {
      const match = path.match(route.regex);
      if (match) {
        req.params = {};
        route.paramNames.forEach((name, i) => {
          req.params[name] = match[i + 1];
        });
        
        req.query = new URLSearchParams(queryString || '');
        
        // Enhance response
        res.json = (data, statusCode = 200) => {
          res.writeHead(statusCode, {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY'
          });
          res.end(JSON.stringify(data));
        };

        // Parse JSON body for POST/PUT
        if (['POST', 'PUT'].includes(method)) {
          let body = '';
          req.on('data', chunk => {
            body += chunk.toString();
          });
          await new Promise((resolve, reject) => {
            req.on('end', () => {
              try {
                req.body = body ? JSON.parse(body) : {};
                resolve();
              } catch (err) {
                reject(err);
              }
            });
            req.on('error', reject);
          }).catch(() => {
            return res.json({ error: 'Invalid JSON body' }, 400);
          });
        }

        try {
          await route.handler(req, res);
        } catch (err) {
          console.error('[Router Error]', err.name, err.message);
          res.json({ error: err.message || 'Internal Server Error' }, 500);
        }
        return true;
      }
    }
    
    return false; // Route not handled by API
  }
}
