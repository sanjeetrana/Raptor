'use strict';
// Zero-dependency real-time push. Electron's main.js used
// `mainWindow.webContents.send(channel, payload)` to push events into the
// renderer over its IPC channel. A browser has no such channel, so this
// module opens a standard Server-Sent Events stream (built on node:http)
// and every connected tab receives the same broadcast.

const clients = new Set();

function attach(req, res) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.write(':ok\n\n');
  clients.add(res);
  const heartbeat = setInterval(() => { try { res.write(':hb\n\n'); } catch { /* client gone */ } }, 20000);
  req.on('close', () => { clearInterval(heartbeat); clients.delete(res); });
}

function broadcast(channel, payload) {
  const frame = `event: message\ndata: ${JSON.stringify({ channel, payload })}\n\n`;
  for (const res of clients) {
    try { res.write(frame); } catch { clients.delete(res); }
  }
}

module.exports = { attach, broadcast };
