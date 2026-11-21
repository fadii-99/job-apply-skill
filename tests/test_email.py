"""Tests for send_email.py and the email-channel paths in tracker.py.

Only offline paths are tested (check, dry-run, validation). Nothing here ever
opens a real network connection or needs a real Gmail account.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from email import message_from_bytes
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import lint_text  # noqa: E402

from test_core import Base  # noqa: E402


def write_env(home, address="tester@example.com", password="fake-app-password-123"):
    (Path(home) / ".env").write_text(f"GMAIL_ADDRESS={address}\nGMAIL_APP_PASSWORD={password}\n")


class CheckTests(Base):
    def test_check_reports_missing_when_no_env_file(self):
        r = self.run_ok("send_email.py", "check")
        self.assertFalse(r["ok"])
        self.assertEqual(set(r["missing"]), {"GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"})

    def test_check_reports_ok_once_env_written(self):
        write_env(self.tmp.name)
        r = self.run_ok("send_email.py", "check")
        self.assertTrue(r["ok"])
        self.assertEqual(r["missing"], [])

    def test_check_reports_partial_env(self):
        (Path(self.tmp.name) / ".env").write_text("GMAIL_ADDRESS=tester@example.com\n")
        r = self.run_ok("send_email.py", "check")
        self.assertFalse(r["ok"])
        self.assertEqual(r["missing"], ["GMAIL_APP_PASSWORD"])

    def test_env_file_permissions_tightened(self):
        write_env(self.tmp.name)
        path = Path(self.tmp.name) / ".env"
        os.chmod(path, 0o644)
        self.run_ok("send_email.py", "check")
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")


class DryRunTests(Base):
    def setUp(self):
        super().setUp()
        write_env(self.tmp.name)
        self.pdf = Path(self.tmp.name) / "Ali_Khan_Resume.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 fake resume content for a test\n%%EOF")
        self.body = Path(self.tmp.name) / "email_body.md"
        self.body.write_text("Hi team,\n\nApplying for the Backend Engineer role. Resume attached.\n\nAli Khan")

    def test_dry_run_writes_eml_with_attachment_and_no_network(self):
        out = Path(self.tmp.name) / "email_dry_run.eml"
        r = self.run_ok("send_email.py", "--to", "jobs@acme.com", "--subject", "Application for Backend Engineer",
                        "--body-file", str(self.body), "--attach", str(self.pdf), "--dry-run",
                        "--save-eml", str(out))
        self.assertTrue(r["ok"]); self.assertTrue(r["dry_run"])
        self.assertTrue(out.exists())
        msg = message_from_bytes(out.read_bytes())
        self.assertEqual(msg["To"], "jobs@acme.com")
        self.assertEqual(msg["From"], "tester@example.com")
        self.assertIn("Application for Backend Engineer", msg["Subject"])
        filenames = [part.get_filename() for part in msg.walk() if part.get_filename()]
        self.assertIn("Ali_Khan_Resume.pdf", filenames)

    def test_missing_attachment_fails(self):
        code, out = self.run_cli("send_email.py", "--to", "jobs@acme.com", "--subject", "x",
                                 "--body-file", str(self.body), "--attach", "/no/such/file.pdf", "--dry-run")
        self.assertNotEqual(code, 0)
        self.assertFalse(out.get("ok", True))

    def test_no_attachment_required(self):
        code, out = self.run_cli("send_email.py", "--to", "jobs@acme.com", "--subject", "x",
                                 "--body-file", str(self.body), "--dry-run")
        self.assertNotEqual(code, 0)
        self.assertIn("resume", out.get("error", ""))

    def test_missing_credentials_fails_cleanly(self):
        (Path(self.tmp.name) / ".env").unlink()
        code, out = self.run_cli("send_email.py", "--to", "jobs@acme.com", "--subject", "x",
                                 "--body-file", str(self.body), "--attach", str(self.pdf), "--dry-run")
        self.assertNotEqual(code, 0)
        self.assertIn("GMAIL_ADDRESS", out.get("missing", []))


GOOD_EMAIL = (
    "Hi Acme team,\n\n"
    "I'm Ali Khan, a backend engineer with three years of experience building payment and billing "
    "systems. I currently work at Beta Pay, where I own the Django services behind subscriptions and invoicing.\n\n"
    "Your posting focuses on reliable payment processing. I built Stripe billing where each payment is applied "
    "exactly once, and moved payment jobs onto their own Celery workers so long uploads never delay billing. "
    "I also write the tests around it, with 200+ on my current platform.\n\n"
    "My resume is attached with the full details. I'd welcome the chance to discuss how I could contribute "
    "to your team, and I look forward to hearing from you.\n\n"
    "Best regards,\nAli Khan\nali@example.com\n+92 300 0000000"
)


class EmailBodyLintTests(unittest.TestCase):
    def test_standard_email_passes(self):
        r = lint_text.lint(GOOD_EMAIL, "email_body")
        self.assertTrue(r["ok"], r)

    def test_greeting_and_best_regards_allowed_in_email(self):
        issues = " ".join(lint_text.lint(GOOD_EMAIL, "email_body")["issues"])
        self.assertNotIn("greeting", issues)
        self.assertNotIn("sign-off", issues)
        r = lint_text.lint("Hi team, short note. Best regards", "field_short")
        self.assertIn("greeting", " ".join(r["issues"]))

    def test_missing_paragraph_flagged(self):
        blocks = GOOD_EMAIL.split("\n\n")
        four = "\n\n".join(blocks[:2] + blocks[3:])  # drop paragraph 2
        r = lint_text.lint(four, "email_body")
        self.assertFalse(r["ok"])
        self.assertTrue(any("too few blocks" in i for i in r["issues"]), r)

    def test_too_short_and_too_long_flagged(self):
        self.assertTrue(any("too short" in i for i in lint_text.lint("Hi team,\n\nShort.\n\nAli", "email_body")["issues"]))
        self.assertTrue(any("too long" in i for i in lint_text.lint("word " * 200, "email_body")["issues"]))

    def test_em_dash_and_double_hyphen_always_flagged(self):
        for bad in ("\u2014", "--"):
            r = lint_text.lint(GOOD_EMAIL.replace("full details.", f"full details {bad} thanks."), "email_body")
            self.assertFalse(r["ok"])
            self.assertTrue(any("em dash" in i for i in r["issues"]), r)

class TrackerEmailChannelTests(Base):
    def test_mailto_url_deduplicates_like_any_other(self):
        a = self.add("mailto:jobs@acme.com?subject=Backend", company="Acme", title="Backend Engineer")
        self.assertTrue(a["added"])
        self.assertTrue(a["canonical_url"].startswith("mailto:"))
        b = self.add("mailto:jobs@acme.com?subject=Backend", company="Acme", title="Backend Engineer")
        self.assertFalse(b["added"])

    def test_recover_splits_browser_and_email_submissions(self):
        web = self.add("https://a.com/1", company="A", title="t1")
        mail = self.add("mailto:jobs@b.com", company="B", title="t2")
        self.run_ok("tracker.py", "claim", "--worker", "w1")
        self.run_ok("tracker.py", "claim", "--worker", "w2")
        self.run_ok("tracker.py", "update", "--id", web["id"], "--status", "submitting")
        self.run_ok("tracker.py", "update", "--id", mail["id"], "--status", "submitting")
        out = self.run_ok("tracker.py", "recover")
        self.assertEqual([v["id"] for v in out["verify_on_site"]], [web["id"]])
        self.assertEqual([v["id"] for v in out["verify_email"]], [mail["id"]])
        self.assertIn("Sent folder", out["note"])


if __name__ == "__main__":
    unittest.main()
