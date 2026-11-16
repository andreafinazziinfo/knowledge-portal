# 📘 Manuale Operativo — Knowledge Portal (V2.2)

> **Piattaforma**: Knowledge Portal — Architecture Intelligence & Living Documentation Engine  
> **Versione**: 2.2.0 (Pragmatic Streamlined Release)  
> **Licenza**: Apache 2.0 (Open Source)

---

## 1. Introduzione & Architettura

**Knowledge Portal** trasforma qualsiasi repository o codebase complessa in un portale interattivo esplorabile via browser (desktop e mobile). Non richiede framework esterni pesanti: il core server, lo scanner poliglotta e l'indicizzatore girano in **pura Python Standard Library (3.10+)**.

### 🌟 Funzionalità Principali (V2.2)

1. **Scanner Poliglotta Full-Stack**: Scansiona contemporaneamente:
   - **Python**: Classi, funzioni sincrone/asincrone, docstring, chiamate.
   - **TypeScript / JavaScript**: Classi, interfacce, tipi, funzioni arrow, export.
   - **Vue 3**: Componenti Single File (`.vue`), script setup, template.
   - **Pinia**: Store reattivi (`defineStore`) con tracciamento dipendenze.
   - **Go**: Struct, interfacce, metodi e funzioni.
   - **Rust**: Struct, enum, trait, blocchi `impl` e funzioni.
2. **21 Viste Interattive**:
   - Grafo 2D Vis.js, WebGL 3D Three.js, DAG ad albero top-down, Whiteboard Canvas, Floorplan SVG, DB Lineage, Async & WebSocket, Worker Tasks, Threat Matrix, Scalar OpenAPI Catalog.
3. **Analytics Architetturali nel Grafo**:
   - 🔴 **Rilevamento Dipendenze Cicliche**: Algoritmo DFS in-memory per scovare accoppiamenti circolari nel grafo delle chiamate.
   - ⚪ **Isolamento Nodi Orfani**: Individuazione immediata di codice morto o documentazione isolata.
4. **Rendering Nativo Mermaid nel Reader**:
   - Visualizzazione istantanea di flowchart, sequence diagrams e diagrammi di stato scritti in Markdown con bundle offline isolato e gestione errori graceful.
5. **Esportatore Statico "Zero-Server"**:
   - Generazione di un sito statico pronto per **GitHub Pages** con `knowledge-portal export`.
6. **Container Docker OCI**:
   - Immagine ufficiale su GitHub Container Registry (`ghcr.io/your-org/knowledge-portal:latest`).

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

### 3.4 Audit di Sicurezza OPSEC (`audit`)

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

### 📖 Reader Markdown con Mermaid
- Seleziona un file dall'albero di sinistra o premi `Ctrl+K` per cercare qualsiasi termine.
- I diagrammi ````mermaid` vengono convertiti al volo in vettori SVG interattivi.
- Se un diagramma contiene errori di sintassi, viene mostrato un banner di avviso senza interrompere la lettura del documento.

### 🔌 API Catalog (Scalar)
- Catalogo interattivo OpenAPI completamente offline con endpoint raggruppati per tag, schema dei modelli e documentazione delle risposte HTTP.

---

## 5. Manutenzione e CI/CD

Il repository include una suite GitHub Actions con verifica continua:
- **Code Quality**: Ruff linter, Mypy type checker e Bandit security scanner.
- **OPSEC Audit**: Verifica `verify_sanitization.py` su ogni push.
- **Unit & Polyglot Tests**: Test deterministici su Python, TypeScript, Vue, Go e Rust.
- **Static Export Check**: Verifica della build statica in ambiente isolato.
