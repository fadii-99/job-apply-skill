"""Tests for lint_text, profile_tools and render_resume."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import lint_text  # noqa: E402
import profile_tools  # noqa: E402

GOOD_LETTER = (
    "I'd like to apply for the Flutter Developer role. I have spent the last three years building "
    "production Flutter apps, and your focus on offline-first field tools is close to what I work on "
    "every day.\n\n"
    "At Acme I built the receipt scanning app used by our sales team: camera capture, on-device OCR "
    "and a sync queue that keeps working without a connection. I structured it with Riverpod and "
    "clean layers so new features stay small. I also wrote the Django REST backend it talks to, so I "
    "am comfortable on both sides of the API and in reviewing contracts between them.\n\n"
    "I'd be glad to walk you through that code or any of my other projects. Thank you for reading.\n\n"
    "Ali Khan"
)


class LintTests(unittest.TestCase):
    def test_good_letter_passes(self):
        r = lint_text.lint(GOOD_LETTER, "cover_letter")
        self.assertTrue(r["ok"], r)

    def test_ai_phrases_flagged(self):
        r = lint_text.lint("I am thrilled to leverage my proven track record in a fast-paced environment!", "field_long")
        joined = " ".join(r["issues"])
        for bit in ("thrilled", "leverag", "proven track record", "fast-paced", "exclamation"):
            self.assertIn(bit, joined)

    def test_short_field_rules(self):
        r = lint_text.lint("Dear team, I can start in one month. Best regards", "field_short")
        joined = " ".join(r["issues"])
        self.assertIn("greeting", joined)
        self.assertIn("sign-off", joined)

    def test_char_limit(self):
        r = lint_text.lint("x" * 95, "field_short", max_chars=100)
        self.assertIn("90%", " ".join(r["issues"]))


class YearsTests(unittest.TestCase):
    def test_overlap_merged(self):
        r = profile_tools.years([
            {"company": "A", "start": "2020-01", "end": "2021-12"},
            {"company": "B", "start": "2021-06", "end": "2022-12"},
        ])
        self.assertEqual(r["months"], 36)
        self.assertEqual(r["display"], "3+ years")

    def test_formats_and_unparsed(self):
        r = profile_tools.years([{"company": "A", "start": "Jan 2023", "end": "Jun 2023"},
                                 {"company": "B", "start": "sometime", "end": None}])
        self.assertEqual(r["months"], 6)
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["unparsed"]), 1)


class CheckResumeTests(unittest.TestCase):
    profile = {"identity": {"full_name": "Ali Khan", "email": "a@x.com", "phone": "+92 300 0000000"},
               "experience": [{"company": "Acme", "title": "Flutter Developer", "start": "2023-01", "end": None}]}
    ledger = {"skills": {"Flutter": {"status": "verified"}, "Kubernetes": {"status": "rejected"},
                         "Firebase Auth": {"status": "user_attested"}}}

    def test_clean_resume(self):
        r = {"name": "Ali Khan", "contact": {"email": "a@x.com", "phone": "+923000000000"},
             "skills": [{"group": "Mobile", "items": ["Flutter", "Firebase Auth"]}],
             "experience": [{"company": "Acme", "title": "Flutter Developer", "start": "Jan 2023", "end": "Present"}]}
        self.assertTrue(profile_tools.check_resume(r, self.profile, self.ledger)["ok"])

    def test_invented_skill_and_wrong_date(self):
        r = {"name": "Ali Khan", "skills": [{"group": "Ops", "items": ["Kubernetes", "Terraform"]}],
             "experience": [{"company": "Acme", "title": "Flutter Developer", "start": "2022-01", "end": "Present"}]}
        probs = " ".join(profile_tools.check_resume(r, self.profile, self.ledger)["problems"])
        self.assertIn("Kubernetes", probs)
        self.assertIn("Terraform", probs)
        self.assertIn("start date differs", probs)


class RenderTests(unittest.TestCase):
    def test_pdf_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "r.json"
            src.write_text(json.dumps({
                "name": "Ali Khan", "headline": "Flutter Developer",
                "contact": {"email": "a@x.com", "phone": "+92 300 0000000", "location": "Lahore, Pakistan",
                            "links": [{"label": "GitHub", "url": "https://github.com/example"}]},
                "summary": "Flutter developer with three years of production apps.",
                "skills": [{"group": "Mobile", "items": ["Flutter", "Dart"]}],
                "experience": [{"company": "Acme", "title": "Flutter Developer", "start": "Jan 2023",
                                "end": "Present", "bullets": ["Built the receipt scanning app <with OCR>."]}],
                "projects": [{"name": "recipe-app", "stack": ["Flutter"], "bullets": ["Offline sync queue."]}],
                "education": [{"institution": "PU", "degree": "BS", "field": "CS", "start": "2018", "end": "2022"}],
                "certifications": [{"name": "AWS Cloud Practitioner", "issuer": "Amazon", "year": "2024"}],
            }))
            out = Path(tmp) / "Ali_Khan_Resume.pdf"
            env = {**os.environ, "JOB_APPLY_HOME": tmp}
            p = subprocess.run([sys.executable, str(SCRIPTS / "render_resume.py"), str(src), str(out)],
                               env=env, capture_output=True, text=True, timeout=120)
            res = json.loads(p.stdout)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["pages"], 1)
            self.assertIn("&lt;with OCR&gt;", out.with_suffix(".html").read_text())


@unittest.skipUnless(__import__("shutil").which("pdftotext") and __import__("shutil").which("pdffonts"),
                     "poppler-utils not installed")
class AtsTests(unittest.TestCase):
    """The PDF must read in order as plain text and use no Type 3 fonts."""

    def test_reading_order_and_fonts(self):
        resume = {
            "name": "Sara Ahmed", "headline": "Backend Engineer",
            "contact": {"location": "Dubai, UAE", "phone": "+971 50 000 0000", "email": "sara@example.com",
                        "links": [{"url": "https://github.com/example"}]},
            "summary": "Backend engineer building payment systems.",
            "experience": [
                {"title": "Backend Engineer", "company": "Alpha", "location": "Remote", "start": "Jan 2024",
                 "bullets": ["ALPHA-BULLET-ONE built the billing service.", "ALPHA-BULLET-TWO added retries."]},
                {"title": "Developer", "company": "Beta", "start": "Jan 2022", "end": "Dec 2023",
                 "bullets": ["BETA-BULLET-ONE wrote the REST API."]}],
            "projects": [{"name": "Ledger", "subtitle": "Double-entry service", "date": "2025",
                          "description": "Keeps balances exact.", "bullets": ["LEDGER-BULLET handles refunds."],
                          "stack": ["Python", "PostgreSQL"], "link": "example.com"}],
            "skills": [{"group": "Backend", "items": ["Python", "PostgreSQL"]}],
            "education": [{"degree": "BS Computer Science", "institution": "Uni", "start": "2018", "end": "2022"}],
            "certifications": [{"name": "Cert", "issuer": "Org", "year": "2025"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "r.json"; src.write_text(json.dumps(resume))
            out = Path(tmp) / "Sara_Ahmed_Resume.pdf"
            env = {**os.environ, "JOB_APPLY_HOME": tmp}
            subprocess.run([sys.executable, str(SCRIPTS / "render_resume.py"), str(src), str(out)],
                           env=env, capture_output=True, text=True, timeout=120, check=True)
            text = subprocess.run(["pdftotext", "-raw", str(out), "-"], capture_output=True, text=True).stdout
            order = ["Sara Ahmed", "PROFESSIONAL SUMMARY", "Backend Engineer, Alpha", "ALPHA-BULLET-ONE",
                     "ALPHA-BULLET-TWO", "Developer, Beta", "BETA-BULLET-ONE", "Ledger:", "Keeps balances exact.",
                     "LEDGER-BULLET", "Stack: Python, PostgreSQL", "TECHNICAL SKILLS", "Backend Python, PostgreSQL",
                     "EDUCATION", "CERTIFICATIONS"]
            positions = [text.find(s) for s in order]
            self.assertNotIn(-1, positions, dict(zip(order, positions)))
            self.assertEqual(positions, sorted(positions), "text order in the PDF is scrambled")
            self.assertIn("• ALPHA-BULLET-ONE", text)
            fonts = subprocess.run(["pdffonts", str(out)], capture_output=True, text=True).stdout
            self.assertNotIn("Type 3", fonts)
            self.assertIn("TrueType", fonts)


if __name__ == "__main__":
    unittest.main()
