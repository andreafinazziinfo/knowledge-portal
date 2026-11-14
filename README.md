# 🌌 Knowledge Portal

> **Universal Interactive Software Architecture & AST Knowledge Engine**

[![CI Suite](https://github.com/andreafinazziinfo/knowledge-portal/actions/workflows/ci.yml/badge.svg)](https://github.com/andreafinazziinfo/knowledge-portal/actions)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

Knowledge Portal is an autonomous, air-gapped web portal that turns any codebase into an interactive, multi-dimensional architecture knowledge base:
- **2D & 3D Interactive Force Graphs**: WebGL 3D networks (Three.js) and 2D organic graphs (Vis.js).
- **Hierarchical Tree & DAG Layouts**: Top-down structural navigation of classes, functions, and modules.
- **Offline OpenAPI / Scalar Catalog**: Self-contained OpenAPI explorer with zero external CDN dependencies.
- **SSE Push Live-Reload**: Instant auto-refresh when code or markdown changes.
- **Responsive Mobile Interface**: Off-canvas drawer and quick-view switcher for desktop, tablet, and smartphone.

---

## ⚡ Quickstart

### 1. Installation

```bash
git clone https://github.com/andreafinazziinfo/knowledge-portal.git
cd knowledge-portal
pip install -e .
```

### 2. Scan your Codebase

```bash
# Scan current directory and build AST graph
knowledge-portal scan /path/to/your/project
```

### 3. Launch the Portal

```bash
# Start threaded server with SSE push
knowledge-portal serve --port 8000
```

Open `http://localhost:8000/dashboard.html` in your browser!

---

## 🔒 Security & Air-Gapped Operation

- **Zero External Telemetry**: All vendor bundles (Scalar, Three.js, Vis.js, KaTeX) are stored locally in `template/vendor/`.
- **Zero Proprietary Leaks**: Verified by automated regex and security scanning (`verify_sanitization.py`).

---

## 📄 License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
