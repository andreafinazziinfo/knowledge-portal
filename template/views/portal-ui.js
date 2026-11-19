/* Knowledge Portal — Floorplan Keyboard & UI Ergonomics */
(function () {
  if (window.__portalUiInit) return;
  window.__portalUiInit = true;

  function findSearchInput() {
    return (
      document.querySelector('input[type="search"]') ||
      document.querySelector('input[placeholder*="Search" i]') ||
      document.querySelector('input[placeholder*="Cerca" i]') ||
      document.querySelector('input[placeholder*="Filter" i]') ||
      document.querySelector('input[placeholder*="Filtra" i]') ||
      document.querySelector('#searchInput, #search, #omniSearch, .search-input')
    );
  }

  document.addEventListener('keydown', function (e) {
    const tag = (e.target && e.target.tagName || '').toLowerCase();
    const isInput = tag === 'input' || tag === 'textarea' || tag === 'select' || (e.target && e.target.isContentEditable);

    if (e.key === '/' && !isInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const inp = findSearchInput();
      if (inp) {
        e.preventDefault();
        inp.focus();
        if (typeof inp.select === 'function') inp.select();
      }
    } else if (e.key === 'Escape') {
      const inp = findSearchInput();
      if (inp && document.activeElement === inp) {
        if (inp.value) {
          inp.value = '';
          inp.dispatchEvent(new Event('input', { bubbles: true }));
        }
        inp.blur();
      }
      document.querySelectorAll('.drawer.open, .modal.open, .dropdown.open, .popover.open').forEach(function (el) {
        el.classList.remove('open');
      });
    }
  });

  window.__fpTransparent3D = function (fg) {
    function clearBg() {
      try {
        if (fg && typeof fg.backgroundColor === 'function') fg.backgroundColor('rgba(0,0,0,0)');
        if (fg && typeof fg.renderer === 'function' && fg.renderer()) {
          fg.renderer().setClearColor(0x000000, 0);
        }
        if (fg && typeof fg.scene === 'function' && fg.scene()) {
          fg.scene().background = null;
        }
      } catch (_) {}
    }
    clearBg();
    setTimeout(clearBg, 50);
    setTimeout(clearBg, 250);
    setTimeout(clearBg, 1000);
    return fg;
  };

  // Phase 3: Lightweight Live Telemetry Micro-Badge on Operational Views
  var OPS_VIEWS = ['runbook-ops.html', 'data-ingestion.html', 'worker-tasks.html', 'async-topology.html'];
  var pageName = (window.location.pathname.split('/').pop() || '');
  if (OPS_VIEWS.indexOf(pageName) !== -1) {
    window.addEventListener('DOMContentLoaded', function () {
      var target = document.querySelector('.header-right, header .hr, header, .header');
      if (!target || document.getElementById('fp-live-pill')) return;
      var pill = document.createElement('span');
      pill.id = 'fp-live-pill';
      pill.className = 'badge';
      pill.style.cssText = 'display:inline-flex;align-items:center;gap:6px;';
      pill.innerHTML = '<span style="width:6px;height:6px;border-radius:50%;background:#8b8b8b;display:inline-block;"></span><span>Static Snapshot</span>';
      target.appendChild(pill);

      var apiBase = (window.location.protocol === 'file:') ? 'http://127.0.0.1:18115' : '';
      function refreshPill() {
        var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
        var tid = ctrl ? setTimeout(function () { ctrl.abort(); }, 1500) : null;
        fetch(apiBase + '/api/telemetry', ctrl ? { signal: ctrl.signal } : {})
          .then(function (r) { if (tid) clearTimeout(tid); return r.ok ? r.json() : null; })
          .then(function (d) {
            if (!d) return;
            var be = d.backend || {};
            var text = 'Live · CPU ' + (d.host && d.host.cpu_pct !== undefined ? d.host.cpu_pct + '%' : 'OK');
            if (be.reachable && be.fastapi) {
              if (pageName === 'data-ingestion.html' && be.dataops && typeof be.dataops.open_gaps === 'number') {
                text = 'Live · Gaps: ' + be.dataops.open_gaps;
              } else {
                text = 'Live · API ' + be.fastapi.latency_ms + 'ms';
              }
            }
            pill.innerHTML = '<span style="width:6px;height:6px;border-radius:50%;background:#6fd7a8;display:inline-block;"></span><span>' + text + '</span>';
          })
          .catch(function () {});
      }
      refreshPill();
      setInterval(refreshPill, 10000);
    });
  }
})();
