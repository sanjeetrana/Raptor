'use strict';
// Zero-dependency replacement for the `dialog:*`, `files:*` ipcMain handlers
// in the original Electron main.js. Uses only node:fs, node:path, node:os
// and node:child_process (for opening files/folders/terminals with the
// platform's own tools — the same OS composition the original app used).

const fs = require('node:fs');
const fsp = fs.promises;
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const store = require('./store');

const isWindows = process.platform === 'win32';
const isMac = process.platform === 'darwin';

function safePath(input) {
  if (typeof input !== 'string' || !input.trim()) throw new Error('A valid path is required.');
  return path.resolve(input);
}

function assertName(name) {
  if (typeof name !== 'string' || !name.trim()) throw new Error('A name is required.');
  if (name === '.' || name === '..' || /[\\/\0]/.test(name)) throw new Error('The name contains an invalid path separator.');
  if (/[<>:"|?*]/.test(name)) throw new Error('The name contains characters not allowed by Windows.');
  if (/[. ]$/.test(name)) throw new Error('Windows names cannot end with a dot or space.');
  return name;
}

async function listDir(inputPath, options = {}) {
  const folder = safePath(inputPath);
  const entries = await fsp.readdir(folder, { withFileTypes: true });
  const result = [];
  for (const entry of entries) {
    if (!options.showHidden && entry.name.startsWith('.')) continue;
    const full = path.join(folder, entry.name);
    try {
      const stat = await fsp.stat(full);
      result.push({ name: entry.name, path: full, isDirectory: entry.isDirectory(), size: stat.size, created: stat.birthtimeMs, modified: stat.mtimeMs, ext: entry.isDirectory() ? '' : path.extname(entry.name).toLowerCase() });
    } catch (error) {
      result.push({ name: entry.name, path: full, isDirectory: entry.isDirectory(), inaccessible: true, error: error.message });
    }
  }
  return { path: folder, entries: result };
}

async function properties(inputPath) {
  const target = safePath(inputPath);
  const stat = await fsp.stat(target);
  return { path: target, name: path.basename(target), isDirectory: stat.isDirectory(), size: stat.size, created: stat.birthtimeMs, modified: stat.mtimeMs, accessed: stat.atimeMs, mode: stat.mode };
}

// `shell.openPath` / `shell.openExternal` in Electron wrap the OS's own
// "open with default app" call. The same call is one spawn away on every
// platform, so no third-party "open" package is needed.
function openWithDefaultApp(target) {
  return new Promise((resolve, reject) => {
    let child;
    if (isWindows) child = spawn('cmd.exe', ['/d', '/s', '/c', 'start', '""', target], { windowsHide: true, shell: false });
    else if (isMac) child = spawn('open', [target]);
    else child = spawn('xdg-open', [target]);
    child.on('error', reject);
    child.on('spawn', () => resolve(true));
  });
}

function openTerminalAt(folder) {
  return new Promise((resolve, reject) => {
    let child;
    if (isWindows) child = spawn('cmd.exe', ['/d', '/s', '/c', 'start', '""', 'cmd.exe', '/K', `cd /d "${folder}"`], { windowsHide: true });
    else if (isMac) child = spawn('open', ['-a', 'Terminal', folder]);
    else child = spawn('x-terminal-emulator', ['--working-directory', folder]).on('error', () => {
      // Best-effort fallback for desktops without x-terminal-emulator.
      spawn('gnome-terminal', ['--working-directory', folder]).on('error', () => {});
    });
    child.on('error', reject);
    child.on('spawn', () => resolve(true));
  });
}

async function createEntry(parent, name, kind) {
  const folder = safePath(parent);
  const clean = assertName(name);
  const target = path.join(folder, clean);
  try {
    if (kind === 'folder') await fsp.mkdir(target);
    else await fsp.writeFile(target, '', { flag: 'wx' });
  } catch (e) {
    throw new Error(e.code === 'EEXIST' ? 'A file or folder with that name already exists.' : e.message);
  }
  store.addActivity(kind === 'folder' ? 'Folder created' : 'File created', target, 'Success');
  return target;
}

async function renameEntry(inputPath, newName) {
  const target = safePath(inputPath);
  const clean = assertName(newName);
  const dest = path.join(path.dirname(target), clean);
  if (path.normalize(dest) === path.normalize(target)) return target;
  try { await fsp.rename(target, dest); } catch (e) { throw new Error(e.code === 'EEXIST' ? 'A file or folder with that name already exists.' : e.message); }
  store.addActivity('File renamed', `${target} -> ${dest}`, 'Success');
  return dest;
}

async function copyEntry(source, destinationFolder) {
  const src = safePath(source);
  const destFolder = safePath(destinationFolder);
  const dest = path.join(destFolder, path.basename(src));
  await fsp.cp(src, dest, { recursive: true, errorOnExist: true });
  store.addActivity('File copied', `${src} -> ${dest}`, 'Success');
  return dest;
}

async function moveEntry(source, destinationFolder) {
  const src = safePath(source);
  const destFolder = safePath(destinationFolder);
  const dest = path.join(destFolder, path.basename(src));
  await fsp.rename(src, dest);
  store.addActivity('File moved', `${src} -> ${dest}`, 'Success');
  return dest;
}

// Electron's `shell.trashItem` calls into the native OS Recycle Bin/Trash
// via Windows shell32 / macOS Finder / freedesktop trash — none of which
// are reachable from the standard library alone. The documented,
// zero-dependency trade-off is a same-drive ".mycli-data/trash" folder;
// see STDLIB.md.
async function deleteEntry(inputPath) {
  const target = safePath(inputPath);
  await fsp.mkdir(store.TRASH_DIR, { recursive: true });
  const dest = path.join(store.TRASH_DIR, `${Date.now()}-${crypto.randomUUID().slice(0, 8)}-${path.basename(target)}`);
  await fsp.rename(target, dest);
  store.addActivity('File deleted', target, 'Success', `Moved to ${dest} (application trash folder)`);
  return true;
}

// Backs the in-app folder/file picker that replaces Electron's native
// `dialog.showOpenDialog`. `mode: 'dir'` lists only directories (for
// choosing a folder); `mode: 'file'` also lists files, optionally
// filtered by extension.
async function browse(inputPath, mode = 'dir', extensions = []) {
  const folder = safePath(inputPath || os.homedir());
  const stat = await fsp.stat(folder);
  const dir = stat.isDirectory() ? folder : path.dirname(folder);
  const entries = await fsp.readdir(dir, { withFileTypes: true });
  const allow = new Set(extensions.map((e) => `.${String(e).replace(/^\./, '').toLowerCase()}`));
  const items = [];
  for (const entry of entries) {
    if (entry.name.startsWith('.')) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { items.push({ name: entry.name, path: full, isDirectory: true }); continue; }
    if (mode === 'file' && (allow.size === 0 || allow.has(path.extname(entry.name).toLowerCase()))) {
      items.push({ name: entry.name, path: full, isDirectory: false });
    }
  }
  items.sort((a, b) => (a.isDirectory === b.isDirectory ? a.name.localeCompare(b.name) : a.isDirectory ? -1 : 1));
  const parent = path.dirname(dir);
  return { path: dir, parent: parent === dir ? null : parent, entries: items };
}

module.exports = {
  isWindows, isMac, safePath, assertName, listDir, properties,
  openWithDefaultApp, openTerminalAt, createEntry, renameEntry,
  copyEntry, moveEntry, deleteEntry, browse,
};
