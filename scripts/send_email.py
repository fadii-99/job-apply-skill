#!/usr/bin/env python3
"""Compose and send one job-application email over Gmail SMTP.

Credential: a Gmail App Password (not the user's real password) the user creates
in their Google Account and pastes into workspace/.env, read only by this script:
  ~/.job-apply/.env
    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
Never read elsewhere, never printed, never written into a resume/letter/log.

Usage:
  send_email.py check
                 prints {"ok": true} if GMAIL_ADDRESS and GMAIL_APP_PASSWORD are set, else
                 {"ok": false, "missing": [...]}. No network call.
  send_email.py --to <addr> [--cc <addr>] --subject "..." --body-file body.txt
                 --attach file.pdf [--attach file2.pdf]
                 [--dry-run] [--save-eml <path>]

--dry-run builds the message and saves it as a .eml (readable by any mail app)
without connecting to any server. Honours config.yaml's dry_run as a default.
"""
from __future__ import annotations

import argparse
import mimetypes
import smtplib
import sys
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from common import emit, fail, load_env, read_yaml, require_env, workspace

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465


def build_message(sender, to, cc, subject, body, attachments):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    if cc:
        msg["Cc"] = cc
    msg_id = make_msgid()
    msg["Message-Id"] = msg_id
    msg.set_content(body)
    for path in attachments:
        p = Path(path)
        if not p.is_file():
            fail(f"attachment not found: {p}")
        mime, _ = mimetypes.guess_type(p.name)
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype or "octet-stream", filename=p.name)
    return msg, msg_id


def main(argv):
    if argv[:1] == ["check"]:
        env = load_env()
        missing = [k for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD") if not env.get(k)]
        emit({"ok": not missing, "missing": missing, "env_file": str(workspace() / ".env")})
        return
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--to", required=True)
    p.add_argument("--cc")
    p.add_argument("--subject", required=True)
    p.add_argument("--body-file", required=True)
    p.add_argument("--attach", action="append", default=[], dest="attachments")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--save-eml", help="where to save the .eml on a dry run (default: alongside the first attachment)")
    a = p.parse_args(argv)

    if not a.attachments:
        fail("at least one --attach is required (the tailored resume)")
    try:
        body = Path(a.body_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        fail(f"cannot read --body-file: {exc}")

    cfg = read_yaml(workspace() / "config.yaml", {}) or {}
    dry = a.dry_run or bool(cfg.get("dry_run"))

    env = require_env("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")
    sender = env["GMAIL_ADDRESS"]
    msg, msg_id = build_message(sender, a.to, a.cc, a.subject, body, a.attachments)

    if dry:
        out = Path(a.save_eml) if a.save_eml else Path(a.attachments[0]).with_suffix("").parent / "email_dry_run.eml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(bytes(msg))
        emit({"ok": True, "dry_run": True, "message_id": msg_id, "eml": str(out),
              "to": a.to, "subject": a.subject, "attachments": a.attachments})
        return

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.login(sender, env["GMAIL_APP_PASSWORD"])
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        fail("Gmail rejected the app password. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in "
             f"{workspace() / '.env'} (the app password may have been revoked or mistyped).")
    except smtplib.SMTPException as exc:
        fail(f"sending failed: {exc}")
    except OSError as exc:
        fail(f"could not reach {SMTP_HOST}: {exc}")

    emit({"ok": True, "dry_run": False, "message_id": msg_id, "from": sender,
          "to": a.to, "subject": a.subject, "attachments": [Path(x).name for x in a.attachments]})


if __name__ == "__main__":
    main(sys.argv[1:])
