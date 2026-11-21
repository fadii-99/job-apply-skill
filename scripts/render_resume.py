#!/usr/bin/env python3
"""Render resume JSON (schema in references/writing-rules.md) to a PDF with headless Chrome.

The layout is fixed (assets/resume_template.html): centred header, blue section titles,
dates on the right, one column, real text only. Content decides everything else.

Usage:
  render_resume.py <resume.json> <out.pdf> [--html-only]
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import ASSETS, emit, fail, read_yaml, workspace

BROWSERS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
LINK_ICON = ('<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M7 1.5h3.5V5M10.5 1.5 5.5 6.5M9 7.5v3H1.5V3h3" '
             'fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/></svg>')
DEFAULT_ORDER = ["summary", "experience", "projects", "skills", "education", "certifications"]
TITLES = {"summary": "Professional Summary", "experience": "Experience", "projects": "Projects",
          "skills": "Technical Skills", "education": "Education", "certifications": "Certifications"}


def e(s):
    return html.escape(str(s or ""), quote=True)


def find_browser():
    for b in BROWSERS:
        path = shutil.which(b) or (b if Path(b).exists() else None)
        if path:
            return path
    return None


def display_url(url):
    return re.sub(r"^https?://(www\.)?", "", str(url or "")).rstrip("/")


def href(url):
    url = str(url or "")
    return url if re.match(r"^(https?:|mailto:|tel:)", url) else f"https://{url}"


def link_obj(link):
    """A link may be a string URL or {"url": ..., "display": ...}."""
    if not link:
        return None
    if isinstance(link, str):
        return {"url": href(link), "display": display_url(link)}
    return {"url": href(link.get("url")), "display": link.get("display") or link.get("label") or display_url(link.get("url"))}


def date_range(item, default_end="Present"):
    if item.get("date"):
        return e(item["date"])
    s = item.get("start")
    if not s:
        return ""
    end = item.get("end", default_end) or default_end
    return f"{e(s)} – {e(end)}"


def bullet_list(items):
    items = [i for i in items or [] if i]
    return "<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>" if items else ""


def row(lead_html, right):
    right_html = f'<span class="dates">{right}</span>' if right else ""
    return f'<div class="row"><span class="lead">{lead_html}</span>{right_html}</div>'


def header(r, include_photo):
    c = r.get("contact", {})
    items = []
    if c.get("location"):
        items.append(f'<span class="m">{e(c["location"])}</span>')
    if c.get("phone"):
        items.append(f'<span class="m"><a href="tel:{e(re.sub(r"[^0-9+]", "", c["phone"]))}">{e(c["phone"])}</a></span>')
    if c.get("email"):
        items.append(f'<span><a href="mailto:{e(c["email"])}">{e(c["email"])}</a></span>')
    for link in c.get("links", []):
        lo = link_obj(link)
        if lo:
            items.append(f'<span><a href="{e(lo["url"])}">{e(lo["display"])}</a></span>')
    photo = ""
    if include_photo and r.get("photo") and Path(r["photo"]).exists():
        mime = mimetypes.guess_type(r["photo"])[0] or "image/jpeg"
        data = base64.b64encode(Path(r["photo"]).read_bytes()).decode()
        photo = (f'<img src="data:{mime};base64,{data}" alt="" '
                 'style="width:62pt;height:62pt;object-fit:cover;border-radius:50%;margin-bottom:4pt">')
    return (f'<header>{photo}<h1>{e(r.get("name"))}</h1>'
            f'<div class="headline">{e(r.get("headline"))}</div>'
            f'<div class="contact">{" ".join(items)}</div></header>')


def sec_summary(r):
    return f'<p class="summary">{e(r["summary"])}</p>' if r.get("summary") else ""


def sec_experience(r):
    out = []
    for j in r.get("experience", []):
        rest = ", ".join(x for x in (j.get("company"), j.get("location")) if x)
        lead = f'<b>{e(j.get("title"))}</b>' + (f'<span class="m">, {e(rest)}</span>' if rest else "")
        out.append(f'<div class="item">{row(lead, date_range(j))}{bullet_list(j.get("bullets"))}</div>')
    return "".join(out)


def sec_projects(r):
    out = []
    for p in r.get("projects", []):
        name = e(p.get("name"))
        # "Name: subtitle" by default; "subtitle_join": " " gives "Name subtitle" (e.g. "... Backend for Event Photo Delivery").
        colon = ":" if p.get("subtitle_join", ":") == ":" else ""
        lead = f"<b>{name}{colon}</b> <span class=\"m\">{e(p['subtitle'])}</span>" if p.get("subtitle") else f"<b>{name}</b>"
        desc = f'<div class="desc">{e(p["description"])}</div>' if p.get("description") else ""
        stack = ", ".join(p.get("stack", []))
        lo = link_obj(p.get("link"))
        stack_html = ""
        if stack or lo:
            left = f'<span><b>Stack:</b> <span class="items">{e(stack)}</span></span>' if stack else "<span></span>"
            right = f'<a class="link" href="{e(lo["url"])}">{e(lo["display"])}{LINK_ICON}</a>' if lo else ""
            stack_html = f'<div class="stack-row">{left}{right}</div>'
        out.append(f'<div class="item">{row(lead, date_range(p, default_end="Present"))}{desc}'
                   f'{bullet_list(p.get("bullets"))}{stack_html}</div>')
    return "".join(out)


def sec_skills(r):
    pairs = "".join(f"<dt>{e(g.get('group'))}</dt><dd>{e(', '.join(g.get('items', [])))}</dd>"
                    for g in r.get("skills", []))
    return f'<dl class="skills">{pairs}</dl>' if pairs else ""


def sec_education(r):
    out = []
    for d in r.get("education", []):
        detail = d.get("detail") or d.get("field")
        lead = f'<b>{e(d.get("degree"))}</b>' + (f'<span class="m">, {e(detail)}</span>' if detail else "")
        inst = ", ".join(x for x in (d.get("institution"), d.get("location")) if x)
        out.append(f'<div class="item edu">{row(lead, date_range(d))}'
                   f'{f"<div class=inst>{e(inst)}</div>" if inst else ""}{bullet_list(d.get("bullets"))}</div>')
    return "".join(out)


def sec_certifications(r):
    out = []
    for c in r.get("certifications", []):
        lead = f'<b>{e(c.get("name"))}</b>' + (f'<span class="m">, {e(c.get("issuer"))}</span>' if c.get("issuer") else "")
        out.append(f'<div class="cert">{row(lead, e(c.get("year")))}</div>')
    return "".join(out)


SECTIONS = {"summary": sec_summary, "experience": sec_experience, "projects": sec_projects,
            "skills": sec_skills, "education": sec_education, "certifications": sec_certifications}


def build_html(r, include_photo):
    order = r.get("section_order") or DEFAULT_ORDER
    if r.get("projects_first") and not r.get("section_order"):
        order = ["summary", "projects", "experience", "skills", "education", "certifications"]
    body = [header(r, include_photo)]
    for key in order:
        content = SECTIONS[key](r) if key in SECTIONS else ""
        if content:
            body.append(f'<section><h2>{TITLES[key]}</h2>{content}</section>')
    tpl = (ASSETS / "resume_template.html").read_text(encoding="utf-8")
    return (tpl.replace("{{FONT_DIR}}", (ASSETS / "fonts").as_uri())
               .replace("{{TITLE}}", e(f"{r.get('name', '')} Resume")).replace("{{BODY}}", "\n".join(body)))


def count_pages(pdf: Path) -> int:
    data = pdf.read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("resume"); p.add_argument("out"); p.add_argument("--html-only", action="store_true")
    a = p.parse_args(argv)
    try:
        r = json.loads(Path(a.resume).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read resume JSON: {exc}")
    cfg = read_yaml(workspace() / "config.yaml", {}) or {}
    page = build_html(r, bool((cfg.get("resume") or {}).get("include_photo")))
    out = Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    html_path = out.with_suffix(".html")
    html_path.write_text(page, encoding="utf-8")
    if a.html_only:
        emit({"ok": True, "html": str(html_path)}); return
    browser = find_browser()
    if not browser:
        fail("Chrome or Chromium not found; install Google Chrome")
    with tempfile.TemporaryDirectory() as prof:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={prof}",
               "--no-pdf-header-footer", "--generate-pdf-document-outline",
               f"--print-to-pdf={out}", html_path.as_uri()]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if not out.exists() or out.stat().st_size < 1000:
        fail("PDF was not created", stderr=res.stderr[-500:])
    emit({"ok": True, "pdf": str(out), "html": str(html_path), "pages": count_pages(out)})


if __name__ == "__main__":
    main(sys.argv[1:])
