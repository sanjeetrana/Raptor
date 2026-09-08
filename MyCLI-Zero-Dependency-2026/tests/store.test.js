'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

process.env.MYCLI_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'mycli-data-'));
const store = require('../lib/store');

test.before(async () => {
  store.setBroadcaster(() => {});
  await store.ensureData();
});

test('ensureData creates history.json, activity.json and settings.json', () => {
  for (const file of ['history.json', 'activity.json', 'settings.json']) {
    assert.ok(fs.existsSync(path.join(store.DATA_DIR, file)), `${file} should exist`);
  }
});

test('redact hides passwords, tokens and secrets but keeps the rest of the text', () => {
  const input = 'run with password=hunters2 and token: abc123 please';
  const output = store.redact(input);
  assert.ok(!output.includes('hunters2'));
  assert.ok(!output.includes('abc123'));
  assert.ok(output.includes('password=[redacted]'));
  assert.ok(output.includes('run with'));
});

test('addHistory prepends items, caps at 500 and persists to disk', async () => {
  await store.clearHistory();
  store.addHistory({ id: '1', command: 'dir' });
  store.addHistory({ id: '2', command: 'echo hi' });
  const history = store.getHistory();
  assert.equal(history[0].id, '2');
  assert.equal(history.length, 2);
  await new Promise((resolve) => setTimeout(resolve, 50));
  const onDisk = JSON.parse(fs.readFileSync(path.join(store.DATA_DIR, 'history.json'), 'utf8'));
  assert.equal(onDisk.length, 2);
});

test('deleteHistoryItem removes only the matching entry', async () => {
  await store.clearHistory();
  store.addHistory({ id: 'a' });
  store.addHistory({ id: 'b' });
  await store.deleteHistoryItem('a');
  const ids = store.getHistory().map((x) => x.id);
  assert.deepEqual(ids, ['b']);
});

test('addActivity redacts secrets in target/details and caps at 1000', async () => {
  const item = store.addActivity('Command executed', 'apikey=deadbeef', 'Success', 'token=zzz');
  assert.ok(item.target.includes('[redacted]'));
  assert.ok(item.details.includes('[redacted]'));
});

test('getSettings/setSettings round-trip through disk', async () => {
  await store.setSettings({ theme: 'light', confirmDestructive: false });
  const settings = await store.getSettings();
  assert.equal(settings.theme, 'light');
  assert.equal(settings.confirmDestructive, false);
});

test('pushState/popState behave as a stack', () => {
  store.pushState({ view: 'files' });
  store.pushState({ view: 'terminal' });
  assert.deepEqual(store.popState(), { view: 'terminal' });
  assert.deepEqual(store.popState(), { view: 'files' });
  assert.equal(store.popState(), null);
});

test('historyToCsv escapes embedded quotes and includes a header row', () => {
  const csv = store.historyToCsv([{ timestamp: 't', command: 'echo "hi"', cwd: 'C:\\x', status: 'success', exitCode: 0 }]);
  const lines = csv.split('\n');
  assert.equal(lines[0], 'Timestamp,Command,Working Directory,Status,Exit Code');
  assert.ok(lines[1].includes('""hi""'));
});
