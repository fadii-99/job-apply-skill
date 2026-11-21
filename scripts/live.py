#!/usr/bin/env python3
"""Live view data. Workers and the coordinator record stage changes here;
the page at <workspace>/live/index.html re-reads live.js every 2 seconds.

Usage:
  live.py event --worker W --stage S [--job A12] [--platform P] [--company C] [--title T] [--note N]
      stages: searching, tailoring, filling, checking, submitting, applied, manual,
              discarded, login_needed, idle, run_started, run_finished
  live.py rebuild
  live.py path                 print the live page path (for opening in a browser)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque

from common import emit, locked, now_iso, read_json, workspace, write_atomic

import tracker

FINAL = {"applied", "manual", "discarded", "idle", "run_finished"}


def events_path():
    return workspace() / "live" / "events.jsonl"


def read_events(limit=400):
    try:
        with open(events_path(), encoding="utf-8") as f:
            return [json.loads(line) for line in deque(f, maxlen=limit) if line.strip()]
    except FileNotFoundError:
        return []


def rebuild():
    events = read_events()
    workers = {}
    for e in events:
        if e.get("stage") == "run_started":
            workers = {}
        if e.get("worker") and e["worker"] != "coordinator":
            workers[e["worker"]] = e
    stats = tracker.cmd_stats(None)
    rows = tracker.load_rows()
    manual = [{k: r[k] for k in ("id", "platform", "company", "title", "canonical_url", "reason")}
              for r in rows if r["status"] == "manual"][-30:]
    lock = read_json(workspace() / "run.lock", None)
    data = {
        "updated_at": now_iso(),
        "running": bool(lock),
        "run_started_at": (lock or {}).get("started_at"),
        "workers": sorted(workers.values(), key=lambda e: e["worker"]),
        "stats": stats,
        "recent": list(reversed(events[-50:])),
        "manual": list(reversed(manual)),
    }
    write_atomic(workspace() / "live" / "live.js",
                 "window.__LIVE = " + json.dumps(data, ensure_ascii=False) + ";\n")
    return data


def event(a):
    rec = {"at": now_iso(), "worker": a.worker, "stage": a.stage, "job": a.job or "",
           "platform": a.platform or "", "company": a.company or "", "title": a.title or "",
           "note": a.note or ""}
    with locked("live"):
        events_path().parent.mkdir(parents=True, exist_ok=True)
        with open(events_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        rebuild()
    return {"ok": True}


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("event")
    for f in ("worker", "stage"):
        s.add_argument(f"--{f}", required=True)
    for f in ("job", "platform", "company", "title", "note"):
        s.add_argument(f"--{f}")
    sub.add_parser("rebuild"); sub.add_parser("path")
    a = p.parse_args(argv)
    if a.cmd == "event":
        emit(event(a))
    elif a.cmd == "rebuild":
        with locked("live"):
            rebuild()
        emit({"ok": True})
    else:
        emit({"ok": True, "path": str(workspace() / "live" / "index.html")})


if __name__ == "__main__":
    main(sys.argv[1:])
