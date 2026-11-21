# LinkedIn hints (may be outdated; always read the page)

The browser is the user's own Chrome, already logged in to LinkedIn. Never log in or out yourself.

## Searching

- Fastest start is a search URL, then check the page really shows those filters:
  `https://www.linkedin.com/jobs/search/?keywords=<role>&location=<place>&f_TPR=r604800&sortBy=DD`
  - `f_TPR=r604800` = past week (`r86400` = past 24 hours).
  - `f_WT=` work mode: `1` on-site, `2` remote, `3` hybrid (several: `2%2C3`).
  - `f_AL=true` = Easy Apply jobs only. Don't add it by default: jobs that send you to the company site are wanted too.
  - `sortBy=DD` = newest first.
  - If the URL filters don't seem to apply, use the filter bar on the page ("Date posted", "Remote", "Easy Apply").
- Results are a list on the left (about 25 per page) and the selected job's details on the right. The list loads more cards as it scrolls; page numbers are at the bottom.
- Each job has a numeric id: `/jobs/view/<id>/`, or `currentJobId=<id>` in a search URL. Record the job as `https://www.linkedin.com/jobs/view/<id>/` and `job_id` = that id.
- Skip cards marked "Applied", "Promoted" by a company you can't verify, or "No longer accepting applications".
- In the details pane: "Easy Apply" button (LinkedIn's own form) or "Apply" with an arrow icon (company website). Read "About the job" fully, and look for an email address in it ("send your CV to ...").

## Easy Apply (LinkedIn's own form)

A dialog with several steps and a progress bar. Typical steps:
1. **Contact info:** email (a dropdown of the user's LinkedIn emails: choose `profile.identity.email` if listed), phone country code and number. Check both against the profile.
2. **Resume:** "Upload resume" and upload this job's tailored PDF with `browser_file_upload`. Then make sure that new file is the one selected (LinkedIn keeps older resumes and may pre-select one).
3. **Additional questions:** years of experience with a skill (a whole number), yes/no, dropdowns, short text. Follow accuracy-rules.md. A number field wants digits only.
4. **Review:** read every step back. Untick "Follow <company>" at the bottom. Then "Submit application".
- Success: "Your application was sent to <company>" (or "Application submitted"). Screenshot, then "Done".
- Pre-filled answers from earlier applications: read each one and correct it against the profile and answers.json.
- Closing the dialog asks "Save this application?" → choose "Discard" when the job goes to the manual list.
- "You've reached the Easy Apply limit for today" → stop all LinkedIn Easy Apply for today (manual reason "LinkedIn daily limit").

## Apply on the company website

- "Apply" opens a new tab (sometimes after a "Continue to apply" / "Share your profile?" prompt: choose to continue without sharing extras). Switch to the new tab with `browser_tabs` and continue there. Hints: careers-pages.md.
- If the company site wants a new account or a password → manual list (never create accounts).

## Profile settings used by Easy Apply

- Resumes Easy Apply offers are at `https://www.linkedin.com/jobs/application-settings/` (upload / manage resumes).
- The public profile (`https://www.linkedin.com/in/me/`) holds location and headline, which recruiters see with every Easy Apply.

## Signs of trouble

- "Security verification", "Let's do a quick security check", a CAPTCHA, "unusual activity", or the sign-in page → stop and report (help is asked from the user, who solves it in Chrome). Never try to pass it yourself.
- LinkedIn's terms prohibit automated access. Stay under the daily limit, one application at a time, with pauses.
