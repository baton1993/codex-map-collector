#!/usr/bin/env python3
"""Launcher: creates venv, installs deps, starts the Codex Map Collector app."""
import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path

ROOT = Path(__file__).parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def pip(*args):
    run([str(VENV / "bin" / "pip"), *args], stdout=subprocess.DEVNULL)


def ensure_venv():
    if not (VENV / "bin" / "python").exists():
        print("Creating virtual environment...")
        run([sys.executable, "-m", "venv", str(VENV)])

    print("Checking dependencies...")
    pip("install", "--quiet", "--upgrade", "pip")
    pip("install", "--quiet", "-r", str(REQ))

    # Ensure Playwright browsers are installed
    pw = VENV / "bin" / "playwright"
    if pw.exists():
        try:
            run([str(pw), "install", "chromium", "--with-deps"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def find_free_port(start=7860):
    import socket
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main():
    os.chdir(ROOT)
    ensure_venv()

    port = find_free_port(7860)
    url = f"http://127.0.0.1:{port}"
    python = str(VENV / "bin" / "python")

    print(f"\n✅ Codex Map Collector is running at {url}\n")

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    os.execv(python, [python, "-m", "uvicorn", "app:app",
                      "--host", "127.0.0.1",
                      "--port", str(port),
                      "--reload"])


if __name__ == "__main__":
    main()
