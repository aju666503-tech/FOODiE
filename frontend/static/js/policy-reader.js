(() => {
  const button = document.getElementById('confirm-policy-read');
  const sentinel = document.getElementById('policy-end-sentinel');
  const message = document.getElementById('policy-read-message');
  if (!button || !sentinel || !message) return;
  let reachedEnd = false;
  const policy = location.pathname === '/terms' ? 'terms' : 'privacy';
  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) {
      reachedEnd = true;
      button.disabled = false;
      message.textContent = 'You reached the end. Confirm to return to your account form.';
    }
  }, { threshold: 0.1 });
  observer.observe(sentinel);
  button.addEventListener('click', async () => {
    if (!reachedEnd || button.disabled) return;
    button.disabled = true;
    message.textContent = 'Saving your review confirmation…';
    try {
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content || document.querySelector('input[name="csrf_token"]')?.value || '';
      const body = new URLSearchParams({ csrf_token: csrf, reviewed_to_end: 'true' });
      const response = await fetch(`/policy-reviewed/${policy}`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body, credentials: 'same-origin' });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.message || 'Unable to save your review confirmation.');
      message.textContent = 'Review confirmed. Returning you to your account form…';
      button.innerHTML = '<span aria-hidden="true">✓</span> Confirmed';
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage({ type: 'foodie-policy-reviewed', policy }, location.origin);
        window.close();
      }
      const fallbackUrl = result.return_url || '/register';
      window.setTimeout(() => {
        if (!window.closed) location.href = fallbackUrl;
      }, 450);
    } catch (error) {
      button.disabled = false;
      message.textContent = error.message;
    }
  });
})();
