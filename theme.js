// FinGroww Global Theme & Interactive Controller
(function() {
  const THEME_KEY = 'fingroww_theme';
  
  // Initialize theme from storage or system preference
  function getPreferredTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved) return saved;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
    
    // Update theme toggle buttons across the page
    document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
      const icon = btn.querySelector('.theme-icon');
      if (icon) {
        icon.textContent = theme === 'dark' ? '☀️' : '🌙';
      }
      const label = btn.querySelector('.theme-label');
      if (label) {
        label.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
      }
    });
  }

  window.toggleTheme = function() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
  };

  // Run immediately before DOM load to avoid flash
  const initialTheme = getPreferredTheme();
  applyTheme(initialTheme);

  // Setup DOM elements once ready
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(getPreferredTheme());

    // Mobile menu drawer toggle
    const mobileBtn = document.getElementById('mobileMenuBtn');
    const mobileDrawer = document.getElementById('mobileDrawer');
    if (mobileBtn && mobileDrawer) {
      mobileBtn.addEventListener('click', () => {
        const isOpen = mobileDrawer.classList.contains('open');
        if (isOpen) {
          mobileDrawer.classList.remove('open');
          mobileBtn.textContent = '☰';
        } else {
          mobileDrawer.classList.add('open');
          mobileBtn.textContent = '✕';
        }
      });
      // Close on drawer link click
      mobileDrawer.querySelectorAll('a').forEach(a => {
        a.addEventListener('click', () => {
          mobileDrawer.classList.remove('open');
          if (mobileBtn) mobileBtn.textContent = '☰';
        });
      });
    }

    // FAQ accordions
    document.querySelectorAll('.faq-item').forEach(item => {
      const q = item.querySelector('.faq-q') || item.querySelector('.faq-question');
      if (q) {
        q.addEventListener('click', () => {
          const wasActive = item.classList.contains('active');
          document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('active'));
          if (!wasActive) item.classList.add('active');
        });
      }
    });
  });

  // Global Toast Notification Helper
  window.showToast = function(msg, duration = 4000) {
    let toast = document.getElementById('fingrowwToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'fingrowwToast';
      toast.className = 'global-toast';
      document.body.appendChild(toast);
    }
    toast.innerHTML = `<span class="toast-check">✔</span> <span>${msg}</span>`;
    toast.classList.add('show');
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(() => {
      toast.classList.remove('show');
    }, duration);
  };
})();
