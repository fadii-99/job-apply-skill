#!/usr/bin/env python3
"""Deterministic profile checks.

Usage:
  profile_tools.py years [--file profile/profile.json]
      total professional experience, overlapping jobs merged
  profile_tools.py check-resume <resume.json>
      every skill must be verified or user_attested in the evidence ledger;
      every company/title/date must match profile.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

from common import emit, fail, read_json, workspace

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
ALLOWED = {"verified", "user_attested"}


def parse_month(value, is_end=False):
    """Accepts 'YYYY-MM', 'YYYY', 'Jan 2023', 'January 2023', None/'Present' (end only)."""
    if value in (None, "", "present", "Present", "current", "Current", "now"):
        if is_end:
            t = date.today()
            return t.year * 12 + t.month - 1
        return None
    v = str(value).strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", v)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2)) - 1
    m = re.fullmatch(r"([A-Za-z]{3})[a-z]*\.? (\d{4})", v)
    if m and m.group(1).lower() in MONTHS:
        return int(m.group(2)) * 12 + MONTHS[m.group(1).lower()] - 1
    m = re.fullmatch(r"(\d{4})", v)
    if m:
        return int(m.group(1)) * 12 + (11 if is_end else 0)
    return None


def years(experience):
    spans, unparsed = [], []
    for job in experience:
        s, e = parse_month(job.get("start")), parse_month(job.get("end"), is_end=True)
        if s is None or e is None or e < s:
            unparsed.append(f"{job.get('company')}: {job.get('start')} - {job.get('end')}")
            continue
        spans.append((s, e + 1))
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    months = sum(e - s for s, e in merged)
    y = months / 12
    display = f"{int(y)}+ years" if y >= 1 else f"{months} months"
    return {"ok": not unparsed, "months": months, "years": round(y, 1), "display": display,
            "unparsed": unparsed}


def _norm(s):
    return re.sub(r"[^a-z0-9+#]", "", (s or "").lower())


STATUS_RANK = {"verified": 0, "user_attested": 1, "rejected": 2, "said_not_seen": 3, "seen_not_said": 4}


def skill_index(ledger, extra_aliases=None):
    """Every name a ledger skill can appear under on a resume -> its entry.
    "Retrieval-Augmented Generation (RAG)" is found as itself, as "RAG" and as
    "Retrieval-Augmented Generation"; plus any aliases recorded with ledger.py alias.
    When two skills share a name, the one with the stronger status wins."""
    index = {}

    def put(name, entry):
        key = _norm(name)
        if not key:
            return
        old = index.get(key)
        if old is None or STATUS_RANK.get(entry.get("status"), 9) < STATUS_RANK.get(old.get("status"), 9):
            index[key] = entry

    skills = ledger.get("skills") or {}
    for name, entry in skills.items():
        put(name, entry)
        m = re.fullmatch(r"\s*(.+?)\s*\((.+)\)\s*", name)
        if m:
            put(m.group(1), entry)
            put(m.group(2), entry)
        for a in entry.get("aliases", []) or []:
            put(a, entry)
    for a, target in (extra_aliases or {}).items():
        if target in skills:
            put(a, skills[target])
    return index


def check_resume(resume, profile, ledger, aliases=None):
    problems = []
    skills = skill_index(ledger, aliases)
    for group in resume.get("skills", []):
        for item in group.get("items", []):
            entry = skills.get(_norm(item))
            if not entry:
                problems.append(f"skill not in evidence ledger: {item}")
            elif entry.get("status") not in ALLOWED:
                problems.append(f"skill not allowed ({entry.get('status')}): {item}")
    for p in resume.get("projects", []):
        for item in p.get("stack", []):
            entry = skills.get(_norm(item))
            if not entry or entry.get("status") not in ALLOWED:
                problems.append(f"project stack item not allowed: {item} ({p.get('name')})")
    jobs = {(_norm(j.get("company")), _norm(j.get("title"))): j for j in profile.get("experience", [])}
    for j in resume.get("experience", []):
        src = jobs.get((_norm(j.get("company")), _norm(j.get("title"))))
        if not src:
            problems.append(f"job not in profile: {j.get('title')} at {j.get('company')}")
            continue
        for k in ("start", "end"):
            if parse_month(j.get(k), k == "end") != parse_month(src.get(k), k == "end"):
                problems.append(f"{k} date differs from profile for {j.get('company')}: {j.get(k)} vs {src.get(k)}")
    ident = profile.get("identity", {})
    if _norm(resume.get("name")) != _norm(ident.get("full_name")):
        problems.append("name differs from profile")
    c = resume.get("contact", {})
    if c.get("email") and c.get("email") != ident.get("email"):
        problems.append("email differs from profile")
    if c.get("phone") and _norm(c.get("phone")) != _norm(ident.get("phone")):
        problems.append("phone differs from profile")
    return {"ok": not problems, "problems": problems}


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("years"); s.add_argument("--file")
    s = sub.add_parser("check-resume"); s.add_argument("resume")
    a = p.parse_args(argv)
    ws = workspace()
    if a.cmd == "years":
        src = read_json(ws / "profile" / "profile.json", None) if not a.file else json.load(open(a.file))
        if src is None:
            src = read_json(ws / "intake" / "intake.json", None)
        if src is None:
            fail("no profile.json or intake.json found")
        emit(years(src.get("experience", [])))
    else:
        resume = json.load(open(a.resume, encoding="utf-8"))
        profile = read_json(ws / "profile" / "profile.json", None)
        ledger = read_json(ws / "profile" / "evidence_ledger.json", None)
        if profile is None or ledger is None:
            fail("profile.json and evidence_ledger.json are needed")
        aliases = read_json(ws / "profile" / "skill_aliases.json", {}) or {}
        emit(check_resume(resume, profile, ledger, aliases))


if __name__ == "__main__":
    main(sys.argv[1:])
