#!/usr/bin/env python3
"""One-time install: link the skill into a project and register the browser tool.

Usage:
  install.py --project /path/to/folder

What it does (safe to run again):
  1. Creates the workspace (~/.job-apply, or JOB_APPLY_HOME).
  2. Links this skill to <project>/.claude/skills/job-apply.
  3. Registers ONE browser tool for that project (local scope), `jobapply-browser`:
     Playwright MCP in extension mode, driving the user's own Chrome through the
     "Playwright Extension". Old jobapply-login / jobapply-w1..w4 tools are removed.
     The extension and its token are set up in the first /job-apply chat
     (scripts/browser.py), which registers the tool again with the token.
Claude Code must be restarted afterwards so the browser tool loads.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from common import SKILL_DIR, emit, fail, workspace

import browser
import state


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    a = p.parse_args(argv)
    if not shutil.which("claude"):
        fail("the 'claude' command was not found on PATH")
    project = Path(a.project).expanduser().resolve()
    if not project.is_dir():
        fail(f"project folder not found: {project}")

    ws_info = state.init()
    ws = workspace()

    link = project / ".claude" / "skills" / "job-apply"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        if link.resolve() != SKILL_DIR:
            fail(f"{link} already exists and points elsewhere; remove it first")
        # Cloned straight into <project>/.claude/skills/job-apply (the recommended way): nothing to link.
        linked = "already linked" if link.is_symlink() else "skill already in place"
    else:
        link.symlink_to(SKILL_DIR, target_is_directory=True)
        linked = "linked"

    # A visible shortcut to the (hidden) workspace, so the user finds their logs,
    # resumes and application folders next to where they run Claude.
    data_link = project / "job-apply-data"
    if data_link.is_symlink() or data_link.exists():
        data_note = "already there" if data_link.resolve() == ws.resolve() else "name taken, skipped"
    else:
        data_link.symlink_to(ws, target_is_directory=True)
        data_note = "created"

    reg = browser.register(project)

    emit({"ok": True, "workspace": ws_info, "skill_link": f"{link} ({linked})",
          "data_link": f"{data_link} ({data_note})", "browser": reg,
          "next": "Restart Claude Code in this project folder, then type /job-apply. "
                  "It will help you add the Playwright Extension to Chrome if it isn't there yet."})


if __name__ == "__main__":
    main(sys.argv[1:])
