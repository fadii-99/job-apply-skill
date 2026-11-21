"""Tests for the deterministic core: state gate, tracker dedupe/queue, browser setup.

Run: python3 -m unittest discover -s job-apply/tests -v
Each test uses its own temporary workspace (JOB_APPLY_HOME), never ~/.job-apply.
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "JOB_APPLY_HOME": self.tmp.name}
        self.run_ok("state.py", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, script, *args):
        p = subprocess.run([sys.executable, str(SCRIPTS / script), *args], env=self.env,
                           capture_output=True, text=True)
        try:
            out = json.loads(p.stdout) if p.stdout.strip() else {}
        except json.JSONDecodeError:
            self.fail(f"non-JSON output from {script} {args}: {p.stdout} {p.stderr}")
        return p.returncode, out

    def run_ok(self, script, *args):
        code, out = self.run_cli(script, *args)
        self.assertEqual(code, 0, f"{script} {args} -> {out}")
        return out

    def add(self, url, company="Acme", title="Flutter Developer", location="Remote", platform="linkedin",
            status="queued", fit=80, **kw):
        args = ["add", "--platform", platform, "--url", url, "--company", company, "--title", title,
                "--location", location, "--status", status, "--fit-score", str(fit)]
        for k, v in kw.items():
            args += [f"--{k.replace('_', '-')}", v]
        return self.run_ok("tracker.py", *args)

    def rows(self):
        with open(Path(self.tmp.name) / "logs" / "applications.csv", newline="") as f:
            return list(csv.DictReader(f))

    def set_row(self, rid, **fields):
        path = Path(self.tmp.name) / "logs" / "applications.csv"
        rows = self.rows()
        for r in rows:
            if r["id"] == rid:
                r.update(fields)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)


class StateTests(Base):
    def test_gate_blocks_until_ready(self):
        code, out = self.run_cli("state.py", "require", "READY")
        self.assertEqual(code, 3)
        self.assertEqual(out["state"], "NOT_SETUP")

    def test_full_setup_path_and_illegal_jump(self):
        code, out = self.run_cli("state.py", "set", "READY")
        self.assertNotEqual(code, 0)
        for s in ["INTAKE", "CLARIFY", "ANALYZING", "BUILDING", "USER_REVIEW", "PREFERENCES", "READY"]:
            self.run_ok("state.py", "set", s)
        self.run_ok("state.py", "require", "READY")

    def test_run_lock_prevents_second_run(self):
        self.assertTrue(self.run_ok("state.py", "run-lock", "acquire")["ok"])
        self.assertFalse(self.run_ok("state.py", "run-lock", "acquire")["ok"])
        self.run_ok("state.py", "run-lock", "release")
        self.assertTrue(self.run_ok("state.py", "run-lock", "acquire")["ok"])

    def test_stale_run_lock_is_detected_and_replaced(self):
        import time
        self.assertTrue(self.run_ok("state.py", "run-lock", "acquire")["ok"])
        self.assertFalse(self.run_ok("state.py", "run-lock", "status")["stale"])
        old = time.time() - 30 * 60
        ws = Path(self.tmp.name)
        for p in [ws / "run.lock", ws / "live" / "events.jsonl", *(ws / "queue").glob("*.json"),
                  ws / "logs" / "applications.csv"]:
            if p.exists():
                os.utime(p, (old, old))
        st = self.run_ok("state.py", "run-lock", "status")
        self.assertTrue(st["stale"], st)
        r = self.run_ok("state.py", "run-lock", "acquire")
        self.assertTrue(r["ok"]); self.assertTrue(r["replaced_stale_lock"])

    def test_init_creates_workspace_files(self):
        ws = Path(self.tmp.name)
        for p in ["config.yaml", "live/index.html", "state.json"]:
            self.assertTrue((ws / p).exists(), p)


class TrackerTests(Base):
    def test_same_posting_is_skipped(self):
        a = self.add("https://www.linkedin.com/jobs/view/4012345678/?trk=abc", platform="linkedin")
        self.assertTrue(a["added"])
        b = self.add("https://linkedin.com/jobs/view/flutter-dev-at-acme-4012345678", platform="linkedin")
        self.assertFalse(b["added"])
        self.assertIn("same opening", b["reason"])

    def test_tracking_params_removed(self):
        self.add("https://jobs.example.com/apply/55?utm_source=x&ref=y&id=55")
        b = self.add("https://jobs.example.com/apply/55?id=55", company="Other Co", title="Different")
        self.assertFalse(b["added"])

    def test_cross_platform_duplicate_within_window(self):
        a = self.add("https://www.linkedin.com/jobs/view/3000001/", company="Acme Inc.", title="Flutter Developer")
        self.run_ok("tracker.py", "update", "--id", a["id"], "--status", "applied")
        b = self.add("https://www.linkedin.com/jobs/view/3000999/",
                     company="ACME", title="Flutter developer", location="Remote (Worldwide)")
        self.assertFalse(b["added"])
        self.assertIn("same role at same company", b["reason"])

    def test_reopened_after_window_is_allowed(self):
        a = self.add("https://www.linkedin.com/jobs/view/3000001/")
        self.run_ok("tracker.py", "update", "--id", a["id"], "--status", "applied")
        old = (datetime.now().astimezone() - timedelta(days=60)).isoformat(timespec="seconds")
        self.set_row(a["id"], applied_at=old, updated_at=old, first_seen_at=old)
        b = self.add("https://www.linkedin.com/jobs/view/3000002/")
        self.assertTrue(b["added"], b)

    def test_company_limit(self):
        for i in range(2):
            a = self.add(f"https://x.com/{i}", title=f"Role {i}")
            self.run_ok("tracker.py", "update", "--id", a["id"], "--status", "applied")
        b = self.add("https://x.com/3", title="Role 3")
        self.assertFalse(b["added"])
        self.assertIn("company limit", b["reason"])

    def test_one_job_at_a_time_by_default(self):
        self.add("https://a.com/1", company="Alpha", title="Dev")
        self.add("https://b.com/1", company="Beta", title="Dev")
        self.assertIsNotNone(self.run_ok("tracker.py", "claim", "--worker", "w1")["job"])
        r = self.run_ok("tracker.py", "claim", "--worker", "w1")
        self.assertIsNone(r["job"])
        self.assertIn("busy", r["why"])

    def test_claim_order_company_lock_and_cap(self):
        cfg = Path(self.tmp.name) / "config.yaml"
        cfg.write_text(cfg.read_text().replace("max_total: 1 ", "max_total: 4 "))
        # a platform without a worker limit, to test the company lock and ordering alone
        self.add("https://a.com/1", company="Alpha", title="Dev", fit=70, platform="web")
        self.add("https://b.com/1", company="Beta", title="Dev", fit=90, platform="web")
        self.add("https://a.com/2", company="Alpha", title="Senior Dev", fit=85, platform="web")
        j1 = self.run_ok("tracker.py", "claim", "--worker", "w1")["job"]
        self.assertEqual(j1["company"], "Beta")
        j2 = self.run_ok("tracker.py", "claim", "--worker", "w2")["job"]
        self.assertEqual((j2["company"], j2["title"]), ("Alpha", "Senior Dev"))
        j3 = self.run_ok("tracker.py", "claim", "--worker", "w3")
        self.assertIsNone(j3["job"])
        self.assertIn("company already being applied to", j3["why"])

    def test_platform_worker_limit(self):
        cfg = Path(self.tmp.name) / "config.yaml"
        cfg.write_text(cfg.read_text().replace("max_total: 1 ", "max_total: 4 "))
        self.add("https://www.linkedin.com/jobs/view/1000001", platform="linkedin", company="A1", title="x")
        self.add("https://www.linkedin.com/jobs/view/1000002", platform="linkedin", company="B1", title="y")
        self.assertIsNotNone(self.run_ok("tracker.py", "claim", "--worker", "w1")["job"])
        r = self.run_ok("tracker.py", "claim", "--worker", "w2")
        self.assertIsNone(r["job"])
        self.assertIn("linkedin worker limit", r["why"])

    def test_manual_and_discarded_lists_written(self):
        a = self.add("https://a.com/1", company="A", title="t1")
        b = self.add("https://b.com/1", company="B", title="t2")
        self.run_ok("tracker.py", "update", "--id", a["id"], "--status", "manual", "--reason", "CAPTCHA")
        self.run_ok("tracker.py", "update", "--id", b["id"], "--status", "discarded", "--reason", "job closed")
        logs = Path(self.tmp.name) / "logs"
        self.assertIn("CAPTCHA", (logs / "manual.csv").read_text())
        self.assertIn("job closed", (logs / "discarded.csv").read_text())

    def test_recover_after_crash(self):
        cfg = Path(self.tmp.name) / "config.yaml"
        cfg.write_text(cfg.read_text().replace("max_total: 1 ", "max_total: 4 "))
        a = self.add("https://a.com/1", company="A", title="t1", platform="web")
        b = self.add("https://b.com/1", company="B", title="t2", platform="web")
        self.run_ok("tracker.py", "claim", "--worker", "w1")
        self.run_ok("tracker.py", "claim", "--worker", "w2")
        self.run_ok("tracker.py", "update", "--id", b["id"], "--status", "submitting")
        out = self.run_ok("tracker.py", "recover")
        self.assertEqual(out["requeued"], [a["id"]])
        self.assertEqual([v["id"] for v in out["verify_on_site"]], [b["id"]])

    def test_requeue_after_login(self):
        a = self.add("https://www.linkedin.com/jobs/view/2000001", platform="linkedin", company="A", title="t")
        self.run_ok("tracker.py", "update", "--id", a["id"], "--status", "manual", "--reason", "login needed")
        out = self.run_ok("tracker.py", "requeue", "--platform", "linkedin", "--reason-contains", "login")
        self.assertEqual(out["requeued"], [a["id"]])

    def test_blocklist(self):
        cfg = Path(self.tmp.name) / "config.yaml"
        cfg.write_text(cfg.read_text().replace("blocklist_companies: []", "blocklist_companies: [\"Acme Ltd\"]"))
        b = self.add("https://a.com/9", company="ACME")
        self.assertFalse(b["added"])
        self.assertEqual(b["reason"], "blocklisted company")


class BrowserSetupTests(unittest.TestCase):
    """browser.py helpers that don't call Chrome or Claude."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))
        import browser
        self.b = browser
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "JOB_APPLY_HOME")}
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        os.environ["JOB_APPLY_HOME"] = str(Path(self.tmp.name) / "ws")

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_token_cleaning(self):
        tok = "AbC_dEf-1234567890abcdefGHIJKLmnop_qrstuv"
        self.assertEqual(self.b.clean_token(f"PLAYWRIGHT_MCP_EXTENSION_TOKEN={tok}"), tok)
        self.assertEqual(self.b.clean_token(f"  '{tok}' "), tok)
        self.assertTrue(self.b.TOKEN_RE.match(tok))
        self.assertFalse(self.b.TOKEN_RE.match("hello world"))

    @unittest.skipIf(sys.platform in ("darwin", "win32"), "Linux profile layout")
    def test_finds_extension_in_profiles(self):
        root = Path(self.tmp.name) / "google-chrome"
        (root / "Default").mkdir(parents=True)
        (root / "Profile 2" / "Extensions" / self.b.EXTENSION_ID).mkdir(parents=True)
        (root / "Profile 3").mkdir()
        (root / "Profile 3" / "Preferences").write_text(json.dumps(
            {"extensions": {"settings": {self.b.EXTENSION_ID: {"state": 1}}}}))
        self.assertEqual(self.b.extension_profiles(), ["Profile 2", "Profile 3"])

    def test_server_config(self):
        cfg = self.b.server_config("tok123", "Profile 2")
        self.assertIn("--extension", cfg["args"])
        self.assertEqual(cfg["args"][cfg["args"].index("--profile-dir-name") + 1], "Profile 2")
        self.assertEqual(cfg["env"], {"PLAYWRIGHT_MCP_EXTENSION_TOKEN": "tok123"})
        plain = self.b.server_config(None, "Default")
        self.assertNotIn("--profile-dir-name", plain["args"])
        self.assertEqual(plain["env"], {})


class LiveTests(Base):
    def test_event_builds_live_js(self):
        self.run_ok("live.py", "event", "--worker", "w1", "--stage", "filling", "--job", "A1",
                    "--company", "Acme", "--title", "Dev")
        js = (Path(self.tmp.name) / "live" / "live.js").read_text()
        self.assertTrue(js.startswith("window.__LIVE = "))
        data = json.loads(js[len("window.__LIVE = "):].rstrip().rstrip(";"))
        self.assertEqual(data["workers"][0]["stage"], "filling")


class ReportTests(Base):
    def test_report_groups(self):
        a = self.add("https://a.com/1", company="A", title="t1")
        self.run_ok("tracker.py", "update", "--id", a["id"], "--status", "applied")
        self.add("https://b.com/1", company="B", title="t2", status="skipped", reason="low fit: needs Go")
        c = self.add("https://c.com/1", company="C", title="t3")
        self.run_ok("tracker.py", "update", "--id", c["id"], "--status", "manual", "--reason", "CAPTCHA")
        r = self.run_ok("tracker.py", "report", "--days", "7")
        self.assertEqual(r["applied"][0]["id"], a["id"])
        self.assertEqual(r["skip_reasons"], {"low fit": 1})
        self.assertEqual(r["manual"][0]["reason"], "CAPTCHA")


class CoverLetterPdfTests(Base):
    def test_letter_pdf(self):
        src = Path(self.tmp.name) / "cover_letter.md"
        src.write_text("Hi team,\n\nFirst paragraph.\n\nAli Khan")
        out = Path(self.tmp.name) / "Ali_Khan_Cover_Letter.pdf"
        r = self.run_ok("render_text.py", str(src), str(out))
        self.assertTrue(out.exists())


class ReadableReportTests(Base):
    def test_report_written_with_plain_statuses_and_details(self):
        import json as _json
        ws = Path(self.tmp.name)
        (ws / "queue").mkdir(exist_ok=True)
        (ws / "queue" / "2026-01-01-linkedin.json").write_text(_json.dumps([
            {"platform": "linkedin", "url": "https://a.com/1?utm_source=x", "apply_url": "https://boards.greenhouse.io/a/jobs/1",
             "email": "", "company": "A", "title": "t1", "location": "Remote", "work_mode": "remote"}]))
        a = self.add("https://a.com/1", company="A", title="t1", fit=90)
        b = self.add("https://b.com/1", company="B", title="t2", fit=70)
        c = self.add("https://c.com/1", company="C", title="t3", status="skipped", reason="low fit: needs Go", fit=40)
        folder = ws / "applications" / "x"; folder.mkdir(parents=True)
        (folder / "Ali_Khan_Resume.pdf").write_bytes(b"%PDF"); (folder / "confirmation.png").write_bytes(b"png")
        self.run_ok("tracker.py", "update", "--id", a["id"], "--status", "applied", "--folder", str(folder))
        self.run_ok("tracker.py", "update", "--id", b["id"], "--status", "manual", "--reason", "CAPTCHA")
        text = (ws / "logs" / "My_Job_Applications.csv").read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(text.splitlines()))
        self.assertEqual([r["Status"] for r in rows], ["Needs you", "Applied", "Skipped"])
        applied = rows[1]
        self.assertEqual(applied["Work mode"], "Remote")
        self.assertEqual(applied["Applied via"], "Website form")
        self.assertEqual(applied["Resume sent"], "Ali_Khan_Resume.pdf")
        self.assertEqual(applied["Confirmation"], "confirmation.png")
        self.assertIn("greenhouse", applied["Apply link or email"])
        self.assertEqual(rows[2]["Reason / notes"], "low fit: needs Go")
        out = self.run_ok("tracker.py", "export")
        self.assertEqual(out["rows"], 3)


if __name__ == "__main__":
    unittest.main()
