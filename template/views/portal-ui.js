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
    'icicle.html': { title: 'Icicle / Flamegraph', what: 'Gerarchia orizzontale impilata per profondità directory con nomi file leggibili per esteso.', how: 'Clicca una barra cartella per zoomare; clicca una foglia file per aprirla nel Reader.', topic: 'structure' },
    'radial-tree.html': { title: '360° Radial Tidy Tree', what: 'Albero directory radiale a 360° con colori per ramo/dominio.', how: 'Usa rotella (zoom 15x) e trascinamento; clicca una foglia file per aprirla nel Reader.', topic: 'structure' },
    'arch-diff.html': { title: 'Architecture Diff & Evolution', what: 'Confronta due scan successivi (moduli/archi aggiunti e rimossi) + timeline evolutiva dello Health Score.', how: 'Clicca un modulo aggiunto/modificato per aprirlo direttamente nel Reader.', topic: 'evolution' },
    'arc-diagram.html': { title: 'Linear Layer Arc Diagram', what: 'Moduli ordinati per layer: archi superiori = dipendenze sane, archi inferiori rossi = cicli / risalite.', how: 'Passa il mouse su un nodo per isolarne gli archi; clicca per aprire nel Reader.', topic: 'cycles' },
    'hive-plot.html': { title: 'Deterministic 3-Axis Hive Plot', what: '3 assi radiali fissi (Core Hubs, Balanced Mid, Leaf/Entrypoints) senza layout casuale.', how: 'Passa il mouse sui nodi per isolare le connessioni; clicca per aprire nel Reader.', topic: 'topology' },
    'codecity.html': { title: 'CodeCity 3D', what: 'Città isometrica 3D: quartieri = cartelle, base = simboli, altezza = grado di accoppiamento.', how: 'Trascina per spostarti, rotella per zoomare, passa il mouse sugli edifici per i dettagli.', topic: 'architecture' },
    'edge-bundling.html': { title: 'Hierarchical Edge Bundling', what: 'I 110 file più connessi disposti in cerchio con curve raggruppate per dominio.', how: 'Passa il mouse su un file: ciano = import in uscita, verde = import in ingresso.', topic: 'dependencies' },
    'sankey-flow.html': { title: 'Sankey Architecture Flow', what: 'Flussi aggregati tra i 5 layer (Presentation → API → Domain → Workers → Data).', how: 'Clicca qualsiasi barra layer per aprire la lista cliccabile dei file di quel layer.', topic: 'layers' },
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
    'runbook-ops.html': { title: 'Ops Incident Runbook', what: 'Procedure operative di recovery, diagnostica e deploy.', how: 'Segui le checklist in caso di incident o manutenzione.', topic: 'runbook' },
    'mission-control.html': { title: 'Mission Control Command Center', what: 'Bento Command Center esecutivo con KPI North Star, semafori sottosistemi e feed anomalie P0/P1/P2.', how: 'Filtra per severità e clicca una cella o card per saltare alla vista di dettaglio.', topic: 'mission-control' },
    'git-pr-dag.html': { title: 'Stacked-PR DAG & Worktree Hygiene', what: 'Grafo SVG di branch/PR impilate, ordine di merge consigliato e matrice igiene worktree.', how: 'Premi / per filtrare i worktree per nome o stato (clean, dirty, detached, stale).', topic: 'git-dag' },
    'adr-runbook-hub.html': { title: 'ADR Timeline & Interactive Runbook Hub', what: 'Timeline/grafo dipendenze ADR e reader interattivo dei runbook con checklist salvate in localStorage.', how: 'Alterna tra ADR Decision Graph e Interactive Runbooks; premi / per filtrare.', topic: 'adr' },
    'ai-mission-launcher.html': { title: 'AI Mission Pack & CodeMode Workbench', what: 'Generatore di Mission Pack AI con budget token, sandbox CodeMode read-only e catalogo MCP v2.', how: 'Scegli un preset o esegui uno snippet CodeMode e copia il context pack per il tuo agente AI.', topic: 'ai-mission' },
    'vertical-slices.html': { title: 'Cross-Stack Vertical Slice Explorer', what: 'Catene end-to-end a 6 layer (UI Component → Store → API Client → Backend Route → Service/Task → Redis/DB) con Swimlane SVG.', how: 'Filtra per feature o endpoint e clicca una riga per visualizzare la Swimlane 6-layer.', topic: 'vertical-slices' },
    'test-oracle.html': { title: 'Test Oracle & Blind-Spots Explorer', what: 'Mappa inversa AST sorgente/simbolo → test pytest/vitest più veloci e lista blind-spot non coperti.', how: 'Cerca un file sorgente o simbolo e copia il comando di test mirato.', topic: 'test-oracle' },
    'data-contracts.html': { title: 'Data Contracts, Error Taxonomy & Runtime Modes', what: 'Registro Pydantic ↔ TypeScript con drift detector, tassonomia HTTPException/Error, matrice DB R/W e modalità runtime.', how: 'Alterna tra i tab Schema Drift, Error Taxonomy, DB R/W Matrix e Runtime Modes; premi / per filtrare.', topic: 'data-contracts' }
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

  // ADR-073: Zero-Dep Visual Strips for ADR Governance (Timeline), Worker Tasks (24h Gantt), Frontend State (Bipartite Flow)
  if (pageName === 'adr-governance.html' || pageName === 'worker-tasks.html' || pageName === 'frontend-state.html') {
    window.addEventListener('DOMContentLoaded', function () {
      setTimeout(function () {
        var anchor = document.querySelector('header, .header, .top-bar, h1');
        if (!anchor || document.getElementById('adr73-visual-strip')) return;
        var box = document.createElement('section');
        box.id = 'adr73-visual-strip';
        box.style.cssText = 'margin:14px auto;max-width:1360px;background:#171717;border:1px solid #262626;border-radius:10px;padding:14px 16px;color:#e5e7eb;';

        if (pageName === 'adr-governance.html') {
          var cards = Array.from(document.querySelectorAll('.card, .adr-card, [data-adr], article')).slice(0, 60);
          var pills = cards.map(function (c, idx) {
            var txt = (c.textContent || '');
            var m = txt.match(/ADR[- ]?\d+/i);
            var lbl = m ? m[0].toUpperCase() : ('ADR #' + (idx + 1));
            var st = /superseded|deprecated/i.test(txt) ? '#737373' : (/proposed|draft/i.test(txt) ? '#fbbf24' : '#34d399');
            return { el: c, lbl: lbl, color: st };
          });
          if (!pills.length) return;
          box.innerHTML = '<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#9ca3af;margin-bottom:8px;">ADR Chronological Timeline (' + pills.length + ' records · click to jump)</div><div id="adr73-tl" style="display:flex;gap:6px;overflow-x:auto;padding-bottom:4px;"></div>';
          anchor.insertAdjacentElement('afterend', box);
          var tl = box.querySelector('#adr73-tl');
          pills.forEach(function (p) {
            var b = document.createElement('button');
            b.type = 'button';
            b.textContent = p.lbl;
            b.style.cssText = 'flex-shrink:0;background:#111;color:#fff;border:1px solid ' + p.color + ';border-left:4px solid ' + p.color + ';border-radius:6px;padding:4px 9px;font-size:11px;cursor:pointer;';
            b.onclick = function () { p.el.scrollIntoView({ behavior: 'smooth', block: 'center' }); };
            tl.appendChild(b);
          });
        } else if (pageName === 'worker-tasks.html') {
          var tCards = Array.from(document.querySelectorAll('.card, .task-card, tr, article')).slice(0, 18);
          var rows = [];
          tCards.forEach(function (c, i) {
            var h = c.querySelector('h3, h4, strong, .title, td');
            var name = h ? (h.textContent || '').trim().slice(0, 32) : '';
            if (name && name.length > 2) rows.push({ name: name, start: (i * 2) % 22, dur: 2 + (i % 4), color: i % 2 === 0 ? '#38bdf8' : '#fbbf24' });
          });
          if (!rows.length) return;
          var html = '<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#9ca3af;margin-bottom:8px;">24h Worker Schedule Gantt (00:00 → 24:00 UTC)</div>';
          html += '<div style="display:flex;flex-direction:column;gap:5px;">';
          rows.slice(0, 10).forEach(function (r) {
            var leftPct = Math.round((r.start / 24) * 100);
            var widthPct = Math.max(8, Math.round((r.dur / 24) * 100));
            html += '<div style="display:flex;align-items:center;gap:10px;font-size:11px;">' +
              '<span style="width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#d4d4d8;">' + r.name + '</span>' +
              '<div style="flex:1;height:12px;background:#111;border:1px solid #262626;border-radius:4px;position:relative;overflow:hidden;">' +
                '<div style="position:absolute;left:' + leftPct + '%;width:' + widthPct + '%;top:1px;bottom:1px;background:' + r.color + ';border-radius:3px;opacity:0.85;"></div>' +
              '</div></div>';
          });
          html += '</div>';
          box.innerHTML = html;
          anchor.insertAdjacentElement('afterend', box);
        } else if (pageName === 'frontend-state.html') {
          var sCards = Array.from(document.querySelectorAll('.card, .store-card, article')).slice(0, 14);
          var stores = [];
          sCards.forEach(function (c) {
            var h = c.querySelector('h3, h4, strong, .title');
            var name = h ? (h.textContent || '').trim().slice(0, 28) : '';
            if (name) stores.push(name);
          });
          if (!stores.length) return;
          var layers = ['Dashboard / Shell', 'Charts & Orderflow', 'Quant & Backtest', 'DataOps & Admin'];
          var hSvg = Math.max(180, stores.length * 22 + 20);
          var svgParts = ['<svg width="100%" viewBox="0 0 760 ' + hSvg + '" style="display:block;">'];
          stores.forEach(function (st, i) {
            var y1 = 18 + i * 20;
            var li = i % layers.length;
            var y2 = 34 + li * Math.floor((hSvg - 50) / Math.max(1, layers.length - 1));
            svgParts.push('<path d="M210,' + y1 + ' C360,' + y1 + ' 400,' + y2 + ' 550,' + y2 + '" fill="none" stroke="rgba(56,189,248,0.32)" stroke-width="1.5"/>');
            svgParts.push('<circle cx="210" cy="' + y1 + '" r="3.5" fill="#38bdf8"/><text x="200" y="' + (y1 + 4) + '" text-anchor="end" fill="#e5e7eb" font-size="10.5">' + st + '</text>');
          });
          layers.forEach(function (ly, li) {
            var y2 = 34 + li * Math.floor((hSvg - 50) / Math.max(1, layers.length - 1));
            svgParts.push('<rect x="550" y="' + (y2 - 10) + '" width="180" height="20" rx="5" fill="#1f1f1f" stroke="#34d399"/><text x="640" y="' + (y2 + 4) + '" text-anchor="middle" fill="#34d399" font-size="11" font-weight="600">' + ly + '</text>');
          });
          svgParts.push('</svg>');
          box.innerHTML = '<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#9ca3af;margin-bottom:8px;">Bipartite Store ↔ View Flow (' + stores.length + ' stores)</div>' + svgParts.join('');
          anchor.insertAdjacentElement('afterend', box);
        }
      }, 350);
    });
  }

  // ADR-083 Sprint 1: Shared PortalUI Freshness SLA & Lazy JSON Data Loader
  var _headMetaPromise = null;
  var _headMetaTs = 0;

  function _apiBase() {
    return (window.location.protocol === 'file:') ? '' : '';
  }

  function getHeadMeta() {
    if (window.location.protocol === 'file:') return Promise.resolve(null);
    var now = Date.now();
    if (_headMetaPromise && (now - _headMetaTs) < 10000) return _headMetaPromise;
    _headMetaTs = now;
    _headMetaPromise = fetch(_apiBase() + '/api/live-status', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.git_head_sha) return d;
        return fetch(_apiBase() + '/api/meta/head', { cache: 'no-store' })
          .then(function (r2) { return r2.ok ? r2.json() : null; })
          .catch(function () { return null; });
      })
      .catch(function () { return null; });
    return _headMetaPromise;
  }

  function _renderFreshnessBadge(info) {
    var mount = function () {
      var target = document.querySelector('.header-right, header .hr, .top-bar .right, header, .header, .top-bar');
      if (!target) return;
      var badge = document.getElementById('fp-freshness-badge');
      if (!badge) {
        badge = document.createElement('span');
        badge.id = 'fp-freshness-badge';
        badge.className = 'badge';
        badge.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:600;font-family:monospace;letter-spacing:0.02em;margin-left:6px;white-space:nowrap;';
        target.appendChild(badge);
      }
      if (info.status === 'stale') {
        badge.style.background = 'rgba(239,68,68,0.16)';
        badge.style.color = '#fca5a5';
        badge.style.border = '1px solid rgba(239,68,68,0.45)';
        var detail = (info.artifact_sha && info.head_sha && info.artifact_sha !== info.head_sha)
          ? (info.artifact_sha + ' ≠ ' + info.head_sha)
          : (info.age_hours !== null ? Math.round(info.age_hours) + 'h old' : 'outdated');
        badge.textContent = '⚠️ STALE · ' + detail;
        badge.title = 'Artifact generated at ' + (info.generated_at || 'unknown') + ' (artifact SHA: ' + (info.artifact_sha || '?') + ', HEAD: ' + (info.head_sha || '?') + ')';
      } else if (info.status === 'fresh') {
        badge.style.background = 'rgba(16,185,129,0.14)';
        badge.style.color = '#6ee7b7';
        badge.style.border = '1px solid rgba(16,185,129,0.38)';
        badge.textContent = '✅ FRESH' + (info.artifact_sha && info.artifact_sha !== 'unknown' ? ' · ' + info.artifact_sha : '');
        badge.title = 'Fresh artifact generated at ' + (info.generated_at || 'unknown');
      }
    };
    if (document.readyState === 'loading') {
      window.addEventListener('DOMContentLoaded', mount, { once: true });
    } else {
      mount();
    }
  }

  function checkFreshness(data, opts) {
    opts = opts || {};
    var maxAgeHours = typeof opts.maxAgeHours === 'number' ? opts.maxAgeHours : 24;
    var meta = (data && typeof data === 'object' && data._meta && typeof data._meta === 'object') ? data._meta : null;
    if (!meta) {
      return Promise.resolve({ status: 'unknown', artifact_sha: null, head_sha: null, generated_at: null, age_hours: null });
    }
    var artifactSha = meta.git_head_sha || null;
    var generatedAt = meta.generated_at || null;
    var ageHours = null;
    if (generatedAt) {
      var ts = Date.parse(generatedAt);
      if (!isNaN(ts)) ageHours = (Date.now() - ts) / 3600000;
    }
    return getHeadMeta().then(function (head) {
      var headSha = (head && head.git_head_sha) ? head.git_head_sha : null;
      var shaMismatch = !!(artifactSha && headSha && artifactSha !== 'unknown' && headSha !== 'unknown' && artifactSha !== headSha);
      var tooOld = (ageHours !== null && ageHours > maxAgeHours);
      var status = (shaMismatch || tooOld) ? 'stale' : 'fresh';
      var result = {
        status: status,
        artifact_sha: artifactSha,
        head_sha: headSha,
        generated_at: generatedAt,
        age_hours: ageHours
      };
      if (opts.renderBadge !== false) _renderFreshnessBadge(result);
      return result;
    });
  }

  function loadData(name, fallbackGlobal) {
    var isFile = window.location.protocol === 'file:';
    var url = '../data/' + name + '.json';
    if (isFile && fallbackGlobal && window[fallbackGlobal]) {
      var localData = window[fallbackGlobal];
      checkFreshness(localData);
      return Promise.resolve(localData);
    }
    return fetch(url, { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) {
        checkFreshness(d);
        return d;
      })
      .catch(function () {
        if (fallbackGlobal && window[fallbackGlobal]) {
          var fb = window[fallbackGlobal];
          checkFreshness(fb);
          return fb;
        }
        return null;
      });
  }

  window.PortalUI = Object.assign(window.PortalUI || {}, {
    getHeadMeta: getHeadMeta,
    checkFreshness: checkFreshness,
    loadData: loadData
  });
})();

// ── ADR-083 Sprint 4: PortalSVGViewport (0-CDN Pan/Zoom/Fit/Export SVG) ─────
(function () {
  if (window.PortalSVGViewport) return;

  function _ensureStyles() {
    if (document.getElementById('portal-svg-vp-style')) return;
    var st = document.createElement('style');
    st.id = 'portal-svg-vp-style';
    st.textContent =
      '.portal-svg-vp-host{position:relative;overflow:hidden;touch-action:none;user-select:none;}' +
      '.portal-svg-vp-host.is-panning{cursor:grabbing !important;}' +
      '.portal-svg-vp-toolbar{position:absolute;top:8px;right:8px;z-index:20;display:flex;gap:4px;' +
      'background:var(--bg-elevated,rgba(15,23,42,0.88));border:1px solid var(--border-subtle,rgba(148,163,184,0.28));' +
      'border-radius:8px;padding:4px;backdrop-filter:blur(6px);box-shadow:0 2px 8px rgba(0,0,0,0.22);}' +
      '.portal-svg-vp-btn{background:transparent;color:var(--text-primary,#e2e8f0);border:1px solid transparent;' +
      'border-radius:5px;padding:2px 8px;font-size:12px;font-weight:600;cursor:pointer;line-height:1.4;' +
      'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;transition:background .15s,border-color .15s;}' +
      '.portal-svg-vp-btn:hover{background:var(--bg-hover,rgba(148,163,184,0.18));border-color:var(--border-subtle,rgba(148,163,184,0.35));}';
    document.head.appendChild(st);
  }

  function attach(svgOrContainer, opts) {
    if (!svgOrContainer) return null;
    _ensureStyles();
    opts = opts || {};
    var minZoom = typeof opts.minZoom === 'number' ? opts.minZoom : 0.3;
    var maxZoom = typeof opts.maxZoom === 'number' ? opts.maxZoom : 4;
    var exportName = opts.exportName || 'portal-diagram.svg';

    var isSvg = svgOrContainer.tagName && svgOrContainer.tagName.toLowerCase() === 'svg';
    var host = isSvg ? svgOrContainer.parentElement : svgOrContainer;
    if (!host) return null;

    if (host._portalSvgVpDestroy) {
      host._portalSvgVpDestroy();
    }

    var getSvg = function () {
      return isSvg ? svgOrContainer : host.querySelector('svg');
    };
    var svg = getSvg();
    if (!svg) return null;

    host.classList.add('portal-svg-vp-host');
    if (!host.style.cursor) host.style.cursor = 'grab';

    var state = { scale: 1, tx: 0, ty: 0, dragging: false, sx: 0, sy: 0, stx: 0, sty: 0 };

    function apply() {
      var cur = getSvg();
      if (!cur) return;
      cur.style.transformOrigin = '0 0';
      cur.style.transform = 'translate(' + state.tx.toFixed(1) + 'px,' + state.ty.toFixed(1) + 'px) scale(' + state.scale.toFixed(3) + ')';
    }

    function zoomAt(factor, cx, cy) {
      var next = Math.max(minZoom, Math.min(maxZoom, state.scale * factor));
      var ratio = next / state.scale;
      state.tx = cx - (cx - state.tx) * ratio;
      state.ty = cy - (cy - state.ty) * ratio;
      state.scale = next;
      apply();
    }

    function zoomCenter(factor) {
      var rect = host.getBoundingClientRect();
      zoomAt(factor, rect.width / 2, rect.height / 2);
    }

    function fit() {
      state.scale = 1;
      state.tx = 0;
      state.ty = 0;
      apply();
    }

    function exportSvg() {
      var cur = getSvg();
      if (!cur) return;
      var clone = cur.cloneNode(true);
      clone.style.transform = '';
      clone.style.transformOrigin = '';
      if (!clone.getAttribute('xmlns')) clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      var xml = new XMLSerializer().serializeToString(clone);
      var blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = exportName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }

    function onWheel(e) {
      e.preventDefault();
      var rect = host.getBoundingClientRect();
      var factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      zoomAt(factor, e.clientX - rect.left, e.clientY - rect.top);
    }

    function onMouseDown(e) {
      if (e.button !== 0) return;
      if (e.target && e.target.closest && e.target.closest('.portal-svg-vp-toolbar,button,a,input,select')) return;
      state.dragging = true;
      state.sx = e.clientX;
      state.sy = e.clientY;
      state.stx = state.tx;
      state.sty = state.ty;
      host.classList.add('is-panning');
    }

    function onMouseMove(e) {
      if (!state.dragging) return;
      state.tx = state.stx + (e.clientX - state.sx);
      state.ty = state.sty + (e.clientY - state.sy);
      apply();
    }

    function onMouseUp() {
      if (!state.dragging) return;
      state.dragging = false;
      host.classList.remove('is-panning');
    }

    var toolbar = document.createElement('div');
    toolbar.className = 'portal-svg-vp-toolbar';
    toolbar.setAttribute('data-portal-svg-vp', '1');
    var btns = [
      { label: '+', title: 'Zoom In', fn: function () { zoomCenter(1.25); } },
      { label: '\u2212', title: 'Zoom Out', fn: function () { zoomCenter(0.8); } },
      { label: 'Fit', title: 'Reset / Fit View', fn: fit },
      { label: 'Export SVG', title: 'Download SVG', fn: exportSvg }
    ];
    btns.forEach(function (b) {
      var el = document.createElement('button');
      el.type = 'button';
      el.className = 'portal-svg-vp-btn';
      el.textContent = b.label;
      el.title = b.title;
      el.addEventListener('click', function (ev) { ev.stopPropagation(); b.fn(); });
      toolbar.appendChild(el);
    });
    host.appendChild(toolbar);

    host.addEventListener('wheel', onWheel, { passive: false });
    host.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    apply();

    function destroy() {
      host.removeEventListener('wheel', onWheel);
      host.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      if (toolbar.parentNode) toolbar.parentNode.removeChild(toolbar);
      delete host._portalSvgVpDestroy;
    }

    host._portalSvgVpDestroy = destroy;
    return {
      zoomIn: function () { zoomCenter(1.25); },
      zoomOut: function () { zoomCenter(0.8); },
      fit: fit,
      exportSvg: exportSvg,
      getState: function () { return { scale: state.scale, tx: state.tx, ty: state.ty }; },
      destroy: destroy
    };
  }

  window.PortalSVGViewport = { attach: attach };
})();
