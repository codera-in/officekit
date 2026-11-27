(function (global) {
  'use strict';

  const TOUR_SEEN_KEY = 'officekit.tour.seen_v1';
  const TOUR_VERSION_KEY = 'officekit.tour.version';
  const TOUR_DONT_SHOW_KEY = 'officekit.tour.dont_show';

  function getAppVersion() {
    try {
      const el = document.getElementById('app-build-version');
      if (el && el.textContent) {
        const match = el.textContent.match(/\d+(?:\.\d+)+/);
        if (match) return match[0];
      }
    } catch (_) {}
    return '1.0.0';
  }

  // Patch releases ship on every merge, so only a new major.minor counts as an update worth a tour.
  function tourEpoch(version) {
    return String(version || '').split('.').slice(0, 2).join('.');
  }

  function shouldAutoStart(options = {}) {
    if (options.force) return true;
    try {
      if (typeof window !== 'undefined') {
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('tour') === 'auto') return true;
        if (urlParams.get('tour') === 'off') return false;
        if (window.OFFICEKIT_DISABLE_AUTO_TOUR) return false;
        if (window.OFFICEKIT_ENABLE_AUTO_TOUR) return true;
        // In Playwright/WebDriver automation, avoid interrupting other tests unless explicit
        if (navigator.webdriver && !options.allowInTests) {
          return false;
        }
      }

      const seen = localStorage.getItem(TOUR_SEEN_KEY);
      const dontShow = localStorage.getItem(TOUR_DONT_SHOW_KEY) === 'true';
      const lastVersion = localStorage.getItem(TOUR_VERSION_KEY);
      const currentVersion = getAppVersion();

      // 1. User Preference: If "Don't show on start" was chosen and version hasn't changed, suppress auto-start
      if (dontShow && tourEpoch(lastVersion) === tourEpoch(currentVersion)) {
        return false;
      }

      // 2. Fresh Install: Tour has never been seen
      if (!seen) {
        return true;
      }

      // 3. Version Update: Seen on a previous version, but app version changed
      if (lastVersion && tourEpoch(lastVersion) !== tourEpoch(currentVersion)) {
        return true;
      }

      return false;
    } catch (_) {
      return false;
    }
  }

  let autoStartExecuted = false;

  function checkAutoStart(options = {}) {
    if (autoStartExecuted && !options.force) return false;
    if (!shouldAutoStart(options)) return false;
    // First-run setup comes first; the tour starts when the setup dialog closes.
    if (global.officekitSetup?.isOpen?.()) {
      global.document.addEventListener('officekit:setup-closed', () => checkAutoStart(options), { once: true });
      return false;
    }
    autoStartExecuted = true;
    const delay = options.immediate ? 0 : 350;
    setTimeout(() => {
      if (!isOpen) {
        start(0);
      }
    }, delay);
    return true;
  }

  function resetTourPreferences() {
    try {
      localStorage.removeItem(TOUR_SEEN_KEY);
      localStorage.removeItem(TOUR_VERSION_KEY);
      localStorage.removeItem(TOUR_DONT_SHOW_KEY);
    } catch (_) {}
  }

  const steps = [
    {
      tab: 'tools',
      target: () => {
        const badge = document.getElementById('officekit-privacy-badge');
        if (badge && badge.getBoundingClientRect && badge.getBoundingClientRect().width > 0) return badge;
        return document.getElementById('officekit-tour-trigger') || document.querySelector('.ok-header-actions');
      },
      badge: 'Step 1 of 7 · On-Device Privacy',
      title: '100% Private & On-Device',
      icon: 'fa-shield-halved text-emerald-500',
      desc: 'All 124 tools, PDF conversions, audio files, and calculations run strictly on your Mac. Nothing is ever sent to external cloud servers.',
    },
    {
      tab: 'tools',
      target: () => {
        const search = document.getElementById('global-search-trigger');
        if (search && search.getBoundingClientRect && search.getBoundingClientRect().width > 0) return search;
        return document.querySelector('.ok-header-actions');
      },
      badge: 'Step 2 of 7 · Global Quick Search',
      title: 'Spotlight Quick Search (⌘K)',
      icon: 'fa-magnifying-glass text-sky-500',
      desc: 'Press ⌘K anywhere in OfficeKit to instantly search and open any tool, format converter, or financial calculator with keyboard filtering.',
    },
    {
      tab: 'dictate',
      target: () => document.querySelector('#tab-dictate h1, #tab-dictate h2'),
      badge: 'Step 3 of 7 · STT & System Rights',
      title: 'Speech-to-Text & System Rights',
      icon: 'fa-microphone text-rose-500',
      desc: 'Local speech transcription powered by Whisper. Requires macOS Microphone and Accessibility rights to enable global Push-to-Talk (PTT) into any Mac app.',
    },
    {
      tab: 'clipboard',
      target: () => document.querySelector('#tab-clipboard h1, #tab-clipboard h2'),
      badge: 'Step 4 of 7 · Clipboard & Snippets',
      title: 'Clipboard History & Snippets Studio',
      icon: 'fa-clipboard-check text-cyan-500',
      desc: 'Local-first clipboard history (⌥V) with privacy filter concealing passwords, quick 1–9 paste, full item deletion, and reusable dynamic snippet templates.',
    },
    {
      tab: 'tools',
      target: () => {
        const winSnap = document.getElementById('officekit-window-snap');
        if (winSnap && winSnap.getBoundingClientRect && winSnap.getBoundingClientRect().width > 0) return winSnap;
        return document.querySelector('.ok-header-utilities') || document.getElementById('stt-floating-hud');
      },
      badge: 'Step 5 of 7 · Window Arrangement & HUD',
      title: 'Floating HUD & Menu Bar Telemetry',
      icon: 'fa-window-restore text-indigo-500',
      desc: 'Use the floating dictation overlay HUD that stays visible above other apps, or pin live system telemetry directly into your macOS menu bar.',
    },
    {
      tab: 'workspace',
      target: () => document.querySelector('#tab-workspace h1, #tab-workspace h2') || document.getElementById('quick-volume'),
      badge: 'Step 6 of 7 · Storage & Vault',
      title: 'Storage Analyzer & Local Cleanup',
      icon: 'fa-database text-amber-500',
      desc: 'Analyze disk usage, find duplicate files, and strip sensitive metadata locally without compromising private documents.',
    },
    {
      tab: 'activity',
      target: () => document.querySelector('[data-sidebar-tab="activity"]'),
      badge: 'Step 7 of 7 · Activity Monitor',
      title: 'Live Activity Monitor',
      icon: 'fa-list-check text-sky-500',
      desc: 'Monitor background operations (PDF exports, duplicate scans, storage indexing) with live progress and cancel controls right in the sidebar.',
    }
  ];

  let currentStep = 0;
  let isOpen = false;
  let modalEl = null;
  let initialTab = null;

  function ensureModal() {
    if (modalEl) return modalEl;
    modalEl = document.createElement('div');
    modalEl.id = 'officekit-tour-modal';
    modalEl.className = 'fixed inset-0 z-[100] overflow-hidden pointer-events-auto transition-opacity';
    modalEl.setAttribute('role', 'dialog');
    modalEl.setAttribute('aria-modal', 'true');
    modalEl.setAttribute('aria-label', 'OfficeKit Tour');
    modalEl.hidden = true;

    modalEl.innerHTML = `
      <div id="officekit-tour-spotlight" class="ok-tour-spotlight" style="opacity: 0;"></div>
      <div id="officekit-tour-card" class="fixed z-[105] w-full max-w-sm rounded-2xl border border-slate-200 dark:border-white/15 bg-white dark:bg-slate-900 p-6 shadow-2xl transition-all duration-300 pointer-events-auto">
        <div id="officekit-tour-arrow" class="arrow-hidden"></div>
        <div class="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-white/10 mb-3">
          <span id="officekit-tour-badge" class="text-[11px] font-bold text-sky-600 dark:text-sky-400 uppercase tracking-wider"></span>
          <button type="button" id="officekit-tour-close" aria-label="Close tour" class="text-slate-400 hover:text-slate-600 dark:hover:text-white p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 btn btn-ghost">
            <i class="fa-solid fa-xmark text-sm" aria-hidden="true"></i>
          </button>
        </div>
        <div class="flex items-start gap-3 mb-3">
          <div id="officekit-tour-icon" class="w-10 h-10 rounded-xl bg-slate-100 dark:bg-white/10 flex items-center justify-center text-lg shrink-0"></div>
          <div>
            <h3 id="officekit-tour-title" class="text-base font-bold text-slate-900 dark:text-white"></h3>
            <p id="officekit-tour-desc" class="text-xs text-slate-600 dark:text-slate-300 mt-1 leading-relaxed"></p>
          </div>
        </div>
        <div class="flex items-center justify-between pt-4 border-t border-slate-100 dark:border-white/10 mt-4">
          <div id="officekit-tour-dots" class="flex items-center gap-1.5"></div>
          <div class="flex items-center gap-2">
            <button type="button" id="officekit-tour-prev" class="btn btn-xs btn-ghost text-slate-500 dark:text-slate-400">Back</button>
            <button type="button" id="officekit-tour-next" class="btn btn-xs btn-primary">Next</button>
          </div>
        </div>
        <div class="flex items-center justify-between text-[11px] text-slate-400 mt-3 pt-2">
          <label class="flex items-center gap-1.5 cursor-pointer select-none">
            <input type="checkbox" id="officekit-tour-dont-show" class="checkbox checkbox-xs checkbox-primary" />
            <span>Don't show on start</span>
          </label>
          <span class="text-[10px]">Esc to close · ← →</span>
        </div>
      </div>
    `;

    document.body.append(modalEl);

    modalEl.querySelector('#officekit-tour-close').addEventListener('click', close);
    modalEl.querySelector('#officekit-tour-prev').addEventListener('click', () => navigate(-1));
    modalEl.querySelector('#officekit-tour-next').addEventListener('click', () => navigate(1));
    const dontShowInput = modalEl.querySelector('#officekit-tour-dont-show');
    try {
      if (dontShowInput) {
        dontShowInput.checked = localStorage.getItem(TOUR_DONT_SHOW_KEY) === 'true';
      }
    } catch (_) {}

    dontShowInput?.addEventListener('change', (e) => {
      try {
        if (e.target.checked) {
          localStorage.setItem(TOUR_DONT_SHOW_KEY, 'true');
          localStorage.setItem(TOUR_SEEN_KEY, 'true');
          localStorage.setItem(TOUR_VERSION_KEY, getAppVersion());
        } else {
          localStorage.removeItem(TOUR_DONT_SHOW_KEY);
        }
      } catch (_) {}
    });

    modalEl.addEventListener('click', (e) => {
      if (e.target === modalEl) close();
    });

    if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
      window.addEventListener('keydown', (e) => {
        if (!isOpen) return;
        if (e.key === 'Escape') close();
        else if (e.key === 'ArrowRight') navigate(1);
        else if (e.key === 'ArrowLeft') navigate(-1);
      });

      window.addEventListener('resize', () => {
        if (isOpen) positionStep(currentStep);
      }, { passive: true });

      window.addEventListener('scroll', () => {
        if (isOpen) positionStep(currentStep);
      }, { passive: true });
    }

    return modalEl;
  }

  function positionStep(idx) {
    if (!isOpen) return;
    const step = steps[idx];
    if (!step) return;

    const modal = ensureModal();
    const spotlight = modal.querySelector('#officekit-tour-spotlight');
    const card = modal.querySelector('#officekit-tour-card');
    const arrow = modal.querySelector('#officekit-tour-arrow');

    let targetEl = null;
    try {
      targetEl = step.target?.();
    } catch (_) {}

    let rect = null;
    if (targetEl && typeof targetEl.getBoundingClientRect === 'function') {
      try {
        rect = targetEl.getBoundingClientRect();
        if (!rect || rect.width === 0 || rect.height === 0) {
          rect = null;
        }
      } catch (_) {}
    }

    const vw = (typeof window !== 'undefined' && window.innerWidth) ? window.innerWidth : 1200;
    const vh = (typeof window !== 'undefined' && window.innerHeight) ? window.innerHeight : 800;

    if (rect && spotlight) {
      const pad = 6;
      const sTop = Math.max(0, rect.top - pad);
      const sLeft = Math.max(0, rect.left - pad);
      const sWidth = rect.width + pad * 2;
      const sHeight = rect.height + pad * 2;

      spotlight.style.top = `${sTop}px`;
      spotlight.style.left = `${sLeft}px`;
      spotlight.style.width = `${sWidth}px`;
      spotlight.style.height = `${sHeight}px`;
      spotlight.style.opacity = '1';

      try {
        const computed = window.getComputedStyle?.(targetEl);
        const radius = computed?.borderRadius;
        if (radius && radius !== '0px') {
          spotlight.style.borderRadius = `${Math.min(24, parseInt(radius, 10) + 4)}px`;
        } else {
          spotlight.style.borderRadius = '14px';
        }
      } catch (_) {
        spotlight.style.borderRadius = '14px';
      }
    } else if (spotlight) {
      spotlight.style.opacity = '0';
    }

    if (card) {
      const cardRect = card.getBoundingClientRect?.() || { width: 380, height: 240 };
      const cardWidth = cardRect.width || 380;
      const cardHeight = cardRect.height || 240;
      const margin = 16;
      const gap = 14;

      let placement = 'center';
      let cardTop = Math.max(margin, (vh - cardHeight) / 2);
      let cardLeft = Math.max(margin, (vw - cardWidth) / 2);

      if (rect) {
        if (rect.left < vw * 0.35 && (vw - rect.right) >= (cardWidth + margin + gap)) {
          placement = 'right';
          cardLeft = rect.right + gap;
          cardTop = Math.max(margin, Math.min(vh - cardHeight - margin, rect.top - 12));
        } else if (rect.top < vh * 0.35 && (vh - rect.bottom) >= (cardHeight + margin + gap)) {
          placement = 'bottom';
          cardTop = rect.bottom + gap;
          const idealLeft = rect.left + (rect.width - cardWidth) / 2;
          cardLeft = Math.max(margin, Math.min(vw - cardWidth - margin, idealLeft));
        } else if (rect.top >= (cardHeight + margin + gap)) {
          placement = 'top';
          cardTop = rect.top - cardHeight - gap;
          const idealLeft = rect.left + (rect.width - cardWidth) / 2;
          cardLeft = Math.max(margin, Math.min(vw - cardWidth - margin, idealLeft));
        } else if ((vw - rect.right) >= (cardWidth + margin + gap)) {
          placement = 'right';
          cardLeft = rect.right + gap;
          cardTop = Math.max(margin, Math.min(vh - cardHeight - margin, rect.top));
        }
      }

      if (vw < 640) {
        card.style.top = 'auto';
        card.style.bottom = '16px';
        card.style.left = '16px';
        card.style.right = '16px';
        card.style.width = 'auto';
        card.style.transform = 'none';
        if (arrow) arrow.className = 'arrow-hidden';
      } else if (placement === 'center') {
        card.style.top = '50%';
        card.style.bottom = 'auto';
        card.style.left = '50%';
        card.style.right = 'auto';
        card.style.width = '';
        card.style.transform = 'translate(-50%, -50%)';
        if (arrow) arrow.className = 'arrow-hidden';
      } else {
        card.style.top = `${cardTop}px`;
        card.style.bottom = 'auto';
        card.style.left = `${cardLeft}px`;
        card.style.right = 'auto';
        card.style.width = '';
        card.style.transform = 'none';

        if (arrow && rect) {
          const arrowDir = placement === 'bottom' ? 'top' : placement === 'right' ? 'left' : placement === 'top' ? 'bottom' : 'right';
          arrow.className = `arrow-${arrowDir}`;
          if (placement === 'bottom' || placement === 'top') {
            const arrowX = Math.max(20, Math.min(cardWidth - 20, (rect.left + rect.width / 2) - cardLeft));
            arrow.style.left = `${arrowX}px`;
            arrow.style.top = '';
          } else {
            const arrowY = Math.max(20, Math.min(cardHeight - 20, (rect.top + rect.height / 2) - cardTop));
            arrow.style.top = `${arrowY}px`;
            arrow.style.left = '';
          }
        } else if (arrow) {
          arrow.className = 'arrow-hidden';
        }
      }
    }
  }

  // While the app is locked (or still checking) a paid tab is not switched to: the guarded switchTab would
  // open the activation modal over the tour. The step still shows and highlights its sidebar entry.
  function canSwitchTo(tab) {
    if (typeof window === 'undefined' || typeof window.switchTab !== 'function') return false;
    if (typeof window.officekitLicenseDecision === 'function' && window.officekitLicenseDecision({ tab }) !== 'allow') return false;
    return true;
  }

  function renderStep(idx) {
    if (!isOpen) return;
    currentStep = idx;
    const step = steps[idx];
    const modal = ensureModal();

    if (step.tab && canSwitchTo(step.tab)) {
      try {
        window.switchTab(step.tab);
      } catch (_) {}
    }

    document.querySelectorAll('.ok-tour-highlight').forEach(el => el.classList.remove('ok-tour-highlight'));

    const targetEl = step.target?.();
    if (targetEl && targetEl.classList) {
      targetEl.classList.add('ok-tour-highlight');
      try { targetEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (_) {}
    }

    modal.querySelector('#officekit-tour-badge').textContent = step.badge;
    modal.querySelector('#officekit-tour-title').textContent = step.title;
    modal.querySelector('#officekit-tour-desc').textContent = step.desc;

    const iconBox = modal.querySelector('#officekit-tour-icon');
    iconBox.innerHTML = `<i class="fa-solid ${step.icon}" aria-hidden="true"></i>`;

    const dots = modal.querySelector('#officekit-tour-dots');
    dots.innerHTML = steps.map((_, i) =>
      `<span class="inline-block h-1.5 rounded-full transition-all ${i === idx ? 'w-5 bg-sky-500' : 'w-1.5 bg-slate-300 dark:bg-white/20'}"></span>`
    ).join('');

    const prevBtn = modal.querySelector('#officekit-tour-prev');
    prevBtn.disabled = idx === 0;

    const nextBtn = modal.querySelector('#officekit-tour-next');
    if (idx === steps.length - 1) {
      nextBtn.innerHTML = '<span>Get Started</span> <i class="fa-solid fa-check ml-1 text-[10px]" aria-hidden="true"></i>';
      nextBtn.className = 'btn btn-xs btn-success text-white';
    } else {
      nextBtn.innerHTML = '<span>Next</span> <i class="fa-solid fa-arrow-right ml-1 text-[10px]" aria-hidden="true"></i>';
      nextBtn.className = 'btn btn-xs btn-primary text-white';
    }

    positionStep(idx);
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => positionStep(idx));
    }
  }

  function navigate(delta) {
    const nextIdx = currentStep + delta;
    if (nextIdx >= 0 && nextIdx < steps.length) {
      renderStep(nextIdx);
    } else if (nextIdx >= steps.length) {
      try {
        localStorage.setItem(TOUR_SEEN_KEY, 'true');
        localStorage.setItem(TOUR_VERSION_KEY, getAppVersion());
      } catch (_) {}
      close();
    }
  }

  function start(stepIdx = 0) {
    isOpen = true;
    try {
      const activeEl = document.querySelector('[data-sidebar-tab][aria-current="page"]');
      initialTab = activeEl?.dataset?.sidebarTab || 'tools';
    } catch (_) {
      initialTab = 'tools';
    }
    const modal = ensureModal();
    try {
      const dontShowInput = modal.querySelector('#officekit-tour-dont-show');
      if (dontShowInput) {
        dontShowInput.checked = localStorage.getItem(TOUR_DONT_SHOW_KEY) === 'true';
      }
    } catch (_) {}
    modal.hidden = false;
    renderStep(stepIdx);
  }

  function close() {
    isOpen = false;
    if (modalEl) modalEl.hidden = true;
    document.querySelectorAll('.ok-tour-highlight').forEach(el => el.classList.remove('ok-tour-highlight'));
    try {
      localStorage.setItem(TOUR_SEEN_KEY, 'true');
      localStorage.setItem(TOUR_VERSION_KEY, getAppVersion());
    } catch (_) {}
    if (initialTab && canSwitchTo(initialTab)) {
      try {
        window.switchTab(initialTab);
      } catch (_) {}
    }
  }

  function isRunning() {
    return isOpen;
  }

  function getSteps() {
    return steps;
  }

  global.OfficeKitTour = {
    start,
    close,
    navigate,
    isRunning,
    getSteps,
    checkAutoStart,
    shouldAutoStart,
    getAppVersion,
    resetTourPreferences,
  };
  global.startAppTour = start;

  if (typeof window !== 'undefined') {
    if (typeof document !== 'undefined' && document.readyState === 'complete') {
      setTimeout(() => checkAutoStart(), 350);
    } else if (typeof window.addEventListener === 'function') {
      window.addEventListener('load', () => {
        setTimeout(() => checkAutoStart(), 350);
      });
    }
  }

})(typeof window !== 'undefined' ? window : globalThis);
