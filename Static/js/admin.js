// Format all timestamps in elements with [data-ts]
function formatTimestamps() {
  document.querySelectorAll('[data-ts]').forEach(el => {
    const ts = parseFloat(el.dataset.ts);
    if (!isNaN(ts)) {
      el.textContent = new Date(ts * 1000).toLocaleString();
    }
  });
}

// Busy overlay
function showBusy(msg = "Working…") {
  const el = document.getElementById('busy');
  if (el) {
    el.setAttribute('aria-hidden', 'false');
    const indicator = el.querySelector('.busy-indicator');
    if (indicator) indicator.textContent = msg;
  }
}

function hideBusy() {
  const el = document.getElementById('busy');
  if (el) el.setAttribute('aria-hidden', 'true');
}

// Theme handling
function updateThemeToggleButtons(theme) {
  document.querySelectorAll('[data-theme-toggle]').forEach(toggle => {
    toggle.textContent = theme === 'dark' ? '☀️ Light' : '🌙 Dark';
    toggle.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    toggle.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
  });
}

function applyTheme(theme) {
  const body = document.body;
  body.classList.remove('theme-light', 'theme-dark');
  body.classList.add(theme === 'dark' ? 'theme-dark' : 'theme-light');

  updateThemeToggleButtons(theme);

  try {
    localStorage.setItem('adminTheme', theme);
  } catch (_) {}
}

function initTheme() {
  try {
    const saved = localStorage.getItem('adminTheme');
    const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    const theme = (saved === 'light' || saved === 'dark') ? saved : (prefersDark ? 'dark' : 'light');
    applyTheme(theme);
  } catch (_) {}
}

function bindThemeToggle() {
  const toggles = document.querySelectorAll('[data-theme-toggle]');
  toggles.forEach(toggle => {
    toggle.addEventListener('click', () => {
      const isDark = document.body.classList.contains('theme-dark');
      applyTheme(isDark ? 'light' : 'dark');
    });
  });
}

// Feedback banner
function showFeedback(message, type = 'info') {
  const feedback = document.getElementById('feedback');
  if (!feedback) return;
  feedback.textContent = message;
  feedback.classList.remove('error', 'success');
  feedback.classList.add(type === 'error' ? 'error' : 'success');
  feedback.hidden = false;
  window.setTimeout(() => {
    feedback.hidden = true;
  }, 8000);
}

document.addEventListener('DOMContentLoaded', () => {
  formatTimestamps();
  initTheme();
  bindThemeToggle();
});
