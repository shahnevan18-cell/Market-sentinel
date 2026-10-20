"""Start Market Sentinel with one command: python launch.py

run_app.bat (Windows) and run_app.command (macOS) call this file, so most people never type it.

On the first run it creates a private Python environment in the .venv folder and installs the packages
listed in requirements.txt (internet needed, a few minutes). Later runs skip that step unless
requirements.txt has changed, or the environment no longer works (for example a .venv copied from
another computer), in which case it is rebuilt. It then starts the app on the first free port from 8501
and opens it in the default browser. Works on Windows, macOS and Linux with Python 3.11 or newer.
"""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
MARKER_NAME = "requirements.sha256"
MIN_PYTHON = (3, 11)
FIRST_PORT = 8501


def venv_python(venv_dir: Path = VENV) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_digest(requirements: Path = REQUIREMENTS) -> str:
    """Fingerprint of the requirement lines; editing a comment does not trigger a reinstall."""
    lines = (line.split("#", 1)[0].strip() for line in requirements.read_text(encoding="utf-8").splitlines())
    return hashlib.sha256("\n".join(line for line in lines if line).encode()).hexdigest()


def packages_current(venv_dir: Path = VENV, requirements: Path = REQUIREMENTS) -> bool:
    """True when the packages were installed from exactly this requirements.txt."""
    marker = venv_dir / MARKER_NAME
    return marker.exists() and marker.read_text().strip() == requirements_digest(requirements)


def python_works(python: Path) -> bool:
    if not python.exists():
        return False
    try:
        return subprocess.run([str(python), "-c", "import sys"], capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_environment() -> Path:
    python = venv_python()
    if not python_works(python):
        rebuild = VENV.exists()
        print("Rebuilding the private Python environment in .venv ..." if rebuild else
              "First run: creating a private Python environment in the .venv folder ...", flush=True)
        try:
            venv.EnvBuilder(with_pip=True, clear=rebuild).create(VENV)
        except Exception as exc:  # noqa: BLE001 - shown to the user as a plain message
            raise SystemExit(f"Could not create the environment: {exc}\n"
                             "On Debian or Ubuntu, install the python3-venv package first.") from exc
    if not packages_current():
        print("Installing the packages the app needs. The first time this downloads about 100 MB and takes a "
              "few minutes ...", flush=True)
        result = subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                                 "-r", str(REQUIREMENTS)])
        if result.returncode != 0:
            raise SystemExit("Installing the packages failed. Check the internet connection and run the launcher "
                             "again; it carries on from where it stopped.")
        (VENV / MARKER_NAME).write_text(requirements_digest())
    return python


def port_is_free(port: int) -> bool:
    """A port is taken when something on this computer accepts connections on it.

    Asking for a connection, rather than trying to bind, ignores ports left in the TIME_WAIT state by an app
    that has just stopped, so a quick restart reuses 8501 instead of moving to 8502.
    """
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if sock.connect_ex((host, port)) == 0:
                    return False
        except OSError:
            continue        # IPv6 switched off on this computer
    return True


def pick_port(first: int = FIRST_PORT, tries: int = 20) -> int:
    for port in range(first, first + tries):
        if port_is_free(port):
            return port
    raise SystemExit(f"No free port between {first} and {first + tries - 1}. Close other copies of the app and "
                     "try again.")


def wait_until_ready(process: subprocess.Popen, url: str, timeout: float = 120.0) -> bool:
    """Poll Streamlit's health endpoint, bypassing any proxy, until the app answers or the process ends."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with opener.open(f"{url}/_stcore/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"Market Sentinel needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer; this is "
              f"{sys.version.split()[0]}. Install a newer one from https://www.python.org/downloads/")
        return 1
    if not (ROOT / "app.py").exists():
        print("app.py is missing next to launch.py. Extract the whole zip first, then run the launcher from the "
              "extracted folder.")
        return 1
    python = ensure_environment()
    port = pick_port()
    url = f"http://localhost:{port}"
    command = [str(python), "-m", "streamlit", "run", str(ROOT / "app.py"),
               "--server.address", "localhost", "--server.port", str(port)]
    print(f"Starting Market Sentinel at {url} ...", flush=True)
    process = subprocess.Popen(command, cwd=ROOT)
    try:
        if wait_until_ready(process, url):
            print(f"\nReady. Opening {url} in your browser.\n"
                  "Keep this window open while you use the app. To stop it, close this window or press Ctrl+C.\n",
                  flush=True)
            webbrowser.open(url)
        elif process.poll() is None:
            print(f"The app is slow to start. Open {url} in your browser in a moment.", flush=True)
        return process.wait()
    except KeyboardInterrupt:
        print("\nStopping Market Sentinel ...", flush=True)
        try:
            process.wait(timeout=15)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            process.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
