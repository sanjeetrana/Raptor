'use strict';
// Zero-dependency replacement for the `terminal:*` ipcMain handlers.
// Same approach as the original: spawn the OS shell with node:child_process
// and stream stdout/stderr chunks back to the client (now over SSE instead
// of Electron IPC). Cross-platform fallback added for non-Windows hosts.

const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const store = require('./store');
const { isWindows } = require('./fsOps');

const processes = new Map();
const terminalSessions = new Map();

function shellFor(kind) {
  if (isWindows) {
    if (kind === 'powershell') return { file: 'powershell.exe', args: ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command'] };
    return { file: process.env.ComSpec || 'cmd.exe', args: ['/d', '/s', '/c'] };
  }
  const shell = process.env.SHELL || '/bin/sh';
  return { file: shell, args: ['-c'] };
}

function runChild({ command, cwd, kind = 'cmd', sessionId, onData, onExit }) {
  const spec = shellFor(kind);
  const child = spawn(spec.file, [...spec.args, command], { cwd, windowsHide: true, env: process.env });
  const id = crypto.randomUUID();
  processes.set(id, child);
  const output = { stdout: '', stderr: '' };
  let settled = false;
  const push = (stream, chunk) => {
    const text = chunk.toString();
    output[stream] += text;
    if (onData) onData({ id, stream, text, sessionId });
  };
  child.stdout.on('data', (d) => push('stdout', d));
  child.stderr.on('data', (d) => push('stderr', d));
  child.on('error', (err) => {
    if (settled) return;
    settled = true;
    push('stderr', Buffer.from(err.message));
    processes.delete(id);
    onExit?.({ id, code: -1, signal: null, output });
  });
  child.on('close', (code, signal) => {
    if (settled) return;
    settled = true;
    processes.delete(id);
    onExit?.({ id, code: code ?? -1, signal, output });
  });
  return id;
}

function updateSessionCwd(session, command) {
  const trimmed = command.trim();
  const match = trimmed.match(/^(?:cd|chdir|Set-Location)\s+(?:\/d\s+)?["']?(.+?)["']?\s*$/i);
  if (!match) return;
  let next = match[1].trim();
  if (next === '..') next = path.dirname(session.cwd);
  else if (!path.isAbsolute(next)) next = path.resolve(session.cwd, next);
  const normalized = path.normalize(next);
  try { if (fs.statSync(normalized).isDirectory()) session.cwd = normalized; } catch { /* keep the last valid directory when cd fails */ }
}

function startSession(kind = isWindows ? 'powershell' : 'sh', cwd = process.cwd()) {
  const id = crypto.randomUUID();
  const folder = path.resolve(cwd);
  const session = { id, kind, cwd: folder };
  terminalSessions.set(id, session);
  return session;
}

function listSessions() { return [...terminalSessions.values()]; }

function setSessionCwd(sessionId, cwd) {
  const session = terminalSessions.get(sessionId);
  if (!session) throw new Error('Terminal session not found.');
  session.cwd = path.resolve(cwd);
  return session;
}

function run(sessionId, command, broadcast) {
  const session = terminalSessions.get(sessionId);
  if (!session) throw new Error('Terminal session not found.');
  const text = String(command || '');
  if (!text.trim()) return { accepted: false };
  const started = Date.now();
  updateSessionCwd(session, text);
  const historyItem = { id: crypto.randomUUID(), timestamp: new Date().toISOString(), command: store.redact(text), cwd: session.cwd, shell: session.kind, status: 'running', exitCode: null, output: '', error: '' };
  store.addHistory(historyItem);
  const processId = runChild({
    command: text,
    cwd: session.cwd,
    kind: session.kind,
    sessionId,
    onData: (chunk) => {
      historyItem[chunk.stream === 'stderr' ? 'error' : 'output'] += store.redact(chunk.text);
      broadcast('terminal:data', chunk);
      broadcast('history:updated', historyItem);
    },
    onExit: ({ code, signal, output }) => {
      historyItem.status = code === 0 ? 'success' : 'failed';
      historyItem.exitCode = code;
      historyItem.durationMs = Date.now() - started;
      historyItem.signal = signal;
      historyItem.output = store.redact(output.stdout);
      historyItem.error = store.redact(output.stderr);
      store.addActivity('Command executed', text, historyItem.status === 'success' ? 'Success' : 'Failed', `Exit code ${code}`);
      broadcast('terminal:exit', { sessionId, processId, code, signal, cwd: session.cwd, historyItem });
      broadcast('history:updated', historyItem);
    },
  });
  return { accepted: true, processId, cwd: session.cwd, historyId: historyItem.id };
}

function stop(processId) {
  const child = processes.get(processId);
  if (!child) return false;
  child.kill();
  return true;
}

module.exports = { runChild, startSession, listSessions, setSessionCwd, run, stop };
