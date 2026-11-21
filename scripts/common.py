"""Shared helpers for the job-apply skill scripts.

Everything personal lives in the workspace (default ~/.job-apply, override with
JOB_APPLY_HOME). The skill folder itself holds only generic code and references.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
REFERENCES = SKILL_DIR / "references"
ASSETS = SKILL_DIR / "assets"


def workspace() -> Path:
    return Path(os.environ.get("JOB_APPLY_HOME", Path.home() / ".job-apply")).expanduser()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().astimezone().date().isoformat()


def write_atomic(path: Path, text: str) -> None:
    """Write via temp file + rename so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_yaml(path: Path, default=None):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    return default if data is None else data


def write_yaml(path: Path, data) -> None:
    write_atomic(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


@contextlib.contextmanager
def locked(name: str = "workspace"):
    """Exclusive lock shared by every script and worker touching the workspace."""
    lock_path = workspace() / f".{name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def env_path() -> Path:
    return workspace() / ".env"


def load_env() -> dict:
    """Read workspace/.env (KEY=VALUE lines, # comments). The only secret this
    skill ever stores: a Gmail App Password the user creates and pastes in
    themselves, used only by send_email.py. Never read from anywhere else,
    never printed, never written into any resume, letter or log."""
    path = env_path()
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)  # tighten permissions if the user created it more openly
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def require_env(*keys):
    env = load_env()
    missing = [k for k in keys if not env.get(k)]
    if missing:
        fail(f"missing from {env_path()}: {', '.join(missing)}", missing=missing)
    return env


def emit(data) -> None:
    """Print a result as JSON for Claude to read."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def fail(message: str, code: int = 1, **extra) -> None:
    emit({"ok": False, "error": message, **extra})
    sys.exit(code)
