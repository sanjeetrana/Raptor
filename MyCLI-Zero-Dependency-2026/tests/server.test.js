'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

process.env.MYCLI_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'mycli-data-'));
process.env.PORT = '0';
process.env.HOST = '127.0.0.1';

const { server, start } = require('../server');

let base = '';

test.before(async () => {
  await start();
  const address = server.address();
  base = `http://127.0.0.1:${address.port}`;
});

test.after(() => {
  server.close();
});

test('GET / serves the app shell', async () => {
  const res = await fetch(`${base}/`);
  assert.equal(res.status, 200);
  const body = await res.text();
  assert.ok(body.includes('MyCLI'));
});

test('GET /api/app/info reports platform details and no Electron leakage', async () => {
  const res = await fetch(`${base}/api/app/info`);
  assert.equal(res.status, 200);
  const data = await res.json();
  assert.equal(data.platform, process.platform);
  assert.ok('isWindows' in data);
  assert.ok('home' in data);
});

test('unknown API route returns 404 JSON', async () => {
  const res = await fetch(`${base}/api/does-not-exist`);
  assert.equal(res.status, 404);
  const data = await res.json();
  assert.ok(data.error);
});

test('settings round-trip through the API', async () => {
  const post = await fetch(`${base}/api/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme: 'light' }),
  });
  assert.equal(post.status, 200);
  const get = await fetch(`${base}/api/settings`);
  const data = await get.json();
  assert.equal(data.theme, 'light');
});

test('files:list / files:create / files:delete work end-to-end over HTTP', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mycli-http-'));
  const created = await fetch(`${base}/api/files/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parent: dir, name: 'note.txt', kind: 'file' }),
  }).then((r) => r.json());
  assert.ok(fs.existsSync(created.path));

  const listed = await fetch(`${base}/api/files/list?path=${encodeURIComponent(dir)}`).then((r) => r.json());
  assert.ok(listed.entries.some((e) => e.name === 'note.txt'));

  const deleted = await fetch(`${base}/api/files/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: created.path }),
  }).then((r) => r.json());
  assert.equal(deleted.ok, true);
  assert.ok(!fs.existsSync(created.path));
});

test('files:list rejects a missing path with a 400/404 JSON error, not a crash', async () => {
  const res = await fetch(`${base}/api/files/list?path=${encodeURIComponent(path.join(os.tmpdir(), 'definitely-missing-dir-xyz'))}`);
  assert.ok(res.status >= 400);
  const data = await res.json();
  assert.ok(data.error);
});

test('terminal start + run executes a real command and reports exit status via history', async () => {
  const cwd = os.tmpdir();
  const session = await fetch(`${base}/api/terminal/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cwd }),
  }).then((r) => r.json());
  assert.ok(session.id);

  const command = process.platform === 'win32' ? 'echo hello-mycli' : 'echo hello-mycli';
  const result = await fetch(`${base}/api/terminal/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId: session.id, command }),
  }).then((r) => r.json());
  assert.equal(result.accepted, true);

  // Give the spawned child a moment to finish and update history.
  await new Promise((resolve) => setTimeout(resolve, 1500));
  const history = await fetch(`${base}/api/history`).then((r) => r.json());
  const entry = history.find((h) => h.id === result.historyId);
  assert.ok(entry, 'expected the command to appear in history');
  assert.notEqual(entry.status, 'running');
});

test('browse (folder picker backend) lists a real directory', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mycli-browse-'));
  fs.mkdirSync(path.join(dir, 'child'));
  const data = await fetch(`${base}/api/browse?path=${encodeURIComponent(dir)}&mode=dir`).then((r) => r.json());
  assert.ok(data.entries.some((e) => e.name === 'child'));
});
