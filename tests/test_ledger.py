"""Tests for ledger.py (merge, decide, alias) and alias-aware resume checks."""
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import profile_tools  # noqa: E402

from test_core import Base  # noqa: E402


def fragment(slug, items, highlights=()):
    return {"project": slug, "name": slug, "head": None, "summary": "", "owner_share": "", "role": "backend",
            "items": items, "highlights": list(highlights)}


class LedgerTests(Base):
    def setUp(self):
        super().setUp()
        self.dir = Path(self.tmp.name) / "profile" / "ledger"
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "shop-api.json").write_text(json.dumps(fragment("shop-api", [
            {"skill": "Django", "status": "verified", "level": "designed", "evidence": ["shop/models.py"]},
            {"skill": "Retrieval-Augmented Generation (RAG)", "status": "verified", "level": "built", "evidence": ["rag.py"]},
            {"skill": "GitHub Actions", "status": "seen_not_said", "level": "used", "evidence": [".github/ci.yml"]},
            {"skill": "Firebase Auth", "status": "said_not_seen", "level": "used", "evidence": []},
        ], [{"text": "Built billing", "evidence": ["billing.py"], "metric": None}])))
        (self.dir / "app.json").write_text(json.dumps(fragment("app", [
            {"skill": "Django", "status": "verified", "level": "used", "evidence": ["app/views.py"]},
        ])))

    def ledger(self):
        return json.loads((Path(self.tmp.name) / "profile" / "evidence_ledger.json").read_text())

    def test_merge_statuses_levels_and_questions(self):
        r = self.run_ok("ledger.py", "merge")
        self.assertEqual(r["skills"], 4)
        sk = self.ledger()["skills"]
        self.assertEqual(sk["Django"]["status"], "verified")
        self.assertEqual(sk["Django"]["level"], "designed")
        self.assertEqual(sorted(sk["Django"]["projects"]), ["app", "shop-api"])
        self.assertEqual({q["skill"] for q in r["needs_question"]}, {"GitHub Actions", "Firebase Auth"})
        self.assertEqual(r["highlights"], 1)

    def test_decisions_survive_a_second_merge(self):
        self.run_ok("ledger.py", "merge")
        self.assertEqual(self.run_ok("ledger.py", "decide", "Firebase Auth", "yes")["to"], "user_attested")
        self.assertEqual(self.run_ok("ledger.py", "decide", "GitHub Actions", "no")["to"], "rejected")
        r = self.run_ok("ledger.py", "merge")
        sk = self.ledger()["skills"]
        self.assertEqual(sk["Firebase Auth"]["status"], "user_attested")
        self.assertEqual(sk["GitHub Actions"]["status"], "rejected")
        self.assertEqual(r["needs_question"], [])

    def test_alias_recorded(self):
        self.run_ok("ledger.py", "merge")
        self.run_ok("ledger.py", "alias", "Django REST", "Django")
        self.assertIn("Django REST", self.ledger()["skills"]["Django"]["aliases"])
        self.run_ok("ledger.py", "merge")  # re-merge keeps it
        self.assertIn("Django REST", self.ledger()["skills"]["Django"]["aliases"])

    def test_unknown_skill_decide_fails(self):
        self.run_ok("ledger.py", "merge")
        code, out = self.run_cli("ledger.py", "decide", "Kubernetes", "yes")
        self.assertNotEqual(code, 0)


class AliasCheckTests(unittest.TestCase):
    profile = {"identity": {"full_name": "Ali Khan"}, "experience": []}
    ledger = {"skills": {
        "Retrieval-Augmented Generation (RAG)": {"status": "verified"},
        "AWS S3": {"status": "verified"},
        "Kubernetes (K8s)": {"status": "rejected"},
        "Blender (bpy)": {"status": "user_attested"},
    }}

    def check(self, items, aliases=None):
        return profile_tools.check_resume({"name": "Ali Khan", "skills": [{"group": "x", "items": items}]},
                                          self.profile, self.ledger, aliases)

    def test_bracket_names_match_both_ways(self):
        self.assertTrue(self.check(["RAG", "Retrieval-Augmented Generation", "Blender"])["ok"])

    def test_explicit_alias(self):
        self.assertFalse(self.check(["S3"])["ok"])
        self.assertTrue(self.check(["S3"], {"S3": "AWS S3"})["ok"])

    def test_rejected_stays_rejected_under_any_name(self):
        r = self.check(["K8s"])
        self.assertFalse(r["ok"])
        self.assertIn("not allowed", r["problems"][0])


if __name__ == "__main__":
    unittest.main()
