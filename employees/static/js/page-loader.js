/* Dovix AI — global page-navigation loader.
   Shows a thin top progress bar immediately on internal navigation, and a
   branded overlay if the navigation takes long enough to need one. Pairs
   with employees/static/css/page-loader.css and the markup in
   templates/layout/master.html. */
(function () {
  if (window.__dvxPageLoaderInit) return;
  window.__dvxPageLoaderInit = true;

  var bar = document.getElementById('dvxPageLoaderBar');
  var overlay = document.getElementById('dvxPageLoaderOverlay');
  if (!bar || !overlay) return;

  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var overlayTimer = null;
  var watchdogTimer = null;
  var started = false;

  function resetLoader() {
    started = false;
    clearTimeout(overlayTimer);
    clearTimeout(watchdogTimer);
    bar.classList.remove('is-active');
    bar.style.width = '0%';
    overlay.classList.remove('is-visible');
  }

  function startLoader() {
    if (started) return;
    started = true;

    bar.style.width = '0%';
    bar.offsetWidth; // force reflow so the width transition below actually animates
    bar.classList.add('is-active');
    requestAnimationFrame(function () {
      bar.style.width = reduceMotion ? '55%' : '78%';
    });

    // Only bring up the branded overlay if the page is genuinely still
    // loading a bit later - avoids a flicker on fast transitions.
    overlayTimer = setTimeout(function () {
      overlay.classList.add('is-visible');
    }, 350);

    // Safety net: if navigation never actually completes (blocked, the
    // browser cancelled it, user pressed Escape, a same-page POST that
    // doesn't redirect), don't leave the UI stuck forever.
    watchdogTimer = setTimeout(resetLoader, 12000);
  }

  function isModifiedClick(event) {
    return event.defaultPrevented || event.button !== 0 ||
      event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
  }

  function sameOrigin(href) {
    try {
      return new URL(href, window.location.href).origin === window.location.origin;
    } catch (e) {
      return false;
    }
  }

  function isSamePageAnchor(href) {
    try {
      var target = new URL(href, window.location.href);
      return target.pathname === window.location.pathname &&
        target.search === window.location.search && target.hash !== '';
    } catch (e) {
      return false;
    }
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('data-no-loader') || isModifiedClick(event)) return;

    var href = link.getAttribute('href');
    if (!href) return;
    var prefix = href.charAt(0);
    if (prefix === '#' || href.indexOf('javascript:') === 0 ||
        href.indexOf('mailto:') === 0 || href.indexOf('tel:') === 0) return;
    if (link.target && link.target !== '_self') return; // opens in a new tab
    if (link.hasAttribute('download')) return;
    if (!sameOrigin(href) || isSamePageAnchor(href)) return;

    startLoader();
  }, true);

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.hasAttribute('data-no-loader')) return;
    if (form.target && form.target !== '_self') return;
    startLoader();
  }, true);

  // Chrome/Safari can restore a page from the back/forward cache mid-animation.
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) resetLoader();
  });

  window.addEventListener('pagehide', function () {
    clearTimeout(watchdogTimer);
    clearTimeout(overlayTimer);
  });
})();
