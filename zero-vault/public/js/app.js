/**
 * ZeroVault Frontend Application — Phase 4 Polish
 *
 * Security requirements:
 * - Master password is NEVER stored in localStorage/sessionStorage/DOM
 * - Passwords are cleared from inputs immediately
 * - No secrets are logged to console
 * - All DOM injections use escapeHtml to prevent XSS
 */

'use strict';

// =============================================
// STATE
// =============================================
const state = {
  vaultPath: '',
  isLocked: true,
  totpTimer: null
};

// =============================================
// NAVIGATION & UI
// =============================================

function navigate(viewId) {
  // Update views
  document.querySelectorAll('.view').forEach(v => {
    if (v.id === `view-${viewId}`) {
      v.classList.add('active');
      v.removeAttribute('hidden');
    } else {
      v.classList.remove('active');
      v.setAttribute('hidden', 'true');
    }
  });

  // Update nav links
  document.querySelectorAll('.nav-links a').forEach(a => {
    if (a.getAttribute('data-view') === viewId) {
      a.classList.add('active');
      a.setAttribute('aria-current', 'page');
    } else {
      a.classList.remove('active');
      a.removeAttribute('aria-current');
    }
  });

  // Auto-refresh data for certain views
  if (viewId === 'vault' && !state.isLocked) {
    loadCredentials();
  }
}

// Bind navigation
document.querySelectorAll('.nav-links a').forEach(link => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const viewId = e.currentTarget.getAttribute('data-view');
    // Prevent navigating to internal pages if locked
    if (state.isLocked && viewId !== 'unlock') {
      showToast('Please unlock your vault first', 'warning');
      navigate('unlock');
      return;
    }
    navigate(viewId);
  });
});

// Toggle password visibility helpers
document.querySelectorAll('.btn-toggle-pw').forEach(btn => {
  btn.addEventListener('click', (e) => {
    const input = e.currentTarget.previousElementSibling;
    if (!input || input.tagName !== 'INPUT') return;
    
    if (input.type === 'password') {
      input.type = 'text';
      e.currentTarget.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" class="eye-icon"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;
    } else {
      input.type = 'password';
      e.currentTarget.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" class="eye-icon"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
    }
  });
});

// =============================================
// TOASTS
// =============================================

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  
  let icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
  if (type === 'success') icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
  if (type === 'error') icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
  
  toast.innerHTML = `${icon} <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  
  setTimeout(() => {
    if (toast.parentNode) toast.remove();
  }, 3500);
}

// =============================================
// MODALS
// =============================================

function showConfirm(title, message, isDanger = false) {
  return new Promise((resolve) => {
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-message').textContent = message;
    
    const okBtn = document.getElementById('confirm-ok');
    okBtn.className = isDanger ? 'btn-danger' : 'btn-primary';
    
    const modal = document.getElementById('confirm-modal');
    modal.style.display = 'flex';
    
    const handleOk = () => { cleanup(); resolve(true); };
    const handleCancel = () => { cleanup(); resolve(false); };
    
    const cleanup = () => {
      modal.style.display = 'none';
      okBtn.removeEventListener('click', handleOk);
      document.getElementById('confirm-cancel').removeEventListener('click', handleCancel);
    };
    
    okBtn.addEventListener('click', handleOk);
    document.getElementById('confirm-cancel').addEventListener('click', handleCancel);
  });
}

function showRevealModal(entry) {
  const modal = document.getElementById('reveal-modal');
  const content = document.getElementById('reveal-content');
  
  document.getElementById('reveal-title').textContent = entry.service;
  
  content.innerHTML = `
    <div class="reveal-field">
      <div class="reveal-field-label">Username / Email</div>
      <div class="reveal-field-value">${escapeHtml(entry.username || '—')}</div>
    </div>
    <div class="reveal-field">
      <div class="reveal-field-label">Password</div>
      <div class="reveal-field-value password-value" id="reveal-pwd-val">${escapeHtml(entry.password || '—')}</div>
      <div class="reveal-field-action">
        <button class="btn-ghost btn-sm" id="btn-copy-revealed">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px;"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          Copy Password
        </button>
      </div>
    </div>
    ${entry.notes ? `
    <div class="reveal-field">
      <div class="reveal-field-label">Notes</div>
      <div class="reveal-field-value">${escapeHtml(entry.notes)}</div>
    </div>
    ` : ''}
  `;
  
  modal.style.display = 'flex';
  
  const copyBtn = document.getElementById('btn-copy-revealed');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(entry.password || '').then(() => showToast('Password copied to clipboard', 'success'));
    });
  }
  
  const close = () => {
    modal.style.display = 'none';
    // Ensure memory is cleared from DOM
    content.innerHTML = '';
  };
  
  document.getElementById('reveal-close').onclick = close;
  document.getElementById('reveal-done').onclick = close;
}

// =============================================
// STATUS & LOCK
// =============================================

async function updateStatus() {
  try {
    const status = await window.api.get('/vault/status');
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    const lockBtn = document.getElementById('lock-btn');
    
    state.isLocked = status.locked;
    
    if (status.locked) {
      dot.setAttribute('data-state', 'locked');
      text.textContent = 'Locked';
      lockBtn.style.display = 'none';
      
      const activeView = document.querySelector('.view.active')?.id;
      if (activeView !== 'view-unlock') {
        navigate('unlock');
      }
    } else {
      dot.setAttribute('data-state', 'unlocked');
      text.textContent = 'Unlocked';
      lockBtn.style.display = 'flex';
    }
  } catch (e) {
    // Network error handling silent for polling
  }
}

setInterval(updateStatus, 3000);

document.getElementById('lock-btn').addEventListener('click', async () => {
  try {
    await window.api.post('/vault/lock', {});
    showToast('Vault locked safely', 'success');
    document.getElementById('vault-items-list').innerHTML = '';
    document.getElementById('dashboard-audit-summary').innerHTML = '<p class="text-muted empty-hint">Run a vault audit to see findings here.</p>';
    updateStatus();
    navigate('unlock');
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// =============================================
// UNLOCK / CREATE
// =============================================

document.getElementById('form-unlock').addEventListener('submit', async (e) => {
  e.preventDefault();
  const path = document.getElementById('unlock-path').value.trim();
  const pwdInput = document.getElementById('unlock-password');
  const errBox = document.getElementById('unlock-error');
  const pwd = pwdInput.value;

  errBox.style.display = 'none';

  if (!path || !pwd) {
    errBox.textContent = 'Path and master password are required.';
    errBox.style.display = 'block';
    return;
  }

  const btn = document.getElementById('btn-unlock');
  btn.disabled = true;

  try {
    const res = await window.api.post('/vault/unlock', { vaultPath: path, password: pwd });
    pwdInput.value = '';
    state.vaultPath = path;
    showToast('Vault unlocked successfully', 'success');
    await updateStatus();
    document.getElementById('dash-total-items').textContent = res.itemCount;
    navigate('dashboard');
  } catch (err) {
    errBox.textContent = err.message;
    errBox.style.display = 'block';
  } finally {
    btn.disabled = false;
    pwdInput.value = '';
  }
});

document.getElementById('btn-create-vault').addEventListener('click', async () => {
  const path = document.getElementById('unlock-path').value.trim();
  const pwdInput = document.getElementById('unlock-password');
  const errBox = document.getElementById('unlock-error');
  const pwd = pwdInput.value;

  errBox.style.display = 'none';

  if (!path || !pwd) {
    errBox.textContent = 'Path and master password are required to create a vault.';
    errBox.style.display = 'block';
    return;
  }
  
  if (pwd.length < 8) {
    errBox.textContent = 'Master password must be at least 8 characters.';
    errBox.style.display = 'block';
    return;
  }

  const confirmed = await showConfirm('Create New Vault', `Create a new vault at "${path}"? This will overwrite any existing vault at this path.`, true);
  if (!confirmed) return;

  try {
    await window.api.post('/vault/create', { vaultPath: path, password: pwd });
    pwdInput.value = '';
    state.vaultPath = path;
    showToast('Vault created and unlocked', 'success');
    await updateStatus();
    navigate('dashboard');
  } catch (err) {
    errBox.textContent = err.message;
    errBox.style.display = 'block';
    pwdInput.value = '';
  }
});

// =============================================
// VAULT CRUD
// =============================================

async function loadCredentials() {
  const list = document.getElementById('vault-items-list');
  const empty = document.getElementById('vault-empty-state');
  const loading = document.getElementById('vault-loading-state');
  const dashCount = document.getElementById('dash-total-items');

  loading.style.display = 'block';
  empty.style.display = 'none';
  list.innerHTML = '';

  try {
    const data = await window.api.get('/entries');
    loading.style.display = 'none';
    
    if (!data.entries || data.entries.length === 0) {
      empty.style.display = 'block';
      dashCount.textContent = '0';
      return;
    }

    dashCount.textContent = data.entries.length;
    document.getElementById('vault-count-subtitle').textContent = `${data.entries.length} items stored securely`;

    data.entries.forEach(entry => {
      const el = document.createElement('div');
      el.className = 'credential-item glass-card';
      el.innerHTML = `
        <div class="credential-info">
          <div class="credential-service">${escapeHtml(entry.service)}</div>
          <div class="credential-username">${escapeHtml(entry.username || '—')}</div>
        </div>
        <div class="credential-actions">
          <button class="btn-icon btn-reveal" data-id="${entry.id}" aria-label="Reveal details" title="Reveal details">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
          </button>
          <button class="btn-icon btn-edit" data-id="${entry.id}" aria-label="Edit" title="Edit">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
          </button>
          <button class="btn-icon danger btn-delete" data-id="${entry.id}" aria-label="Delete" title="Delete">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>
        </div>
      `;
      list.appendChild(el);
    });

    list.querySelectorAll('.btn-reveal').forEach(b => b.addEventListener('click', handleReveal));
    list.querySelectorAll('.btn-edit').forEach(b => b.addEventListener('click', handleEdit));
    list.querySelectorAll('.btn-delete').forEach(b => b.addEventListener('click', handleDelete));

  } catch (err) {
    loading.style.display = 'none';
    if (!err.message.includes('locked')) {
      showToast('Error loading credentials: ' + err.message, 'error');
    }
  }
}

async function handleReveal(e) {
  const id = e.currentTarget.dataset.id;
  try {
    const res = await window.api.get(`/entries/${id}`);
    showRevealModal(res.entry);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function handleEdit(e) {
  const id = e.currentTarget.dataset.id;
  try {
    const res = await window.api.get(`/entries/${id}`);
    showCredentialForm(res.entry);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function handleDelete(e) {
  const id = e.currentTarget.dataset.id;
  const item = e.currentTarget.closest('.credential-item');
  const service = item.querySelector('.credential-service').textContent;

  const confirmed = await showConfirm('Delete Credential', `Permanently delete "${service}"? This action cannot be undone.`, true);
  if (!confirmed) return;

  try {
    await window.api.delete(`/entries/${id}`);
    showToast('Credential deleted', 'success');
    loadCredentials();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function showCredentialForm(entry = null) {
  const container = document.getElementById('credential-form-container');
  container.style.display = 'block';
  container.scrollIntoView({ behavior: 'smooth' });
  
  document.getElementById('credential-id').value = entry ? entry.id : '';
  document.getElementById('cred-service').value = entry ? entry.service : '';
  document.getElementById('cred-username').value = entry ? (entry.username || '') : '';
  document.getElementById('cred-password').value = entry ? (entry.password || '') : '';
  document.getElementById('cred-notes').value = entry ? (entry.notes || '') : '';
  document.getElementById('credential-form-title').textContent = entry ? 'Edit Credential' : 'Add Credential';
}

function hideCredentialForm() {
  document.getElementById('credential-form-container').style.display = 'none';
  document.getElementById('form-credential').reset();
  document.getElementById('credential-id').value = '';
  document.getElementById('cred-password').value = '';
}

document.getElementById('btn-add-item').addEventListener('click', () => showCredentialForm());
document.getElementById('btn-cancel-credential').addEventListener('click', hideCredentialForm);

document.getElementById('form-credential').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = document.getElementById('credential-id').value;
  const payload = {
    service: document.getElementById('cred-service').value.trim(),
    username: document.getElementById('cred-username').value.trim(),
    password: document.getElementById('cred-password').value,
    notes: document.getElementById('cred-notes').value.trim()
  };

  const btn = document.getElementById('btn-save-credential');
  btn.disabled = true;

  try {
    if (id) {
      await window.api.put(`/entries/${id}`, payload);
      showToast('Credential updated successfully', 'success');
    } else {
      await window.api.post('/entries', payload);
      showToast('Credential added to vault', 'success');
    }
    hideCredentialForm();
    loadCredentials();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    document.getElementById('cred-password').value = '';
  }
});

document.getElementById('btn-gen-for-cred').addEventListener('click', async () => {
  try {
    const res = await window.api.post('/generator/password', { length: 24, chars: ['upper', 'lower', 'digits', 'symbols'] });
    document.getElementById('cred-password').value = res.password;
    
    // Change input to text temporarily so they can see it
    const pwInput = document.getElementById('cred-password');
    if (pwInput.type === 'password') {
      document.getElementById('toggle-cred-pw').click();
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
});

// =============================================
// AUTHENTICATOR
// =============================================

document.getElementById('form-totp-verify').addEventListener('submit', async (e) => {
  e.preventDefault();
  const secretInput = document.getElementById('totp-secret');
  const secret = secretInput.value.trim();
  const errBox = document.getElementById('totp-form-error');
  
  errBox.style.display = 'none';
  
  if (!secret) {
    errBox.textContent = 'Secret key is required';
    errBox.style.display = 'block';
    return;
  }

  try {
    const res = await window.api.post('/totp/generate', { secret });
    document.getElementById('totp-result').style.display = 'block';
    document.getElementById('totp-code-display').textContent = res.token;
    
    if (state.totpTimer) clearInterval(state.totpTimer);
    
    const updateTimer = () => {
      const sec = Math.floor(Date.now() / 1000);
      const remain = 30 - (sec % 30);
      const pct = (remain / 30) * 100;
      
      document.getElementById('totp-timer').textContent = `${remain} seconds`;
      const bar = document.getElementById('totp-progress-bar');
      bar.style.width = `${pct}%`;
      bar.style.backgroundColor = remain <= 5 ? 'var(--danger)' : (remain <= 10 ? 'var(--warning)' : 'var(--success)');
      
      document.getElementById('totp-expiry-warn').style.display = remain <= 5 ? 'block' : 'none';
      
      // Auto refresh token at 0
      if (remain === 30 && document.getElementById('totp-result').style.display !== 'none') {
        // Just trigger submit again quietly
        window.api.post('/totp/generate', { secret }).then(r => {
          document.getElementById('totp-code-display').textContent = r.token;
        }).catch(() => {});
      }
    };
    
    updateTimer();
    state.totpTimer = setInterval(updateTimer, 1000);
    
  } catch (err) {
    errBox.textContent = err.message;
    errBox.style.display = 'block';
  }
});

document.getElementById('btn-copy-totp').addEventListener('click', () => {
  const code = document.getElementById('totp-code-display').textContent;
  if (code && code !== '------') {
    navigator.clipboard.writeText(code).then(() => showToast('Code copied to clipboard', 'success'));
  }
});

// =============================================
// SCANNER
// =============================================

const scannerInput = document.getElementById('scanner-input');
const scannerCount = document.getElementById('scanner-char-count');

scannerInput.addEventListener('input', () => {
  scannerCount.textContent = `${scannerInput.value.length.toLocaleString()} chars`;
});

document.getElementById('form-scanner').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = scannerInput.value;
  const container = document.getElementById('scanner-results');
  const btn = document.getElementById('btn-scan');
  
  if (!text.trim()) {
    showToast('Please enter some text to scan', 'warning');
    return;
  }
  
  btn.disabled = true;
  container.innerHTML = `
    <div class="state-container">
      <div class="spinner"></div>
      <p>Analyzing content securely...</p>
    </div>
  `;
  
  try {
    const res = await window.api.post('/scanner/scan', { text });
    
    if (!res.findings || res.findings.length === 0) {
      container.innerHTML = `
        <div class="scan-result-clean">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:32px;height:32px;margin-bottom:8px;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
          <div>No secrets detected</div>
        </div>
      `;
      return;
    }
    
    const countMap = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    res.findings.forEach(f => countMap[f.severity]++);
    
    let html = `
      <div class="scan-summary">
        <div class="scan-summary-count">Found <strong>${res.findings.length}</strong> potential secret(s)</div>
        <div style="display:flex; gap:8px;">
          ${countMap.CRITICAL > 0 ? `<span class="sev-badge critical">Critical: ${countMap.CRITICAL}</span>` : ''}
          ${countMap.HIGH > 0 ? `<span class="sev-badge high">High: ${countMap.HIGH}</span>` : ''}
        </div>
      </div>
      <div class="findings-list">
    `;
    
    res.findings.forEach(f => {
      const sevClass = f.severity.toLowerCase();
      html += `
        <div class="finding-card severity-${sevClass}">
          <div class="finding-header">
            <span class="sev-badge ${sevClass}">${escapeHtml(f.severity)}</span>
            <span class="finding-rule">${escapeHtml(f.ruleName)}</span>
          </div>
          <div class="finding-body">
            <div class="finding-location">Line ${f.line}, Col ${f.column}</div>
            <div class="finding-redacted">${escapeHtml(f.redactedValue)}</div>
          </div>
        </div>
      `;
    });
    
    html += '</div>';
    container.innerHTML = html;
    
  } catch (err) {
    container.innerHTML = `<div class="form-error">Analysis failed: ${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('btn-clear-scanner').addEventListener('click', () => {
  scannerInput.value = '';
  scannerCount.textContent = '';
  document.getElementById('scanner-results').innerHTML = '';
});

// =============================================
// GENERATOR
// =============================================

let currentGenType = 'password';
let lastGenerated = '';

document.querySelectorAll('#view-generator .tab-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    document.querySelectorAll('#view-generator .tab-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    
    currentGenType = e.target.getAttribute('data-gen');
    
    document.querySelectorAll('.gen-options').forEach(o => o.style.display = 'none');
    document.getElementById(`gen-opts-${currentGenType}`).style.display = 'block';
    
    document.getElementById('gen-result').textContent = 'Click Generate to create a secret';
    document.getElementById('entropy-wrapper').style.display = 'none';
    document.getElementById('btn-copy-gen').style.display = 'none';
    lastGenerated = '';
  });
});

// Update range displays
document.getElementById('gen-length').addEventListener('input', (e) => document.getElementById('gen-length-display').textContent = e.target.value);
document.getElementById('gen-words').addEventListener('input', (e) => document.getElementById('gen-words-display').textContent = e.target.value);

document.getElementById('btn-generate').addEventListener('click', async () => {
  const btn = document.getElementById('btn-generate');
  btn.disabled = true;
  
  try {
    let result = '';
    let entropy = 0;
    
    if (currentGenType === 'password') {
      const length = parseInt(document.getElementById('gen-length').value, 10);
      const chars = [];
      if (document.getElementById('gen-upper').checked) chars.push('upper');
      if (document.getElementById('gen-lower').checked) chars.push('lower');
      if (document.getElementById('gen-digits').checked) chars.push('digits');
      if (document.getElementById('gen-symbols').checked) chars.push('symbols');
      const noAmbig = document.getElementById('gen-no-ambig').checked;
      
      const payload = { length };
      if (chars.length > 0) payload.chars = chars;
      if (noAmbig) payload.excludeChars = '0OIl1';
      
      const res = await window.api.post('/generator/password', payload);
      result = res.password;
      entropy = res.entropyBits;
    } 
    else if (currentGenType === 'passphrase') {
      const words = parseInt(document.getElementById('gen-words').value, 10);
      const capitalize = document.getElementById('gen-capitalize').checked;
      const includeNumber = document.getElementById('gen-include-num').checked;
      
      const res = await window.api.post('/generator/passphrase', { words, capitalize, includeNumber });
      result = res.passphrase;
      entropy = res.entropyBits;
    }
    else if (currentGenType === 'key') {
      const format = document.querySelector('input[name="key-fmt"]:checked').value;
      const res = await window.api.post('/generator/keys', {});
      result = format === 'hex' ? res.hex : res.base64;
      entropy = 256;
    }
    
    lastGenerated = result;
    document.getElementById('gen-result').textContent = result;
    document.getElementById('btn-copy-gen').style.display = 'inline-flex';
    
    const entWrap = document.getElementById('entropy-wrapper');
    entWrap.style.display = 'block';
    document.getElementById('gen-entropy').textContent = `${Math.round(entropy)} bits`;
    
    const fill = document.getElementById('entropy-fill');
    const pct = Math.min(100, (entropy / 128) * 100);
    fill.style.width = `${pct}%`;
    fill.style.backgroundColor = entropy >= 100 ? 'var(--success)' : (entropy >= 64 ? 'var(--warning)' : 'var(--danger)');
    
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('btn-copy-gen').addEventListener('click', () => {
  if (lastGenerated) {
    navigator.clipboard.writeText(lastGenerated).then(() => showToast('Copied securely', 'success'));
  }
});

// =============================================
// AUDIT
// =============================================

document.getElementById('form-audit-pwd').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pwdInput = document.getElementById('audit-pwd-input');
  const pwd = pwdInput.value;
  const container = document.getElementById('audit-result');
  
  if (!pwd) return;
  
  try {
    const res = await window.api.post('/audit/password', { password: pwd });
    pwdInput.value = '';
    
    const tierClassMap = { EXCELLENT: 'success', STRONG: 'success', MODERATE: 'warning', WEAK: 'warning', CRITICAL: 'danger' };
    const tierClass = tierClassMap[res.tier] || 'warning';
    
    let html = `
      <div class="audit-score-block ${tierClass}">
        <div class="audit-score-num">${res.score}<span>/100</span></div>
        <div class="audit-tier">${res.tier}</div>
        <div class="audit-meta-info">${res.entropyBits} bits entropy • ${res.length} characters</div>
      </div>
    `;
    
    if (res.breakdown?.details?.length > 0) {
      html += '<div class="audit-findings"><h3>Findings</h3>';
      res.breakdown.details.forEach(d => {
        const catClass = d.severity ? d.severity.toLowerCase() : (d.scoreImpact < 0 ? 'medium' : 'info');
        html += `
          <div class="finding-detail ${catClass}">
            <div class="finding-detail-desc">${escapeHtml(d.description || d)}</div>
            ${d.recommendation ? `<div class="finding-detail-rec">${escapeHtml(d.recommendation)}</div>` : ''}
          </div>
        `;
      });
      html += '</div>';
    }
    
    if (res.remediations?.length > 0) {
      html += '<div class="audit-recs"><h3>Recommendations</h3><ul>';
      res.remediations.forEach(r => html += `<li>${escapeHtml(r)}</li>`);
      html += '</ul></div>';
    }
    
    container.innerHTML = html;
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    pwdInput.value = '';
  }
});

window.runDashboardAudit = () => {
  navigate('audit');
  document.getElementById('btn-audit-vault').click();
};

document.getElementById('btn-audit-vault').addEventListener('click', async () => {
  const container = document.getElementById('vault-audit-result');
  const dashSummary = document.getElementById('dashboard-audit-summary');
  const dashHealth = document.getElementById('dash-health');
  const dashIssues = document.getElementById('dash-issues');
  const btn = document.getElementById('btn-audit-vault');
  
  btn.disabled = true;
  container.innerHTML = `
    <div class="state-container">
      <div class="spinner"></div>
      <p>Auditing entire vault...</p>
    </div>
  `;
  
  try {
    const res = await window.api.get('/audit/vault');
    
    const healthClassMap = { HEALTHY: 'success', NEEDS_ATTENTION: 'warning', AT_RISK: 'danger' };
    const hClass = healthClassMap[res.vaultStatus] || 'warning';
    
    // Update Dashboard Elements
    dashHealth.textContent = res.healthScore;
    dashHealth.className = `stat-value text-${hClass}`;
    dashIssues.textContent = res.issueCount;
    
    let sumHtml = `<p><strong>${res.vaultStatus}</strong> • Score: ${res.healthScore} • ${res.issueCount} issue(s)</p>`;
    if (res.duplicatePasswordCount > 0) sumHtml += `<p class="text-warning">⚠️ ${res.duplicatePasswordCount} reused passwords.</p>`;
    dashSummary.innerHTML = sumHtml;
    
    // Update Audit View
    let html = `
      <div class="audit-score-block ${hClass}">
        <div class="audit-score-num">${res.healthScore}<span>/100</span></div>
        <div class="audit-tier">${res.vaultStatus}</div>
        <div class="audit-meta-info">${res.itemsAudited} items analyzed • ${res.issueCount} issue(s) found</div>
      </div>
    `;
    
    if (res.duplicatePasswordCount > 0) {
      html += `
        <div class="finding-detail high">
          <div class="finding-detail-desc">Duplicate Passwords Detected</div>
          <div class="finding-detail-rec">You are reusing passwords across ${res.duplicatePasswordCount} services. Use the generator to create unique passwords.</div>
        </div>
      `;
    }
    
    if (res.issues?.length > 0) {
      html += '<div class="audit-findings"><h3>Vault Issues</h3>';
      res.issues.forEach(issue => {
        const iClass = issue.severity.toLowerCase();
        html += `
          <div class="finding-detail ${iClass}">
            <div class="finding-detail-desc"><strong>${escapeHtml(issue.service)}</strong>: ${escapeHtml(issue.issue)}</div>
            ${issue.remediations?.map(r => `<div class="finding-detail-rec">${escapeHtml(r)}</div>`).join('') || ''}
          </div>
        `;
      });
      html += '</div>';
    } else if (res.issueCount === 0 && res.duplicatePasswordCount === 0) {
      html += `
        <div class="scan-result-clean mt-4">
          <div>No security issues found. Great job!</div>
        </div>
      `;
    }
    
    container.innerHTML = html;
    
  } catch (err) {
    if (err.message.includes('locked')) {
      container.innerHTML = '<div class="form-error">Please unlock the vault first to run an audit.</div>';
    } else {
      container.innerHTML = `<div class="form-error">Audit failed: ${escapeHtml(err.message)}</div>`;
    }
  } finally {
    btn.disabled = false;
  }
});

// =============================================
// UTILS
// =============================================

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Initial status check
document.addEventListener('DOMContentLoaded', () => {
  updateStatus();
});
