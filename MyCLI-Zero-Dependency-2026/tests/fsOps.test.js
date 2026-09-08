'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

process.env.MYCLI_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'mycli-data-'));
const fsOps = require('../lib/fsOps');

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'mycli-test-'));
}

test('safePath rejects empty input', () => {
  assert.throws(() => fsOps.safePath(''), /valid path is required/);
  assert.throws(() => fsOps.safePath(null), /valid path is required/);
});

test('safePath resolves relative paths to absolute', () => {
  const resolved = fsOps.safePath('.');
  assert.ok(path.isAbsolute(resolved));
});

test('assertName rejects path separators and reserved characters', () => {
  assert.throws(() => fsOps.assertName('a/b'));
  assert.throws(() => fsOps.assertName('a\\b'));
  assert.throws(() => fsOps.assertName('.'));
  assert.throws(() => fsOps.assertName('..'));
  assert.throws(() => fsOps.assertName('bad:name'));
  assert.throws(() => fsOps.assertName('trailing.'));
  assert.throws(() => fsOps.assertName(''));
});

test('assertName accepts an ordinary file name', () => {
  assert.equal(fsOps.assertName('notes.txt'), 'notes.txt');
});

test('createEntry creates a file and a folder, and rejects duplicates', async () => {
  const dir = tmpDir();
  const filePath = await fsOps.createEntry(dir, 'hello.txt', 'file');
  assert.ok(fs.existsSync(filePath));
  const folderPath = await fsOps.createEntry(dir, 'sub', 'folder');
  assert.ok(fs.statSync(folderPath).isDirectory());
  await assert.rejects(() => fsOps.createEntry(dir, 'hello.txt', 'file'), /already exists/);
});

test('listDir hides dotfiles by default and lists them when requested', async () => {
  const dir = tmpDir();
  fs.writeFileSync(path.join(dir, 'visible.txt'), '');
  fs.writeFileSync(path.join(dir, '.hidden'), '');
  const hidden = await fsOps.listDir(dir, { showHidden: false });
  assert.ok(!hidden.entries.some((e) => e.name === '.hidden'));
  const shown = await fsOps.listDir(dir, { showHidden: true });
  assert.ok(shown.entries.some((e) => e.name === '.hidden'));
});

test('renameEntry, copyEntry and moveEntry round-trip correctly', async () => {
  const dir = tmpDir();
  const destDir = tmpDir();
  const original = await fsOps.createEntry(dir, 'a.txt', 'file');
  const renamed = await fsOps.renameEntry(original, 'b.txt');
  assert.ok(fs.existsSync(renamed));
  assert.ok(!fs.existsSync(original));
  const copied = await fsOps.copyEntry(renamed, destDir);
  assert.ok(fs.existsSync(renamed));
  assert.ok(fs.existsSync(copied));
  const moved = await fsOps.moveEntry(copied, dir);
  assert.ok(!fs.existsSync(copied));
  assert.ok(fs.existsSync(moved));
});

test('deleteEntry moves the target into the application trash folder rather than deleting it', async () => {
  const dir = tmpDir();
  const file = await fsOps.createEntry(dir, 'gone.txt', 'file');
  await fsOps.deleteEntry(file);
  assert.ok(!fs.existsSync(file));
  const trashed = fs.readdirSync(require('../lib/store').TRASH_DIR).some((n) => n.endsWith('gone.txt'));
  assert.ok(trashed, 'expected the deleted file to be recoverable from the trash folder');
});

test('browse lists directories in dir mode and filters by extension in file mode', async () => {
  const dir = tmpDir();
  fs.mkdirSync(path.join(dir, 'child-dir'));
  fs.writeFileSync(path.join(dir, 'app.exe'), '');
  fs.writeFileSync(path.join(dir, 'notes.txt'), '');

  const dirMode = await fsOps.browse(dir, 'dir', []);
  assert.ok(dirMode.entries.every((e) => e.isDirectory));
  assert.ok(dirMode.entries.some((e) => e.name === 'child-dir'));

  const fileMode = await fsOps.browse(dir, 'file', ['exe']);
  const names = fileMode.entries.map((e) => e.name);
  assert.ok(names.includes('app.exe'));
  assert.ok(!names.includes('notes.txt'));
  assert.ok(names.includes('child-dir'));
});
