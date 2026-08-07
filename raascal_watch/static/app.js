const scanButton = document.getElementById('scan-button');
const toast = document.getElementById('toast');

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle('error', isError);
  toast.classList.add('visible');
  window.setTimeout(() => toast.classList.remove('visible'), 4200);
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
      window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      showToast(error.message || 'Scan failed', true);
      scanButton.disabled = false;
      scanButton.textContent = 'Run scan';
    }
  });
}

document.querySelectorAll('.ack-button').forEach((button) => {
  button.addEventListener('click', async () => {
    const id = button.dataset.matchId;
    button.disabled = true;
    try {
      const response = await fetch(`/api/matches/${id}/acknowledge`, { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Could not acknowledge');
      button.outerHTML = '<span class="acknowledged">Acknowledged</span>';
      showToast('Alert acknowledged.');
    } catch (error) {
      button.disabled = false;
      showToast(error.message || 'Could not acknowledge', true);
    }
  });
});
