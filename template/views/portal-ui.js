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
})();
