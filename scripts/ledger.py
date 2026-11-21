#!/usr/bin/env python3
"""Evidence ledger: merge per-project findings, record the user's answers, map aliases.

Usage (all print JSON):
  ledger.py merge
      Merge profile/ledger/*.json into profile/evidence_ledger.json. Re-applies every
      answer saved with `decide` and every alias saved with `alias`, so it is safe to
      run again after re-reading a project. Lists the items that still need a question.
  ledger.py decide <skill> yes|no
      Record the user's answer to a reconciliation question:
        said_not_seen + yes -> user_attested     seen_not_said + yes -> verified
        any no              -> rejected (never used, never asked again)
  ledger.py alias <name> <skill>
      Treat <name> as the same skill as <skill> (e.g. "S3" -> "AWS S3") when checking resumes.

Files (workspace/profile/): ledger/*.json (from project sub-agents), evidence_ledger.json,
ledger_decisions.json, skill_aliases.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import emit, fail, locked, now_iso, read_json, workspace, write_json

RANK_LEVEL = {"used": 1, "built": 2, "designed": 3}
STATUS_ORDER = ["verified", "user_attested", "rejected", "said_not_seen", "seen_not_said"]
MAX_EVIDENCE = 6


def profile_dir() -> Path:
    return workspace() / "profile"


def decisions_path() -> Path:
    return profile_dir() / "ledger_decisions.json"


def aliases_path() -> Path:
    return profile_dir() / "skill_aliases.json"


def merge():
    frags = sorted((profile_dir() / "ledger").glob("*.json"))
    if not frags:
        fail("no project ledgers in profile/ledger/ yet")
    decisions = read_json(decisions_path(), {}) or {}
    aliases = read_json(aliases_path(), {}) or {}
    skills, highlights, bad = {}, [], []
    for f in frags:
        d = read_json(f, None)
        if not d or "items" not in d:
            bad.append(f.name)
            continue
        slug = d.get("project", f.stem)
        for it in d["items"]:
            name = (it.get("skill") or "").strip()
            if not name:
                continue
            s = skills.setdefault(name, {"status": None, "level": "used", "category": it.get("category"),
                                         "projects": [], "evidence": [], "per_project": {}})
            s["per_project"][slug] = it.get("status", "seen_not_said")
            if s["per_project"][slug] in ("verified", "user_attested"):
                if slug not in s["projects"]:
                    s["projects"].append(slug)
                if RANK_LEVEL.get(it.get("level"), 1) > RANK_LEVEL.get(s["level"], 1):
                    s["level"] = it["level"]
            for ev in it.get("evidence", [])[:3]:
                if len(s["evidence"]) < MAX_EVIDENCE:
                    s["evidence"].append(f"{slug}:{ev}")
        for h in d.get("highlights", []):
            highlights.append({"project": slug, **h})

    for name, s in skills.items():
        found = set(s["per_project"].values())
        s["status"] = next((st for st in STATUS_ORDER if st in found), "seen_not_said")
        dec = decisions.get(name)
        if dec and s["status"] != "verified":
            s["status"] = dec["status"]
        elif dec and dec["status"] == "rejected" and s["status"] == "verified":
            s["status"] = "rejected"  # the user's explicit "no" always wins
    for alias, target in aliases.items():
        if target in skills:
            skills[target].setdefault("aliases", [])
            if alias not in skills[target]["aliases"]:
                skills[target]["aliases"].append(alias)

    write_json(profile_dir() / "evidence_ledger.json",
               {"skills": skills, "highlights": highlights, "updated_at": now_iso()})
    counts = {}
    for s in skills.values():
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    ask = [{"skill": n, "status": s["status"], "projects": s["per_project"]}
           for n, s in sorted(skills.items()) if s["status"] in ("said_not_seen", "seen_not_said")]
    return {"ok": not bad, "skills": len(skills), "counts": counts, "highlights": len(highlights),
            "needs_question": ask, "unreadable_fragments": bad}


def decide(skill, answer):
    if answer not in ("yes", "no"):
        fail("answer must be yes or no")
    ledger = read_json(profile_dir() / "evidence_ledger.json", {}) or {}
    cur = ((ledger.get("skills") or {}).get(skill) or {}).get("status")
    if cur is None:
        fail(f"skill not in the ledger: {skill}")
    if answer == "no":
        new = "rejected"
    elif cur == "said_not_seen":
        new = "user_attested"
    elif cur == "seen_not_said":
        new = "verified"
    else:
        new = cur
    with locked():
        decisions = read_json(decisions_path(), {}) or {}
        decisions[skill] = {"status": new, "answer": answer, "was": cur, "at": now_iso()}
        write_json(decisions_path(), decisions)
        ledger["skills"][skill]["status"] = new
        write_json(profile_dir() / "evidence_ledger.json", ledger)
    return {"ok": True, "skill": skill, "from": cur, "to": new}


def alias(name, skill):
    ledger = read_json(profile_dir() / "evidence_ledger.json", {}) or {}
    if skill not in (ledger.get("skills") or {}):
        fail(f"target skill not in the ledger: {skill}")
    with locked():
        aliases = read_json(aliases_path(), {}) or {}
        aliases[name] = skill
        write_json(aliases_path(), aliases)
        entry = ledger["skills"][skill]
        entry.setdefault("aliases", [])
        if name not in entry["aliases"]:
            entry["aliases"].append(name)
        write_json(profile_dir() / "evidence_ledger.json", ledger)
    return {"ok": True, "alias": name, "skill": skill}


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("merge")
    s = sub.add_parser("decide"); s.add_argument("skill"); s.add_argument("answer")
    s = sub.add_parser("alias"); s.add_argument("name"); s.add_argument("skill")
    a = p.parse_args(argv)
    if a.cmd == "merge":
        with locked():
            emit(merge())
    elif a.cmd == "decide":
        emit(decide(a.skill, a.answer))
    else:
        emit(alias(a.name, a.skill))


if __name__ == "__main__":
    main(sys.argv[1:])
