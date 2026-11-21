#!/usr/bin/env python3
"""Application log, duplicate check and job queue (logs/applications.csv).

Every write happens under the workspace lock, through a temp file + rename.

Usage (all print JSON):
  tracker.py check  --platform P --url U --company C --title T [--location L] [--job-id ID]
  tracker.py add    --platform P --url U --company C --title T [--location L] [--job-id ID]
                    --status queued|skipped [--fit-score N] [--reason R] [--posted-at D]
  tracker.py claim  --worker W            next queued job this worker may take, or none
  tracker.py update --id A12 --status S [--reason R] [--folder F]
  tracker.py requeue (--ids A1,A2 | --platform P [--from-status claimed,manual] [--reason-contains TEXT])
  tracker.py recover                      after a crash: claimed -> queued, list submitting
  tracker.py stats                        today's counters and caps left
  tracker.py list   [--status S] [--limit N]
  tracker.py report [--days 7]                applied, skipped by reason, manual list
  tracker.py export                          rewrite logs/My_Job_Applications.csv (the readable report)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from common import REFERENCES, emit, fail, locked, now_iso, read_yaml, today, workspace, write_atomic

FIELDS = [
    "id", "first_seen_at", "applied_at", "updated_at", "platform", "posting_key",
    "canonical_url", "fingerprint", "company", "title", "location", "job_posted_at",
    "fit_score", "status", "reason", "worker", "folder",
]
STATUSES = {
    "queued", "skipped", "claimed", "submitting", "applied", "manual", "discarded",
    "interview", "rejected", "offer",
}
# Statuses that mean "this opening has been handled; never touch it again".
DONE = {"claimed", "submitting", "applied", "manual", "discarded", "interview", "rejected", "offer", "queued"}
APPLIED_LIKE = {"applied", "interview", "rejected", "offer", "submitting"}
ACTIVE = {"claimed", "submitting"}

TRACKING_PARAMS = re.compile(
    r"^(utm_.*|ref|refid|ref_id|trackingid|trk|trkinfo|src|source|from|gh_src|lever-source|"
    r"lever-origin|fbclid|gclid|mc_.*|_hs.*|hsa_.*|origin|alid|eid|position|pagenum|"
    r"currentjobid|referer|referrer|campaign)$",
    re.I,
)
COMPANY_SUFFIX = re.compile(
    r"\b(inc|incorporated|ltd|limited|llc|l\.l\.c|gmbh|pvt|private|corp|corporation|co|company|"
    r"plc|sa|ag|bv|fz[ec]?|fz-?llc|llp)\b\.?", re.I)
KEY_PATTERNS = [
    ("linkedin", re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d{6,})")),
    ("linkedin", re.compile(r"[?&]currentJobId=(\d{6,})")),
    ("indeed", re.compile(r"[?&](?:jk|vjk)=([0-9a-f]{12,})", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/(?:[^/]+/)?(?:[^/]+/)?jobs/(\d+)")),
    ("greenhouse", re.compile(r"[?&]gh_jid=(\d+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([^/?#]+/[0-9a-f-]{36})", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([^/?#]+/[0-9a-f-]{36})", re.I)),
]


# ---------- identity ----------

def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not TRACKING_PARAMS.match(k)]
    path = re.sub(r"/+$", "", parts.path) or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower().removeprefix("www."),
                       path, urlencode(sorted(query)), ""))


def posting_key(platform: str, url: str, job_id: str | None) -> str:
    if job_id:
        return f"{platform}:{job_id}"
    for name, pattern in KEY_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"{name}:{m.group(1).lower()}"
    return f"{platform}:url:{hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]}"


def _norm(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def norm_company(name: str) -> str:
    return _norm(COMPANY_SUFFIX.sub(" ", name or ""))


def norm_location(loc: str) -> str:
    loc = _norm(loc)
    return "remote" if "remote" in loc or "anywhere" in loc else loc


def fingerprint(company: str, title: str, location: str) -> str:
    raw = f"{norm_company(company)}|{_norm(title)}|{norm_location(location)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# ---------- storage ----------

def csv_path():
    return workspace() / "logs" / "applications.csv"


def load_rows():
    try:
        with open(csv_path(), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def _to_csv(rows, fields):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fields})
    return buf.getvalue()


def save_rows(rows):
    write_atomic(csv_path(), _to_csv(rows, FIELDS))
    # Convenience lists the user reads by hand.
    side = ["id", "updated_at", "platform", "company", "title", "canonical_url", "reason", "folder"]
    logs = workspace() / "logs"
    write_atomic(logs / "manual.csv", _to_csv([r for r in rows if r["status"] == "manual"], side))
    write_atomic(logs / "discarded.csv", _to_csv([r for r in rows if r["status"] == "discarded"], side))
    try:
        write_report(rows)
    except Exception as exc:  # the readable report must never break a run
        print(f"warning: could not write {REPORT_NAME}: {exc}", file=sys.stderr)


# ---------- readable report (logs/My_Job_Applications.csv) ----------

REPORT_NAME = "My_Job_Applications.csv"
STATUS_TEXT = {
    "claimed": ("Applying now", "A worker is filling this application right now."),
    "submitting": ("Submitting", "Being submitted; if it stays here, check the site or your Sent folder."),
    "applied": ("Applied", "Done. Wait for a reply."),
    "interview": ("Interview", "You got an interview."),
    "offer": ("Offer", "You got an offer."),
    "rejected": ("Rejected", "The company said no."),
    "manual": ("Needs you", "Finish this one by hand. The reason says why; the tailored resume is in the job folder."),
    "queued": ("Waiting to apply", "Will be applied to in a coming run (daily limit)."),
    "discarded": ("Could not apply", "Closed, expired or no way to apply."),
    "skipped": ("Skipped", "Not applied on purpose; the reason says why."),
}
STATUS_SORT = ["claimed", "submitting", "manual", "applied", "interview", "offer", "rejected",
               "queued", "discarded", "skipped"]
REPORT_FIELDS = ["Code", "Status", "What it means", "Company", "Job title", "Location", "Work mode",
                 "Platform", "Fit score", "Found on", "Posted", "Applied on", "Applied via", "Reason / notes",
                 "Job link", "Apply link or email", "Resume sent", "Cover letter", "Confirmation", "Job folder"]


def _when(ts):
    d = _parse(ts)
    return d.astimezone().strftime("%Y-%m-%d %H:%M") if d else ""


def _queue_details():
    """Extra details the search phase saved (work mode, apply link, email), by canonical URL."""
    index = {}
    for f in sorted((workspace() / "queue").glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for job in data if isinstance(data, list) else []:
            if not isinstance(job, dict):
                continue
            if job.get("url"):
                index[canonical_url(job["url"])] = job
            if job.get("email"):
                index[canonical_url("mailto:" + job["email"])] = job
    return index


def _folder_files(folder):
    out = {"resume": "", "cover": "", "confirmation": "", "email_sent": False, "dry_run": False}
    if not folder:
        return out
    p = Path(folder)
    if not p.is_dir():
        return out
    names = sorted(x.name for x in p.iterdir())
    out["resume"] = next((n for n in names if n.endswith("_Resume.pdf")), "")
    out["cover"] = next((n for n in names if n.endswith("_Cover_Letter.pdf")), "") or \
        ("cover_letter.md" if "cover_letter.md" in names else "")
    out["confirmation"] = "confirmation.png" if "confirmation.png" in names else ""
    out["email_sent"] = "email_sent.json" in names
    out["dry_run"] = "dry_run.png" in names or "email_dry_run.eml" in names
    return out


def write_report(rows):
    details = _queue_details()
    order = {s: i for i, s in enumerate(STATUS_SORT)}
    rows = sorted(rows, key=lambda r: (order.get(r["status"], 99), -float(r["fit_score"] or 0)))
    out = []
    for r in rows:
        q = details.get(r["canonical_url"], {})
        files = _folder_files(r.get("folder"))
        label, meaning = STATUS_TEXT.get(r["status"], (r["status"], ""))
        by_email = r["canonical_url"].startswith("mailto:") or files["email_sent"] or bool(q.get("email"))
        via = ""
        if r["status"] in ("applied", "interview", "offer", "rejected", "submitting"):
            via = "Email" if by_email else "Website form"
        notes = r["reason"]
        if files["dry_run"] and r["status"] == "manual":
            notes = (notes + "; " if notes else "") + "dry run, nothing was sent"
        out.append({
            "Code": r["id"], "Status": label, "What it means": meaning,
            "Company": r["company"], "Job title": r["title"], "Location": r["location"],
            "Work mode": (q.get("work_mode") or "").capitalize(),
            "Platform": r["platform"],
            "Fit score": f"{float(r['fit_score']):.0f}" if r["fit_score"] else "",
            "Found on": _when(r["first_seen_at"]), "Posted": r["job_posted_at"],
            "Applied on": _when(r["applied_at"]) if via else "", "Applied via": via,
            "Reason / notes": notes,
            "Job link": "" if r["canonical_url"].startswith("mailto:") else r["canonical_url"],
            "Apply link or email": q.get("email") or q.get("apply_url") or
                                   (r["canonical_url"][7:] if r["canonical_url"].startswith("mailto:") else ""),
            "Resume sent": files["resume"] if via else "",
            "Cover letter": files["cover"] if via else "",
            "Confirmation": files["confirmation"],
            "Job folder": r.get("folder") or "",
        })
    # utf-8 with BOM so Excel and LibreOffice open it with the right characters
    write_atomic(workspace() / "logs" / REPORT_NAME, "\ufeff" + _to_csv(out, REPORT_FIELDS))


def next_id(rows):
    nums = [int(r["id"][1:]) for r in rows if re.fullmatch(r"A\d+", r.get("id", ""))]
    return f"A{max(nums, default=0) + 1}"


# ---------- config ----------

def config():
    return read_yaml(workspace() / "config.yaml", {}) or {}


def registry():
    data = read_yaml(REFERENCES / "platforms.yaml", {}) or {}
    return {p["id"]: p for p in data.get("platforms", [])}


def platform_limits(cfg, reg, platform):
    settings = (cfg.get("platforms", {}).get("settings", {}) or {}).get(platform, {}) or {}
    entry = reg.get(platform, {})
    return {
        "daily_cap": settings.get("daily_cap", entry.get("default_daily_cap")),
        "max_workers": settings.get("max_workers", entry.get("max_workers")),
    }


def _parse(ts):
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _is_today(ts):
    d = _parse(ts)
    return bool(d) and d.astimezone().date().isoformat() == today()


# ---------- duplicate check ----------

def verdict(rows, cfg, platform, url, company, title, location, job_id):
    key = posting_key(platform, url, job_id)
    curl = canonical_url(url)
    fp = fingerprint(company, title, location)
    limits = cfg.get("limits", {}) or {}
    search = cfg.get("search", {}) or {}
    now = datetime.now().astimezone()
    ident = {"posting_key": key, "canonical_url": curl, "fingerprint": fp}

    blocked = {norm_company(c) for c in search.get("blocklist_companies", []) or []}
    if norm_company(company) in blocked:
        return {"verdict": "skip", "reason": "blocklisted company", **ident}
    text = f"{title} {company}".lower()
    for kw in search.get("exclude_keywords", []) or []:
        if kw.lower() in text:
            return {"verdict": "skip", "reason": f"excluded keyword: {kw}", **ident}

    reapply = timedelta(days=int(limits.get("reapply_after_days", 30)))
    recheck = timedelta(days=int(limits.get("low_fit_recheck_days", 14)))
    month = timedelta(days=30)
    company_n = norm_company(company)
    company_recent = 0
    for r in rows:
        seen = _parse(r.get("applied_at") or r.get("updated_at") or r.get("first_seen_at")) or now
        same_post = r["posting_key"] == key or r["canonical_url"] == curl
        if same_post and r["status"] in DONE:
            return {"verdict": "skip", "reason": f"same opening already {r['status']} ({r['id']})", "match": r["id"], **ident}
        if same_post and r["status"] == "skipped" and now - seen < recheck:
            return {"verdict": "skip", "reason": f"evaluated recently: {r['reason']} ({r['id']})", "match": r["id"], **ident}
        if r["fingerprint"] == fp and r["status"] in APPLIED_LIKE | {"queued", "claimed"} and now - seen < reapply:
            return {"verdict": "skip", "reason": f"same role at same company within {reapply.days} days ({r['id']})", "match": r["id"], **ident}
        if norm_company(r["company"]) == company_n and r["status"] in APPLIED_LIKE and now - seen < month:
            company_recent += 1
    cap = int(limits.get("per_company_per_30_days", 2))
    if company_recent >= cap:
        return {"verdict": "skip", "reason": f"company limit: {company_recent} in the last 30 days", **ident}
    return {"verdict": "new", **ident}


# ---------- commands ----------

def cmd_check(a):
    return verdict(load_rows(), config(), a.platform, a.url, a.company, a.title, a.location or "", a.job_id)


def cmd_add(a):
    if a.status not in {"queued", "skipped"}:
        fail("add only takes --status queued or skipped")
    with locked():
        rows = load_rows()
        v = verdict(rows, config(), a.platform, a.url, a.company, a.title, a.location or "", a.job_id)
        if v["verdict"] == "skip":
            return {"ok": True, "added": False, **v}
        row = {
            "id": next_id(rows), "first_seen_at": now_iso(), "applied_at": "", "updated_at": now_iso(),
            "platform": a.platform, "posting_key": v["posting_key"], "canonical_url": v["canonical_url"],
            "fingerprint": v["fingerprint"], "company": a.company, "title": a.title,
            "location": a.location or "", "job_posted_at": a.posted_at or "",
            "fit_score": "" if a.fit_score is None else str(a.fit_score), "status": a.status,
            "reason": a.reason or "", "worker": "", "folder": "",
        }
        rows.append(row)
        save_rows(rows)
    return {"ok": True, "added": True, "id": row["id"], **v}


def _caps(rows, cfg, reg):
    limits = cfg.get("limits", {}) or {}
    total_cap = int(limits.get("daily_cap", 15))
    used_today = [r for r in rows if (r["status"] in APPLIED_LIKE and _is_today(r["applied_at"])) or r["status"] in ACTIVE]
    per_platform = {}
    for r in used_today:
        per_platform[r["platform"]] = per_platform.get(r["platform"], 0) + 1
    return total_cap, used_today, per_platform


def cmd_claim(a):
    with locked():
        rows = load_rows()
        cfg, reg = config(), registry()
        total_cap, used_today, per_platform = _caps(rows, cfg, reg)
        if len(used_today) >= total_cap:
            return {"ok": True, "job": None, "why": "daily cap reached"}
        active = [r for r in rows if r["status"] in ACTIVE]
        max_total = int((cfg.get("workers", {}) or {}).get("max_total", 1))
        if len(active) >= max_total:
            return {"ok": True, "job": None, "why": "all worker slots busy"}
        busy_companies = {norm_company(r["company"]) for r in active}
        active_by_platform = {}
        for r in active:
            active_by_platform[r["platform"]] = active_by_platform.get(r["platform"], 0) + 1
        queued = sorted((r for r in rows if r["status"] == "queued"),
                        key=lambda r: -float(r["fit_score"] or 0))
        reasons = set()
        for r in queued:
            lim = platform_limits(cfg, reg, r["platform"])
            if norm_company(r["company"]) in busy_companies:
                reasons.add("company already being applied to"); continue
            if lim["daily_cap"] is not None and per_platform.get(r["platform"], 0) >= int(lim["daily_cap"]):
                reasons.add(f"{r['platform']} daily cap reached"); continue
            if lim["max_workers"] is not None and active_by_platform.get(r["platform"], 0) >= int(lim["max_workers"]):
                reasons.add(f"{r['platform']} worker limit"); continue
            r["status"], r["worker"], r["updated_at"] = "claimed", a.worker, now_iso()
            save_rows(rows)
            return {"ok": True, "job": r}
        return {"ok": True, "job": None, "why": "; ".join(sorted(reasons)) or "queue empty"}


def cmd_update(a):
    if a.status not in STATUSES:
        fail(f"unknown status {a.status}", statuses=sorted(STATUSES))
    with locked():
        rows = load_rows()
        for r in rows:
            if r["id"] == a.id:
                r["status"], r["updated_at"] = a.status, now_iso()
                if a.reason is not None:
                    r["reason"] = a.reason
                if a.folder is not None:
                    r["folder"] = a.folder
                if a.status in {"submitting", "applied"} and not r["applied_at"]:
                    r["applied_at"] = now_iso()
                if a.status not in ACTIVE:
                    r["worker"] = ""
                save_rows(rows)
                return {"ok": True, "row": r}
    fail(f"no application with id {a.id}")


def cmd_requeue(a):
    with locked():
        rows = load_rows()
        ids = set(filter(None, (a.ids or "").split(",")))
        statuses = set((a.from_status or "claimed,manual").split(","))
        moved = []
        for r in rows:
            hit = r["id"] in ids if ids else (
                (not a.platform or r["platform"] == a.platform) and r["status"] in statuses
                and (not a.reason_contains or a.reason_contains.lower() in r["reason"].lower()))
            if hit and r["status"] not in APPLIED_LIKE:
                r["status"], r["worker"], r["updated_at"] = "queued", "", now_iso()
                moved.append(r["id"])
        save_rows(rows)
    return {"ok": True, "requeued": moved}


def cmd_recover(_a):
    with locked():
        rows = load_rows()
        back, verify_on_site, verify_email = [], [], []
        for r in rows:
            if r["status"] == "claimed":
                r["status"], r["worker"], r["updated_at"] = "queued", "", now_iso()
                back.append(r["id"])
            elif r["status"] == "submitting":
                item = {k: r[k] for k in ("id", "platform", "company", "title", "canonical_url", "folder", "updated_at")}
                (verify_email if r["canonical_url"].startswith("mailto:") else verify_on_site).append(item)
        save_rows(rows)
    return {"ok": True, "requeued": back, "verify_on_site": verify_on_site, "verify_email": verify_email,
            "note": ("For verify_on_site: open each job and look for an 'applied' state, then update to applied "
                     "or queued. For verify_email: check the Sent folder for a message to that address around "
                     "updated_at before marking applied or queued; never resend.")}


def cmd_stats(_a):
    rows = load_rows()
    cfg, reg = config(), registry()
    total_cap, used_today, per_platform = _caps(rows, cfg, reg)
    today_rows = [r for r in rows if _is_today(r["updated_at"])]
    by_status = {}
    for r in today_rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    platforms = {}
    for p in sorted({r["platform"] for r in rows} | set((cfg.get("platforms", {}) or {}).get("enabled", []) or [])):
        lim = platform_limits(cfg, reg, p)
        platforms[p] = {"used_today": per_platform.get(p, 0), "daily_cap": lim["daily_cap"]}
    return {
        "ok": True, "date": today(), "daily_cap": total_cap, "used_today": len(used_today),
        "left_today": max(0, total_cap - len(used_today)), "today_by_status": by_status,
        "queued": sum(r["status"] == "queued" for r in rows),
        "manual_total": sum(r["status"] == "manual" for r in rows),
        "applied_total": sum(r["status"] in APPLIED_LIKE - {"submitting"} for r in rows),
        "platforms": platforms,
    }


def cmd_report(a):
    rows = load_rows()
    since = datetime.now().astimezone() - timedelta(days=a.days)
    recent = [r for r in rows if (_parse(r["updated_at"]) or since) >= since]
    by_status, by_platform, skip_reasons = {}, {}, {}
    for r in recent:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r["status"] in APPLIED_LIKE:
            by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1
        if r["status"] == "skipped":
            key = re.sub(r"\s*\(.*\)$", "", r["reason"]).split(":")[0] or "other"
            skip_reasons[key] = skip_reasons.get(key, 0) + 1
    pick = lambda st: [{k: r[k] for k in ("id", "platform", "company", "title", "canonical_url", "reason", "applied_at")}
                       for r in recent if r["status"] in st]
    return {"ok": True, "days": a.days, "by_status": by_status, "applied_by_platform": by_platform,
            "skip_reasons": skip_reasons, "applied": pick(APPLIED_LIKE - {"submitting"}),
            "manual": pick({"manual"}), "discarded_count": by_status.get("discarded", 0)}


def cmd_export(_a):
    with locked():
        rows = load_rows()
        write_report(rows)
    return {"ok": True, "report": str(workspace() / "logs" / REPORT_NAME), "rows": len(rows)}


def cmd_list(a):
    rows = load_rows()
    if a.status:
        rows = [r for r in rows if r["status"] in set(a.status.split(","))]
    return {"ok": True, "count": len(rows), "rows": rows[-a.limit:]}


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "add"):
        s = sub.add_parser(name)
        s.add_argument("--platform", required=True)
        s.add_argument("--url", required=True)
        s.add_argument("--company", required=True)
        s.add_argument("--title", required=True)
        s.add_argument("--location", default="")
        s.add_argument("--job-id")
        if name == "add":
            s.add_argument("--status", required=True)
            s.add_argument("--fit-score", type=float)
            s.add_argument("--reason")
            s.add_argument("--posted-at")
    s = sub.add_parser("claim"); s.add_argument("--worker", required=True)
    s = sub.add_parser("update")
    s.add_argument("--id", required=True); s.add_argument("--status", required=True)
    s.add_argument("--reason"); s.add_argument("--folder")
    s = sub.add_parser("requeue")
    s.add_argument("--ids"); s.add_argument("--platform"); s.add_argument("--from-status")
    s.add_argument("--reason-contains")
    sub.add_parser("recover"); sub.add_parser("stats")
    s = sub.add_parser("list"); s.add_argument("--status"); s.add_argument("--limit", type=int, default=50)
    s = sub.add_parser("report"); s.add_argument("--days", type=int, default=7)
    sub.add_parser("export")
    a = p.parse_args(argv)
    emit({"check": cmd_check, "add": cmd_add, "claim": cmd_claim, "update": cmd_update,
          "requeue": cmd_requeue, "recover": cmd_recover, "stats": cmd_stats, "list": cmd_list,
          "report": cmd_report, "export": cmd_export}[a.cmd](a))


if __name__ == "__main__":
    main(sys.argv[1:])
