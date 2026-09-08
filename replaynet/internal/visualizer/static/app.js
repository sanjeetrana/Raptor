// ==========================================================================
// REPLAYNET LIVE INSPECTOR - CORE APPLICATION ENGINE
// ==========================================================================

(function () {
  'use strict';

  // State
  let eventsData = [];
  let activeFilter = 'all';
  let searchQuery = '';
  let selectedEvent = null;
  let activePayloadMode = 'formatted';
  let transactionPairs = new Map(); // reqIndex -> { req, resp, rtt }

  // DOM Elements
  const timeline = document.getElementById('timeline');
  const emptyState = document.getElementById('empty-state');
  const statusIndicator = document.getElementById('connection-status');
  const searchInput = document.getElementById('search-input');
  const searchClearBtn = document.getElementById('search-clear-btn');
  const autoscrollToggle = document.getElementById('autoscroll-toggle');
  const clearBtn = document.getElementById('clear-btn');
  const exportJsonBtn = document.getElementById('export-json-btn');
  const simulateDemoBtn = document.getElementById('simulate-demo-btn');
  const emptyDemoBtn = document.getElementById('empty-demo-btn');
  const filterBtns = document.querySelectorAll('.filter-btn');
  const themeBtns = document.querySelectorAll('.theme-btn');

  // Metrics
  const metricTotal = document.getElementById('metric-total');
  const metricRequests = document.getElementById('metric-requests');
  const metricResponses = document.getElementById('metric-responses');
  const metricErrors = document.getElementById('metric-errors');
  const metricLatency = document.getElementById('metric-latency');
  const metricRate = document.getElementById('metric-rate');
  const metricReqSize = document.getElementById('metric-req-size');
  const metricRespSize = document.getElementById('metric-resp-size');
  const metricErrRate = document.getElementById('metric-err-rate');
  const metricMaxOffset = document.getElementById('metric-max-offset');

  // Status Distribution Bar
  const bar2xx = document.getElementById('bar-2xx');
  const bar3xx = document.getElementById('bar-3xx');
  const bar4xx = document.getElementById('bar-4xx');
  const bar5xx = document.getElementById('bar-5xx');
  const legend2xxVal = document.getElementById('legend-2xx-val');
  const legend3xxVal = document.getElementById('legend-3xx-val');
  const legend4xxVal = document.getElementById('legend-4xx-val');
  const legend5xxVal = document.getElementById('legend-5xx-val');

  // Filter Counts
  const countAll = document.getElementById('count-all');
  const countReq = document.getElementById('count-req');
  const countResp = document.getElementById('count-resp');
  const count2xx = document.getElementById('count-2xx');
  const countErr = document.getElementById('count-err');

  // Drawer Elements
  const drawer = document.getElementById('inspector-drawer');
  const drawerCloseBtn = document.getElementById('drawer-close-btn');
  const drawerTitle = document.getElementById('drawer-title');
  const drawerBadge = document.getElementById('drawer-badge');
  const drawerTabs = document.querySelectorAll('.drawer-tab');
  const drawerContents = document.querySelectorAll('.drawer-content');
  const toast = document.getElementById('toast');

  // Drawer Tab 1: Overview
  const drawerIndex = document.getElementById('drawer-index');
  const drawerType = document.getElementById('drawer-type');
  const drawerStatusCode = document.getElementById('drawer-status-code');
  const drawerPath = document.getElementById('drawer-path');
  const drawerOffset = document.getElementById('drawer-offset');
  const drawerSize = document.getElementById('drawer-size');
  const drawerStep2 = document.getElementById('drawer-step-2');
  const drawerStep3 = document.getElementById('drawer-step-3');

  // Drawer Tab 2: Headers
  const headersContainer = document.getElementById('headers-container');
  const copyHeadersBtn = document.getElementById('copy-headers-btn');

  // Drawer Tab 3: Payload
  const payloadViewer = document.getElementById('payload-viewer');
  const payloadFormatBtn = document.getElementById('payload-format-btn');
  const payloadRawBtn = document.getElementById('payload-raw-btn');
  const copyBodyBtn = document.getElementById('copy-body-btn');

  // Drawer Tab 4: cURL
  const curlViewer = document.getElementById('curl-viewer');
  const copyCurlBtn = document.getElementById('copy-curl-btn');

  // Drawer Tab 5: Pair
  const pairContainer = document.getElementById('pair-container');

  const statusTexts = {
    200: '200 OK',
    201: '201 Created',
    202: '202 Accepted',
    204: '204 No Content',
    301: '301 Moved Permanently',
    302: '302 Found',
    304: '304 Not Modified',
    400: '400 Bad Request',
    401: '401 Unauthorized',
    403: '403 Forbidden',
    404: '404 Not Found',
    409: '409 Conflict',
    413: '413 Payload Too Large',
    422: '422 Unprocessable Entity',
    429: '429 Too Many Requests',
    500: '500 Internal Server Error',
    502: '502 Bad Gateway',
    503: '503 Service Unavailable',
    504: '504 Gateway Timeout',
    0: '0 Connection Reset / Dropped'
  };

  // Toast Utility
  let toastTimer = null;
  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2200);
  }

  function copyToClipboard(text, msg = 'Copied to clipboard!') {
    navigator.clipboard.writeText(text).then(() => {
      showToast(msg);
    }).catch(() => {
      showToast('Copied text');
    });
  }

  // Formatting helpers
  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // Syntax highlight JSON
  function syntaxHighlightJson(jsonObj) {
    if (typeof jsonObj !== 'string') {
      jsonObj = JSON.stringify(jsonObj, null, 2);
    }
    jsonObj = escapeHtml(jsonObj);
    return jsonObj.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
      let cls = 'json-number';
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'json-key';
        } else {
          cls = 'json-string';
        }
      } else if (/true|false/.test(match)) {
        cls = 'json-boolean';
      } else if (/null/.test(match)) {
        cls = 'json-null';
      }
      return '<span class="' + cls + '">' + match + '</span>';
    });
  }

  // Topology Packet Flow Animation
  function triggerPacketAnimation(packetId, animClass) {
    const el = document.getElementById(packetId);
    if (!el) return;
    el.classList.remove('anim-forward', 'anim-backward');
    void el.offsetWidth; // force DOM reflow
    el.classList.add(animClass);
  }

  function animateEventFlow(msg) {
    if (msg.type === 'request') {
      triggerPacketAnimation('packet-client-to-proxy', 'anim-forward');
      setTimeout(() => triggerPacketAnimation('packet-proxy-to-upstream', 'anim-forward'), 180);
    } else {
      triggerPacketAnimation('packet-upstream-to-proxy', 'anim-backward');
      setTimeout(() => triggerPacketAnimation('packet-proxy-to-client', 'anim-backward'), 180);
    }
  }

  // Transaction Pairing (Request <-> Response link)
  function pairTransactions() {
    transactionPairs.clear();
    const pendingReqs = [];

    for (let i = 0; i < eventsData.length; i++) {
      const ev = eventsData[i];
      if (ev.type === 'request') {
        pendingReqs.push(ev);
      } else if (ev.type === 'response') {
        if (pendingReqs.length > 0) {
          const req = pendingReqs.shift();
          const rtt = Math.max(0, ev.offsetMs - req.offsetMs);
          transactionPairs.set(req.index, { req, resp: ev, rtt });
          transactionPairs.set(ev.index, { req, resp: ev, rtt });
        }
      }
    }
  }

  // Update Metrics & Progress Bars
  function updateMetrics() {
    let reqs = 0;
    let resps = 0;
    let errs = 0;
    let status2xxCount = 0;
    let status3xxCount = 0;
    let status4xxCount = 0;
    let status5xxCount = 0;
    let totalReqBytes = 0;
    let totalRespBytes = 0;
    let maxOffset = 0;
    let rttSum = 0;
    let rttCount = 0;

    pairTransactions();

    eventsData.forEach(ev => {
      const size = ev.bodySize || (ev.body ? ev.body.length : 0);
      if (ev.offsetMs > maxOffset) maxOffset = ev.offsetMs;

      if (ev.type === 'request') {
        reqs++;
        totalReqBytes += size;
      } else {
        resps++;
        totalRespBytes += size;
        const st = ev.status || 0;
        if (st >= 200 && st < 300) status2xxCount++;
        else if (st >= 300 && st < 400) status3xxCount++;
        else if (st >= 400 && st < 500) {
          status4xxCount++;
          errs++;
        } else if (st >= 500 || st === 0) {
          status5xxCount++;
          errs++;
        }
      }
    });

    transactionPairs.forEach(pair => {
      if (pair.rtt !== undefined) {
        rttSum += pair.rtt;
        rttCount++;
      }
    });

    const avgRtt = rttCount > 0 ? Math.round(rttSum / rttCount) : 0;
    const errRate = resps > 0 ? ((errs / resps) * 100).toFixed(1) : '0.0';

    metricTotal.textContent = eventsData.length;
    metricRequests.textContent = reqs;
    metricResponses.textContent = resps;
    metricErrors.textContent = errs;
    metricLatency.textContent = avgRtt + 'ms';
    metricMaxOffset.textContent = 'Latest: +' + maxOffset + 'ms';
    metricReqSize.textContent = formatBytes(totalReqBytes) + ' sent';
    metricRespSize.textContent = formatBytes(totalRespBytes) + ' received';
    metricErrRate.textContent = errRate + '% error rate';

    if (maxOffset > 0) {
      const rate = ((eventsData.length / (maxOffset / 1000)) || 0).toFixed(1);
      metricRate.textContent = rate + ' ev/sec';
    } else {
      metricRate.textContent = '0.0 ev/sec';
    }

    // Filter counts
    countAll.textContent = eventsData.length;
    countReq.textContent = reqs;
    countResp.textContent = resps;
    count2xx.textContent = status2xxCount;
    countErr.textContent = errs;

    // Status bar distribution
    if (resps > 0) {
      const p2 = ((status2xxCount / resps) * 100).toFixed(0);
      const p3 = ((status3xxCount / resps) * 100).toFixed(0);
      const p4 = ((status4xxCount / resps) * 100).toFixed(0);
      const p5 = ((status5xxCount / resps) * 100).toFixed(0);

      bar2xx.style.width = p2 + '%';
      bar3xx.style.width = p3 + '%';
      bar4xx.style.width = p4 + '%';
      bar5xx.style.width = p5 + '%';

      legend2xxVal.textContent = p2 + '%';
      legend3xxVal.textContent = p3 + '%';
      legend4xxVal.textContent = p4 + '%';
      legend5xxVal.textContent = p5 + '%';
    } else {
      bar2xx.style.width = '0%';
      bar3xx.style.width = '0%';
      bar4xx.style.width = '0%';
      bar5xx.style.width = '0%';
      legend2xxVal.textContent = '0%';
      legend3xxVal.textContent = '0%';
      legend4xxVal.textContent = '0%';
      legend5xxVal.textContent = '0%';
    }
  }

  // Filter Match Logic
  function matchFilter(ev) {
    if (activeFilter === 'request' && ev.type !== 'request') return false;
    if (activeFilter === 'response' && ev.type !== 'response') return false;
    if (activeFilter === 'success' && (ev.type !== 'response' || (ev.status < 200 || ev.status >= 300))) return false;
    if (activeFilter === 'error' && (ev.type !== 'response' || (ev.status < 400 && ev.status !== 0))) return false;

    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    const path = (ev.path || '').toLowerCase();
    const method = (ev.method || '').toLowerCase();
    const status = String(ev.status || '');
    const index = '#' + ev.index;
    const body = (ev.body || '').toLowerCase();

    return path.includes(q) || method.includes(q) || status.includes(q) || index.includes(q) || body.includes(q);
  }

  // Render Table Row
  function renderRow(msg) {
    if (emptyState && emptyState.parentNode) {
      emptyState.style.display = 'none';
    }

    const row = document.createElement('div');
    row.className = 'timeline-row';
    row.dataset.index = msg.index;
    row.dataset.type = msg.type;
    row.id = 'row-' + msg.index;

    const isReq = msg.type === 'request';
    const pair = transactionPairs.get(msg.index);
    const rttText = pair && pair.rtt !== undefined ? `+${pair.rtt}ms` : '—';

    let codeHtml = '';
    let detailsHtml = '';

    if (isReq) {
      const method = msg.method || 'GET';
      codeHtml = `<span class="method-tag method-${method}">${method}</span>`;
      detailsHtml = `<span class="event-path-text">${escapeHtml(msg.path || '/')}</span>`;
    } else {
      const st = msg.status || 0;
      let stClass = 'status-0';
      if (st >= 200 && st < 300) stClass = 'status-2xx';
      else if (st >= 300 && st < 400) stClass = 'status-3xx';
      else if (st >= 400 && st < 500) stClass = 'status-4xx';
      else if (st >= 500) stClass = 'status-5xx';

      const label = statusTexts[st] || (st + ' Status');
      codeHtml = `<span class="status-pill-code ${stClass}">${label}</span>`;

      if (msg.body) {
        const preview = msg.body.length > 50 ? msg.body.substring(0, 50) + '...' : msg.body;
        detailsHtml = `<span class="event-path-text" style="color: var(--text-muted); font-size: 11px;">${escapeHtml(preview)}</span>`;
      } else {
        detailsHtml = `<span class="event-path-text" style="color: var(--text-muted); font-size: 11px;">(empty body)</span>`;
      }
    }

    const badgeClass = isReq ? 'badge-req' : 'badge-resp';
    const badgeText = isReq ? 'REQ' : 'RESP';
    const sizeFormatted = formatBytes(msg.bodySize || (msg.body ? msg.body.length : 0));

    row.innerHTML = `
      <div class="col-idx"><span class="event-index">#${msg.index}</span></div>
      <div class="col-offset"><span class="event-offset">+${msg.offsetMs}ms</span></div>
      <div class="col-delta"><span class="event-delta">${rttText}</span></div>
      <div class="col-flow"><span class="event-flow-badge ${badgeClass}">${badgeText}</span></div>
      <div class="col-code">${codeHtml}</div>
      <div class="col-details">${detailsHtml}</div>
      <div class="col-size"><span class="event-size">${sizeFormatted}</span></div>
      <div class="col-actions"><button class="row-action-btn">Inspect</button></div>
    `;

    if (!matchFilter(msg)) {
      row.classList.add('hidden');
    }

    row.addEventListener('click', () => {
      openInspector(msg);
    });

    timeline.appendChild(row);

    if (autoscrollToggle.checked) {
      timeline.scrollTop = timeline.scrollHeight;
    }
  }

  // Open Inspector Drawer
  function openInspector(msg) {
    selectedEvent = msg;

    // Highlight row
    document.querySelectorAll('.timeline-row').forEach(r => r.classList.remove('selected'));
    const selectedRow = document.getElementById('row-' + msg.index);
    if (selectedRow) selectedRow.classList.add('selected');

    const isReq = msg.type === 'request';
    drawerTitle.textContent = `Event #${msg.index} Inspector`;
    drawerBadge.textContent = isReq ? 'REQUEST' : 'RESPONSE';
    drawerBadge.className = `drawer-badge ${isReq ? 'badge-req' : 'badge-resp'}`;

    // Overview fields
    drawerIndex.textContent = '#' + msg.index;
    drawerType.textContent = isReq ? 'HTTP Request Frame' : 'HTTP Response Frame';
    drawerStatusCode.textContent = isReq ? (msg.method || 'GET') : (statusTexts[msg.status] || msg.status);
    drawerPath.textContent = msg.path || (isReq ? '/' : `Response to #${Math.max(0, msg.index - 1)}`);
    drawerOffset.textContent = `+${msg.offsetMs} ms`;
    drawerSize.textContent = formatBytes(msg.bodySize || (msg.body ? msg.body.length : 0));

    if (isReq) {
      drawerStep2.textContent = 'Forwarded to Upstream Target';
      drawerStep3.textContent = 'Persisted frame to Session Buffer';
    } else {
      drawerStep2.textContent = 'Streamed from Upstream Target';
      drawerStep3.textContent = 'Returned to Client & Recorded';
    }

    // Headers Tab
    headersContainer.innerHTML = '';
    if (msg.headers && Object.keys(msg.headers).length > 0) {
      for (const [key, values] of Object.entries(msg.headers)) {
        const entry = document.createElement('div');
        entry.className = 'header-entry';
        const valStr = Array.isArray(values) ? values.join(', ') : String(values);
        entry.innerHTML = `
          <span class="header-name">${escapeHtml(key)}</span>
          <span class="header-val">${escapeHtml(valStr)}</span>
        `;
        headersContainer.appendChild(entry);
      }
    } else {
      headersContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 12px;">No headers recorded for this event.</div>';
    }

    // Payload Tab
    renderPayloadView();

    // cURL Tab
    renderCurlCommand(msg);

    // Pair Tab
    renderPairView(msg);

    drawer.classList.add('open');
  }

  function renderPayloadView() {
    if (!selectedEvent) return;
    const body = selectedEvent.body || '';

    if (!body) {
      payloadViewer.innerHTML = '<span style="color: var(--text-muted);">(empty payload)</span>';
      return;
    }

    if (activePayloadMode === 'formatted') {
      try {
        const parsed = JSON.parse(body);
        payloadViewer.innerHTML = syntaxHighlightJson(parsed);
      } catch {
        payloadViewer.textContent = body;
      }
    } else {
      payloadViewer.textContent = body;
    }
  }

  function renderCurlCommand(msg) {
    let curl = '';
    if (msg.type === 'request') {
      curl = `curl -X ${msg.method || 'GET'} "http://localhost:9000${msg.path || '/'}"`;
      if (msg.headers) {
        for (const [k, vs] of Object.entries(msg.headers)) {
          const val = Array.isArray(vs) ? vs.join(', ') : vs;
          curl += ` \\\n  -H "${k}: ${val}"`;
        }
      }
      if (msg.body) {
        curl += ` \\\n  -d '${msg.body.replace(/'/g, "\\'")}'`;
      }
    } else {
      curl = `# Response Event #${msg.index} (${statusTexts[msg.status] || msg.status})\n# Target Path: ${msg.path || '/'}\n# Offset: +${msg.offsetMs}ms`;
    }
    curlViewer.textContent = curl;
  }

  function renderPairView(msg) {
    pairContainer.innerHTML = '';
    const pair = transactionPairs.get(msg.index);

    if (!pair) {
      pairContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 12px;">No matching transaction pair found.</div>';
      return;
    }

    const req = pair.req;
    const resp = pair.resp;

    pairContainer.innerHTML = `
      <div class="pair-block">
        <span class="pair-badge badge-req">Request #${req.index}</span>
        <div style="font-family: var(--font-mono); font-size: 12px; font-weight: 700;">${req.method || 'GET'} ${escapeHtml(req.path || '/')}</div>
        <div style="color: var(--text-muted); font-size: 11px;">Offset: +${req.offsetMs}ms • Size: ${formatBytes(req.bodySize || 0)}</div>
      </div>

      <div class="pair-latency-box">
        <span>⏱ Round-Trip Latency:</span>
        <strong style="color: var(--emerald); font-family: var(--font-mono); font-size: 13px;">${pair.rtt}ms</strong>
      </div>

      <div class="pair-block">
        <span class="pair-badge badge-resp">Response #${resp.index}</span>
        <div style="font-family: var(--font-mono); font-size: 12px; font-weight: 700; color: var(--emerald);">${statusTexts[resp.status] || resp.status}</div>
        <div style="color: var(--text-muted); font-size: 11px;">Offset: +${resp.offsetMs}ms • Size: ${formatBytes(resp.bodySize || 0)}</div>
      </div>
    `;
  }

  // Close Drawer
  function closeInspector() {
    drawer.classList.remove('open');
    document.querySelectorAll('.timeline-row').forEach(r => r.classList.remove('selected'));
    selectedEvent = null;
  }

  if (drawerCloseBtn) {
    drawerCloseBtn.addEventListener('click', closeInspector);
  }

  // Drawer Tabs Click
  drawerTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      drawerTabs.forEach(t => t.classList.remove('active'));
      drawerContents.forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      const target = document.getElementById('tab-' + tab.dataset.tab);
      if (target) target.classList.add('active');
    });
  });

  // Drawer Copy Handlers
  if (copyHeadersBtn) {
    copyHeadersBtn.addEventListener('click', () => {
      if (!selectedEvent || !selectedEvent.headers) return;
      copyToClipboard(JSON.stringify(selectedEvent.headers, null, 2), 'Headers copied!');
    });
  }

  if (copyBodyBtn) {
    copyBodyBtn.addEventListener('click', () => {
      if (!selectedEvent || !selectedEvent.body) return;
      copyToClipboard(selectedEvent.body, 'Payload body copied!');
    });
  }

  if (copyCurlBtn) {
    copyCurlBtn.addEventListener('click', () => {
      if (!curlViewer) return;
      copyToClipboard(curlViewer.textContent, 'cURL command copied!');
    });
  }

  // Payload Format Toggle
  if (payloadFormatBtn && payloadRawBtn) {
    payloadFormatBtn.addEventListener('click', () => {
      payloadFormatBtn.classList.add('active');
      payloadRawBtn.classList.remove('active');
      activePayloadMode = 'formatted';
      renderPayloadView();
    });

    payloadRawBtn.addEventListener('click', () => {
      payloadRawBtn.classList.add('active');
      payloadFormatBtn.classList.remove('active');
      activePayloadMode = 'raw';
      renderPayloadView();
    });
  }

  // Filter Buttons
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      applyCurrentFilters();
    });
  });

  // Search Input
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchQuery = e.target.value.trim();
      if (searchClearBtn) {
        searchClearBtn.classList.toggle('visible', searchQuery.length > 0);
      }
      applyCurrentFilters();
    });
  }

  if (searchClearBtn) {
    searchClearBtn.addEventListener('click', () => {
      searchInput.value = '';
      searchQuery = '';
      searchClearBtn.classList.remove('visible');
      applyCurrentFilters();
      searchInput.focus();
    });
  }

  function applyCurrentFilters() {
    const rows = timeline.querySelectorAll('.timeline-row');
    rows.forEach(row => {
      const idx = parseInt(row.dataset.index, 10);
      const ev = eventsData.find(e => e.index === idx);
      if (ev && matchFilter(ev)) {
        row.classList.remove('hidden');
      } else {
        row.classList.add('hidden');
      }
    });
  }

  // Clear Button
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      timeline.innerHTML = '';
      if (emptyState) {
        emptyState.style.display = 'flex';
        timeline.appendChild(emptyState);
      }
      eventsData = [];
      transactionPairs.clear();
      updateMetrics();
      closeInspector();
      showToast('Timeline cleared');
    });
  }

  // Export JSON Button
  if (exportJsonBtn) {
    exportJsonBtn.addEventListener('click', () => {
      if (eventsData.length === 0) {
        showToast('No events to export');
        return;
      }
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(eventsData, null, 2));
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute('download', `replaynet_events_${Date.now()}.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
      showToast('Exported session JSON');
    });
  }

  // Theme Switcher
  themeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      themeBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const theme = btn.dataset.theme;
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('replaynet-theme', theme);
    });
  });

  const savedTheme = localStorage.getItem('replaynet-theme');
  if (savedTheme) {
    document.documentElement.setAttribute('data-theme', savedTheme);
    themeBtns.forEach(b => {
      b.classList.toggle('active', b.dataset.theme === savedTheme);
    });
  }

  // Demo Traffic Simulator (Useful for previewing and offline demonstrations)
  function simulateSampleTraffic() {
    const demoSequence = [
      {
        index: 0,
        offsetMs: 12,
        type: 'request',
        method: 'GET',
        path: '/login',
        headers: { 'User-Agent': ['curl/8.7.1'], 'Accept': ['*/*'] },
        body: '',
        bodySize: 0
      },
      {
        index: 1,
        offsetMs: 38,
        type: 'response',
        path: '/login',
        status: 200,
        headers: { 'Content-Type': ['application/json'], 'Server': ['ReplayNet/1.0'] },
        body: '{"token": "demo_jwt_9921", "user": "charlie", "expires_in": 3600}',
        bodySize: 67
      },
      {
        index: 2,
        offsetMs: 85,
        type: 'request',
        method: 'GET',
        path: '/profile',
        headers: { 'Authorization': ['Bearer demo_jwt_9921'], 'Accept': ['application/json'] },
        body: '',
        bodySize: 0
      },
      {
        index: 3,
        offsetMs: 110,
        type: 'response',
        path: '/profile',
        status: 200,
        headers: { 'Content-Type': ['application/json'] },
        body: '{"name": "Charlie Engineer", "role": "sre", "status": "active", "dept": "platform"}',
        bodySize: 84
      },
      {
        index: 4,
        offsetMs: 160,
        type: 'request',
        method: 'GET',
        path: '/permissions',
        headers: { 'Authorization': ['Bearer demo_jwt_9921'] },
        body: '',
        bodySize: 0
      },
      {
        index: 5,
        offsetMs: 195,
        type: 'response',
        path: '/permissions',
        status: 500,
        headers: { 'Content-Type': ['application/json'] },
        body: '{"error": "database connection pool exhausted", "code": 5001}',
        bodySize: 61
      },
      {
        index: 6,
        offsetMs: 250,
        type: 'request',
        method: 'GET',
        path: '/permissions',
        headers: { 'Authorization': ['Bearer demo_jwt_9921'], 'X-Retry-Attempt': ['1'] },
        body: '',
        bodySize: 0
      },
      {
        index: 7,
        offsetMs: 280,
        type: 'response',
        path: '/permissions',
        status: 200,
        headers: { 'Content-Type': ['application/json'] },
        body: '{"permissions": ["admin", "deploy", "audit"], "retried": true}',
        bodySize: 62
      }
    ];

    let delay = 0;
    demoSequence.forEach(item => {
      setTimeout(() => {
        eventsData.push(item);
        animateEventFlow(item);
        renderRow(item);
        updateMetrics();
      }, delay);
      delay += 350;
    });

    showToast('Simulating realistic demo sequence...');
  }

  if (simulateDemoBtn) simulateDemoBtn.addEventListener('click', simulateSampleTraffic);
  if (emptyDemoBtn) emptyDemoBtn.addEventListener('click', simulateSampleTraffic);

  // Keyboard Navigation
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (drawer.classList.contains('open')) {
        closeInspector();
      } else if (searchInput && document.activeElement === searchInput) {
        searchInput.blur();
      }
    } else if (e.key === '/' && document.activeElement !== searchInput) {
      e.preventDefault();
      if (searchInput) searchInput.focus();
    }
  });

  // SSE Live Stream Connection
  function initSSE() {
    const source = new EventSource('/events');

    source.onopen = function () {
      if (statusIndicator) {
        statusIndicator.className = 'status-pill connected';
        statusIndicator.querySelector('.status-text').textContent = 'SSE Live Stream';
      }
    };

    source.onerror = function () {
      if (statusIndicator) {
        statusIndicator.className = 'status-pill disconnected';
        statusIndicator.querySelector('.status-text').textContent = 'Disconnected';
      }
    };

    source.onmessage = function (e) {
      try {
        const msg = JSON.parse(e.data);
        eventsData.push(msg);
        animateEventFlow(msg);
        renderRow(msg);
        updateMetrics();
      } catch (err) {
        console.error('Error handling SSE message:', err);
      }
    };
  }

  // Initialize
  initSSE();

})();
