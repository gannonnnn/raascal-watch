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
