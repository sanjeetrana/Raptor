'use strict';
// Zero-dependency replacement for Electron's `app.getPath('userData')` +
// ipcMain history/activity/settings handlers in the original main.js.
// Uses only node:fs, node:path, node:os, node:crypto.

const fs = require('node:fs');
const fsp = fs.promises;
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');

const DATA_DIR = process.env.MYCLI_DATA_DIR || path.join(os.homedir(), '.mycli-data');
const TRASH_DIR = path.join(DATA_DIR, 'trash');
const dataFile = (name) => path.join(DATA_DIR, name);

let history = [];
let activity = [];
let settings = {};
const stateStack = [];

function redact(text = '') {
  return String(text).replace(/(password|passwd|token|secret|apikey|api_key)\s*[=:]\s*[^\s]+/gi, '$1=[redacted]');
}

async function readDefaultSettings() {
  try {
    const raw = await fsp.readFile(path.join(__dirname, '..', 'data', 'config.json'), 'utf8');
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

async function ensureData() {
  await fsp.mkdir(DATA_DIR, { recursive: true });
  await fsp.mkdir(TRASH_DIR, { recursive: true });
  const defaults = await readDefaultSettings();
  for (const [file, fallback] of [['history.json', []], ['activity.json', []], ['settings.json', defaults]]) {
    try {
      JSON.parse(await fsp.readFile(dataFile(file), 'utf8'));
    } catch {
      await fsp.writeFile(dataFile(file), JSON.stringify(fallback, null, 2));
    }
  }
  try { history = JSON.parse(await fsp.readFile(dataFile('history.json'), 'utf8')); } catch { history = []; }
  try { activity = JSON.parse(await fsp.readFile(dataFile('activity.json'), 'utf8')); } catch { activity = []; }
  try { settings = JSON.parse(await fsp.readFile(dataFile('settings.json'), 'utf8')); } catch { settings = defaults; }
}

async function saveJson(file, value) {
  await fsp.writeFile(dataFile(file), JSON.stringify(value, null, 2), 'utf8');
}

let broadcast = () => {}; // wired up by lib/events.js to avoid a circular require
function setBroadcaster(fn) { broadcast = fn; }

function addActivity(action, target, result, details = '') {
  const item = { id: crypto.randomUUID(), timestamp: new Date().toISOString(), action, target: redact(target), result, details: redact(details) };
  activity.unshift(item);
  activity = activity.slice(0, 1000);
  saveJson('activity.json', activity).catch(() => {});
  broadcast('activity:added', item);
  return item;
}

function addHistory(item) {
  history.unshift(item);
  history = history.slice(0, 500);
  saveJson('history.json', history).catch(() => {});
  broadcast('history:added', item);
}

function updateHistory(item) {
  broadcast('history:updated', item);
}

function getHistory() { return history; }
function getActivity() { return activity; }

async function clearHistory() { history = []; await saveJson('history.json', history); }
async function deleteHistoryItem(id) { history = history.filter((item) => item.id !== id); await saveJson('history.json', history); }
async function clearActivity() { activity = []; await saveJson('activity.json', activity); }

async function getSettings() {
  try { return JSON.parse(await fsp.readFile(dataFile('settings.json'), 'utf8')); } catch { return settings; }
}
async function setSettings(value) { settings = value || {}; await saveJson('settings.json', settings); return settings; }

function pushState(value) { stateStack.push(value && typeof value === 'object' ? value : {}); return stateStack.length; }
function popState() { return stateStack.pop() || null; }

function historyToCsv(rows) {
  const header = 'Timestamp,Command,Working Directory,Status,Exit Code';
  const lines = rows.map((x) => [x.timestamp, x.command, x.cwd, x.status, x.exitCode]
    .map((v) => `"${String(v ?? '').replaceAll('"', '""')}"`).join(','));
  return [header, ...lines].join('\n');
}

module.exports = {
  DATA_DIR, TRASH_DIR, redact, ensureData, setBroadcaster,
  addActivity, addHistory, updateHistory, getHistory, getActivity,
  clearHistory, deleteHistoryItem, clearActivity,
  getSettings, setSettings, pushState, popState, historyToCsv,
};
