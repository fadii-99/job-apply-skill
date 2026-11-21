#!/usr/bin/env python3
"""Lifecycle state and setup gate for the job-apply skill.

Usage:
  state.py init                       create the workspace if missing
  state.py get                        print current state + checkpoints
  state.py require READY [RUNNING]    exit 3 unless state is one of these
  state.py set <STATE>                move to a new state (transition checked)
  state.py checkpoint <key> <json>    save a resumable setup checkpoint
  state.py run-lock acquire|release|status
"""
from __future__ import annotations

import json
import os
import shutil
import sys

from common import ASSETS, emit, fail, locked, now_iso, read_json, workspace, write_json

STATES = [
    "NOT_SETUP", "INTAKE", "CLARIFY", "ANALYZING", "BUILDING",
    "USER_REVIEW", "PREFERENCES", "READY", "RUNNING", "PAUSED",
]
TRANSITIONS = {
    "NOT_SETUP": {"INTAKE"},
    "INTAKE": {"CLARIFY"},
    "CLARIFY": {"INTAKE", "ANALYZING"},
    "ANALYZING": {"ANALYZING", "BUILDING", "CLARIFY"},
    "BUILDING": {"USER_REVIEW"},
    "USER_REVIEW": {"BUILDING", "PREFERENCES"},
    "PREFERENCES": {"READY"},
    "READY": {"RUNNING", "ANALYZING", "PREFERENCES"},
    "RUNNING": {"READY", "PAUSED"},
    "PAUSED": {"RUNNING", "READY"},
}
# Any state may be reset back to the start.
RESET_OK = {"NOT_SETUP"}

DIRS = [
    "intake", "profile/projects", "resume", "applications", "queue",
    "logs/runs", "live", "session", "browser-output",
]


def state_path():
    return workspace() / "state.json"


def load():
    return read_json(state_path(), None)


def init():
    ws = workspace()
    created = not state_path().exists()
    for d in DIRS:
        (ws / d).mkdir(parents=True, exist_ok=True)
    os.chmod(ws, 0o700)
    if created:
        write_json(state_path(), {
            "state": "NOT_SETUP",
            "updated_at": now_iso(),
            "checkpoints": {},
            "history": [{"state": "NOT_SETUP", "at": now_iso()}],
        })
    cfg = ws / "config.yaml"
    if not cfg.exists():
        shutil.copy(ASSETS / "config_template.yaml", cfg)
    live = ws / "live" / "index.html"
    shutil.copy(ASSETS / "live_index.html", live)
    for name in ("events.jsonl",):
        (ws / "live" / name).touch(exist_ok=True)
    return {"ok": True, "workspace": str(ws), "created": created, "state": load()["state"]}


def set_state(new):
    if new not in STATES:
        fail(f"unknown state {new}", states=STATES)
    with locked():
        data = load()
        if data is None:
            fail("workspace not initialised; run state.py init")
        cur = data["state"]
        if new != cur and new not in TRANSITIONS.get(cur, set()) and new not in RESET_OK:
            fail(f"transition {cur} -> {new} not allowed", allowed=sorted(TRANSITIONS.get(cur, set())))
        data["state"] = new
        data["updated_at"] = now_iso()
        data.setdefault("history", []).append({"state": new, "at": now_iso()})
        data["history"] = data["history"][-50:]
        write_json(state_path(), data)
    return {"ok": True, "from": cur, "to": new}


def require(allowed):
    data = load()
    cur = data["state"] if data else "NOT_SETUP"
    if cur not in allowed:
        emit({"ok": False, "state": cur, "required": allowed,
              "message": "Setup isn't finished yet." if cur != "RUNNING" else "A run is already going."})
        sys.exit(3)
    return {"ok": True, "state": cur}


def checkpoint(key, value):
    with locked():
        data = load()
        data.setdefault("checkpoints", {})[key] = {"value": value, "at": now_iso()}
        write_json(state_path(), data)
    return {"ok": True, "key": key}


STALE_MINUTES = 15


def idle_minutes():
    """Minutes since the run last did anything (live event, log write, queue file).
    A run that has been silent this long has stopped (chat closed, turn ended, crash)."""
    ws = workspace()
    paths = [ws / "live" / "events.jsonl", ws / "logs" / "applications.csv", ws / "run.lock"]
    paths += list((ws / "queue").glob("*.json"))
    times = [p.stat().st_mtime for p in paths if p.exists()]
    if not times:
        return None
    import time
    return round((time.time() - max(times)) / 60, 1)


def run_lock(action):
    lock = workspace() / "run.lock"
    with locked():
        held = read_json(lock, None)
        idle = idle_minutes() if held else None
        stale = bool(held) and idle is not None and idle >= STALE_MINUTES
        if action == "status":
            return {"ok": True, "held": bool(held), "lock": held, "idle_minutes": idle, "stale": stale}
        if action == "acquire":
            if held and not stale:
                return {"ok": False, "held": True, "lock": held, "idle_minutes": idle,
                        "message": "A run is already going."}
            write_json(lock, {"started_at": now_iso(), "replaced_stale": stale})
            return {"ok": True, "held": True, "replaced_stale_lock": stale}
        if action == "release":
            if lock.exists():
                lock.unlink()
            return {"ok": True, "held": False}
    fail(f"unknown run-lock action {action}")


def main(argv):
    if not argv:
        fail(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "init":
        emit(init())
    elif cmd == "get":
        data = load()
        emit(data if data else {"state": "NOT_SETUP", "initialised": False})
    elif cmd == "require":
        emit(require(args or ["READY"]))
    elif cmd == "set" and args:
        emit(set_state(args[0]))
    elif cmd == "checkpoint" and len(args) == 2:
        try:
            value = json.loads(args[1])
        except json.JSONDecodeError:
            value = args[1]
        emit(checkpoint(args[0], value))
    elif cmd == "run-lock" and args:
        emit(run_lock(args[0]))
    else:
        fail(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
