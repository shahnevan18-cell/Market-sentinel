"""Build a clean zip of the project to share: python scripts/make_share_zip.py

The zip leaves out everything that is private, bulky or specific to this computer:
  - .env and .streamlit/secrets.toml, which may hold API keys (.env.example is kept)
  - the private Python environment (.venv), which only works on the computer that made it
  - cached market data, saved investigations and other files under data/ (the empty folders are kept)
  - Python caches, editor folders and older zips
The recipient extracts it and double-clicks run_app.bat (Windows) or run_app.command (macOS), which
rebuild the environment on their computer. By default the zip is written next to the project folder as
Market_Sentinel_share.zip; pass another path as the first argument to change that.
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT.parent / "Market_Sentinel_share.zip"

SKIP_DIRS = {".venv", "venv", "env", "__pycache__", ".pytest_cache", ".git", ".idea", ".vscode", ".mypy_cache",
             ".ruff_cache", "dist", "build"}
SKIP_FILES = {".env", ".DS_Store", "Thumbs.db", "desktop.ini"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".zip", ".log"}
EXECUTABLE = {"run_app.command"}


def include(relative: PurePosixPath) -> bool:
    """Whether a file (path relative to the project root) belongs in the shared zip."""
    parts = relative.parts
    if any(part in SKIP_DIRS or part.startswith(".venv") for part in parts[:-1]):
        return False
    name = parts[-1]
    if name in SKIP_FILES or relative.suffix.lower() in SKIP_SUFFIXES:
        return False
    if relative == PurePosixPath(".streamlit/secrets.toml"):
        return False                         # deployment secrets, like .env
    if parts[0] == "data":
        return name == ".gitkeep"          # keep the empty folders, never cached data or saved runs
    return True


def build_share_zip(root: Path = ROOT, output: Path = DEFAULT_OUTPUT) -> list[str]:
    root = root.resolve()
    output = output.resolve()
    names = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".venv"))   # never walk .venv
        for file in sorted(files):
            path = Path(folder) / file
            if path.resolve() == output:
                continue
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if include(relative):
                names.append(str(relative))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            info = zipfile.ZipInfo.from_file(root / name, arcname=name)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if PurePosixPath(name).name in EXECUTABLE else 0o644
            info.external_attr = (0o100000 | mode) << 16      # regular file with Unix permissions
            archive.writestr(info, (root / name).read_bytes(), compresslevel=9)
    return names


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    names = build_share_zip(ROOT, output)
    size_kb = output.stat().st_size / 1024
    print(f"Wrote {output} ({len(names)} files, {size_kb:,.0f} KB).")
    print("Left out: .env, .venv, cached market data, saved investigations and Python caches.")
    print("The recipient extracts it and double-clicks run_app.bat (Windows) or run_app.command (macOS).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
