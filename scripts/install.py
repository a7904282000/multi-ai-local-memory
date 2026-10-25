#!/usr/bin/env python3
"""Zero-config installer for Multi-AI Local Memory.

Creates a private Python venv, installs the bundled Local Bridge runtime,
then runs the bridge's zero-config installer. It never rewrites existing
source memories; provider/native memory migrations are archived byte-for-byte.
"""
from __future__ import annotations
import os, subprocess, sys, venv
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RUNTIME = BASE / "runtime" / "multi-ai-local-bridge"
HOME = Path.home()
VENV = HOME / ".multi-ai-local-memory" / "runtime-venv"

def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"

def main() -> int:
    if sys.version_info < (3, 11):
        print("STATUS=BLOCKED")
        print("EXTERNAL_BLOCKER=Python 3.11 or newer is required.")
        return 2
    VENV.parent.mkdir(parents=True, exist_ok=True)
    if not venv_python().exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    py = str(venv_python())
    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([py, "-m", "pip", "install", "--upgrade", str(RUNTIME)], check=True)
    cmd = [py, "-m", "malm_bridge.installer", "install"]
    result = subprocess.run(cmd)
    return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())
