#!/usr/bin/env python3
"""Render a plain-text cover letter (paragraphs separated by blank lines) to a PDF.

Usage:
  render_text.py <letter.md> <out.pdf>
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from common import emit, fail
from render_resume import find_browser

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Cover letter</title>
<style>@page {{ size: A4; margin: 22mm 22mm; }}
body {{ margin: 0; color: #1a1a1a; font: 11pt/1.5 "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif; }}
p {{ margin: 0 0 10pt; }}</style></head><body>{body}</body></html>"""


def main(argv):
    if len(argv) != 2:
        fail(__doc__)
    src, out = Path(argv[0]), Path(argv[1]).expanduser().resolve()
    text = src.read_text(encoding="utf-8").strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    body = "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paras)
    browser = find_browser()
    if not browser:
        fail("Chrome or Chromium not found")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "letter.html"
        page.write_text(PAGE.format(body=body), encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run",
                        f"--user-data-dir={tmp}/profile", "--no-pdf-header-footer",
                        f"--print-to-pdf={out}", page.as_uri()], capture_output=True, timeout=90)
    if not out.exists() or out.stat().st_size < 800:
        fail("PDF was not created")
    emit({"ok": True, "pdf": str(out)})


if __name__ == "__main__":
    main(sys.argv[1:])
