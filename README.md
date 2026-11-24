# 🌌 Knowledge Portal

> **Universal Interactive Software Architecture, Multi-Dimensional AST Knowledge Graph, AI Process Flow Engine & Air-Gapped Documentation Suite**

[![CI Suite](https://github.com/andreafinazziinfo/knowledge-portal/actions/workflows/ci.yml/badge.svg)](https://github.com/andreafinazziinfo/knowledge-portal/actions/workflows/ci.yml)
[![Docker Publish GHCR](https://github.com/andreafinazziinfo/knowledge-portal/actions/workflows/docker.yml/badge.svg)](https://github.com/andreafinazziinfo/knowledge-portal/actions/workflows/docker.yml)
[![CodeQL Security Analysis](https://github.com/andreafinazziinfo/knowledge-portal/actions/workflows/codeql.yml/badge.svg)](https://github.com/andreafinazziinfo/knowledge-portal/actions/workflows/codeql.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type Checked: Mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)
[![Security: Bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
[![Release: v3.0.0 Enterprise Edition](https://img.shields.io/badge/release-v3.0.0%20Enterprise%20Edition-purple.svg)](https://github.com/andreafinazziinfo/knowledge-portal/releases)
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
- **🕸️ Unified Graph Studio (18 Visualization Modes + SVG/PNG Snapshot)**: Switch seamlessly between 18 zero-CDN visualizers (2D/3D Graph, Particle Flow, Chord, Edge Bundling, Arc Diagram, Hive Plot, 2D/3D Canvas, CodeCity 3D, Sankey, Tree, Treemap, Sunburst, Circle Pack, Icicle, Radial Tidy Tree, 3D Tree) with `?focus=` persistence and 1-click `📷 Snapshot` export.
- **🩺 Health & Audit Center 4.0+ (10 Diagnostic Tabs · Deep Audit · SARIF & CI Gate — ADR-080)**: File-level Tarjan SCC cycles, Robert C. Martin metrics & DSM, McCabe/Cognitive/MI, CodeScene Risk Matrix, OWASP Quick-Audit, Reliability AST, DB N+1 & **TimescaleDB Hypertables/CAGGs**, API Governance, Per-Domain Test Ratio & Smells, Ownership & Conway Map, Git-Ref Arch Diff & Doc-Drift, **Tab 9 `🐛 Runtime Bugs & CI/CVE`** (Python + Vue/TS Runtime Bugs v2, GitHub Actions CI/CD hardening, local CVE JSON ingestion for `pip-audit`/`npm-audit`/`osv-scanner`/`trivy` correlated with CycloneDX 1.5 SBOM), and **Tab 10 `🧬 Deep Audit: Dead Code, Migrations, FE & Telemetry`** (symbol-level Python/JS/TS/Vue dead code, SQL migration safety & SRE resilience, Pinia/Vue frontend hygiene & static a11y, Quality Telemetry ingestion for JUnit/Coverage/Ruff/Mypy/TSC, and **AST Semantic Clones**), plus Print/PDF, Markdown, SARIF 2.1.0 export and `knowledge-portal gate`.
- **🎛️ Enterprise Control Hub OSS (ADR-081)**: Four air-gapped operational views — **Mission Control (`views/mission-control.html`)** unified KPI & anomaly board, **Git & PR DAG (`views/git-pr-dag.html`)** worktree/branch/stacked-PR topology, **ADR & Runbook Hub (`views/adr-runbook-hub.html`)** decision graph & lifecycle tracker, and **AI Mission Launcher (`views/ai-mission-launcher.html`)** one-click prompt & context-pack generator.
- **⚡ End-to-End Sequence Tracer & 💥 What-If Impact Simulator**: Trace AST symbol-level `Route → Handler → Service → DB` call chains (`views/sequence-tracer.html`) and visually simulate `d=1 / d=2 / d=3` blast radius with suggested `pytest` commands (`views/impact-simulator.html`).
- **🔌 Live Auto-Discovered API Catalog & CycloneDX 1.5 SBOM**: Polyglot AST/regex route extraction (FastAPI, Flask, Express, Go, OpenAPI 3.1) in `views/api-catalog.html`, plus license compliance & downloadable `sbom.cdx.json` in `views/stack-ecosystem.html`.
- **⚡ Cross-Stack Intelligence, Test Oracle & Data Contracts (ADR-082)**: 100% air-gapped 0-CDN views for **Vertical Slices (`views/vertical-slices.html`)**, **Test-to-Code Reverse Oracle (`views/test-oracle.html`)**, **Data Contracts & Runtime Modes (`views/data-contracts.html`)**, plus data-driven conversions of `async-topology.html`, `worker-tasks.html`, `frontend-state.html`, and `data-ingestion.html` (**40 interactive HTML views** in `template/views/`).
- **🤖 Enterprise AI Context Engine (MCP · 37 OSS Tools · 22 Resources · Token-Budget Engine · Code Mode)**: **37 read-only OSS MCP tools** (35 standard + 2 Cloudflare-style AST-sandboxed `--code-mode` tools `portal_discover` & `portal_codemode`) with Token-Budget Engine (`-98.7%` payload reduction, default `detail="summary"`), including `portal_slice_for_task`, `portal_check_diff`, `portal_test_oracle`, `portal_vertical_slice`, `portal_async_topology`, `portal_contract`, `portal_sarif_findings`, `portal_handoff_pack`, `portal_agent_instructions_audit`, `portal_mission_control`, `portal_git_dag`, and `portal_adr_graph`; **22 MCP `portal://` resources** (`portal://llms.txt`, `portal://health`, `portal://api-catalog`, `portal://arch-diff`, `portal://sbom`, `portal://invariants`, `portal://ownership`, `portal://compliance`, `portal://cve-report`, `portal://dead-code`, `portal://quality-telemetry`, `portal://git-dag`, `portal://adr-graph`, `portal://mission-control`, `portal://module-cards`, `portal://test-oracle`, `portal://agent-instructions-audit`, `portal://sarif-findings`, `portal://vertical-slices`, `portal://async-topology`, `portal://data-contracts`, `portal://runtime-modes`), `prompts/*`, hybrid FTS5 + 1-hop graph search, and `knowledge-portal pr-comment` Doc-Drift detector.
- **🧭 Guided Onboarding, Universal `Cmd+K`, Deep-Linking & Dark/Light Theme**: Fuzzy keyboard-navigable `Cmd+K` across views/docs/APIs, 3 interactive onboarding tracks, shareable `?tab=&file=&target=` URLs, and 1-click `🌙 / ☀️` presentation theme toggle.
- **🛡️ Zero-Dependency Core Runtime**: The server, watcher, and Polyglot AST scanner rely strictly on the **Python 3.10+ Standard Library** (zero heavy framework dependencies).

---

## 🖼️ Visual Showcase (40 Air-Gapped Portal Views)

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

### 6. Enterprise Studio, Health Engine 4.0 & Intelligence Views (v3.0)
| Unified Graph Studio (20 Modes · CodeCity 3D) | Health & Audit Center 4.0+ (16 Pillars · 10 Tabs) |
|---|---|
| ![Graph Studio](docs/screenshots/graph-studio-view.png) | ![Health & Audit 4.0](docs/screenshots/health-audit-v4-view.png) |

| End-to-End Sequence & Call-Chain Tracer | What-If Blast-Radius Impact Simulator |
|---|---|
| ![Sequence Tracer](docs/screenshots/sequence-tracer-view.png) | ![Impact Simulator](docs/screenshots/impact-simulator-view.png) |

| Architecture Diff, Git-Ref & Doc-Drift | Live Auto-Discovered API & OpenAPI 3.1 Explorer |
|---|---|
| ![Arch Diff](docs/screenshots/arch-diff-view.png) | ![Live API Catalog](docs/screenshots/api-catalog-live-view.png) |

| 360° Radial Tidy Tree | Hierarchical Edge Bundling |
|---|---|
| ![Radial Tree](docs/screenshots/radial-tree-view.png) | ![Edge Bundling](docs/screenshots/edge-bundling-view.png) |

### 7. Control Hub & Cross-Stack Intelligence (ADR-081 & ADR-082)
| Executive Mission Control | Cross-Stack Vertical Slices |
|---|---|
| ![Mission Control](docs/screenshots/mission-control.png) | ![Vertical Slices](docs/screenshots/vertical-slices.png) |

| Data Contracts & Schema Drift Registry | |
|---|---|
| ![Data Contracts](docs/screenshots/data-contracts.png) | |

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
| **🩺 Health & Studio** | **Health & Audit Center 4.0+** (`arch-health.html`) | 10-Tab D3 Engine | Tarjan SCC cycles, Martin DSM, OWASP, Runtime Bugs v2, CVE/SBOM, Dead Code, SARIF 2.1.0, AST Clones. |
| | **Unified Graph Studio** (`graph-studio.html`) | 20 Modes · 0-CDN | 2D/3D Graph, CodeCity 3D, Sankey, Chord, Edge Bundling, Arc, Hive Plot, Sunburst, Circle Pack, Icicle, Radial Tree. |
| | **Sequence Tracer & Impact Simulator** | AST Call Graph | `Route → Handler → Service → DB` chains (`sequence-tracer.html`) and `d=1/2/3` blast radius (`impact-simulator.html`). |
| **🎛️ Control Hub (ADR-081)** | **Mission Control** (`mission-control.html`) | Air-Gapped Bento | Executive KPI grid, subsystem traffic lights, prioritized P0/P1/P2 anomalies, quick jumps. |
| | **Git & PR DAG** (`git-pr-dag.html`) | Git Hygiene DAG | Worktree matrix (`clean/dirty/stale/detached/locked`), stacked PR chains, and merge order. |
| | **ADR & Runbook Hub** (`adr-runbook-hub.html`) | Decision Graph | Chronological ADR dependency/supersession graph and interactive runbook checklists. |
| | **AI Mission Launcher** (`ai-mission-launcher.html`) | Context Builder | One-click scoped AI mission briefs and token-budgeted context packs. |
| **⚡ Cross-Stack (ADR-082)** | **Vertical Slices** (`vertical-slices.html`) | 6-Layer Tracer | End-to-end `UI Component → Store → API → Backend → Worker → DB` slice explorer. |
| | **Test-to-Code Oracle** (`test-oracle.html`) | Reverse AST Map | Maps modules/symbols to fastest direct tests and highlights untested blind spots. |
| | **Data Contracts** (`data-contracts.html`) | Drift Registry | Pydantic↔TypeScript schema drift, Error Taxonomy, DB readers/writers, and runtime modes. |
| | **Async, Workers, State & Ingestion** | 0-CDN Data Views | `async-topology.html`, `worker-tasks.html`, `frontend-state.html`, `data-ingestion.html` (**40 HTML views total** in `template/views/`). |

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
usage: knowledge-portal [-h]
                        {scan,export,serve,floorplan,audit,mcp,status,query,report,gate,pr-comment}
                        ...

Knowledge Portal — Universal Interactive Software Architecture & AST Knowledge Engine

positional arguments:
  {scan,export,serve,floorplan,audit,mcp,status,query,report,gate,pr-comment}
                        Available commands (11 subcommands)
    scan                Scan codebase AST and generate graph data
    export              Export static zero-server bundle ready for GitHub Pages or offline use
    serve               Start the Knowledge Portal HTTP server with SSE live-reload
    floorplan           Generate interactive vector floorplan from architecture.yaml
    audit               Run Zero-Proprietary Sanitization Audit
    mcp                 Start stdio MCP (Model Context Protocol) server for AI agents (37 OSS tools / 22 resources)
    status              Inspect live portal telemetry or static snapshot status
    query               Query portal knowledge artifacts (search, flow, schema, stack)
    report              Generate Executive Markdown or SARIF 2.1.0 audit report
    gate                CI Quality Gate — exits 0 on pass, 1 on threshold violation
    pr-comment          Generate Markdown PR review comment with Doc-Drift & impacted tests

options:
  -h, --help            show this help message and exit
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

Knowledge Portal enforces strict code quality and security standards across **3 GitHub Actions workflows**:

- **`.github/workflows/ci.yml` (`CI Suite`)**: [Ruff](https://github.com/astral-sh/ruff) lint, [Mypy](https://mypy-lang.org/) type checking, [Bandit](https://github.com/PyCQA/bandit) SAST, `verify_sanitization.py` OPSEC gate, Pytest unit suite + coverage, and Playwright headless E2E verification.
- **`.github/workflows/docker.yml` (`Docker Publish GHCR`)**: Multi-arch Alpine container build and automated publish to `ghcr.io`.
- **`.github/workflows/codeql.yml` (`CodeQL Security Analysis`)**: Automated Python & JavaScript CodeQL scanning with SARIF 2.1.0 security reporting.

Run the full verification gate locally:
```bash
# Run sanitization OPSEC audit (must report 0 violations)
python3 verify_sanitization.py .

# Run linter & static type checker
ruff check .
mypy knowledge_portal/ --ignore-missing-imports

# Run unit tests
python3 -m pytest tests/unit -q
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

## 🧭 Unified Graph Studio (20 Modes), Health & Audit Center, AI Intelligence & Code Mode MCP (ADR-069 – ADR-074)

- **Unified Graph Studio (`views/graph-studio.html`)**: Consolidates **20 zero-dependency interactive visualizations** into a single 60 FPS studio shell with clean WebGL disposal:
  - *Network*: `2D Graph`, `3D Sphere`, `Particle Flow` (60 FPS white particles), `Chord Matrix`, `Edge Bundling`, `Arc Diagram` (backward cycle detector), `Hive Plot` (deterministic 3-axis)
  - *Arch*: `2D Canvas`, `3D Z-Planes` (60 FPS white particles), `CodeCity 3D` (isometric buildings with district titles), `Sankey Flow` (clickable layer drawer)
  - *Hierarchy*: `Tree` (Horizontal/Vertical toggle + branch colors), `Treemap`, `Sunburst` (20x zoom), `Circle Pack`, `Icicle / Flamegraph`, `Radial Tree` (360° tidy tree), `3D Tree`
  - *Audit*: `Arch Health` & `Arch Diff` (snapshot evolution viewer via `graph-prev.json` & `/api/arch-diff`)
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

---

## 🚀 Health Engine v4+ Deep Audit & Enterprise Control Hub OSS (ADR-080 & ADR-081)

### 🩺 ADR-080 — Health Engine v4+ (Tab 9 & Tab 10)
- **Tab 9 — `🐛 Runtime Bugs & CI/CVE`**:
  - **Runtime Bugs v2 (Python + Vue/TS)**: detects `ASYNC_BLOCKING_IO` inside `async def`, `UNCLOSED_RESOURCE`, `LATE_BINDING_CLOSURE`, `SWALLOWED_EXCEPTION`, `VUE_VFOR_NO_KEY`, `JS_LEAKED_LISTENER_OR_TIMER`, and `TS_FLOATING_PROMISE`.
  - **TimescaleDB & SQL Deep Health**: auto-discovers Hypertables (`create_hypertable`), Continuous Aggregates (`WITH (timescaledb.continuous)`), compression policies, and PK-less tables.
  - **CVE JSON Ingestion & SBOM Correlation**: ingests local `pip-audit`, `npm-audit`, `osv-scanner`, and `trivy` JSON reports (`data/cve-report.json`), enriching `sbom.cdx.json` `vulnerabilities[]`.
  - **CI/CD & IaC Security**: detects self-hosted `issue_comment` risks, privileged Docker Compose services, root Dockerfiles, open Terraform CIDRs, and missing healthchecks.
- **Tab 10 — `🧬 Deep Audit: Dead Code, Migrations, FE & Telemetry`**:
  - **Symbol-Level Dead Code (`data/dead-code.json`)**: zero-caller Python functions/classes, unused JS/TS exports, and unreferenced Vue SFC components.
  - **Migration Safety & SRE Resilience**: flags `SQL_INDEX_WITHOUT_CONCURRENTLY`, `SQL_LOCK_TIMEOUT_MISSING`, `SRE_FSTRING_LOGGING`, and HTTP/LLM clients missing retry policies.
  - **Frontend Hygiene & Static a11y**: identifies Pinia/Vuex God-Stores, eager routes, error-boundary coverage, and accessibility issues (`A11Y_INPUT_MISSING_LABEL`, `A11Y_CLICKABLE_DIV_NO_ROLE`).
  - **Quality Telemetry Ingestion (`data/quality-telemetry.json`)**: aggregates local Coverage (`coverage.xml`/`lcov.info`), JUnit XML, Ruff, Mypy, and TypeScript (`tsc`) reports.
  - **AST Semantic Clones**: normalized Python AST fingerprinting detecting structural duplicate functions across files.

### 🎛️ ADR-081 — Control Hub OSS & MCP v2 Expansion
- **4 New Air-Gapped Control Hub Views**:
  - `views/mission-control.html` (`data/mission-control.json`, `GET /api/mission-control`) — executive KPI grid, prioritized P0/P1/P2 anomaly radar, and subsystem health cards.
  - `views/git-pr-dag.html` (`data/git-dag.json`, `GET /api/git-dag`) — interactive Git worktree matrix (clean/dirty/stale/detached/locked), branch hygiene, and PR/workflow topology.
  - `views/adr-runbook-hub.html` (`data/adr-graph.json`, `GET /api/adr-graph`) — Architecture Decision Record lifecycle graph, supersession links, and operational runbooks catalog.
  - `views/ai-mission-launcher.html` — interactive mission builder generating copy-ready AI context packs and scoped engineering prompts.
- **MCP v2 Server (`knowledge-portal mcp`)**: expanded to **28 tools** (26 standard + 2 `--code-mode`) and **14 `portal://` resources**, enabling autonomous agents to inspect Mission Control, Git DAG, ADR Graph, Dead Code, Deep Audit, Quality Telemetry, and CVE reports in a single read-only call.

### ⚡ ADR-082 — AI Token-Efficiency Engine, Cross-Stack Intelligence & Zero-CDN Expansion
- **Token-Budget Engine (`-98.7%` MCP payload reduction)**: all heavyweight audit & graph MCP tools default to compact `detail="summary"` responses (`≤800` tokens), paired with `data/module-cards.json` (`GET /api/module-cards`, `≤180` tok/file), task-scoped context slicing (`portal_slice_for_task`), and diff-aware pre-commit/PR impact checks (`portal_check_diff`).
- **Test-to-Code Reverse Oracle (`data/test-oracle.json`, `GET /api/test-oracle`, `views/test-oracle.html`)**: reverse-maps source modules and symbols to their fastest direct tests and surfaces high-risk untested blind spots (`portal_test_oracle`).
- **Agent Instructions Audit (`data/agent-instructions-audit.json`, `GET /api/agent-instructions-audit`)**: audits AI instruction, rule, and skill files for token budget bloat, dead file-path references, and overall hygiene score.
- **Universal SARIF 2.1.0 Ingestor (`data/sarif-findings.json`, `GET /api/sarif-findings`) & CodeQL Workflow (`.github/workflows/codeql.yml`)**: ingests standard SARIF 2.1.0 reports from CodeQL, Semgrep, Trivy, Ruff, or Bandit into the unified health & security dashboard.
- **Cross-Stack Vertical Slices (`data/vertical-slices.json`, `GET /api/vertical-slices`, `views/vertical-slices.html`)**: traces end-to-end `UI Component / Store → REST API → Backend Handler → Database Table` edges (`portal_vertical_slice`).
- **Async Topology (`data/async-topology.json`, `GET /api/async-topology`)**: inventories background worker tasks, scheduled beats, Redis keys/locks, Pub/Sub channels, WebSockets, and SSE streams (`portal_async_topology`).
- **Data Contracts & Runtime Modes (`data/data-contracts.json`, `data/runtime-modes.json`, `GET /api/data-contracts`, `GET /api/runtime-modes`, `views/data-contracts.html`)**: detects Pydantic↔TypeScript schema drift, untyped API routes, exception taxonomy, DB table readers/writers, and environment/runtime mode matrices (`portal_contract`).
- **6+ New & Converted 0-CDN Data-Driven Views**: `vertical-slices.html`, `test-oracle.html`, `data-contracts.html`, plus full data-driven zero-CDN conversions of `async-topology.html`, `worker-tasks.html`, `frontend-state.html`, and `data-ingestion.html`.
- **MCP Server Expansion**: expanded to **37 OSS tools** and **22 `portal://` resources** (extensible to **43 tools** with optional domain-hub plugins), all read-only and token-budgeted.
