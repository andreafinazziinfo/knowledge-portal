# 📘 Manuale Operativo — Knowledge Portal (V2.3)

> **Piattaforma**: Knowledge Portal — Architecture Intelligence & Living Documentation Engine  
> **Versione**: 2.3.0 (Architecture & Data Lineage Engine)  
> **Licenza**: Apache 2.0 (Open Source)

---

## 1. Introduzione & Architettura

**Knowledge Portal** trasforma qualsiasi repository o codebase complessa in un portale interattivo esplorabile via browser (desktop e mobile). Non richiede framework esterni pesanti: il core server, lo scanner poliglotta e l'indicizzatore girano in **pura Python Standard Library (3.10+)**.

### 🌟 Funzionalità Principali (V2.3)

1. **Scanner Poliglotta Full-Stack (10 Linguaggi)**: Scansiona contemporaneamente:
   - **Python**: Classi, funzioni sincrone/asincrone, docstring, chiamate.
   - **TypeScript / JavaScript**: Classi, interfacce, tipi, funzioni arrow, export.
   - **Vue 3**: Componenti Single File (`.vue`), script setup, template.
   - **Pinia**: Store reattivi (`defineStore`) con tracciamento dipendenze.
   - **Go**: Struct, interfacce, metodi e funzioni.
   - **Rust**: Struct, enum, trait, blocchi `impl` e funzioni.
   - **C / C++**: Struct, classi, metodi, funzioni e header.
   - **Java / Kotlin**: Classi, interfacce, dataclass e metodi.
   - **C#**: Classi, interfacce, record e metodi.
   - **SQL**: Tabelle DDL (`CREATE TABLE`), colonne, tipi, chiavi primarie e foreign keys.
2. **Generatore Dichiarativo di Floorplan SVG (`architecture.yaml`)**:
   - Compilazione automatica di piante topologiche e mappe microservizi vettoriali interattive a partire da un semplice file YAML, senza librerie grafiche pesanti.
3. **Database & Schema Lineage Explorer**:
   - Ispezione visiva di schede tabelle (colonne, PK, FK) e grafo relazionale interattivo Vis.js a nodi e archi orientati generato nativamente da file SQL.
4. **Dashboard Adattiva Dinamica (`views-manifest.json`)**:
   - Rilevamento automatico delle viste attive: tab, card e voci di menu per viste prive di dati vengono automaticamente nascoste, eliminando schede vuote e 404.
5. **Indipendenza Totale da Graphify**:
   - Le viste storiche (`graph`, `canvas`, `tree`, `graph_3d`) consumano i dati nativamente prodotti dallo scanner interno (`polyglot.py`), eliminando qualsiasi dipendenza da repository o tool esterni.
6. **Analytics Architetturali nel Grafo**:
   - 🔴 **Rilevamento Dipendenze Cicliche**: Algoritmo DFS in-memory per scovare accoppiamenti circolari nel grafo delle chiamate.
   - ⚪ **Isolamento Nodi Orfani**: Individuazione immediata di codice morto o documentazione isolata.
7. **Rendering Nativo Mermaid nel Reader**:
   - Visualizzazione istantanea di diagrammi con bundle offline isolato e gestione errori graceful.
8. **Esportatore Statico "Zero-Server"**:
   - Generazione di un sito statico pronto per **GitHub Pages** con `knowledge-portal export`.
9. **Container Docker OCI**:
   - Immagine ufficiale su GitHub Container Registry (`ghcr.io/andreafinazziinfo/knowledge-portal:latest`).

---

## 2. Installazione Rapida

### Metodo A: Installazione da Sorgente (Python)

```bash
git clone https://github.com/your-org/knowledge-portal.git
cd knowledge-portal
pip install -e .
```

### Metodo B: Docker (Zero Setup)

```bash
docker run -d -p 8000:8000 -v $(pwd):/app/data ghcr.io/your-org/knowledge-portal:latest
```

---

## 3. Guida ai Comandi CLI

### 3.1 Scansione del Codice (`scan`)

Scansiona la cartella di progetto ed estrae l'albero AST poliglotta generando `graph.json` e `graph_viz.js`:

```bash
# Scansione della directory corrente
knowledge-portal scan

# Scansione di una cartella specifica con output personalizzato
knowledge-portal scan /path/to/my-codebase --output /path/to/output

# Scansione classica solo Python (se non si desidera analizzare JS/TS/Go/Rust)
knowledge-portal scan --classic
```

### 3.2 Avvio del Portale Interattivo (`serve`)

Avvia il server HTTP locale con supporto SSE per il live-reload automatico quando i file vengono modificati:

```bash
knowledge-portal serve --port 8000
```
Apri il browser su: `http://localhost:8000/dashboard.html`

### 3.3 Esportazione Statica per GitHub Pages (`export`)

Crea un bundle statico auto-contenuto (HTML + JS + dati inlined) consultabile a freddo senza alcun server attivo:

```bash
knowledge-portal export /path/to/codebase --output ./dist --name "My Project"
```

Per pubblicare su GitHub Pages:
```bash
cd dist
git init
git checkout -b gh-pages
git add .
git commit -m "Deploy Knowledge Portal to GitHub Pages"
git remote add origin https://github.com/<user>/<repo>.git
git push -f origin gh-pages
```

### 3.4 Generatore Floorplan Dichiarativo (`floorplan`)

Compila una pianta topologica e mappa architetturale SVG a partire da un descrittore `architecture.yaml`:

```bash
knowledge-portal floorplan architecture.yaml --output template/views/floorplan.html
```

### 3.5 Audit di Sicurezza OPSEC (`audit`)

Verifica che nel portale non vi siano token segreti, credenziali, formule proprietarie o percorsi locali sensibili:

```bash
knowledge-portal audit .
```

---

## 4. Guida alle Viste Principali

### 🌌 2D Network Graph & 🌐 3D WebGL
- **Navigazione**: Trascina per ruotare o spostare la vista, usa la rotella per lo zoom.
- **Ispezione**: Clicca su un nodo per visualizzare il file di appartenenza, la riga, la docstring e i collegamenti.
- **Pulsanti Analytics**:
  - Clicca su **🔴 Cicli** per evidenziare in rosso brillante eventuali dipendenze circolari.
  - Clicca su **⚪ Orfani** per evidenziare in giallo i nodi non collegati.
  - Clicca su **↺** per ripristinare la colorazione per community.

### 🗄️ Database & Schema Lineage Explorer
- **Catalogo Tabelle**: Visualizza ogni tabella estratta dai file SQL con tipi di colonna, chiavi primarie e foreign keys.
- **Filtri di Ricerca**: Ricerca per tabella, colonna o relazione; filtri rapidi per tabelle con dipendenze o radici.
- **Grafo Relazionale Interattivo (Vis.js)**: Mappa topologica delle tabelle collegate da foreign keys con fisica dinamica. Cliccando su un nodo del grafo, la vista passa alla scheda dettagliata della tabella selezionata.

### 🏗️ Floorplan SVG Interattivo
- Mappa vettoriale multilivello (Frontend, Gateway, Core Services, Database/Cache) generata da `architecture.yaml`.
- Hotspot interattivi sui microservizi con cassetto laterale dettagliato, controlli Zoom In/Out e Reset.

### 🧭 Dashboard Adattiva (Zero 404)
- La dashboard rileva all'avvio il manifesto delle viste (`data/views-manifest.json`).
- I tab e le card delle viste non attive vengono nascosti automaticamente.

### 📖 Reader Markdown con Mermaid
- Seleziona un file dall'albero di sinistra o premi `Ctrl+K` per cercare qualsiasi termine.
- I diagrammi ````mermaid` vengono convertiti al volo in vettori SVG interattivi.
- Se un diagramma contiene errori di sintassi, viene mostrato un banner di avviso senza interrompere la lettura del documento.

### 🔌 API Catalog (Scalar)
- Catalogo interattivo OpenAPI completamente offline con endpoint raggruppati per tag, schema dei modelli e documentazione delle risposte HTTP.

---

## 5. Sicurezza, Container & CI/CD

### Hardening Server & Container (`docker-compose.yml`)
- **`PORTAL_READ_ONLY=1`**: Blocca tutti gli endpoint mutanti (`POST`, rebuild, sync, console) con `403`, mantenendo attivi tutti i `GET` e `/api/telemetry`.
- **`PORTAL_API_TOKEN`**: Se impostato, richiede `X-Portal-Token` o `Authorization: Bearer <token>` sulle operazioni di scrittura.
- **`PORTAL_ACCESS_LOG=1`**: Emette access log JSON strutturati su `stdout`.
- **Container Hardened**: Esegue come utente non-root `portaluser` con filesystem `read_only: true`, `no-new-privileges:true` e healthcheck su `/api/telemetry`.
- **CLI & MCP Integration**: `knowledge-portal mcp`, `knowledge-portal status` e `knowledge-portal query` usano `PortalMcpEngine` (zero dipendenze esterne, `safe_resolve_under` attivo su `portal_read_doc`).

### Pipeline CI/CD (`CI Suite`)
Il repository include una suite GitHub Actions con verifica continua:
- **Code Quality**: Ruff linter, Mypy type checker e Bandit security scanner.
- **OPSEC Audit**: Verifica `verify_sanitization.py` su ogni push.
- **Unit, Polyglot & Coverage Tests**: `pytest` su Python 3.10, 3.11 e 3.12 con `pytest-cov` (`--cov-fail-under=65`), inclusi test su path traversal, security headers, `/api/telemetry` e `cli.py`.
- **Frontend Playwright E2E & Style Gate**: Verifica headless Chromium su `dashboard.html` e tutte le viste (`0` errori JS/HTTP, sfondo `#0f0f0f`, scorciatoia `/`, responsiveness `1440×900`, `768×1024`, `390×844`).
- **Container Build Check**: Verifica `docker build` dell'immagine di produzione su ogni push/PR.
