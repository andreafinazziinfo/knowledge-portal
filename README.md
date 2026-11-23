# 🌌 Knowledge Portal

> **Universal Interactive Software Architecture, Multi-Dimensional AST Knowledge Graph, AI Process Flow Engine & Air-Gapped Documentation Suite**

[![CI Suite](https://github.com/andreafinazziinfo/knowledge-portal/actions/workflows/ci.yml/badge.svg)](https://github.com/andreafinazziinfo/knowledge-portal/actions)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type Checked: Mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)
[![Security: Bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![Release: v2.4.0 Peak Excellence](https://img.shields.io/badge/release-v2.4.0%20Peak%20Excellence-purple.svg)](https://github.com/andreafinazziinfo/knowledge-portal/releases)
[![Offline Ready](https://img.shields.io/badge/air--gapped-100%25%20offline-success.svg)](#-air-gapped-architecture--zero-telemetry)

---

## 📖 Overview

**Knowledge Portal** is an autonomous, self-contained developer portal and architectural intelligence platform. It scans your source code using Abstract Syntax Tree (AST) analysis and instantly transforms static repositories into a **live, multi-dimensional knowledge universe**:

- **🗺️ Radar Minimap & Ego-Network (2D Vis.js)**: Navigate large-scale topologies with a real-time world radar minimap. Isolate selected nodes and their 1-hop/2-hop neighborhood with one click to cut clutter in massive codebases.
- **🚀 3D WebGL Fly-To Camera & HUD Analytics (Three.js)**: Explore 3D force-directed networks with smooth camera tweening (Fly-To), interactive inspector cards, live Depth-First Search cycle detection (`🔴 Cicli`), and orphan finder (`⚪ Orfani`).
- **📑 Smart Markdown Reader with TOC & Mermaid Lightbox**: Collapsible sticky Table of Contents (TOC) with smooth scrolling, one-click code copy buttons, and full-screen vector SVG Mermaid diagrams with interactive zoom.
- **🗄️ Database Lineage with SQL DDL & JOIN Synthesizer**: Interactive ER catalog supporting 10 languages and raw SQL. Features live DDL SQL preview (`CREATE TABLE` with PKs and FKs), automated multi-table `JOIN` query generation, and JSON schema export.
- **🏗️ Declarative Interactive Floorplan (Zero Dependencies)**: Vector SVG architectural floorplan compiler with real-time microservices search, layer isolation toggles, and service lifecycle status badges (`active`, `dev`, `frozen`, `deprecated`).
- **🤖 AI Process Flow Bridge**: Generates end-to-end execution maps (`process-flows.json` & `process_flows.js`) linking API routes and CLI entrypoints to intermediary call chains and SQL database tables, elevating AI agent comprehension to ~98%.
- **🔌 Air-Gapped Offline Scalar OpenAPI Catalog**: Explore and test REST APIs directly inside an embedded, zero-CDN `@scalar/api-reference` suite.
- **⚡ Native SSE Live-Reload Push**: File modifications trigger instantaneous AST updates and browser sync over HTTP Server-Sent Events without manual page reloads.
- **🎨 Unified Carbon-Black Floorplan Design System**: Every view shares the `#0f0f0f` dot-grid canvas, `#191919` surfaces, transparent gradient headers, crisp white hover borders, monochrome active controls, and `/` + `Esc` keyboard ergonomics.
- **📡 Live Telemetry & Auto-Sync (`views/live-telemetry.html`)**: Real-time `/api/telemetry` dashboard with CPU/RAM/Disk sparklines, rebuild progress bars, service latency probes, and graceful offline fallback (`Static Snapshot`).
- **📊 Offline Perspective WASM Pivot Explorer (`views/data-explorer.html`)**: Air-gapped WebAssembly data grid and pivot analytics for architecture nodes, metrics, and schemas.
- **🛡️ Production-Grade Hardening & CI E2E Gate**: Strict path-confinement (`safe_resolve_under`), `PORTAL_READ_ONLY` & `PORTAL_API_TOKEN` guards, HTTP security headers, hardened `read_only` non-root Docker Compose, `pytest-cov` coverage gate, and automated Playwright E2E checks.
- **🔌 Native Zero-Dep MCP Server & CLI Query (`knowledge-portal mcp | status | query`)**: Connect any MCP client (`stdio` JSON-RPC 2.0) to query SQLite FTS5 BM25 search, 1-hop/2-hop graph neighbors, `process-flows.json`, `db-schema.json`, `stack-ecosystem.json`, live `/api/telemetry`, and safe workspace docs. Optional `pip install knowledge-portal[treesitter]` extra available for multi-language AST parsing.
- **🛡️ Zero-Dependency Core Runtime**: The server, watcher, and Polyglot AST scanner rely strictly on the **Python 3.10+ Standard Library** (zero heavy framework dependencies).

---

## 🖼️ Visual Showcase (All 25 Portal Views)

### 1. Core Dashboard Shell & Interactive Architecture
| Home Hub & Federated Omni-Search | Interactive Floorplan (SVG) |
|---|---|
| ![Home Dashboard](docs/screenshots/home-dashboard.png) | ![Floorplan View](docs/screenshots/floorplan-view.png) |

| Tech Stack & Dependencies Ecosystem | Vendor Stack Architecture Diagram |
|---|---|
| ![Stack Ecosystem](docs/screenshots/stack-ecosystem-view.png) | ![Stack Diagram](docs/screenshots/stack-diagram-view.png) |

### 2. Multi-Dimensional Graphs, Canvas & Directory Trees (2D & 3D WebGL)
| 2D Community Galaxy Graph | 3D WebGL Spherical Nebulae Graph |
|---|---|
| ![2D Graph](docs/screenshots/graph-2d-view.png) | ![3D Graph](docs/screenshots/graph-3d-view.png) |

| Full Organic Network Graph | 2D Whiteboard Canvas |
|---|---|
| ![Full Graph](docs/screenshots/graph-full-view.png) | ![2D Canvas](docs/screenshots/canvas-2d-view.png) |

| 3D WebGL Canvas Panels | 2D Collapsible Directory Tree |
|---|---|
| ![3D Canvas](docs/screenshots/canvas-3d-view.png) | ![2D Tree](docs/screenshots/tree-2d-view.png) |

| 3D WebGL Top-Down Directory DAG | |
|---|---|
| ![3D Tree](docs/screenshots/tree-3d-view.png) | |

### 3. Data, Schemas, APIs & Real-Time Telemetry
| Pivot Data Explorer (Perspective WASM Offline) | Database & Schema Lineage |
|---|---|
| ![Data Explorer](docs/screenshots/data-explorer-view.png) | ![DB Lineage](docs/screenshots/db-lineage-view.png) |

| OpenAPI Catalog (Offline Scalar) | Live Telemetry & Auto-Sync |
|---|---|
| ![API Catalog](docs/screenshots/api-catalog-view.png) | ![Live Telemetry](docs/screenshots/live-telemetry-view.png) |

| Async & WebSocket Topology | Data Ingestion Pipeline |
|---|---|
| ![Async Topology](docs/screenshots/async-topology-view.png) | ![Data Ingestion](docs/screenshots/data-ingestion-view.png) |

### 4. Engineering, State, Codex & Visual Explainers
| UI Reactive State & Stores | Background Worker Tasks |
|---|---|
| ![Frontend State](docs/screenshots/frontend-state-view.png) | ![Worker Tasks](docs/screenshots/worker-tasks-view.png) |

| Mathematical Codex (KaTeX) | Visual Explainers Hub |
|---|---|
| ![Quant Codex](docs/screenshots/quant-codex-view.png) | ![Visual Explainers](docs/screenshots/visual-explainers-view.png) |

### 5. Governance, Security & Operations
| ADR Governance Matrix | Engineering Quality Constitution |
|---|---|
| ![ADR Governance](docs/screenshots/adr-governance-view.png) | ![Framework Constitution](docs/screenshots/framework-constitution-view.png) |

| Security Threat Matrix | Operations & Disaster Recovery Runbook |
|---|---|
| ![Threat Matrix](docs/screenshots/threat-matrix-view.png) | ![Ops Runbook](docs/screenshots/runbook-ops-view.png) |

---

## 📚 Documentazione & Guide Operative

- 📘 **[Manuale Utente & Guida per Agenti AI](docs/MANUALE_UTENTE_E_AI.md)**: Manuale completo per sviluppatori umani (ergonomia, scorciatoie, comandi) e protocollo di query JSON per agenti autonomi.
- 📖 **[Manuale Operativo e Amministrativo](docs/MANUALE_OPERATIVO.md)**: Guida all'installazione, configurazione server, container Docker e pipeline CI/CD.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph CoreEngine["⚙️ Knowledge Portal Core (Zero-Dependency Python)"]
        Scanner["🔍 Polyglot AST Code Scanner\n(Python, TS, Go, Rust, C++, SQL...)"]
        Indexer["📑 Federated Omni-Search\n(JSON Inverted Index)"]
        FlowEngine["🤖 AI Process Flow Bridge\n(Routes -> Call Chain -> Tables)"]
        FloorplanCompiler["🏗️ Declarative Floorplan Compiler\n(architecture.yaml -> Vector SVG)"]
        Server["🚀 ThreadingHTTPServer\n(REST API + SSE Push)"]
        Watcher["👁️ Debounced File Watcher\n(Live Event Bus)"]
    end

    subgraph TargetCodebase["📁 Target Codebase / Repository"]
        SourceFiles["🐍 Polyglot Source Files"]
        DocFiles["📝 Markdown Architecture Notes"]
        OpenAPISpec["📄 OpenAPI JSON / YAML Spec"]
        ArchYaml["🏗️ architecture.yaml"]
    end

    subgraph DataArtifacts["📦 Data Artifacts (data/)"]
        GraphJSON["graph.json & graph_viz.js\n(Nodes, Edges, Communities)"]
        DBSchema["db-schema.json & db_schema.js\n(Tables, Columns, FKs)"]
        ProcessFlows["process-flows.json & process_flows.js\n(End-to-End Execution Traces)"]
        OmniIndex["omni-search-index.json\n(Federated Registry)"]
        ViewsManifest["views-manifest.json\n(Adaptive Views Map)"]
    end

    subgraph WebPortal["🌐 Air-Gapped Interactive Web Portal"]
        Shell["📱 Responsive Dashboard Shell\n(Off-Canvas Drawer & View Picker)"]
        View2D["🗺️ 2D Vis.js Network (Radar Minimap & Ego-Isolation)"]
        View3D["🌐 3D Three.js WebGL (Fly-To & Cycle Detection HUD)"]
        ViewDB["🗄️ DB Lineage Explorer (DDL Preview & JOIN Synthesizer)"]
        ViewFP["🏗️ Declarative Floorplan (Live Search & Status Badges)"]
        ViewReader["📖 Markdown Reader (Sticky TOC & Mermaid Lightbox)"]
        ViewScalar["🔌 Offline Scalar OpenAPI Reference"]
    end

    SourceFiles -->|Parsed by| Scanner
    SourceFiles -->|Traced by| FlowEngine
    DocFiles -->|Indexed by| Indexer
    ArchYaml -->|Compiled by| FloorplanCompiler
    OpenAPISpec -->|Rendered by| ViewScalar

    Scanner --> GraphJSON & DBSchema & ViewsManifest
    FlowEngine --> ProcessFlows
    Indexer --> OmniIndex

    GraphJSON & DBSchema & ProcessFlows & OmniIndex --> Server
    Server -->|HTTP & SSE Push| Shell

    Shell --> View2D & View3D & ViewDB & ViewFP & ViewReader & ViewScalar
    SourceFiles -.->|File Change Detected| Watcher
    Watcher -->|SSE Event Broadcast| Server
```

---

## 🔄 Live-Reload & Event-Driven Topology

Knowledge Portal provides sub-second live feedback when modifying code, markdown docs, or API specifications:

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant FS as Codebase Filesystem
    participant PW as Portal Watcher
    participant TS as Threading Server (:8000)
    participant UI as Browser Dashboard (EventSource)

    Dev->>FS: Save file edit (e.g. models.py / doc.md)
    FS-->>PW: Filesystem modification event
    PW->>PW: Debounce batch (250ms)
    PW->>TS: Rebuild AST, DB lineage & process flows
    TS-->>UI: SSE Push (`event: change`, status: updated)
    UI->>UI: Hot-reload active iframe or DOM tree
    Note over UI: Zero full-page refresh required!
```

---

## 🗂️ Interactive Views & Capabilities

| Category | View Name | Technology | Peak Excellence Capability |
| :--- | :--- | :--- | :--- |
| **🌐 Topology** | **2D Organic Network** | Vis.js Physics | Radar minimap with real-time bounding box and ego-network 1/2-hop noise isolation. |
| | **3D WebGL Universe** | Three.js WebGL | Camera fly-to tweening, floating inspector card, DFS cycle detection, orphan node detector. |
| | **Hierarchical DAG** | 3D Collapsible | Top-down tree hierarchy showing module and class inheritance. |
| | **Collapsible Tree** | D3 / 2D Tree | 2D hierarchical navigation tree with search filtering. |
| | **Architecture Floorplan** | Declarative SVG | Real-time microservices search, layer toggles, and status badges (`active`, `dev`, `frozen`, `deprecated`). |
| **🗄️ Database** | **DB Lineage Explorer** | Polyglot SQL AST | Foreign key dependency graph, instant DDL `CREATE TABLE` generator, and automatic SQL `JOIN` generator. |
| **🤖 AI Bridge** | **Process Flow Map** | AST Call Tracing | Maps routes/CLI entrypoints to functions and database tables (`data/process-flows.json`). |
| **📜 Documentation** | **Markdown Reader** | Marked.js + KaTeX | Sticky auto-generated TOC, one-click code copy with visual feedback, Mermaid lightbox zoom. |
| | **Scalar API Catalog** | `@scalar/api-reference` | Air-gapped offline OpenAPI reference with interactive request playground. |
| | **Architecture Decision Records (ADR)** | Markdown Vault | Versioned governance log documenting architectural decisions and status. |
| | **Engineering Constitution** | Quality Framework | Operational engineering principles, circuit breakers, idempotency, and audit standards. |

---

## ⚡ Quickstart

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/andreafinazziinfo/knowledge-portal.git
cd knowledge-portal

# Install in editable mode
pip install -e .
```

### 2. Scan your Codebase

```bash
# Scan any target project directory (generates graph.json, db-schema.json, process-flows.json)
knowledge-portal scan /path/to/your/project

# Example on the bundled sample project:
knowledge-portal scan sample_project --output template/data
```

### 3. Launch the Portal

```bash
# Start the threaded web server with SSE live-reload on port 8000
knowledge-portal serve --port 8000 --dir sample_project
```

### 4. Static Zero-Server Export (GitHub Pages)

```bash
# Export self-contained static site with pre-calculated graphs and omni-search
knowledge-portal export /path/to/your/project --output ./dist --name "My Project"

# The dist/ directory can be opened locally via file:// or pushed directly to GitHub Pages!
```

### 5. Run with Docker

```bash
# Pull and run the official lightweight multi-arch Alpine container (< 50MB)
docker run -d -p 8000:8000 -v $(pwd):/app/data ghcr.io/andreafinazziinfo/knowledge-portal:latest
```

Open **`http://localhost:8000/dashboard.html`** in your browser.

---

## 💻 CLI Command Reference

The `knowledge-portal` CLI provides modular subcommands:

```text
usage: knowledge-portal [-h] {scan,export,floorplan,serve,audit} ...

Knowledge Portal — Universal Interactive Software Architecture & AST Knowledge Engine

positional arguments:
  {scan,export,floorplan,serve,audit}  Available commands
    scan              Scan codebase AST, DB schema, and AI process flows
    export            Export static zero-server bundle ready for GitHub Pages or offline use
    floorplan         Generate interactive vector floorplan from architecture.yaml
    serve             Start the Knowledge Portal HTTP server with SSE live-reload
    audit             Run Zero-Proprietary Sanitization Audit

options:
  -h, --help          Show this help message and exit
```

---

## 🔒 Air-Gapped Architecture & Zero Telemetry

Knowledge Portal was designed from the ground up for **air-gapped and high-security enterprise environments**:

1. **100% Local Vendor Bundles**:
   - Scalar API Reference (`template/vendor/scalar.api-reference.js`)
   - Three.js & 3D Force Graph (`template/assets/3d-force-graph.min.js`)
   - Vis.js Network (`template/vendor/vis-network.min.js`)
   - KaTeX Math Typesetting (`template/vendor/katex/`)
   - FontAwesome Icons & Local Typography
2. **Zero Outbound Network Calls**: No CDN tracking, external telemetry, third-party analytics, or cloud dependencies. The portal functions identically on an air-gapped subnet, internal VPN, or off-grid workstation.
3. **Automated OPSEC Gate**: Includes [`verify_sanitization.py`](verify_sanitization.py) to prevent accidental data leaks in open-source distributions.

---

## 🧪 Testing & CI / CD

Knowledge Portal enforces strict code quality and security standards in GitHub Actions:

- **Linting**: [Ruff](https://github.com/astral-sh/ruff) for rapid, comprehensive style enforcement.
- **Type Checking**: [Mypy](https://mypy-lang.org/) for complete type safety across all AST scanner and server modules.
- **Security Audit**: [Bandit](https://github.com/PyCQA/bandit) automated AST vulnerability scanner + `verify_sanitization.py`.
- **E2E & Unit Tests**: Automated scans on sample codebases validating graph schema integrity, floorplan generator, and process flows.

Run tests locally:
```bash
# Run sanitization audit
python3 verify_sanitization.py .

# Run linter
python3 -m ruff check .

# Run unit tests
python3 -m unittest discover tests/unit -v
```

---

## 🤝 Contributing

Contributions are welcome! Whether it's adding new visual analyzers, multi-language AST parsers, or UI enhancements:

1. Fork the repository.
2. Create your feature branch (`git checkout -b feat/my-new-view`).
3. Commit your changes (`git commit -m 'feat: add interactive sequence diagram view'`).
4. Push to the branch (`git push origin feat/my-new-view`).
5. Open a Pull Request.

Please ensure all tests and `verify_sanitization.py` pass before opening PRs.

---

## 📄 License

This project is licensed under the **Apache License, Version 2.0**. See the [LICENSE](LICENSE) file for details.

## 🧭 Unified Graph Studio (18 Modes), Health & Audit Center, AI Intelligence & Code Mode MCP (ADR-069 / 070 / 071 / 072 / 073)

- **Unified Graph Studio (`views/graph-studio.html`)**: Consolidates **18 zero-dependency interactive visualizations** into a single 60 FPS studio shell with clean WebGL disposal:
  - *Network*: `2D Graph`, `3D Sphere`, `Particle Flow` (60 FPS white particles), `Chord Matrix`, `Edge Bundling`, `Arc Diagram` (backward cycle detector), `Hive Plot` (deterministic 3-axis)
  - *Arch*: `2D Canvas`, `3D Z-Planes` (60 FPS white particles), `CodeCity 3D` (isometric buildings with district titles), `Sankey Flow` (clickable layer drawer)
  - *Hierarchy*: `Tree` (Horizontal/Vertical toggle + branch colors), `Treemap`, `Sunburst` (20x zoom), `Circle Pack`, `Icicle / Flamegraph`, `3D Tree`
  - *Audit*: Quick jump to `Arch Health`
- **Dedicated 8-Pillar Health & Audit Center (`views/arch-health.html`)**: Promoted to top-level navigation with 6 diagnostic tabs — File-level Tarjan SCC cycles, Robert C. Martin Main Sequence ($I$ vs $A$), Domain DSM Heatmap, 6-Axis Radar, AST McCabe/Cognitive Complexity & Maintainability Index, Git Crime Scene (90d Churn Hotspots, Hotspot Bubble Map & Temporal Coupling), 4-Axis Parallel Coordinates, Coverage Report ingestion (`coverage.xml` / `lcov.info`), SQL/Asset Bloat, DB Health, AI Readiness Score, Historical Trend (`arch-health-history.json`), and ROI-prioritized Fix Queue (click any file to open directly in Reader).
- **Full-Project Sidebar & Specialist Visuals**: `📚 Docs | 💻 Source Code` sidebar toggle (`/api/tree?scope=docs|code`, P4 Gate enforced), `ADR Chronological Timeline`, `24h Worker Schedule Gantt`, `Bipartite Store ↔ View Flow`, and universal `? Guida & AI` overlay (`Copy AI Context Pack`, `/llms.txt`, inline `Blast Radius`).
- **AI Intelligence Endpoints & Generators**:
  - `GET /api/context-pack?q=<topic>&max_tokens=4000` — single-call compressed Markdown briefing fusing FTS5 BM25 search, blast radius, process flows, and architectural health.
  - `GET /api/impact?target=<symbol>&depth=3` — native reverse-dependency blast radius (`d=1`, `d=2`, `d=3`).
  - `GET /api/health-audit` (`data/arch-health.json`) — Tarjan SCC dependency cycles, orphans, god-files, and UI→DB layer violations.
  - `GET /llms.txt` & `GET /llms-full.txt` — auto-generated AI discovery manifests.
- **Cloudflare-Style Code Mode MCP (`--code-mode`)**:
  ```bash
  # Compact 2-tool MCP (~1k token schema): portal_discover + read-only AST-sandboxed portal_codemode
  knowledge-portal mcp --dir . --code-mode
  ```
