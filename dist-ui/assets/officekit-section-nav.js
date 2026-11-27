// Section list for long screens: a left list of links that jump to each section and mark the one in view.
(function (global) {
  'use strict';

  function mark(links, id) {
    links.forEach(link => {
      if (link.getAttribute('href') === `#${id}`) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  }

  // A smooth scroll passes other sections on the way; hold the observer until it settles so the clicked link stays marked.
  const SCROLL_SETTLE_MS = 900;

  function init(nav) {
    const links = [...nav.querySelectorAll('a[href^="#"]')];
    const targets = links
      .map(link => ({ link, section: document.getElementById(link.getAttribute('href').slice(1)) }))
      .filter(item => item.section && !item.section.closest('[hidden]'));
    let settledAt = 0;
    links.forEach(link => link.addEventListener('click', event => {
      const target = document.getElementById(link.getAttribute('href').slice(1));
      if (!target) return;
      event.preventDefault();
      settledAt = Date.now() + SCROLL_SETTLE_MS;
      mark(links, target.id);
      target.scrollIntoView({ block: 'start', behavior: 'smooth' });
      const heading = target.matches('h1, h2, h3') ? target : target.querySelector('h1, h2, h3');
      if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus({ preventScroll: true }); }
    }));
    if (!('IntersectionObserver' in global)) return;
    const observer = new IntersectionObserver(entries => {
      if (Date.now() < settledAt) return;
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.target.offsetTop - b.target.offsetTop);
      if (visible.length) mark(links, visible[0].target.id);
    }, { rootMargin: '-10% 0px -70% 0px' });
    targets.forEach(item => observer.observe(item.section));
  }

  function initAll() {
    document.querySelectorAll('[data-section-nav]').forEach(init);
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAll);
    else initAll();
  }
  global.officekitSectionNav = { init };
})(typeof window !== 'undefined' ? window : globalThis);
