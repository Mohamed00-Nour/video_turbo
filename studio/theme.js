(() => {
  'use strict';
  const key = 'video-turbo-theme';
  let theme = 'light';
  try { const saved = localStorage.getItem(key); if (saved === 'light' || saved === 'dark') theme = saved; } catch (_) {}
  document.documentElement.dataset.theme = theme;
  function updateButton() {
    const dark = document.documentElement.dataset.theme === 'dark';
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    button.setAttribute('aria-pressed', String(dark));
    button.setAttribute('aria-label', 'Switch to ' + (dark ? 'light' : 'dark') + ' theme');
    button.title = button.getAttribute('aria-label');
    document.getElementById('theme-label').textContent = dark ? 'Light' : 'Dark';
  }
  document.addEventListener('DOMContentLoaded', () => {
    updateButton();
    document.getElementById('theme-toggle').addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem(key, next); } catch (_) {}
      updateButton();
    });
  });
})();
