#!/usr/bin/env python3
"""Check a piece of application text for length, tone and AI-sounding phrases.

Usage:
  lint_text.py --kind cover_letter|email_body|field_long|field_short|summary|bullet [--max-chars N] (--file F | --text T)
Prints {"ok": true|false, "words": n, "issues": [...]}. Fix every issue by rewriting.
"""
from __future__ import annotations

import argparse
import re
import sys

from common import emit

BUDGETS = {
    "cover_letter": {"min_words": 120, "max_words": 180, "max_paragraphs": 4},
    # greeting, three paragraphs, footer (see references/email-writing.md)
    "email_body": {"min_words": 90, "max_words": 180, "max_sentences": 10, "min_paragraphs": 5, "max_paragraphs": 5},
    "field_long": {"max_words": 90, "max_sentences": 4},
    "field_short": {"max_words": 25, "max_sentences": 1},
    "summary": {"max_words": 70, "max_sentences": 3},
    "bullet": {"max_words": 28, "max_sentences": 1},
}
BANNED = [
    r"\bi am (so |very |truly )?(excited|thrilled|delighted|eager)\b", r"\bthrilled\b",
    r"\bpassionate about\b", r"\bpassion for\b", r"\bdelve\b", r"\bleverag(e|ing)\b", r"\bsynerg",
    r"\bproven track record\b", r"\bfast-paced environment\b", r"\bdynamic\b", r"\bresults-driven\b",
    r"\bgo-getter\b", r"\bteam player\b", r"\bself-starter\b", r"\bdetail-oriented\b",
    r"\bi believe i (would|will) be a (great|perfect|strong) fit\b", r"\bin today'?s .{0,30}world\b",
    r"\blook forward to the opportunity\b", r"\bunique blend\b", r"\btapestry\b", r"\bseamless(ly)?\b",
    r"\bcutting-edge\b", r"\bstate-of-the-art\b", r"\bspearhead", r"\bempower", r"\bharness(ing)?\b",
    r"\bjourney\b", r"\brobust\b", r"\bit is worth noting\b", r"\bwhether you'?re\b", r"\bnot only .{0,40} but also\b",
]
GREETING = re.compile(r"^\s*(dear|hi|hello|to whom)\b", re.I)
SIGNOFF = re.compile(r"\b(sincerely|best regards|kind regards|regards|yours (truly|faithfully))\b", re.I)
TRIAD = re.compile(r"\b(\w+), (\w+),? and (\w+) (\w+)\b", re.I)


def lint(text, kind, max_chars=None):
    issues = []
    b = BUDGETS[kind]
    words = len(re.findall(r"\b[\w'’-]+\b", text))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if words > b["max_words"]:
        issues.append(f"too long: {words} words, max {b['max_words']}")
    if words < b.get("min_words", 0):
        issues.append(f"too short: {words} words, min {b['min_words']}")
    if "max_sentences" in b and len(sentences) > b["max_sentences"]:
        issues.append(f"too many sentences: {len(sentences)}, max {b['max_sentences']}")
    if "max_paragraphs" in b and len(paragraphs) > b["max_paragraphs"]:
        issues.append(f"too many paragraphs: {len(paragraphs)}, max {b['max_paragraphs']}")
    if "min_paragraphs" in b and len(paragraphs) < b["min_paragraphs"]:
        issues.append(f"too few blocks: {len(paragraphs)}, need {b['min_paragraphs']} (greeting, 3 paragraphs, footer)")
    if max_chars and len(text) > int(max_chars * 0.9):
        issues.append(f"over 90% of the field limit: {len(text)} of {max_chars} characters")
    low = text.lower()
    for pat in BANNED:
        m = re.search(pat, low)
        if m:
            issues.append(f"AI-sounding phrase: '{m.group(0)}'")
    if "—" in text or "--" in text:
        issues.append("em dash; rewrite with a comma, colon or period instead")
    if "!" in text:
        issues.append("exclamation mark")
    if kind not in ("cover_letter", "email_body") and GREETING.search(text):
        issues.append("greeting in a short field")
    if kind not in ("cover_letter", "email_body") and SIGNOFF.search(text):
        issues.append("sign-off in a short field")
    for m in TRIAD.finditer(text):
        if all(w.lower().endswith(("ive", "ful", "ous", "ent", "ant", "ic", "al", "ed")) for w in m.groups()[:3]):
            issues.append(f"three-adjective list: '{m.group(0)}'")
    return {"ok": not issues, "kind": kind, "words": words, "characters": len(text), "issues": issues}


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--kind", required=True, choices=sorted(BUDGETS))
    p.add_argument("--max-chars", type=int)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--file"); g.add_argument("--text")
    a = p.parse_args(argv)
    text = open(a.file, encoding="utf-8").read() if a.file else a.text
    emit(lint(text, a.kind, a.max_chars))


if __name__ == "__main__":
    main(sys.argv[1:])
