// Zero-dependency replacement for preload.js.
//
// The original app used Electron's contextBridge to expose `window.mycli`,
// backed by ipcRenderer.invoke()/on(). This file exposes the exact same
// `window.mycli` shape — same methods, same arguments — but backed by
// fetch() and an EventSource(SSE) connection to server.js. Nothing here
// depends on anything outside the browser's built-in Fetch/DOM/EventSource
// APIs, so renderer.js and index.html did not need to change.
(() => {
  'use strict';

  async function api(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let message = `${res.status} ${res.statusText}`;
      try { const data = await res.json(); if (data?.error) message = data.error; } catch { /* ignore */ }
      throw new Error(message);
    }
    if (res.status === 204) return null;
    const text = await res.text();
    return text ? JSON.parse(text) : null;
  }

  function qs(params) {
    const usp = new URLSearchParams();
    for (const [key, value] of Object.entries(params || {})) {
      if (value !== undefined && value !== null && value !== '') usp.set(key, value);
    }
    const s = usp.toString();
    return s ? `?${s}` : '';
  }

  function download(path) {
    const frame = document.createElement('iframe');
    frame.style.display = 'none';
    frame.src = path;
    document.body.appendChild(frame);
    setTimeout(() => frame.remove(), 15000);
  }

  // --- In-app folder/file picker, replacing Electron's native dialogs ---
  function openPicker({ mode = 'dir', extensions = [], startPath = '' } = {}) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'mycli-picker-overlay';
      overlay.innerHTML = `
        <div class="mycli-picker">
          <div class="mycli-picker-path"></div>
          <div class="mycli-picker-list"></div>
          <div class="mycli-picker-actions">
            <button type="button" data-act="cancel">Cancel</button>
            ${mode === 'dir' ? '<button type="button" class="primary" data-act="choose">Use this folder</button>' : ''}
          </div>
        </div>`;
      document.body.appendChild(overlay);

      const close = (value) => { overlay.remove(); resolve(value); };
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });
      overlay.querySelector('[data-act="cancel"]').onclick = () => close(null);
      const chooseBtn = overlay.querySelector('[data-act="choose"]');
      if (chooseBtn) chooseBtn.onclick = () => close(current.path);

      let current = { path: startPath };
      async function load(target) {
        const data = await api('GET', `/api/browse${qs({ path: target || '', mode, ext: extensions.join(',') })}`);
        current = data;
        overlay.querySelector('.mycli-picker-path').textContent = data.path;
        const list = overlay.querySelector('.mycli-picker-list');
        const rows = [];
        if (data.parent) rows.push(`<button type="button" class="mycli-picker-row" data-nav="${encodeURIComponent(data.parent)}">.. (up)</button>`);
        for (const entry of data.entries) {
          const icon = entry.isDirectory ? '📁' : '📄';
          rows.push(`<button type="button" class="mycli-picker-row" data-${entry.isDirectory ? 'nav' : 'pick'}="${encodeURIComponent(entry.path)}">${icon} ${entry.name}</button>`);
        }
        list.innerHTML = rows.join('') || '<div class="mycli-picker-empty">No matching entries.</div>';
        list.querySelectorAll('[data-nav]').forEach((b) => { b.onclick = () => load(decodeURIComponent(b.dataset.nav)); });
        list.querySelectorAll('[data-pick]').forEach((b) => { b.onclick = () => close(decodeURIComponent(b.dataset.pick)); });
      }
      load(startPath).catch(() => close(null));
    });
  }

  if (!document.getElementById('mycli-picker-style')) {
    const style = document.createElement('style');
    style.id = 'mycli-picker-style';
    style.textContent = `
      .mycli-picker-overlay { position: fixed; inset: 0; background: rgba(4,10,12,0.72); display: flex; align-items: center; justify-content: center; z-index: 9999; }
      .mycli-picker { width: min(560px, 92vw); max-height: 76vh; display: flex; flex-direction: column; background: #0e1a1d; border: 1px solid #1f3a3f; border-radius: 10px; padding: 14px; gap: 10px; color: #e6f2f1; font: 14px system-ui, sans-serif; }
      .mycli-picker-path { font-family: monospace; font-size: 12px; opacity: 0.75; word-break: break-all; }
      .mycli-picker-list { overflow: auto; display: flex; flex-direction: column; gap: 2px; border: 1px solid #1f3a3f; border-radius: 6px; padding: 6px; min-height: 200px; }
      .mycli-picker-row { text-align: left; background: transparent; border: none; color: inherit; padding: 6px 8px; border-radius: 4px; cursor: pointer; }
      .mycli-picker-row:hover { background: #16292c; }
      .mycli-picker-empty { opacity: 0.6; padding: 8px; }
      .mycli-picker-actions { display: flex; justify-content: flex-end; gap: 8px; }
      .mycli-picker-actions button { padding: 6px 12px; border-radius: 6px; border: 1px solid #1f3a3f; background: #16292c; color: inherit; cursor: pointer; }
      .mycli-picker-actions button.primary { background: #1c7f72; border-color: #1c7f72; }
    `;
    document.head.appendChild(style);
  }

  const listeners = {
    terminalData: [], terminalExit: [], operationData: [],
    historyAdded: [], historyUpdated: [], activityAdded: [],
  };
  const CHANNEL_TO_KEY = {
    'terminal:data': 'terminalData',
    'terminal:exit': 'terminalExit',
    'operation:data': 'operationData',
    'history:added': 'historyAdded',
    'history:updated': 'historyUpdated',
    'activity:added': 'activityAdded',
  };

  function connectEvents() {
    const source = new EventSource('/api/events');
    source.onmessage = (event) => {
      try {
        const { channel, payload } = JSON.parse(event.data);
        const key = CHANNEL_TO_KEY[channel];
        if (key) listeners[key].forEach((cb) => cb(payload));
      } catch { /* ignore malformed frame */ }
    };
    source.onerror = () => { source.close(); setTimeout(connectEvents, 2000); };
  }
  connectEvents();

  function listen(key, callback) {
    listeners[key].push(callback);
    return () => { const i = listeners[key].indexOf(callback); if (i >= 0) listeners[key].splice(i, 1); };
  }

  window.mycli = Object.freeze({
    app: {
      info: () => api('GET', '/api/app/info'),
    },
    dialog: {
      openFile: (options = {}) => openPicker({ mode: 'file', extensions: (options.filters || []).flatMap((f) => f.extensions || []) }),
      openFolder: () => openPicker({ mode: 'dir' }),
      save: async (options = {}) => options.defaultPath || null, // actual export uses direct downloads; see history/activity.export
    },
    files: {
      list: (p, options = {}) => api('GET', `/api/files/list${qs({ path: p, showHidden: options.showHidden })}`),
      properties: (p) => api('GET', `/api/files/properties${qs({ path: p })}`),
      open: (p) => api('POST', '/api/files/open', { path: p }),
      openTerminal: (p) => api('POST', '/api/files/open-terminal', { path: p }),
      create: (parent, name, kind) => api('POST', '/api/files/create', { parent, name, kind }).then((r) => r.path),
      rename: (p, name) => api('POST', '/api/files/rename', { path: p, name }).then((r) => r.path),
      copy: (p, destination) => api('POST', '/api/files/copy', { source: p, destination }).then((r) => r.path),
      move: (p, destination) => api('POST', '/api/files/move', { source: p, destination }).then((r) => r.path),
      delete: (p) => api('POST', '/api/files/delete', { path: p }).then((r) => r.ok),
    },
    terminal: {
      start: (kind, cwd) => api('POST', '/api/terminal/start', { kind, cwd }),
      list: () => api('GET', '/api/terminal/list'),
      run: (sessionId, command) => api('POST', '/api/terminal/run', { sessionId, command }),
      stop: (processId) => api('POST', '/api/terminal/stop', { processId }),
      setCwd: (sessionId, cwd) => api('POST', '/api/terminal/set-cwd', { sessionId, cwd }),
    },
    history: {
      get: () => api('GET', '/api/history'),
      clear: () => api('POST', '/api/history/clear'),
      delete: (id) => api('POST', '/api/history/delete', { id }),
      export: (format = 'json') => { download(`/api/history/export${qs({ format })}`); return Promise.resolve(true); },
    },
    activity: {
      get: () => api('GET', '/api/activity'),
      clear: () => api('POST', '/api/activity/clear'),
      export: () => { download('/api/activity/export'); return Promise.resolve(true); },
    },
    state: {
      push: (value) => api('POST', '/api/state/push', value),
      pop: () => api('POST', '/api/state/pop'),
    },
    system: {
      info: () => api('GET', '/api/system/info'),
      processes: () => api('GET', '/api/system/processes'),
      services: () => api('GET', '/api/system/services'),
      startup: () => api('GET', '/api/system/startup'),
      storage: () => api('GET', '/api/system/storage'),
      network: () => api('GET', '/api/system/network'),
      health: () => api('GET', '/api/system/health'),
      killProcess: (pid) => api('POST', '/api/system/kill-process', { pid }),
      serviceAction: (name, action) => api('POST', '/api/system/service-action', { name, action }),
      tool: (name) => api('POST', '/api/system/tool', { tool: name }),
      runScript: (script, label) => api('POST', '/api/system/run-script', { script, label }),
    },
    apps: {
      installed: () => api('GET', '/api/apps/installed'),
      winget: (args) => api('POST', '/api/apps/winget', { args }),
    },
    installer: {
      run: (p, args) => api('POST', '/api/installer/run', { installer: p, args }),
    },
    settings: {
      get: () => api('GET', '/api/settings'),
      set: (value) => api('POST', '/api/settings', value),
    },
    events: {
      terminalData: (cb) => listen('terminalData', cb),
      terminalExit: (cb) => listen('terminalExit', cb),
      operationData: (cb) => listen('operationData', cb),
      historyAdded: (cb) => listen('historyAdded', cb),
      historyUpdated: (cb) => listen('historyUpdated', cb),
      activityAdded: (cb) => listen('activityAdded', cb),
    },
  });
})();
