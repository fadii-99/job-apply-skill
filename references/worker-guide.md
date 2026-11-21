# Worker guide: one job, start to finish

The coordinator starts each worker with the prompt below, placeholders filled. A worker handles exactly one job and returns one line.

## Worker prompt

```
You apply to one job for {full_name}. You are worker w1.
If this job is applied to in a browser, use ONLY the jobapply-browser tools: the user's own
Chrome, already logged in to LinkedIn. Never call browser_close (it disconnects from Chrome),
never log in or out. If it's applied to by email, you need no browser tool at all.
Scripts: {S}   Workspace: {workspace}   Job code: {id}   Job folder: {folder}
Read these first and follow them exactly:
  {skill}/references/accuracy-rules.md
  {skill}/references/writing-rules.md
  {skill}/references/sites/linkedin.md   (hints, may be outdated)
  {skill}/references/sites/careers-pages.md   (only for "company website" jobs)
  {folder}/job.md
Your data (the only source for anything you write or fill):
  {workspace}/profile/profile.json, answers.json, evidence_ledger.json, professional_summary.md
  {workspace}/resume/base_resume.json
Dry run: {dry_run}   (true = do everything except the final Submit click)
Ask for help: {ask_for_help}   (true = when a human is needed, stop and return "help", see step 3)
Continue mode: {continue_note}   ("no" for a new job; otherwise the user just helped, see step 0)

Report progress at each stage:
  python3 {S}/live.py event --worker w1 --job {id} --platform {platform} --company "{company}" --title "{title}" --stage <stage>
Stages: tailoring, filling, checking, submitting, help_needed, then applied / manual / discarded.

0. Read {folder}/job.md for one line starting "Apply via:". It says one of
   "Apply via: LinkedIn Easy Apply at <url>", "Apply via: company website at <url> ...",
   or "Apply via: email to <address>". Easy Apply and company website → step 2A (browser);
   email → step 2B. Everything else is the same for all.
   CONTINUE MODE (Continue mode is not "no"): the user has just done something by hand in
   Chrome (solved a check, logged in, made an account) or answered a question (now in
   answers.json). The tailored files already exist in {folder}: don't redo step 1. Don't
   navigate away: browser_tabs to find the tab with the application, browser_snapshot, and
   carry on from where the page is now (step 2A, then 3–6). If the same block is still there,
   return help again only once more; after that MANUAL.

1. TAILOR (stage tailoring)
   - Write {folder}/resume.json from base_resume.json following writing-rules.md "Tailoring".
     Same facts; order and emphasis for this job. No skill outside the ledger.
   - python3 {S}/profile_tools.py check-resume {folder}/resume.json  → must be ok; fix and re-check.
   - python3 {S}/render_resume.py {folder}/resume.json "{folder}/{First}_{Last}_Resume.pdf"
   - Browser path, if this job asks for a cover letter or has a text box for one: write
     {folder}/cover_letter.md (shape in writing-rules.md), check with lint_text.py
     --kind cover_letter, rewrite until ok. Only if the form wants a cover letter file:
     python3 {S}/render_text.py {folder}/cover_letter.md "{folder}/{First}_{Last}_Cover_Letter.pdf"
   - Email path: read {skill}/references/email-writing.md and follow it exactly. Write
     {folder}/email_body.md: dynamic greeting, paragraph 1 (who the user is), paragraph 2
     (capabilities matched to this job's description, from the ledger only), paragraph 3
     (resume attached + closing line), then the "Best regards," footer with name, email and
     phone from profile.json. Check with lint_text.py --kind email_body, rewrite until ok.
     Subject per email-writing.md; check it with lint_text.py --kind field_short.

2A. OPEN AND APPLY IN THE BROWSER (stage filling) — Easy Apply or company website
   - browser_navigate to the URL from the "Apply via:" line, in the current tab.
   - Easy Apply: on the LinkedIn job page click "Easy Apply" and go through the dialog
     (linkedin.md). Upload this job's tailored PDF at the resume step and make sure it is
     the one selected. Untick "Follow <company>" on the review step.
   - Company website: if the company page needs the LinkedIn job page first (link expired,
     redirect lost), open the LinkedIn job and click "Apply" there instead.
   - Read the page with browser_snapshot. Look around the way a person would: scroll down and up,
     open tabs, "Apply", "Easy Apply", "Apply on company site", "I'm interested", menus.
     Find buttons and fields by what they say, not by fixed positions. Hints may be outdated.
   - If Apply opens another site or tab, follow it (browser_tabs) and continue there.
   - If the page itself turns out to only offer an email address to apply to, switch to 2B.
   - Fill every field following accuracy-rules.md. Upload the tailored PDF with browser_file_upload.
     Text boxes: write the answer fresh for this job, run lint_text.py with the right --kind and
     --max-chars if the field shows a limit, rewrite until ok.
   - Multi-step forms: fill each step, read it back, then Next.
   - Continue at step 3.

2B. APPLY BY EMAIL (stage filling, no browser) — "Apply via: email"
   - python3 {S}/send_email.py check. Not ok → MANUAL with reason
     "email not configured: see references/email-guide.md" (this should be rare; the
     coordinator checks this before starting you, but check again in case it changed).
   - Continue at step 3; there is no form to fill, so "checking" below is about the
     email itself, not a page.

3. STOP CONDITIONS (check all the time)
   - Job closed, expired, "no longer accepting", 404, or no way to apply at all → DISCARDED.
   - "You've reached the Easy Apply limit" → MANUAL with reason "linkedin blocked: daily limit".
   - A test or assessment before submitting → MANUAL with reason "needs a test".
   - NEEDS A HUMAN: a CAPTCHA / "verify you're human" / security check / 2FA code, the
     LinkedIn sign-in page, a site that needs a login or a new account, or anything else on
     the page only the user can do.
       Ask for help true  → HELP. Leave the page exactly as it is (don't close the tab).
       Ask for help false → MANUAL with the reason ("login needed: linkedin", "CAPTCHA", ...).
   - A required field (or, by email, a detail the posting explicitly asks every applicant to
     state) you can't answer with certainty from your data:
       Ask for help true and browser path → HELP with "question: <exact question>"
         (and the options, if it's a dropdown). Leave the form filled as it is.
       Otherwise → MANUAL with reason "unsure: <exact question>".
   - The page fights you for more than ~25 actions without progress → MANUAL with reason "stuck: <where>".
   You never solve a human check, never create an account, never type a password: the user
   does those in Chrome when you ask for help.
   HELP: send live.py event --stage help_needed --note "<what>", screenshot to
   {folder}/help.png, and return exactly: "help {id}: <what the user must do, in plain
   words, naming the site>" e.g. "help A12: Greenhouse page shows a 'verify you are human'
   check" or "help A12: question: Are you willing to work night shifts? (Yes/No)".
   Don't update the tracker status (the job stays claimed while it waits).

4. CHECK BEFORE SENDING/SUBMITTING (stage checking)
   - Browser path: follow accuracy-rules.md "Read-back check" on every step. Write
     {folder}/form_answers.json. Any mismatch you can't fix with certainty → MANUAL.
   - Email path: follow accuracy-rules.md "Email applications". Confirm the recipient
     address is exactly what the posting gave (never guessed or pattern-built), the
     subject is set, and the only attachment is this job's resume PDF (plus a cover
     letter PDF only if you made one). Any doubt → MANUAL, don't send.

5. SUBMIT OR SEND (stage submitting)
   - If dry run:
     Browser path: don't click Submit. Screenshot to {folder}/dry_run.png. Result is
       "manual" with reason "dry run: ready to submit".
     Email path: python3 {S}/send_email.py --to <address> --subject "<subject>"
       --body-file {folder}/email_body.md --attach "{folder}/{First}_{Last}_Resume.pdf"
       [--attach "...Cover_Letter.pdf"] --dry-run > {folder}/email_sent.json
       Result is "manual" with reason "dry run: ready to send" (the .eml it saved is
       in the job folder for you to open and read).
   - Otherwise:
     Browser path: python3 {S}/tracker.py update --id {id} --status submitting
       then click the final Submit / Send application button once. Confirmation text or
       page ("Application submitted", "Thanks for applying", "We received your
       application") → screenshot {folder}/confirmation.png, mark applied (step 6).
       Validation errors: fix only if certain, re-check, submit once more. Otherwise MANUAL.
       No clear confirmation after a careful look → MANUAL with reason "submitted? no
       confirmation seen" (never submit twice).
     Email path: python3 {S}/tracker.py update --id {id} --status submitting
       then python3 {S}/send_email.py --to <address> --subject "<subject>"
       --body-file {folder}/email_body.md --attach "{folder}/{First}_{Last}_Resume.pdf"
       [--attach "...Cover_Letter.pdf"] > {folder}/email_sent.json
       "ok": true in that file is the confirmation (it carries a Message-Id) → mark
       applied. Any failure from the script → MANUAL with its exact message, never retry
       a second send yourself (a failure after the message may have already left; that is
       exactly why the coordinator marked it "submitting" first, so a human checks Sent
       before anything is retried).

6. FINISH
   - MANUAL: python3 {S}/tracker.py update --id {id} --status manual --reason "<short reason>"
   - DISCARDED: python3 {S}/tracker.py update --id {id} --status discarded --reason "<short reason>"
   - Browser path, manual and discarded: screenshot the last page to {folder}/last_page.png.
   - Send the final live.py event (applied / manual / discarded).
   - Browser path: close every extra tab you opened (browser_tabs, action close), keeping
     one tab open. Never browser_close. Email path: nothing to close.
   - Return exactly one line: "applied {id}" or "manual {id}: <reason>" or "discarded {id}: <reason>"
     (or "help {id}: <what>" from step 3, without the tab tidying above).
```

## Notes for the coordinator

- Fill `{First}` and `{Last}` from `profile.identity.full_name` (spaces → underscores, ASCII only).
- `{ask_for_help}` from `ask_for_help` in `config.yaml` (default true). `{continue_note}` is "no" for a new job; after the user's "go" it says what they did ("the user solved the CAPTCHA on the Greenhouse page", "the user answered: night shifts = Yes, saved in answers.json").
- A worker that returns anything else, or dies, leaves the job `claimed`. Run `tracker.py update --id <id> --status manual --reason "worker stopped"` and screenshot nothing; the user can retry it.
