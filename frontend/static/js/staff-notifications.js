(() => {
  const panel = document.getElementById('staff-notifications');
  const list = document.getElementById('staff-notification-list');
  const count = document.getElementById('staff-notification-count');
  if (!panel || !list || !count) return;
  let known = new Set(Array.from(list.querySelectorAll('a')).map(a => a.dataset.notificationId).filter(Boolean));
  const safe = value => String(value ?? '');
  async function refresh() {
    try {
      const response = await fetch(panel.dataset.feedUrl, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) return;
      const data = await response.json();
      const rows = data.notifications || [];
      count.textContent = `${rows.length} unread`;
      if (!rows.length) {
        list.innerHTML = '<p class="muted">No new notifications. This panel checks for new orders automatically.</p>';
        known.clear();
        return;
      }
      list.replaceChildren();
      rows.forEach(row => {
        const link = document.createElement('a');
        link.className = 'staff-notification-item';
        link.href = row.link || '/staff';
        link.dataset.notificationId = safe(row.id);
        const icon = document.createElement('span'); icon.className = 'staff-notification-icon'; icon.textContent = '●';
        const body = document.createElement('span');
        const title = document.createElement('b'); title.textContent = safe(row.title);
        const message = document.createElement('small'); message.textContent = safe(row.message);
        const time = document.createElement('small'); time.className = 'notification-time'; time.textContent = safe(row.created_at);
        body.append(title, message, time);
        const badge = document.createElement('span'); badge.className = 'notification-new'; badge.textContent = 'NEW';
        if (!known.has(safe(row.id))) { link.classList.add('notification-arrived'); }
        link.append(icon, body, badge); list.append(link);
      });
      known = new Set(rows.map(row => safe(row.id)));
    } catch (_) { /* Keep the last visible notification list if polling is temporarily unavailable. */ }
  }
  refresh();
  window.setInterval(refresh, 10000);
})();
