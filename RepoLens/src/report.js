/**
 * RepoLens - Zero-Dependency Static HTML Report Generator
 * Built using only Node.js standard library (zero external dependencies/CDNs).
 */

const fs = require('fs');
const path = require('path');

/**
 * Escapes special HTML characters to prevent XSS / markup corruption.
 *
 * @param {string} str - Raw string.
 * @returns {string} Safe HTML string.
 */
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Returns a CSS badge class for HTTP methods.
 *
 * @param {string} method - HTTP method (e.g. GET, POST).
 * @returns {string} CSS class name.
 */
function getMethodBadgeClass(method) {
  const m = String(method).toUpperCase();
  switch (m) {
    case 'GET': return 'badge-get';
    case 'POST': return 'badge-post';
    case 'PUT': return 'badge-put';
    case 'PATCH': return 'badge-patch';
    case 'DELETE': return 'badge-delete';
    default: return 'badge-default';
  }
}

/**
 * Generates a standalone, zero-dependency HTML report string from a project analysis report.
 *
 * @param {Object} report - Project analysis report from analyzeProject().
 * @param {Object} [options={}] - Customization options.
 * @param {string} [options.title="RepoLens Repository Report"] - Document title.
 * @returns {string} Self-contained HTML report.
 */
function generateHtmlReport(report, options = {}) {
  if (!report || typeof report !== 'object') {
    throw new TypeError('generateHtmlReport requires a valid report object');
  }

  const project = report.project || { path: 'Unknown', fileCount: 0 };
  const stats = report.statistics || {
    totalFiles: 0,
    totalLines: 0,
    totalBlankLines: 0,
    totalFunctions: 0,
    totalClasses: 0,
    totalTodos: 0,
    totalFixmes: 0,
    largestFile: null
  };
  const arch = report.architecture || {
    graph: {},
    dependencyCounts: {},
    dependentCounts: {},
    entryPoints: [],
    leafModules: [],
    circularDependencies: [],
    mostDependedOn: []
  };
  const recommendations = report.recommendations || [];
  const routes = report.routes || [];

  const title = options.title || 'RepoLens — Repository Intelligence Report';
  const rawJson = JSON.stringify(report, null, 2);

  // Recommendations HTML
  let recommendationsHtml = '';
  if (recommendations.length === 0) {
    recommendationsHtml = `
      <div class="empty-state">
        <p>No starting file recommendations available for this project.</p>
      </div>`;
  } else {
    recommendationsHtml = `
      <div class="recommendations-grid">
        ${recommendations.map((rec, index) => `
          <div class="rec-card ${index === 0 ? 'rec-card-top' : ''}">
            <div class="rec-header">
              <span class="rec-rank">#${index + 1}</span>
              <div class="rec-score-badge">Score: <strong>${rec.score.toFixed(2)}</strong></div>
            </div>
            <div class="rec-path"><code>${escapeHtml(rec.path)}</code></div>
            <ul class="rec-reasons">
              ${rec.reasons.map(r => `<li><span class="rec-bullet">✓</span> ${escapeHtml(r)}</li>`).join('')}
            </ul>
          </div>
        `).join('')}
      </div>`;
  }

  // Circular dependencies banner
  let cyclesHtml = '';
  if (arch.circularDependencies && arch.circularDependencies.length > 0) {
    cyclesHtml = `
      <div class="alert-box alert-warning">
        <div class="alert-title">⚠️ Circular Dependencies Detected (${arch.circularDependencies.length})</div>
        <ul class="cycle-list">
          ${arch.circularDependencies.map(c => `<li><code>${c.map(escapeHtml).join(' &rarr; ')}</code></li>`).join('')}
        </ul>
      </div>`;
  } else {
    cyclesHtml = `
      <div class="alert-box alert-success">
        <span class="alert-icon">✓</span> No circular dependencies detected in the static import graph.
      </div>`;
  }

  // Dependency graph cards
  const graphKeys = Object.keys(arch.graph || {});
  let graphHtml = '';
  if (graphKeys.length === 0) {
    graphHtml = '<p class="text-muted">No module dependencies found.</p>';
  } else {
    graphHtml = `
      <div class="graph-container">
        ${graphKeys.map(file => {
          const imports = arch.graph[file] || [];
          return `
            <div class="graph-card">
              <div class="graph-source">
                <code>${escapeHtml(file)}</code>
                <span class="badge badge-subtle">${imports.length} dep${imports.length === 1 ? '' : 's'}</span>
              </div>
              <div class="graph-targets">
                ${imports.length === 0
                  ? '<span class="text-muted text-small">&empty; imports nothing (leaf module)</span>'
                  : imports.map(imp => `<span class="dep-chip">&rarr; <code>${escapeHtml(imp)}</code></span>`).join('')
                }
              </div>
            </div>
          `;
        }).join('')}
      </div>`;
  }

  // Routes table HTML
  let routesHtml = '';
  if (routes.length === 0) {
    routesHtml = `
      <div class="empty-state">
        <p>No Express-style HTTP route declarations statically detected.</p>
      </div>`;
  } else {
    routesHtml = `
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 100px;">Method</th>
              <th>Route Path</th>
              <th>Handler</th>
              <th>File</th>
            </tr>
          </thead>
          <tbody>
            ${routes.map(r => `
              <tr>
                <td><span class="badge ${getMethodBadgeClass(r.method)}">${escapeHtml(r.method)}</span></td>
                <td><code>${escapeHtml(r.path)}</code></td>
                <td><span class="handler-name">${escapeHtml(r.handler)}</span></td>
                <td><span class="file-path">${escapeHtml(r.file)}</span></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>`;
  }

  // Most Depended On list
  const mostDependedOn = arch.mostDependedOn || [];
  let mostDependedOnHtml = '';
  if (mostDependedOn.length === 0) {
    mostDependedOnHtml = '<p class="text-muted">No dependent information available.</p>';
  } else {
    mostDependedOnHtml = `
      <ul class="depended-list">
        ${mostDependedOn.slice(0, 8).map(item => `
          <li class="depended-item">
            <code>${escapeHtml(item.path)}</code>
            <span class="badge badge-primary">${item.dependents} dependent${item.dependents === 1 ? '' : 's'}</span>
          </li>
        `).join('')}
      </ul>`;
  }

  // Entry points and Leaf modules badges
  const entryPointsHtml = (arch.entryPoints && arch.entryPoints.length > 0)
    ? arch.entryPoints.map(ep => `<span class="pill pill-entry"><code>${escapeHtml(ep)}</code></span>`).join(' ')
    : '<span class="text-muted">None</span>';

  const leafModulesHtml = (arch.leafModules && arch.leafModules.length > 0)
    ? arch.leafModules.slice(0, 15).map(lm => `<span class="pill pill-leaf"><code>${escapeHtml(lm)}</code></span>`).join(' ')
    : '<span class="text-muted">None</span>';

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(title)}</title>
  <style>
    /* Zero-Dependency Clean Light Developer Theme */
    :root {
      --bg-main: #f8fafc;
      --bg-card: #ffffff;
      --border-color: #e2e8f0;
      --border-hover: #cbd5e1;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --text-dim: #94a3b8;
      --primary: #3b82f6;
      --primary-dark: #2563eb;
      --primary-light: #eff6ff;
      --accent-purple: #6366f1;
      --accent-green: #10b981;
      --accent-amber: #f59e0b;
      --accent-red: #ef4444;
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 14px;
      --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
      --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
      --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -4px rgba(0, 0, 0, 0.04);
      --font-system: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }

    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      font-family: var(--font-system);
      background-color: var(--bg-main);
      color: var(--text-main);
      line-height: 1.6;
      padding: 2rem 1rem;
      -webkit-font-smoothing: antialiased;
    }

    .container {
      max-width: 1200px;
      margin: 0 auto;
    }

    /* Header */
    .header {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-lg);
      padding: 2rem;
      margin-bottom: 2rem;
      box-shadow: var(--shadow-sm);
    }

    .header-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      margin-bottom: 0.5rem;
    }

    .brand-title {
      font-size: 2rem;
      font-weight: 800;
      letter-spacing: -0.025em;
      background: linear-gradient(135deg, #1e293b 0%, #3b82f6 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .brand-subtitle {
      font-size: 1rem;
      color: var(--text-muted);
      font-weight: 500;
    }

    .project-meta {
      font-family: var(--font-mono);
      font-size: 0.875rem;
      background: var(--bg-main);
      border: 1px solid var(--border-color);
      padding: 0.5rem 0.875rem;
      border-radius: var(--radius-sm);
      word-break: break-all;
      color: var(--text-muted);
    }

    /* Sections */
    .section {
      margin-bottom: 2.5rem;
    }

    .section-title {
      font-size: 1.35rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 1rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .section-title span {
      color: var(--primary);
    }

    /* Stat Cards Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 1rem;
      margin-bottom: 1rem;
    }

    .stat-card {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 1.25rem;
      box-shadow: var(--shadow-sm);
      transition: transform 0.15s ease, border-color 0.15s ease;
    }

    .stat-card:hover {
      border-color: var(--border-hover);
      transform: translateY(-1px);
    }

    .stat-label {
      font-size: 0.8125rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.25rem;
    }

    .stat-value {
      font-size: 1.875rem;
      font-weight: 800;
      color: var(--text-main);
    }

    .stat-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
    }

    /* Recommendations Grid */
    .recommendations-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1.25rem;
    }

    .rec-card {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 1.5rem;
      box-shadow: var(--shadow-sm);
      position: relative;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }

    .rec-card-top {
      border: 2px solid #93c5fd;
      background: linear-gradient(to bottom, #ffffff, #f0f7ff);
    }

    .rec-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .rec-rank {
      font-size: 1.125rem;
      font-weight: 800;
      color: var(--primary-dark);
      background: var(--primary-light);
      padding: 0.25rem 0.625rem;
      border-radius: var(--radius-sm);
    }

    .rec-score-badge {
      font-size: 0.875rem;
      color: #1e3a8a;
      background: #dbeafe;
      padding: 0.25rem 0.625rem;
      border-radius: 9999px;
      font-weight: 600;
    }

    .rec-path code {
      font-family: var(--font-mono);
      font-size: 0.95rem;
      font-weight: 700;
      color: #0f172a;
      word-break: break-all;
    }

    .rec-reasons {
      list-style: none;
      margin-top: 0.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }

    .rec-reasons li {
      font-size: 0.875rem;
      color: #334155;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .rec-bullet {
      color: var(--accent-green);
      font-weight: bold;
    }

    /* Architecture Grid */
    .arch-layout {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1.5rem;
      margin-bottom: 1.5rem;
    }

    .card {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 1.5rem;
      box-shadow: var(--shadow-sm);
    }

    .card-title {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 0.75rem;
      color: var(--text-main);
    }

    .pills-container {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }

    .pill {
      font-family: var(--font-mono);
      font-size: 0.8125rem;
      padding: 0.25rem 0.5rem;
      border-radius: var(--radius-sm);
      border: 1px solid transparent;
    }

    .pill-entry {
      background: #eff6ff;
      color: #1e40af;
      border-color: #bfdbfe;
    }

    .pill-leaf {
      background: #f1f5f9;
      color: #475569;
      border-color: #cbd5e1;
    }

    .depended-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }

    .depended-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.875rem;
      padding: 0.35rem 0;
      border-bottom: 1px dashed var(--border-color);
    }

    .depended-item:last-child {
      border-bottom: none;
    }

    .depended-item code {
      font-family: var(--font-mono);
      font-size: 0.8125rem;
      color: var(--text-main);
    }

    /* Alerts */
    .alert-box {
      border-radius: var(--radius-md);
      padding: 1rem 1.25rem;
      margin-bottom: 1.5rem;
      font-size: 0.9375rem;
    }

    .alert-success {
      background: #f0fdf4;
      border: 1px solid #bbf7d0;
      color: #166534;
    }

    .alert-warning {
      background: #fffbeb;
      border: 1px solid #fde68a;
      color: #92400e;
    }

    .alert-title {
      font-weight: 700;
      margin-bottom: 0.5rem;
    }

    .cycle-list {
      margin-left: 1.25rem;
      font-family: var(--font-mono);
      font-size: 0.8125rem;
    }

    /* Dependency Graph Cards */
    .graph-container {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 0.75rem;
      max-height: 480px;
      overflow-y: auto;
      padding: 0.25rem;
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      background: var(--bg-main);
    }

    .graph-card {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      padding: 0.75rem;
    }

    .graph-source {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-family: var(--font-mono);
      font-size: 0.8125rem;
      font-weight: 700;
      color: #0f172a;
      margin-bottom: 0.35rem;
    }

    .graph-targets {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }

    .dep-chip {
      font-size: 0.75rem;
      font-family: var(--font-mono);
      background: #f8fafc;
      border: 1px solid var(--border-color);
      padding: 0.15rem 0.4rem;
      border-radius: var(--radius-sm);
      color: #334155;
    }

    /* Table */
    .table-responsive {
      overflow-x: auto;
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-sm);
    }

    .data-table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.875rem;
    }

    .data-table th {
      background: #f8fafc;
      padding: 0.75rem 1rem;
      font-weight: 700;
      color: #475569;
      border-bottom: 1px solid var(--border-color);
    }

    .data-table td {
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border-color);
      color: #1e293b;
    }

    .data-table tr:last-child td {
      border-bottom: none;
    }

    .data-table tr:hover {
      background-color: #f8fafc;
    }

    /* Badges */
    .badge {
      display: inline-block;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      font-weight: 700;
      padding: 0.2rem 0.5rem;
      border-radius: var(--radius-sm);
    }

    .badge-primary { background: #dbeafe; color: #1e40af; }
    .badge-subtle { background: #f1f5f9; color: #475569; }
    .badge-get { background: #dcfce7; color: #166534; }
    .badge-post { background: #dbeafe; color: #1e40af; }
    .badge-put { background: #fef3c7; color: #92400e; }
    .badge-patch { background: #f3e8ff; color: #6b21a8; }
    .badge-delete { background: #fee2e2; color: #991b1b; }
    .badge-default { background: #f1f5f9; color: #334155; }

    .handler-name {
      font-weight: 600;
      color: #4338ca;
    }

    .file-path {
      font-family: var(--font-mono);
      color: #64748b;
      font-size: 0.8125rem;
    }

    /* Signals Bars */
    .signals-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1rem;
    }

    .signal-box {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 1.25rem;
    }

    .progress-bar-bg {
      background: #f1f5f9;
      border-radius: 9999px;
      height: 10px;
      overflow: hidden;
      margin-top: 0.5rem;
    }

    .progress-fill {
      height: 100%;
      border-radius: 9999px;
    }

    .progress-todo { background: var(--accent-amber); }
    .progress-fixme { background: var(--accent-red); }

    /* Raw JSON Section */
    details.raw-json-details {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      overflow: hidden;
    }

    details.raw-json-details summary {
      padding: 1rem 1.25rem;
      cursor: pointer;
      font-weight: 700;
      color: var(--text-main);
      background: #f8fafc;
      user-select: none;
    }

    details.raw-json-details summary:hover {
      background: #f1f5f9;
    }

    .json-code-block {
      padding: 1.25rem;
      background: #0f172a;
      color: #e2e8f0;
      font-family: var(--font-mono);
      font-size: 0.8125rem;
      overflow-x: auto;
      max-height: 480px;
    }

    /* Empty state */
    .empty-state {
      background: var(--bg-card);
      border: 1px dashed var(--border-color);
      border-radius: var(--radius-md);
      padding: 2rem;
      text-align: center;
      color: var(--text-muted);
    }

    .text-muted { color: var(--text-muted); }
    .text-small { font-size: 0.75rem; }

    /* Footer */
    .footer {
      text-align: center;
      color: var(--text-dim);
      font-size: 0.8125rem;
      margin-top: 3rem;
      padding-top: 1.5rem;
      border-top: 1px solid var(--border-color);
    }
  </style>
</head>
<body>

  <div class="container">

    <!-- Header -->
    <header class="header">
      <div class="header-top">
        <div>
          <h1 class="brand-title">RepoLens</h1>
          <p class="brand-subtitle">Repository Intelligence &amp; Architecture Report</p>
        </div>
        <div class="project-meta">
          <strong>Target:</strong> ${escapeHtml(project.path)}
        </div>
      </div>
    </header>

    <!-- Section 1: Project Overview -->
    <section class="section">
      <h2 class="section-title"><span>#1</span> Project Overview</h2>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">JavaScript Files</div>
          <div class="stat-value">${stats.totalFiles}</div>
          <div class="stat-sub">Scanned files</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Total Lines</div>
          <div class="stat-value">${stats.totalLines}</div>
          <div class="stat-sub">${stats.totalBlankLines} blank lines</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Functions</div>
          <div class="stat-value">${stats.totalFunctions}</div>
          <div class="stat-sub">Declared functions</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Classes</div>
          <div class="stat-value">${stats.totalClasses}</div>
          <div class="stat-sub">Declared classes</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">TODOs</div>
          <div class="stat-value" style="color: var(--accent-amber);">${stats.totalTodos}</div>
          <div class="stat-sub">Pending tasks</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">FIXMEs</div>
          <div class="stat-value" style="color: var(--accent-red);">${stats.totalFixmes}</div>
          <div class="stat-sub">Known issues</div>
        </div>
      </div>

      ${stats.largestFile ? `
        <div class="stat-card" style="margin-top: 1rem;">
          <div class="stat-label">Largest File</div>
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.25rem;">
            <code>${escapeHtml(stats.largestFile.path)}</code>
            <span class="badge badge-primary">${stats.largestFile.lines} lines</span>
          </div>
        </div>
      ` : ''}
    </section>

    <!-- Section 2: Where Should I Start? (Top Priority) -->
    <section class="section">
      <h2 class="section-title"><span>#2</span> Where Should I Start?</h2>
      <p class="text-muted" style="margin-bottom: 1rem;">Recommended entry points and core modules ranked by structural importance and logic density.</p>
      ${recommendationsHtml}
    </section>

    <!-- Section 3: Architecture & Dependency Graph -->
    <section class="section">
      <h2 class="section-title"><span>#3</span> Architecture &amp; Dependency Graph</h2>

      ${cyclesHtml}

      <div class="arch-layout">
        <div class="card">
          <h3 class="card-title">Application Entry Points (${arch.entryPoints.length})</h3>
          <div class="pills-container">
            ${entryPointsHtml}
          </div>
        </div>

        <div class="card">
          <h3 class="card-title">Most Depended On Modules</h3>
          ${mostDependedOnHtml}
        </div>

        <div class="card">
          <h3 class="card-title">Leaf Modules (${arch.leafModules.length})</h3>
          <div class="pills-container">
            ${leafModulesHtml}
          </div>
        </div>
      </div>

      <div class="card">
        <h3 class="card-title">Module Dependency Map</h3>
        ${graphHtml}
      </div>
    </section>

    <!-- Section 4: Route Map -->
    <section class="section">
      <h2 class="section-title"><span>#4</span> Route Map</h2>
      <p class="text-muted" style="margin-bottom: 1rem;">Statically detected Express-style HTTP endpoints.</p>
      ${routesHtml}
    </section>

    <!-- Section 5: Code Signals -->
    <section class="section">
      <h2 class="section-title"><span>#5</span> Code Signals</h2>
      <div class="signals-grid">
        <div class="signal-box">
          <div style="display: flex; justify-content: space-between;">
            <strong>TODO Comments</strong>
            <span>${stats.totalTodos}</span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-fill progress-todo" style="width: ${Math.min(100, stats.totalTodos * 10)}%;"></div>
          </div>
        </div>

        <div class="signal-box">
          <div style="display: flex; justify-content: space-between;">
            <strong>FIXME Comments</strong>
            <span>${stats.totalFixmes}</span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-fill progress-fixme" style="width: ${Math.min(100, stats.totalFixmes * 10)}%;"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 6: Raw Data -->
    <section class="section">
      <details class="raw-json-details">
        <summary>View Raw JSON Report</summary>
        <pre class="json-code-block"><code>${escapeHtml(rawJson)}</code></pre>
      </details>
    </section>

    <!-- Footer -->
    <footer class="footer">
      Generated by <strong>RepoLens</strong> &bull; Zero Dependency Codebase Intelligence
    </footer>

  </div>

</body>
</html>`;
}

/**
 * Generates and writes the HTML report to disk.
 *
 * @param {Object} report - Project analysis report object.
 * @param {string} outputPath - Destination file path (e.g., 'repolens-report.html').
 * @param {Object} [options={}] - Report options.
 * @returns {string} Absolute path to the written file.
 */
function writeHtmlReport(report, outputPath, options = {}) {
  if (!outputPath || typeof outputPath !== 'string') {
    throw new TypeError('writeHtmlReport requires an outputPath string');
  }

  const html = generateHtmlReport(report, options);
  const resolvedPath = path.resolve(outputPath);
  fs.writeFileSync(resolvedPath, html, 'utf-8');
  return resolvedPath;
}

module.exports = {
  generateHtmlReport,
  writeHtmlReport,
  escapeHtml
};
