"""The shared zip and the one-click launcher."""
import importlib.util
import socket
import stat
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


share = _load("make_share_zip", ROOT / "scripts" / "make_share_zip.py")
launcher = _load("launch", ROOT / "launch.py")


def test_share_zip_leaves_out_secrets_environment_and_cached_data(tmp_path):
    project = tmp_path / "market_sentinel"
    files = {
        "app.py": "print('app')", "run_app.bat": "@echo off", "run_app.command": "#!/bin/sh",
        ".env": "ANTHROPIC_API_KEY=secret", ".env.example": "ANTHROPIC_API_KEY=",
        ".streamlit/config.toml": "[server]", ".streamlit/secrets.toml": "ANTHROPIC_API_KEY = 'secret'",
        ".venv/Scripts/python.exe": "binary",
        ".venv/requirements.sha256": "abc", "agents/__pycache__/tools.cpython-315.pyc": "x",
        "data/cache/.gitkeep": "", "data/cache/market/yfinance/AAPL.csv": "date,close",
        "data/investigations/.gitkeep": "", "data/investigations/BAC-2026-10-14.json": "{}",
        "data/laptop_pytest.txt": "84 passed", "docs/user_manual.md": "# Manual",
        "tests/fixtures/sec_submissions.json": "{}", "old_copy.zip": "PK",
    }
    for name, text in files.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    output = tmp_path / "share.zip"
    names = share.build_share_zip(project, output)
    assert sorted(names) == sorted([
        "app.py", "run_app.bat", "run_app.command", ".env.example", ".streamlit/config.toml", "data/cache/.gitkeep",
        "data/investigations/.gitkeep", "docs/user_manual.md", "tests/fixtures/sec_submissions.json"])
    with zipfile.ZipFile(output) as archive:
        assert sorted(archive.namelist()) == sorted(names)
        assert archive.read(".env.example") == b"ANTHROPIC_API_KEY="
        mode = archive.getinfo("run_app.command").external_attr >> 16
        assert mode & stat.S_IXUSR                     # the Mac launcher stays executable


def test_real_project_zip_contains_launchers_and_no_private_files(tmp_path):
    output = tmp_path / "share.zip"
    names = set(share.build_share_zip(ROOT, output))
    assert {"app.py", "launch.py", "run_app.bat", "run_app.command", "START_HERE.txt", "requirements.txt"} <= names
    assert not any(n == ".env" or n.startswith(".venv") or "__pycache__" in n for n in names)
    assert all(PurePosixPath(n).name == ".gitkeep" for n in names if n.startswith("data/"))


def test_launcher_skips_install_only_when_requirements_match(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("streamlit>=1.55\n")
    env_dir = tmp_path / ".venv"
    env_dir.mkdir()
    assert not launcher.packages_current(env_dir, requirements)
    (env_dir / launcher.MARKER_NAME).write_text(launcher.requirements_digest(requirements))
    assert launcher.packages_current(env_dir, requirements)
    requirements.write_text("# a comment edit alone\nstreamlit>=1.55\n")
    assert launcher.packages_current(env_dir, requirements)
    requirements.write_text("streamlit>=1.55\npandas>=2.2\n")
    assert not launcher.packages_current(env_dir, requirements)


def test_launcher_moves_to_the_next_port_when_one_is_busy():
    # The stand-in server must queue several connections, as Streamlit's does: Windows refuses a connection once
    # the queue is full, so with a queue of one the launcher's second check saw the port as free (laptop run,
    # 20 Oct 2026).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(16)
        taken = busy.getsockname()[1]
        assert not launcher.port_is_free(taken)
        assert launcher.pick_port(taken, tries=5) != taken
