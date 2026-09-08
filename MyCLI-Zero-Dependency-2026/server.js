#!/usr/bin/env node
'use strict';

/**
 * MyCLI — Windows Control Center (Zero Dependency edition)
 *
 * Local Node.js HTTP server + Vercel-compatible serverless handler.
 */

const http = require('node:http');
const fs = require('node:fs');
const fsp = fs.promises;
const path = require('node:path');
const { URL } = require('node:url');
const os = require('node:os');

const store = require('./lib/store');
const events = require('./lib/events');
const fsOps = require('./lib/fsOps');
const terminalOps = require('./lib/terminalOps');
const systemOps = require('./lib/systemOps');

store.setBroadcaster(events.broadcast);

const PORT = Number(process.env.PORT) || 4173;
const HOST = process.env.HOST || '127.0.0.1';
const PUBLIC_DIR = path.join(__dirname, 'public');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.ico': 'image/vnd.microsoft.icon',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

function sendJson(res, status, body) {
  const data = JSON.stringify(body);

  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(data),
  });

  res.end(data);
}

function sendError(res, error) {
  const message = error?.message || String(error);

  const status =
    /not found/i.test(message)
      ? 404
      : /only on Windows|only available/i.test(message)
        ? 409
        : 400;

  sendJson(res, status, {
    error: message,
  });
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    let size = 0;
    let finished = false;

    req.on('data', (chunk) => {
      if (finished) return;

      size += chunk.length;

      if (size > 10 * 1024 * 1024) {
        finished = true;
        reject(new Error('Request body too large.'));
        req.destroy();
        return;
      }

      raw += chunk;
    });

    req.on('end', () => {
      if (finished) return;

      finished = true;

      if (!raw) {
        resolve({});
        return;
      }

      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new Error('Invalid JSON body.'));
      }
    });

    req.on('error', (error) => {
      if (!finished) {
        finished = true;
        reject(error);
      }
    });
  });
}

async function serveStatic(req, res, pathname) {
  const relative = pathname === '/' ? '/index.html' : pathname;

  const resolved = path.normalize(
    path.join(PUBLIC_DIR, relative)
  );

  if (
    resolved !== PUBLIC_DIR &&
    !resolved.startsWith(PUBLIC_DIR + path.sep)
  ) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  try {
    const stat = await fsp.stat(resolved);

    if (stat.isDirectory()) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }

    const type =
      MIME[path.extname(resolved).toLowerCase()] ||
      'application/octet-stream';

    res.writeHead(200, {
      'Content-Type': type,
      'Content-Length': stat.size,
    });

    fs.createReadStream(resolved).pipe(res);
  } catch {
    res.writeHead(404);
    res.end('Not found');
  }
}

function downloadResponse(res, filename, content, contentType) {
  res.writeHead(200, {
    'Content-Type': contentType,
    'Content-Disposition': `attachment; filename="${filename}"`,
    'Content-Length': Buffer.byteLength(content),
  });

  res.end(content);
}

const routes = [];

function route(method, pattern, handler) {
  routes.push({
    method,
    pattern,
    handler,
  });
}

/* -------------------------------------------------------
   APP
------------------------------------------------------- */

route('GET', '/api/app/info', async (req, res) => {
  sendJson(res, 200, {
    version: '1.0.0',
    platform: process.platform,
    arch: process.arch,
    isWindows: fsOps.isWindows,
    home: os.homedir(),
    cwd: process.cwd(),
  });
});

/* -------------------------------------------------------
   SETTINGS
------------------------------------------------------- */

route(
  'GET',
  '/api/settings',
  async (req, res) => {
    sendJson(
      res,
      200,
      await store.getSettings()
    );
  }
);

route(
  'POST',
  '/api/settings',
  async (req, res) => {
    const body = await readBody(req);

    sendJson(
      res,
      200,
      await store.setSettings(body)
    );
  }
);

/* -------------------------------------------------------
   HISTORY
------------------------------------------------------- */

route(
  'GET',
  '/api/history',
  async (req, res) => {
    sendJson(
      res,
      200,
      store.getHistory()
    );
  }
);

route(
  'POST',
  '/api/history/clear',
  async (req, res) => {
    await store.clearHistory();

    sendJson(res, 200, {
      ok: true,
    });
  }
);

route(
  'POST',
  '/api/history/delete',
  async (req, res) => {
    const { id } = await readBody(req);

    await store.deleteHistoryItem(id);

    sendJson(res, 200, {
      ok: true,
    });
  }
);

route(
  'GET',
  '/api/history/export',
  async (req, res, url) => {
    const format =
      url.searchParams.get('format') === 'csv'
        ? 'csv'
        : 'json';

    const rows = store.getHistory();

    const content =
      format === 'csv'
        ? store.historyToCsv(rows)
        : JSON.stringify(rows, null, 2);

    downloadResponse(
      res,
      `mycli-history.${format}`,
      content,
      format === 'csv'
        ? 'text/csv'
        : 'application/json'
    );
  }
);

/* -------------------------------------------------------
   ACTIVITY
------------------------------------------------------- */

route(
  'GET',
  '/api/activity',
  async (req, res) => {
    sendJson(
      res,
      200,
      store.getActivity()
    );
  }
);

route(
  'POST',
  '/api/activity/clear',
  async (req, res) => {
    await store.clearActivity();

    sendJson(res, 200, {
      ok: true,
    });
  }
);

route(
  'GET',
  '/api/activity/export',
  async (req, res) => {
    downloadResponse(
      res,
      'mycli-activity.json',
      JSON.stringify(
        store.getActivity(),
        null,
        2
      ),
      'application/json'
    );
  }
);

/* -------------------------------------------------------
   STATE
------------------------------------------------------- */

route(
  'POST',
  '/api/state/push',
  async (req, res) => {
    const body = await readBody(req);

    sendJson(res, 200, {
      size: store.pushState(body),
    });
  }
);

route(
  'POST',
  '/api/state/pop',
  async (req, res) => {
    sendJson(
      res,
      200,
      store.popState()
    );
  }
);

/* -------------------------------------------------------
   FILES
------------------------------------------------------- */

route(
  'GET',
  '/api/files/list',
  async (req, res, url) => {
    const result = await fsOps.listDir(
      url.searchParams.get('path'),
      {
        showHidden:
          url.searchParams.get(
            'showHidden'
          ) === 'true',
      }
    );

    sendJson(res, 200, result);
  }
);

route(
  'GET',
  '/api/files/properties',
  async (req, res, url) => {
    sendJson(
      res,
      200,
      await fsOps.properties(
        url.searchParams.get('path')
      )
    );
  }
);

route(
  'POST',
  '/api/files/open',
  async (req, res) => {
    const { path: p } =
      await readBody(req);

    await fsOps.openWithDefaultApp(
      fsOps.safePath(p)
    );

    sendJson(res, 200, {
      ok: true,
    });
  }
);

route(
  'POST',
  '/api/files/open-terminal',
  async (req, res) => {
    const { path: p } =
      await readBody(req);

    const target =
      fsOps.safePath(p);

    const stat =
      await fsp.stat(target);

    const folder =
      stat.isDirectory()
        ? target
        : path.dirname(target);

    await fsOps.openTerminalAt(folder);

    sendJson(res, 200, {
      path: folder,
    });
  }
);

route(
  'POST',
  '/api/files/create',
  async (req, res) => {
    const {
      parent,
      name,
      kind,
    } = await readBody(req);

    sendJson(res, 200, {
      path: await fsOps.createEntry(
        parent,
        name,
        kind
      ),
    });
  }
);

route(
  'POST',
  '/api/files/rename',
  async (req, res) => {
    const {
      path: p,
      name,
    } = await readBody(req);

    sendJson(res, 200, {
      path: await fsOps.renameEntry(
        p,
        name
      ),
    });
  }
);

route(
  'POST',
  '/api/files/copy',
  async (req, res) => {
    const {
      source,
      destination,
    } = await readBody(req);

    sendJson(res, 200, {
      path: await fsOps.copyEntry(
        source,
        destination
      ),
    });
  }
);

route(
  'POST',
  '/api/files/move',
  async (req, res) => {
    const {
      source,
      destination,
    } = await readBody(req);

    sendJson(res, 200, {
      path: await fsOps.moveEntry(
        source,
        destination
      ),
    });
  }
);

route(
  'POST',
  '/api/files/delete',
  async (req, res) => {
    const { path: p } =
      await readBody(req);

    await fsOps.deleteEntry(p);

    sendJson(res, 200, {
      ok: true,
    });
  }
);

/* -------------------------------------------------------
   BROWSE
------------------------------------------------------- */

route(
  'GET',
  '/api/browse',
  async (req, res, url) => {
    const mode =
      url.searchParams.get('mode') === 'file'
        ? 'file'
        : 'dir';

    const ext =
      (url.searchParams.get('ext') || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    sendJson(
      res,
      200,
      await fsOps.browse(
        url.searchParams.get('path'),
        mode,
        ext
      )
    );
  }
);

/* -------------------------------------------------------
   TERMINAL
------------------------------------------------------- */

route(
  'POST',
  '/api/terminal/start',
  async (req, res) => {
    const {
      kind,
      cwd,
    } = await readBody(req);

    sendJson(
      res,
      200,
      terminalOps.startSession(
        kind,
        cwd || process.cwd()
      )
    );
  }
);

route(
  'GET',
  '/api/terminal/list',
  async (req, res) => {
    sendJson(
      res,
      200,
      terminalOps.listSessions()
    );
  }
);

route(
  'POST',
  '/api/terminal/run',
  async (req, res) => {
    const {
      sessionId,
      command,
    } = await readBody(req);

    sendJson(
      res,
      200,
      terminalOps.run(
        sessionId,
        command,
        events.broadcast
      )
    );
  }
);

route(
  'POST',
  '/api/terminal/stop',
  async (req, res) => {
    const {
      processId,
    } = await readBody(req);

    sendJson(
      res,
      200,
      terminalOps.stop(processId)
    );
  }
);

route(
  'POST',
  '/api/terminal/set-cwd',
  async (req, res) => {
    const {
      sessionId,
      cwd,
    } = await readBody(req);

    sendJson(
      res,
      200,
      terminalOps.setSessionCwd(
        sessionId,
        cwd
      )
    );
  }
);

/* -------------------------------------------------------
   SYSTEM
------------------------------------------------------- */

route(
  'GET',
  '/api/system/info',
  async (req, res) => {
    sendJson(
      res,
      200,
      await systemOps.info()
    );
  }
);

route(
  'GET',
  '/api/system/processes',
  async (req, res) => {
    sendJson(
      res,
      200,
      await systemOps.processesList()
    );
  }
);

route(
  'GET',
  '/api/system/services',
  async (req, res) => {
    sendJson(
      res,
      200,
      await systemOps.services()
    );
  }
);

route(
  'GET',
  '/api/system/startup',
  async (req, res) => {
    sendJson(
      res,
      200,
      await systemOps.startup()
    );
  }
);

route(
  'GET',
  '/api/system/storage',
  async (req, res) => {
    sendJson(
      res,
      200,
      await systemOps.storage()
    );
  }
);

route(
  'GET',
  '/api/system/network',
  async (req, res) => {
    sendJson(
      res,
      200,
      await systemOps.network()
    );
  }
);

route(
  'GET',
  '/api/system/health',
  async (req, res) => {
    sendJson(
      res,
      200,
      await systemOps.health()
    );
  }
);

route(
  'POST',
  '/api/system/kill-process',
  async (req, res) => {
    const { pid } =
      await readBody(req);

    sendJson(
      res,
      200,
      await systemOps.killProcess(pid)
    );
  }
);

route(
  'POST',
  '/api/system/service-action',
  async (req, res) => {
    const {
      name,
      action,
    } = await readBody(req);

    sendJson(
      res,
      200,
      await systemOps.serviceAction(
        name,
        action
      )
    );
  }
);

route(
  'POST',
  '/api/system/tool',
  async (req, res) => {
    const { tool } =
      await readBody(req);

    sendJson(
      res,
      200,
      await systemOps.launchTool(tool)
    );
  }
);

route(
  'POST',
  '/api/system/run-script',
  async (req, res) => {
    const {
      script,
      label,
    } = await readBody(req);

    sendJson(
      res,
      200,
      await systemOps.runDiagnosticScript(
        script,
        label
      )
    );
  }
);

/* -------------------------------------------------------
   APPS
------------------------------------------------------- */

route(
  'GET',
  '/api/apps/installed',
  async (req, res) => {
    sendJson(
      res,
      200,
      await systemOps.installedApps()
    );
  }
);

route(
  'POST',
  '/api/apps/winget',
  async (req, res) => {
    const { args } =
      await readBody(req);

    sendJson(
      res,
      200,
      await systemOps.winget(
        args,
        events.broadcast
      )
    );
  }
);

/* -------------------------------------------------------
   INSTALLER
------------------------------------------------------- */

route(
  'POST',
  '/api/installer/run',
  async (req, res) => {
    const {
      installer,
      args,
    } = await readBody(req);

    sendJson(
      res,
      200,
      await systemOps.runInstaller(
        installer,
        args,
        events.broadcast
      )
    );
  }
);

/* -------------------------------------------------------
   EVENTS
------------------------------------------------------- */

route(
  'GET',
  '/api/events',
  async (req, res) => {
    return events.attach(req, res);
  }
);

/* -------------------------------------------------------
   API HANDLER
------------------------------------------------------- */

async function handleApi(req, res, url) {
  const match = routes.find(
    (r) =>
      r.method === req.method &&
      r.pattern === url.pathname
  );

  if (!match) {
    return sendJson(res, 404, {
      error: 'Unknown API route.',
    });
  }

  try {
    await match.handler(
      req,
      res,
      url
    );
  } catch (error) {
    console.error(
      'API error:',
      error
    );

    if (!res.headersSent) {
      sendError(res, error);
    } else {
      res.end();
    }
  }
}

/* -------------------------------------------------------
   VERCEL / SERVERLESS HANDLER
------------------------------------------------------- */

async function handler(req, res) {
  try {
    await store.ensureData();

    const url = new URL(
      req.url || '/',
      `http://${req.headers.host || `${HOST}:${PORT}`}`
    );

    if (
      url.pathname.startsWith('/api/')
    ) {
      return handleApi(
        req,
        res,
        url
      );
    }

    if (
      req.method !== 'GET' &&
      req.method !== 'HEAD'
    ) {
      res.writeHead(405);
      res.end('Method not allowed');
      return;
    }

    return serveStatic(
      req,
      res,
      url.pathname
    );
  } catch (error) {
    console.error(
      'Handler error:',
      error
    );

    if (!res.headersSent) {
      sendError(res, error);
    } else {
      res.end();
    }
  }
}

/* -------------------------------------------------------
   LOCAL SERVER
------------------------------------------------------- */

const server =
  http.createServer(handler);

async function start() {
  await store.ensureData();

  await new Promise(
    (resolve, reject) => {
      server.once(
        'error',
        reject
      );

      server.listen(
        PORT,
        HOST,
        resolve
      );
    }
  );

  const address =
    server.address();

  const port =
    typeof address === 'object' &&
    address
      ? address.port
      : PORT;

  console.log(
    `MyCLI (Zero Dependency edition) running at http://${HOST}:${port}`
  );

  console.log(
    `Data directory: ${store.DATA_DIR}`
  );
}

/* -------------------------------------------------------
   LOCAL EXECUTION ONLY
------------------------------------------------------- */

if (
  require.main === module
) {
  start().catch(
    (error) => {
      console.error(
        'Failed to start MyCLI:',
        error
      );

      process.exitCode = 1;
    }
  );
}

/*
 * IMPORTANT:
 *
 * Vercel needs the exported value to be a request handler
 * function. Do NOT export { server, start } here.
 */
module.exports = handler;
