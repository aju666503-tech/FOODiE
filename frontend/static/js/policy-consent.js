(() => {
  const keys = ['privacy', 'terms'];
  const labels = { privacy: 'Privacy Policy', terms: 'Terms & Conditions' };
  const enable = policy => {
    if (!keys.includes(policy)) return;
    const checkbox = document.getElementById(`${policy}-accepted`);
    const state = document.getElementById(`${policy}-review-state`);
    if (checkbox) checkbox.disabled = false;
    if (state) state.innerHTML = `<b class="reviewed-label">Reviewed</b> · ${labels[policy]} is ready for acknowledgement.`;
  };
  const apply = values => (values || []).forEach(enable);
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.data?.type !== 'foodie-policy-reviewed') return;
    enable(event.data.policy);
  });
  async function refreshReviewStatus() {
    try {
      const response = await fetch('/policy-review-status', { credentials: 'same-origin', cache: 'no-store' });
      if (response.ok) apply((await response.json()).reviewed);
    } catch (_) { /* The user can still return from the policy tab and retry. */ }
  }
  refreshReviewStatus();
  window.setInterval(refreshReviewStatus, 1500);
})();
