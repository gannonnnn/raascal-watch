const scanButton = document.getElementById('scan-button');
const toast = document.getElementById('toast');
const filterForm = document.querySelector('[data-auto-submit-form]');
const filterStatus = document.getElementById('filter-status');

function showToast(message, isError = false) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle('error', isError);
  toast.classList.add('visible');
  window.setTimeout(() => toast.classList.remove('visible'), 4200);
}

if (filterForm) {
  filterForm.querySelectorAll('[data-auto-submit]').forEach((control) => {
    control.addEventListener('change', () => {
      if (filterStatus) filterStatus.textContent = 'Updating…';
      filterForm.classList.add('is-updating');
      // HTMLFormElement.submit() bypasses submit-button assumptions and works
      // even though the old Apply button has intentionally been removed.
      filterForm.submit();
    });
  });
}

// No long-running POST: accept a scan, then poll the cheap status endpoint.
const stopScanButton = document.getElementById('cancel-scan-button');
const progressPanel = document.getElementById('scan-progress-panel');
let reviewerHasUnsavedChanges = false;
let watchedRunId = null;
let refreshedRunId = null;
let lastRunning = false;
let polling = false;

document.querySelectorAll('[data-feedback-form]').forEach((form) => {
  form.addEventListener('input', () => { reviewerHasUnsavedChanges = true; });
  form.addEventListener('change', () => { reviewerHasUnsavedChanges = true; });
});

async function scanRequest(path, options = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(path, { ...options, cache: 'no-store', signal: controller.signal });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Scan request failed');
    return payload;
  } finally { window.clearTimeout(timer); }
}

function renderScanProgress(status) {
  const running = Boolean(status.running);
  lastRunning = running;
  if (running) watchedRunId = status.run_id;
  if (scanButton) {
    scanButton.disabled = running;
    scanButton.textContent = running ? 'Scanning…' : 'Run scan';
  }
  if (stopScanButton) {
    stopScanButton.hidden = !running;
    stopScanButton.disabled = Boolean(status.cancel_requested);
    stopScanButton.textContent = status.cancel_requested ? 'Stopping…' : 'Stop scan';
  }
  const stateLabel = document.getElementById('system-state-text');
  if (stateLabel) stateLabel.textContent = running ? (status.cancel_requested ? 'Stopping' : 'Scanning') : (status.state === 'failed' || status.state === 'partial' ? 'Check source status' : 'Ready');
  document.getElementById('system-state')?.classList.toggle('running', running);
  if (progressPanel) {
    progressPanel.hidden = status.state === 'idle';
    document.getElementById('scan-progress-title').textContent = running ? 'Scan in progress — dashboard remains available' : 'Latest scan';
    document.getElementById('scan-progress-elapsed').textContent = `${Math.floor((status.elapsed_seconds || 0) / 60)}m ${Math.floor((status.elapsed_seconds || 0) % 60)}s`;
    document.getElementById('scan-progress-message').textContent = status.message || '';
    const sources = document.getElementById('scan-progress-sources');
    sources.replaceChildren();
    for (const [name, source] of Object.entries(status.sources || {})) {
      const row = document.createElement('div');
      row.className = 'scan-progress-source';
      const heading = document.createElement('strong'); heading.textContent = name;
      const detail = document.createElement('span');
      detail.textContent = `${source.phase} · ${Number(source.pages || 0).toLocaleString()} pages · ${Number(source.downloaded || 0).toLocaleString()} downloaded · ${Number(source.processed || 0).toLocaleString()} saved · ${Number(source.matches || 0).toLocaleString()} profile matches`;
      row.append(heading, detail);
      if (source.phase === 'processing' && source.downloaded > 0) {
        const bar = document.createElement('progress');
        bar.max = source.downloaded; bar.value = source.processed || 0;
        bar.setAttribute('aria-label', `${name}: processing downloaded records`);
        row.append(bar);
      }
      sources.append(row);
      for (const warning of [...(source.warnings || []), ...(source.error ? [source.error] : [])]) {
        const note = document.createElement('p'); note.className = 'scan-progress-warning'; note.textContent = warning; sources.append(note);
      }
    }
    if (running && status.seconds_since_progress > 30) {
      const note = document.createElement('p');
      note.textContent = 'No new progress recently. The source may be retrying or a batch may be slow. You can stop this scan without deleting saved results.';
      sources.append(note);
    }
  }
  // Do not lose a draft assessment or interrupt an expanded investigation.
  const refreshLink = document.getElementById('scan-results-refresh');
  if (refreshLink) {
    refreshLink.hidden = !status.run_id || (running && !status.processed);
    refreshLink.textContent = running ? 'View saved results so far (scan continues)' : 'Refresh to see saved results';
  }
  if (!running && watchedRunId === status.run_id && refreshedRunId !== status.run_id) {
    refreshedRunId = status.run_id;
    const reading = Boolean(document.querySelector('details[open]'));
    if (!reviewerHasUnsavedChanges && !reading) {
      window.setTimeout(() => { if (!reviewerHasUnsavedChanges && !document.querySelector('details[open]')) window.location.reload(); }, 500);
    } else {
      showToast('Scan finished. Your open review is preserved; refresh when ready.');
    }
  }
}

async function pollScanProgress() {
  if (polling || !progressPanel) return;
  polling = true;
  try { renderScanProgress(await scanRequest('/api/scan/status')); }
  catch (error) {
    progressPanel.hidden = false;
    document.getElementById('scan-progress-message').textContent = 'Cannot reach the local server right now. This does not confirm the scan has stopped. Check Terminal; do not start another copy.';
  } finally {
    polling = false;
    window.setTimeout(pollScanProgress, lastRunning ? 2000 : 5000);
  }
}
if (progressPanel) pollScanProgress();

if (scanButton) {
  scanButton.addEventListener('click', async () => {
    scanButton.disabled = true;
    try { renderScanProgress(await scanRequest('/api/scan', { method: 'POST' })); }
    catch (error) {
      showToast(error.message || 'Could not start scan', true);
      // Check server state before offering another start after a timeout/conflict.
      try { renderScanProgress(await scanRequest('/api/scan/status')); } catch (_) { /* keep disabled until next successful poll */ }
    }
  });
}
if (stopScanButton) {
  stopScanButton.addEventListener('click', async () => {
    stopScanButton.disabled = true;
    try { renderScanProgress(await scanRequest('/api/scan/cancel', { method: 'POST' })); }
    catch (error) { showToast('Stop request could not be confirmed. Check Terminal.', true); }
  });
}

document.querySelectorAll('.contract-review-button').forEach((button) => {
  button.addEventListener('click', async () => {
    const marketId = button.dataset.marketId;
    button.disabled = true;
    button.textContent = 'Saving…';
    try {
      const response = await fetch(`/api/contracts/${marketId}/acknowledge`, { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Could not mark reviewed');
      button.outerHTML = '<span class="acknowledged">Reviewed</span>';
      showToast(`Contract marked reviewed for ${payload.matches_updated} organization match${payload.matches_updated === 1 ? '' : 'es'}.`);
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Mark reviewed';
      showToast(error.message || 'Could not mark reviewed', true);
    }
  });
});

// v0.6 structured reviewer feedback. Each form applies to one profile match,
// not the entire contract, because one market can affect several organizations
// in materially different ways.
const savedScrollTarget = window.sessionStorage.getItem('raascal-scroll-target');
if (savedScrollTarget) {
  window.sessionStorage.removeItem('raascal-scroll-target');
  window.requestAnimationFrame(() => {
    document.getElementById(savedScrollTarget)?.scrollIntoView({ block: 'center' });
  });
}

document.querySelectorAll('[data-feedback-form]').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const matchId = form.dataset.matchId;
    const marketId = form.dataset.marketId;
    const button = form.querySelector('.save-feedback-button');
    const status = form.querySelector('.feedback-save-status');
    const formData = new FormData(form);
    const decision = formData.get('decision');

    if (!decision) {
      showToast('Choose an assessment before saving.', true);
      return;
    }

    if (button) {
      button.disabled = true;
      button.textContent = 'Saving…';
    }
    if (status) status.textContent = 'Saving…';

    const payload = {
      decision,
      reason_codes: formData.getAll('reason_codes'),
      guidance_rating: formData.get('guidance_rating') || null,
      note: formData.get('note') || '',
      corrected_role: formData.get('corrected_role') || '',
      suggested_owner: formData.get('suggested_owner') || '',
    };

    try {
      const response = await fetch(`/api/matches/${matchId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Could not save assessment');
      if (status) status.textContent = 'Saved';
      showToast(`${result.decision_label} assessment saved.`);
      window.sessionStorage.setItem('raascal-scroll-target', `contract-${marketId}`);
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      if (button) {
        button.disabled = false;
        button.textContent = 'Save assessment';
      }
      if (status) status.textContent = '';
      showToast(error.message || 'Could not save assessment', true);
    }
  });
});

// v0.7 source-aware public exposure snapshots. These are deliberately
// on-demand so the dashboard does not make one external request per contract.
function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatNumber(value, maximumFractionDigits = 2) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString(undefined, { maximumFractionDigits });
}

function formatMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const number = Number(value);
  const sign = number < 0 ? '-' : '';
  const absolute = Math.abs(number);
  if (absolute >= 1_000_000) return `${sign}$${(absolute / 1_000_000).toFixed(2)}M`;
  if (absolute >= 1_000) return `${sign}$${(absolute / 1_000).toFixed(1)}K`;
  return `${sign}$${absolute.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatCents(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return `${(Number(value) * 100).toFixed(1)}¢`;
}

function formatTimestamp(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function publicExposurePositionHtml(exposure) {
  const groups = Array.isArray(exposure.position_groups) ? exposure.position_groups : [];
  if (!groups.length) return '';
  return `
    <div class="exposure-section-heading"><strong>Public market positions</strong><span>Wallet labels may be pseudonymous</span></div>
    <div class="exposure-outcomes">${groups.map((group) => {
      const positions = Array.isArray(group.positions) ? group.positions : [];
      const rows = positions.length
        ? positions.map((position) => {
            const pnl = Number(position.total_pnl);
            const pnlClass = Number.isNaN(pnl) || pnl === 0 ? '' : (pnl > 0 ? 'positive-value' : 'negative-value');
            const verified = position.verified_profile ? '<span class="verified-mark">verified</span>' : '';
            return `<tr>
              <td><code title="${escapeHtml(position.wallet || '')}">${escapeHtml(position.display_name || 'Public wallet')}</code>${verified}</td>
              <td>${formatNumber(position.size)}</td>
              <td>${formatCents(position.average_price)}</td>
              <td>${formatMoney(position.current_value)}</td>
              <td class="${pnlClass}">${formatMoney(position.total_pnl)}</td>
            </tr>`;
          }).join('')
        : '<tr><td colspan="5">No public position rows were returned for this outcome.</td></tr>';
      return `<div class="exposure-outcome-card">
        <h6>${escapeHtml(group.outcome || 'Outcome')}</h6>
        <div class="position-table-wrap"><table class="position-table">
          <thead><tr><th>Wallet / profile</th><th>Shares</th><th>Avg. entry</th><th>Current value</th><th>Total P&amp;L</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </div>`;
    }).join('')}</div>`;
}

function publicExposureHolderHtml(exposure) {
  const groups = Array.isArray(exposure.holder_groups) ? exposure.holder_groups : [];
  if (!groups.length) return '';
  return `
    <div class="exposure-section-heading"><strong>Largest publicly returned holders</strong><span>Position profit was not available from this snapshot</span></div>
    <div class="holder-groups">${groups.map((group) => {
      const holders = Array.isArray(group.holders) ? group.holders : [];
      const holdersHtml = holders.length
        ? holders.map((holder) => `<span><code title="${escapeHtml(holder.wallet || '')}">${escapeHtml(holder.display_name || 'Public wallet')}</code> · ${formatNumber(holder.amount)} shares</span>`).join('')
        : '<span>No holder rows returned for this outcome.</span>';
      return `<div class="holder-group"><strong>${escapeHtml(group.outcome || 'Outcome')}</strong>${holdersHtml}</div>`;
    }).join('')}</div>`;
}

function publicExposureTradesHtml(exposure) {
  const trades = Array.isArray(exposure.recent_trades) ? exposure.recent_trades : [];
  if (!trades.length) return '';
  const visibility = exposure.visibility === 'wallet_level' ? 'Wallet-level' : 'Aggregate only';
  return `
    <div class="exposure-section-heading"><strong>Recent publicly returned trades</strong><span>${visibility}</span></div>
    <div class="recent-trades-wrap"><table class="recent-trades-table">
      <thead><tr><th>Time</th><th>Participant visibility</th><th>Outcome / side</th><th>Size</th><th>Price</th></tr></thead>
      <tbody>${trades.map((trade) => `<tr>
        <td>${escapeHtml(formatTimestamp(trade.timestamp))}</td>
        <td><code title="${escapeHtml(trade.wallet || '')}">${escapeHtml(trade.display_name || 'Participant not public')}</code></td>
        <td>${escapeHtml([trade.outcome, trade.side].filter(Boolean).join(' · '))}</td>
        <td>${formatNumber(trade.size)}</td>
        <td>${formatCents(trade.price)}</td>
      </tr>`).join('')}</tbody>
    </table></div>`;
}

function renderPublicExposure(container, exposure) {
  const openInterest = exposure.open_interest == null
    ? ''
    : `<p><strong>Reported open interest:</strong> ${formatNumber(exposure.open_interest)}</p>`;
  const positionsHtml = publicExposurePositionHtml(exposure);
  const holdersHtml = positionsHtml ? '' : publicExposureHolderHtml(exposure);
  const tradesHtml = publicExposureTradesHtml(exposure);
  const sourceWarnings = [
    ['Position detail unavailable', exposure.positions_error],
    ['Holder detail unavailable', exposure.holders_error],
    ['Open-interest detail unavailable', exposure.open_interest_error],
    ['Trade detail unavailable', exposure.trades_error],
  ].filter(([, value]) => value)
    .map(([label, value]) => `<p class="small-muted"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</p>`)
    .join('');
  container.innerHTML = `
    <p><strong>${escapeHtml(exposure.visibility_label || exposure.visibility || 'Public visibility')}:</strong> ${escapeHtml(exposure.detail || '')}</p>
    ${openInterest}
    ${positionsHtml}
    ${holdersHtml}
    ${tradesHtml}
    ${sourceWarnings}
    <small>Snapshot captured ${escapeHtml(formatTimestamp(exposure.captured_at || ''))}. ${escapeHtml(exposure.caveat || '')}</small>
  `;
}

function setExposureButtons(marketId, label, disabled = false) {
  document.querySelectorAll(`[data-load-public-exposure][data-market-id="${CSS.escape(String(marketId))}"]`).forEach((button) => {
    button.disabled = disabled;
    button.textContent = label;
  });
}

function renderExposureEverywhere(marketId, exposure) {
  document.querySelectorAll(`[data-public-exposure-panel][data-market-id="${CSS.escape(String(marketId))}"] [data-public-exposure-content]`).forEach((content) => {
    renderPublicExposure(content, exposure);
  });
}

document.querySelectorAll('[data-load-public-exposure]').forEach((button) => {
  button.addEventListener('click', async () => {
    const marketId = button.dataset.marketId;
    setExposureButtons(marketId, 'Checking…', true);
    try {
      const response = await fetch(`/api/contracts/${encodeURIComponent(marketId)}/public-exposure`, { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Could not load public exposure');
      renderExposureEverywhere(marketId, payload);
      setExposureButtons(marketId, 'Refresh public visibility', false);
      showToast('Public visibility snapshot saved. Visibility is a clue—not a verdict.');
    } catch (error) {
      setExposureButtons(marketId, 'Capture public visibility', false);
      const panels = document.querySelectorAll(`[data-public-exposure-panel][data-market-id="${CSS.escape(String(marketId))}"] [data-public-exposure-content]`);
      panels.forEach((content) => {
        content.innerHTML = `<p class="exposure-error"><strong>Could not capture this source:</strong> ${escapeHtml(error.message || 'Unknown error')}</p>`;
      });
      showToast(error.message || 'Could not load public exposure', true);
    }
  });
});

