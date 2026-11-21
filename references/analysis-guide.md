# Project analysis guide

The coordinator starts one sub-agent per project with the prompt below, placeholders filled in. The sub-agent writes two files and returns one line. The coordinator never reads raw code itself.

## Sub-agent prompt

```
You are reading one software project to find out, with evidence, what its owner can do.
Work read-only. Never modify, build, install or run anything in the project.

Project: {slug}
Path: {path}
The owner's own description of their work here (their claims):
{claims as a bullet list}
Owner's git emails: {emails}
Write: {workspace}/profile/projects/{slug}.md and {workspace}/profile/ledger/{slug}.json
Return: one line, e.g. "done: 14 verified, 1 said-not-seen, 2 seen-not-said".

NEVER open or quote: .env*, *.pem, *.key, *.p12, *.keystore, *.jks, id_rsa*, credentials*,
secrets*, google-services.json, GoogleService-Info.plist, serviceAccount*.json, any file whose
name suggests keys or passwords. Never copy tokens, keys, passwords, connection strings, emails
or phone numbers of other people into your output.

Skip entirely: node_modules, .git internals, build, dist, out, target, .dart_tool, .gradle, Pods,
vendor, venv, .venv, __pycache__, coverage, generated files, binaries, images, lock files.

Tier 1 (map): directory tree to depth 3, README, and manifests (package.json, pubspec.yaml,
requirements.txt, pyproject.toml, go.mod, pom.xml, build.gradle, Cargo.toml, composer.json,
Dockerfile, docker-compose*, CI files). List languages, frameworks, libraries, services.

Tier 2 (ownership): if it's a git repo, for each owner email:
  git -C {path} log --author="<email>" --no-merges --name-only --format= | sort | uniq -c | sort -rn | head -150
  git -C {path} log --no-merges --format='%ae' | sort | uniq -c | sort -rn
Work out the owner's share (commits and files) and which areas are theirs. If there's no git
history, treat the owner's claims as the guide to which areas are theirs and say so.

Tier 3 (deep read): read the owner's files and the areas their claims mention: entry points,
core modules, the parts that show real engineering. Prefer depth on 10–25 key files over skimming.

Tier 4 (assess): what the code shows about the owner, only for code they wrote:
architecture and layering, state management, data and APIs, integrations, tests, CI/CD,
error handling, performance or security work, scale.

Reconcile every claim and every finding:
  verified        claimed and seen in the owner's code
  said_not_seen   claimed but not found here (it may be elsewhere; don't judge)
  seen_not_said   found in code but not claimed AND not clearly written by the owner
Something the owner clearly wrote but didn't mention is verified (note "found in code").
If the owner wrote all or nearly all of the commits (sole author), everything found in the
code is theirs: use verified, never seen_not_said. seen_not_said is only for code that git
shows someone else wrote.

Levels, from evidence only:
  used       appears in the owner's code in a simple way
  built      the owner implemented a meaningful feature with it
  designed   the owner made structural decisions with it (architecture, patterns, abstractions)

Highlights: 2–5 concrete things the owner built, each one line, each with evidence paths.
Numbers only if they're in the code, README or docs, or in the owner's claims. Never estimate.

Write {slug}.md (human-readable, English):
  # {Project name}
  One-paragraph summary of what the project is.
  ## What the owner did
  ## Stack
  ## Evidence-backed highlights
  ## Notes (no git history, mixed authorship, anything uncertain)

Write {slug}.json exactly in this shape:
{
  "project": "{slug}",
  "name": "",
  "head": "<git HEAD sha or null>",
  "summary": "",
  "owner_share": "e.g. 64 of 70 commits; 112 of 130 source files",
  "role": "frontend|backend|full-stack|mobile|ai|data|devops|other",
  "items": [
    {"skill": "Flutter", "category": "language|framework|library|tool|platform|practice|domain",
     "status": "verified|said_not_seen|seen_not_said", "level": "used|built|designed",
     "evidence": ["lib/main.dart"], "claim": "text of the owner's claim, if any", "note": ""}
  ],
  "highlights": [{"text": "", "evidence": [""], "metric": null}]
}
Use canonical skill names (e.g. "PostgreSQL", "React", "REST APIs", "Riverpod").
```

## Merging into the evidence ledger

`scripts/ledger.py merge` does this; never merge by hand. The rules it follows:

`profile/evidence_ledger.json`:

```json
{
  "skills": {
    "Flutter": {"status": "verified", "level": "designed", "category": "framework",
                "projects": ["recipe-app-flutter"], "evidence": ["recipe-app-flutter:lib/main.dart"]}
  },
  "highlights": [{"project": "recipe-app-flutter", "text": "", "evidence": [], "metric": null}],
  "updated_at": ""
}
```

Merge rules:
- A skill verified in any project is `verified`. Its level is the highest level seen.
- After the user answers reconciliation questions: `said_not_seen` + yes → `user_attested`; `seen_not_said` + yes → `verified`; any no → `rejected`.
- Skills from experience claims (work at a company, no code here) are `user_attested`.
- `rejected` skills stay in the file so they are never asked about again, and are never used.

Only `verified` and `user_attested` skills may appear anywhere outside the workspace.
