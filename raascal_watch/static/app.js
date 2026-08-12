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

if (scanButton) {
  scanButton.addEventListener('click', async () => {
    scanButton.disabled = true;
    scanButton.textContent = 'Scanning…';
    try {
      const response = await fetch('/api/scan', { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Scan failed');
      showToast(`Scan complete: ${payload.fetched} markets, ${payload.new_markets} new, ${payload.notifications} alerts.`);
      // Reload the current URL so organization/source/sort filters remain intact.
      window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      showToast(error.message || 'Scan failed', true);
      scanButton.disabled = false;
      scanButton.textContent = 'Run scan';
    }
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
