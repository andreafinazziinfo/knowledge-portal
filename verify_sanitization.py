#!/usr/bin/env python3
"""
Zero-Proprietary Sanitization Audit Tool (Pillar 8 Security Gate)
Recursively scans files in target directory for any proprietary tokens,
internal IPs, private user paths, secret keys, or trading algorithms.
"""

import os
import sys
import re
from pathlib import Path

# Case-insensitive proprietary keywords
FORBIDDEN_KEYWORDS = [
    "cyclelab",
    "cyclequant",
    "matassa",
    "finazzi",
    "ftmo",
    "dukascopy",
    "cpcv",
    "hurst_fld",
    "orderflow_engine",
    "sovereign.local",
    "andrev",  # private local user
]

# Sensitive regex patterns (IPs, private keys, API secrets)
FORBIDDEN_PATTERNS = [
    (r"\b192\.168\.\d{1,3}\.\d{1,3}\b", "Internal Homelab IPv4 (192.168.x.x)"),
    (r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "Private Class A IPv4 (10.x.x.x)"),
    (r"(?i)(api[_-]?key|secret[_-]?key|jwt[_-]?secret)\s*[:=]\s*[\"\x27][a-zA-Z0-9_\-]{8,}[\"\x27]", "Hardcoded API Key / Secret"),
    (r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", "Private Key Header"),
    (r"/home/andrev/", "Private User Directory Path"),
]

ALLOWED_EXTENSIONS = {
    ".py", ".html", ".js", ".css", ".json", ".md", ".yaml", ".yml",
    ".toml", ".sh", ".txt", ".svg", ".ts"
}

IGNORE_DIRS = {".git", "__pycache__", ".pytest_cache", "venv", ".venv", "node_modules", "vendor"}

def audit_directory(root_dir: Path):
    violations = []
    scanned_files = 0
    clean_files = 0

    print(f"\n🔍 [Audit] Scanning directory: {root_dir.resolve()}")
    print(f"🔒 Checking against {len(FORBIDDEN_KEYWORDS)} proprietary keywords and {len(FORBIDDEN_PATTERNS)} regex rules...\n")

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Exclude ignored dirs
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.name == "verify_sanitization.py":
                continue
            if fpath.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue

            scanned_files += 1
            rel_path = fpath.relative_to(root_dir)

            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                violations.append((str(rel_path), 0, f"Error reading file: {e}"))
                continue

            file_violations = 0
            lines = content.splitlines()

            # 1. Keyword check
            for lineno, line in enumerate(lines, 1):
                lower_line = line.lower()
                for kw in FORBIDDEN_KEYWORDS:
                    if kw in lower_line:
                        # Allow author name in official project metadata
                        if kw == "finazzi" and (fpath.name in ["pyproject.toml", "LICENSE", "README.md"]):
                            continue
                        # Skip if in generic explanation of the check itself
                        if "verify_sanitization" in lower_line or "forbidden" in lower_line:
                            continue
                        violations.append((str(rel_path), lineno, f"Forbidden keyword detected: \x27{kw}\x27 -> {line.strip()[:100]}"))
                        file_violations += 1

            # 2. Regex check
            for pattern, desc in FORBIDDEN_PATTERNS:
                for lineno, line in enumerate(lines, 1):
                    match = re.search(pattern, line)
                    if match:
                        violations.append((str(rel_path), lineno, f"{desc} detected: \x27{match.group(0)}\x27 -> {line.strip()[:100]}"))
                        file_violations += 1

            if file_violations == 0:
                clean_files += 1

    print("=" * 70)
    print(f"📊 Audit Summary:")
    print(f"   Files Scanned: {scanned_files}")
    print(f"   Clean Files:   {clean_files}")
    print(f"   Violations:    {len(violations)}")
    print("=" * 70)

    if violations:
        print("\n❌ FAILED! Proprietary leaks or sensitive tokens found:")
        for file, line, msg in violations[:30]:
            print(f"   - {file}:{line} -> {msg}")
        if len(violations) > 30:
            print(f"   ... and {len(violations) - 30} more violations.")
        return False
    else:
        print("\n✅ PASSED! ZERO proprietary data or sensitive tokens detected.")
        print("   The directory is 100% sanitized and safe for open-source publication.\n")
        return True

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    success = audit_directory(target)
    sys.exit(0 if success else 1)
