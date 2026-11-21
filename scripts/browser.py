#!/usr/bin/env python3
"""The user's own Chrome, driven through the Playwright Extension.

The skill uses ONE browser tool, `jobapply-browser`: Playwright MCP in extension mode.
It connects to the user's normal Chrome (where they are already logged in to LinkedIn)
through the "Playwright Extension" from the Chrome Web Store. A token copied from the
extension lets it connect without a click each time.

Usage (all print JSON):
  browser.py check                 what is ready and the next step to take
  browser.py open-store            open the extension's Chrome Web Store page in Chrome
  browser.py open-token-page       open the extension page that shows the token
  browser.py save-token <token>    save the token and register the browser tool with it
  browser.py register [--project DIR]
                                   (re)register jobapply-browser for the project folder,
                                   removing the old jobapply-login / jobapply-w1..w4 tools
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import emit, fail, now_iso, read_json, workspace, write_json

SERVER = "jobapply-browser"
OLD_SERVERS = ["jobapply-login"] + [f"jobapply-w{i}" for i in range(1, 5)]
PLAYWRIGHT_MCP = "@playwright/mcp@0.0.84"
EXTENSION_ID = "mmlmfjhmonkocbjadbfplnigmagldckm"
STORE_URL = f"https://chromewebstore.google.com/detail/playwright-extension/{EXTENSION_ID}"
TOKEN_PAGE = f"chrome-extension://{EXTENSION_ID}/manage.html"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def record_path() -> Path:
    return workspace() / "session" / "browser.json"


def load_record() -> dict:
    return read_json(record_path(), {}) or {}


def save_record(rec: dict) -> None:
    write_json(record_path(), rec)
    os.chmod(record_path(), 0o600)


def chrome_user_data_dirs() -> list[Path]:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        base = home / "Library" / "Application Support" / "Google"
        return [base / "Chrome", base / "Chrome Beta"]
    if system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return [local / "Google" / "Chrome" / "User Data"]
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return [cfg / "google-chrome", cfg / "google-chrome-beta", cfg / "chromium"]


def chrome_command() -> list[str] | None:
    system = platform.system()
    if system == "Darwin":
        app = Path("/Applications/Google Chrome.app")
        return ["open", "-a", "Google Chrome"] if app.exists() else None
    if system == "Windows":
        for root in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if root:
                exe = Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
                if exe.exists():
                    return [str(exe)]
        return None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return [name]
    return None


def _has_extension(profile_dir: Path) -> bool:
    if (profile_dir / "Extensions" / EXTENSION_ID).is_dir():
        return True
    for name in ("Preferences", "Secure Preferences"):
        try:
            prefs = json.loads((profile_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rec = ((prefs.get("extensions") or {}).get("settings") or {}).get(EXTENSION_ID)
        if isinstance(rec, dict) and rec:
            return True
    return False


def extension_profiles() -> list[str]:
    """Chrome profile folder names ("Default", "Profile 1", ...) that have the extension."""
    found = []
    for root in chrome_user_data_dirs():
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d.name == "Default" or d.name.startswith("Profile ")) and _has_extension(d):
                found.append(d.name)
    return list(dict.fromkeys(found))


def clean_token(text: str) -> str:
    t = text.strip().strip("'\"` ")
    if "=" in t and t.upper().startswith("PLAYWRIGHT_MCP_EXTENSION_TOKEN"):
        t = t.split("=", 1)[1].strip().strip("'\"` ")
    return t


def project_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    saved = load_record().get("project")
    if saved:
        return Path(saved)
    # The project is the folder that holds .claude/skills/job-apply (Claude Code runs there).
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / ".claude" / "skills" / "job-apply").exists():
            return d
    return here


def _claude(args, project: Path):
    return subprocess.run(["claude", *args], cwd=project, capture_output=True, text=True)


def server_config(token: str | None, profile: str | None) -> dict:
    out = workspace() / "browser-output"
    out.mkdir(parents=True, exist_ok=True)
    args = ["-y", PLAYWRIGHT_MCP, "--extension", "--browser", "chrome", "--allow-unrestricted-file-access",
            "--timeout-action", "15000", "--timeout-navigation", "60000", "--output-dir", str(out)]
    if profile and profile != "Default":
        args += ["--profile-dir-name", profile]
    cfg = {"type": "stdio", "command": "npx", "args": args, "env": {}}
    if token:
        cfg["env"]["PLAYWRIGHT_MCP_EXTENSION_TOKEN"] = token
    return cfg


def register(project: Path) -> dict:
    """Register jobapply-browser (local scope) for `project`; remove the old per-worker browsers."""
    if not shutil.which("claude"):
        fail("the 'claude' command was not found on PATH")
    if not project.is_dir():
        fail(f"project folder not found: {project}")
    rec = load_record()
    profiles = extension_profiles()
    profile = rec.get("profile") if rec.get("profile") in profiles else (profiles[0] if profiles else None)
    removed = []
    for name in OLD_SERVERS + [SERVER]:
        if _claude(["mcp", "get", name], project).returncode == 0:
            _claude(["mcp", "remove", name, "-s", "local"], project)
            if name != SERVER:
                removed.append(name)
    cfg = server_config(rec.get("token"), profile)
    r = _claude(["mcp", "add-json", SERVER, json.dumps(cfg), "-s", "local"], project)
    if r.returncode != 0:
        fail(f"could not register {SERVER}: {r.stderr.strip() or r.stdout.strip()}")
    rec.update({"project": str(project), "profile": profile, "registered_at": now_iso(),
                "registered_with_token": bool(rec.get("token"))})
    save_record(rec)
    return {"ok": True, "registered": SERVER, "project": str(project), "chrome_profile": profile,
            "with_token": bool(rec.get("token")), "removed_old": removed,
            "restart_needed": True,
            "next": "Claude Code must be restarted in this project folder so the browser tool loads."}


def open_url(url: str) -> dict:
    cmd = chrome_command()
    if not cmd:
        return {"ok": False, "error": "Google Chrome was not found", "url": url}
    subprocess.Popen([*cmd, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"ok": True, "opened": url}


def cmd_check(a):
    rec = load_record()
    chrome = chrome_command() is not None
    profiles = extension_profiles()
    proj = project_dir(None)
    registered = None
    if shutil.which("claude"):
        registered = _claude(["mcp", "get", SERVER], proj).returncode == 0
        old_left = [n for n in OLD_SERVERS if _claude(["mcp", "get", n], proj).returncode == 0]
    else:
        old_left = []
    token = bool(rec.get("token"))
    if not chrome:
        nxt = "install_chrome"
    elif not profiles:
        nxt = "install_extension"
    elif not token:
        nxt = "get_token"
    elif not registered or not rec.get("registered_with_token") or old_left:
        nxt = "register"
    else:
        nxt = "ready_if_tools_loaded"
    return {"ok": True, "chrome_installed": chrome, "extension_in_profiles": profiles,
            "token_saved": token, "registered": registered, "registered_with_token": bool(rec.get("registered_with_token")),
            "old_browser_tools_left": old_left, "project": str(proj), "next": nxt,
            "store_url": STORE_URL}


def cmd_save_token(a):
    token = clean_token(" ".join(a.token))
    if not TOKEN_RE.match(token):
        fail("that does not look like the extension token; copy it again with the Copy button")
    rec = load_record()
    rec["token"] = token
    rec["token_saved_at"] = now_iso()
    save_record(rec)
    return {**register(project_dir(a.project)), "token_saved": True}


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("open-store")
    sub.add_parser("open-token-page")
    s = sub.add_parser("save-token"); s.add_argument("token", nargs="+"); s.add_argument("--project")
    s = sub.add_parser("register"); s.add_argument("--project")
    a = p.parse_args(argv)
    if a.cmd == "check":
        emit(cmd_check(a))
    elif a.cmd == "open-store":
        emit(open_url(STORE_URL))
    elif a.cmd == "open-token-page":
        emit(open_url(TOKEN_PAGE))
    elif a.cmd == "save-token":
        emit(cmd_save_token(a))
    else:
        emit(register(project_dir(a.project)))


if __name__ == "__main__":
    main(sys.argv[1:])
