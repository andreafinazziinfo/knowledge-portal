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

  // ADR-070: Universal View Guide (?) & Quick AI Context / Blast Radius Popover
  var VIEW_GUIDES = {
    'graph.html': { title: '2D Network Graph', what: 'Grafo organico Vis.js dei simboli e delle dipendenze.', how: 'Trascina i nodi, usa la rotella per zoomare, clicca un nodo per ispezionare vicini e percorso.', topic: 'architecture' },
    'graph_3d.html': { title: '3D Spherical Nebulae', what: 'Cluster tridimensionali su sfere di Fibonacci raggruppati per dominio.', how: 'Ruota con click sinistro, sposta con destro, zoom con rotella.', topic: 'architecture' },
    'graph_full.html': { title: 'Particle Flow & Chord Matrix', what: 'Flusso particellare live lungo gli import + Matrice Chord tra domini.', how: 'In Particle Flow attiva Connected Backbone; in Chord passa il mouse su un arco o clicca per bloccare.', topic: 'dependencies' },
    'canvas.html': { title: '2D Whiteboard Canvas', what: 'Lavagna architetturale 2D con raggruppamenti logici.', how: 'Pan e zoom liberi per esplorare moduli e collegamenti.', topic: 'canvas' },
    'canvas_3d.html': { title: '3D Z-Layered Planes', what: '5 piani architetturali separati sull\'asse Z con particelle live tra i layer.', how: 'Ruota in 3D per osservare le chiamate verticali UI → API → Core → DB.', topic: 'layers' },
    'GRAPH_TREE.html': { title: 'Directory Tree / Treemap / Sunburst', what: 'Gerarchia file/cartelle in 3 modalità (Albero, Treemap, Sunburst radiale 20x).', how: 'Clicca un settore nel Sunburst per drill-down; clicca il centro per risalire.', topic: 'structure' },
    'circle-pack.html': { title: 'Zoomable Circle Packing', what: 'Cartelle annidate come cerchi proporzionali alla connettività dei moduli.', how: 'Clicca un cerchio per zoomare dentro il modulo; clicca lo sfondo per tornare alla root.', topic: 'modules' },
    'tree_3d.html': { title: '3D Top-Down DAG Tree', what: 'Albero gerarchico 3D orientato dall\'alto verso il basso.', how: 'Ruota e zooma per leggere la profondità dei moduli.', topic: 'hierarchy' },
    'arch-health.html': { title: 'Arch Health Audit 2.0', what: 'Audit file-level: Radar 6 assi, Martin Main Sequence (I vs A), DSM Heatmap, Cicli Tarjan SCC e God-Files.', how: 'Passa il mouse sui punti dello scatter e sulle celle rosse della DSM (cicli bidirezionali).', topic: 'health' },
    'db-lineage.html': { title: 'Database Schema & Lineage', what: 'Tabelle SQL, chiavi primarie/esterne e lettori/scrittori nel codice.', how: 'Premi / per cercare una tabella o colonna e ispezionare chi la legge/scrive.', topic: 'database' },
    'async-topology.html': { title: 'Async & WebSocket Topology', what: 'Canali pub/sub, broker e flussi real-time in Cards, 2D Flow e 3D Z-Layers.', how: 'Usa i pulsanti in alto per passare da Cards a 2D Flow o 3D Z-Layers animato.', topic: 'websocket' },
    'data-ingestion.html': { title: 'Data Ingestion Pipeline', what: 'Pipeline end-to-end di acquisizione dati con flussi animati.', how: 'Alterna Cards e 2D Pipeline per seguire il flusso sorgente → storage.', topic: 'ingestion' },
    'live-telemetry.html': { title: 'Live System Telemetry', what: 'CPU, RAM, disco, stato watcher e latenza backend in tempo reale.', how: 'Si aggiorna automaticamente ogni pochi secondi via /api/telemetry.', topic: 'telemetry' },
    'stack-ecosystem.html': { title: 'Tech Stack & Ecosystem', what: 'Inventario completo di linguaggi, dipendenze, container e tool.', how: 'Filtra per ecosistema o cerca un pacchetto specifico con /.', topic: 'stack' },
    'data-explorer.html': { title: 'Pivot Data Explorer (WASM)', what: 'Tabella pivot ad alte prestazioni su nodi AST, API, flussi e DB.', how: 'Raggruppa, ordina e filtra qualsiasi colonna; esporta CSV/JSON.', topic: 'explorer' },
    'adr-governance.html': { title: 'ADR Governance', what: 'Registro completo delle Architecture Decision Records.', how: 'Premi / per filtrare gli ADR per stato o parola chiave.', topic: 'adr' },
    'api-catalog.html': { title: 'API Catalog', what: 'Documentazione interattiva degli endpoint HTTP/REST.', how: 'Espandi un endpoint per leggere parametri, schemi e risposte.', topic: 'api' },
    'frontend-state.html': { title: 'UI State & Stores', what: 'Mappa degli store frontend, azioni e stato reattivo.', how: 'Cerca uno store per vederne proprietà e collegamenti.', topic: 'store' },
    'worker-tasks.html': { title: 'Worker & Scheduled Tasks', what: 'Code asincrone, task schedulati e job di background.', how: 'Ispeziona frequenza, coda e dipendenze di ciascun task.', topic: 'worker' },
    'threat-matrix.html': { title: 'Threat Matrix & Security', what: 'Perimetri di sicurezza, access control e mitigazioni.', how: 'Filtra per severità o superficie di attacco.', topic: 'security' },
    'runbook-ops.html': { title: 'Ops Incident Runbook', what: 'Procedure operative di recovery, diagnostica e deploy.', how: 'Segui le checklist in caso di incident o manutenzione.', topic: 'runbook' }
  };

  if (pageName && pageName !== 'dashboard.html' && pageName !== 'graph-studio.html') {
    window.addEventListener('DOMContentLoaded', function () {
      if (document.getElementById('fp-guide-fab')) return;
      var info = VIEW_GUIDES[pageName] || {
        title: pageName.replace('.html', ''),
        what: 'Vista interattiva del Knowledge Portal.',
        how: 'Usa / per cercare rapidamente ed Esc per chiudere i pannelli.',
        topic: pageName.replace('.html', '')
      };
      var apiBase = (window.location.protocol === 'file:') ? 'http://127.0.0.1:18115' : '';

      var fab = document.createElement('button');
      fab.id = 'fp-guide-fab';
      fab.type = 'button';
      fab.title = 'Guida Vista & Azioni AI';
      fab.textContent = '? Guida & AI';
      fab.style.cssText = 'position:fixed;right:14px;bottom:14px;z-index:9990;background:rgba(25,25,25,0.94);color:#e5e7eb;border:1px solid #383838;border-radius:999px;padding:6px 12px;font-size:11px;font-weight:600;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,0.5);';

      var pop = document.createElement('div');
      pop.id = 'fp-guide-popover';
      pop.className = 'popover';
      pop.style.cssText = 'display:none;position:fixed;right:14px;bottom:52px;width:320px;max-width:calc(100vw - 28px);z-index:9991;background:#171717;border:1px solid #333333;border-radius:12px;padding:14px;color:#e5e7eb;font-size:12px;box-shadow:0 16px 40px rgba(0,0,0,0.7);';
      pop.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
          '<strong style="color:#fff;font-size:13px;">' + info.title + '</strong>' +
          '<button type="button" id="fp-guide-close" style="background:none;border:none;color:#9ca3af;cursor:pointer;font-size:14px;">✕</button>' +
        '</div>' +
        '<div style="color:#d4d4d8;line-height:1.45;margin-bottom:6px;"><strong>Cos\'è:</strong> ' + info.what + '</div>' +
        '<div style="color:#9ca3af;line-height:1.45;margin-bottom:10px;"><strong>Come usarla:</strong> ' + info.how + '</div>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">' +
          '<button type="button" id="fp-copy-ai" style="flex:1;background:#262626;color:#fff;border:1px solid #404040;border-radius:6px;padding:6px 8px;font-size:11px;cursor:pointer;">📋 Copia AI Context</button>' +
          '<a href="' + apiBase + '/llms.txt" target="_blank" rel="noopener" style="text-decoration:none;background:#1f1f1f;color:#38bdf8;border:1px solid #333;border-radius:6px;padding:6px 10px;font-size:11px;">llms.txt ↗</a>' +
        '</div>' +
        '<div style="display:flex;gap:6px;">' +
          '<input id="fp-impact-in" type="text" placeholder="Blast Radius (es. auth, server)..." style="flex:1;background:#111;color:#fff;border:1px solid #333;border-radius:6px;padding:5px 8px;font-size:11px;">' +
          '<button type="button" id="fp-impact-go" style="background:#38bdf8;color:#0f0f0f;border:none;border-radius:6px;padding:5px 9px;font-size:11px;font-weight:700;cursor:pointer;">💥</button>' +
        '</div>' +
        '<div id="fp-impact-out" style="margin-top:8px;font-size:11px;color:#9ca3af;max-height:110px;overflow-y:auto;"></div>';

      document.body.appendChild(fab);
      document.body.appendChild(pop);

      function setOpen(v) {
        pop.style.display = v ? 'block' : 'none';
        pop.classList.toggle('open', v);
      }
      fab.onclick = function () { setOpen(pop.style.display === 'none'); };
      pop.querySelector('#fp-guide-close').onclick = function () { setOpen(false); };

      pop.querySelector('#fp-copy-ai').onclick = function () {
        var btn = this;
        btn.textContent = 'Caricamento...';
        fetch(apiBase + '/api/context-pack?q=' + encodeURIComponent(info.topic) + '&max_tokens=3000')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            var md = (d && d.markdown) ? d.markdown : ('# ' + info.title + '\n' + info.what);
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(md);
            }
            btn.textContent = '✅ Copiato!';
            setTimeout(function () { btn.textContent = '📋 Copia AI Context'; }, 1800);
          })
          .catch(function () { btn.textContent = '📋 Copia AI Context'; });
      };

      function runImpact() {
        var q = (pop.querySelector('#fp-impact-in').value || '').trim();
        var out = pop.querySelector('#fp-impact-out');
        if (!q) return;
        out.textContent = 'Calcolo blast radius...';
        fetch(apiBase + '/api/impact?target=' + encodeURIComponent(q) + '&depth=2')
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            if (!d || !d.counts) { out.textContent = 'Nessun dato impact disponibile.'; return; }
            out.innerHTML = '<strong>Risk: ' + d.risk + '</strong> · d1: ' + d.counts.d1 + ' · d2: ' + d.counts.d2 + ' · total: ' + d.counts.total;
          })
          .catch(function () { out.textContent = 'Endpoint /api/impact non raggiungibile.'; });
      }
      pop.querySelector('#fp-impact-go').onclick = runImpact;
      pop.querySelector('#fp-impact-in').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') runImpact(); });
    });
  }
})();
