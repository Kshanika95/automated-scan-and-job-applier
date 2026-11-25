---
name: automated-scan-and-job-applier
description: Set up and run a personal job-search autopilot that scans company job boards (Greenhouse, Lever, Ashby, Workday; Indeed through the Indeed connector) every hour, rejects weak fits, writes a truthful tailored resume for each strong fit, fills in the application form, and submits it where the site allows, with a daily email report and one email per job that needs the person (CAPTCHAs, questions only they can answer). Use this skill whenever someone wants to automate or speed up job applications, "auto-apply", "apply to jobs for me", set up hourly job scans or alerts, tailor resumes to job descriptions at scale, build a job-application tracker or pipeline, or keep a job hunt running in the background, even if they never say the word "skill". Also use it to check on, fix, extend or switch off an existing installation (run logs, "why wasn't this job applied to", "add Workday", "turn on submissions").
---

# Automated Scan and Job Applier

This skill installs a small system on the person's own computer that keeps their job search running:

```
every hour:  scan job boards → filter by their tracks and locations → fit check (Claude) → tailored resume
             → answer the form → fill it in a browser → submit (only on sites they switched on) → record proof
evening:     report email (applied, needs-you, skipped) + one email per job that needs them
```

The person's own Claude Code subscription does the thinking (`claude -p`), their own mailbox sends the
reports, and everything lives in one workspace folder (default `~/job-applier`). The code is in `scripts/`,
the starting files in `templates/`, and the details in `references/`.

## Ground rules (read these first; they are the reason this is safe to run unattended)

1. **Truth only.** Every resume line and form answer must come from the person's own profile. The tailoring code
   enforces it: bullets come from an approved bank, numbers can't change, unfamiliar skills or domains are
   rejected, and anything that fails falls back to approved wording. Never loosen these checks to "get more
   applications out". A fabricated claim can cost someone an offer or a job later.
2. **Humans-only checks stay human.** If a site shows a CAPTCHA, a "verify you're human" challenge, or blocks
   account sign-ups from automated browsers, the job goes to the person's list. Don't solve CAPTCHAs, use
   CAPTCHA services, add stealth plugins, spoof browser fingerprints, rotate IPs, or switch HTTP clients to
   get around a block or rate limit. Those checks are the employer saying "a person must do this step", and
   getting caught can get the candidate flagged by that employer. Reading a verification code from the person's
   own inbox (when they've agreed) is fine: it proves control of the email address, which is genuinely true.
3. **Unknown means ask, never guess.** A required question the profile can't answer (middle name, a self-rating,
   "years of X") sends the job to the person with that question listed. Add the answer to the profile once,
   and future forms fill themselves.
4. **Be a good citizen.** Keep the caps (`daily_cap`, `per_company_30d`), never apply twice to the same role,
   apply only above the fit threshold, scan politely, and stop for the hour on any rate limit.
5. **Consent before anything goes out.** Submission is off by default (`config.json` → `"live_ats": []`).
   Switch it on per site only after the person has seen dry runs and said yes. Creating employer accounts,
   reading their inbox for codes, and installing the schedule all need their explicit OK too.

See `references/guardrails.md` for the full list and the reasoning.

## Setting it up (walk the person through this in order)

### 1. Install
Run `zsh scripts/install.sh [WORKSPACE]` from this skill's folder (it copies the scripts, installs Playwright
and pypdf into the workspace, and fetches the MIT-licensed career-ops scanner). Tell the person where the
workspace is. Prerequisites and fixes: `references/setup.md`.

### 2. Build the profile: the most important step
Everything downstream is only as good as `profile.md`. Follow `references/profile-guide.md`:
- Collect their real material (resumes, past versions, cover letters, portfolio, LinkedIn text) and read it all.
- Draft `profile.md`: canonical titles and dates, approved bullets, metrics with the rules for using them,
  retired claims, education (only completed degrees), skills they actually have, case studies, search criteria.
- **Interview them about every conflict or gap**: which title is official, whether a metric is real, why there's
  a gap. Don't resolve contradictions yourself. Mark unresolved items ⚠️ and keep them out of resumes.
- Fill `facts.json` with their confirmed form answers: contact, address, work authorization and sponsorship,
  EEO choices ("decline" is always fine), start date, how they heard, previous employers.
- Write `resume/master.json` (their approved resume) and `resume/bank.json` (the bullet bank tailoring may
  choose from, with `master: true` on the default set and `forbidden_phrases` for rejected claims).
- Build the master PDF and show it to them:
  `python3 -I WORKSPACE/resume/build_resume.py WORKSPACE/resume/master.json "WORKSPACE/resume/out/<Name> Resume.pdf"`.
  It must pass the layout check at `config.resume_pages` (1 or 2 full pages). Iterate until they approve it.

### 3. Search criteria
Edit `search.json` with them: title tracks (regex, priority, `min_fit` 0-10), exclusions, locations
(onsite cities, remote countries), and `fit_rules` (plain-language hard blockers: levels, time zones,
clearances, skills they lack). Then run `node WORKSPACE/mkportals.mjs` to configure the scanner.

### 4. Email, notifications, schedule
- Email: an app password for their mailbox, stored outside the workspace (Keychain on macOS, an environment
  variable, or `~/.config/job-applier/email_app_password`). Steps in `references/setup.md`.
- Optional phone pings: an ntfy topic in `config.json`.
- `python3 -I WORKSPACE/doctor.py` must be all green before going further.

### 5. Dry runs, then go live
1. Run one scan: `zsh WORKSPACE/run.sh` (with `live_ats` empty this only fills forms).
2. Show the person 3-5 results from `WORKSPACE/applications/<date>-<company>-<title>/`: the tailored resume PDF,
   `answers.json`, and the `filled.png` screenshot of the completed form. Fix anything they dislike in the profile
   or rules, not by hand-editing outputs.
3. With their explicit OK, add sites to `live_ats` one at a time (e.g. `["greenhouse"]`), then
   `python3 -I WORKSPACE/schedule.py install`. Confirm the first live run in the logs and their inbox.

## Running and maintaining it

- Commands, logs, statuses and the daily rhythm: `references/operations.md`.
- Something failed, a site changed, or a rate limit hit: `references/troubleshooting.md`. It records what each
  ATS actually does (Greenhouse emails a security code; Ashby and Lever often show image CAPTCHAs to automated
  browsers; Workday refuses automated account sign-ups and rate-limits fast scanners).
- When the person answers a new question (e.g. their pronouns or a portfolio file), add it to `facts.json` or
  `profile.md`, then re-queue the affected jobs (`status` → `"queued"` in `state/jobs.jsonl`) instead of
  filling those forms by hand.
- Monthly: the reminder email prompts a profile review. Rebuild the master PDF after any change.

## Reporting results to the person

Lead with counts they care about: applied (with confirmation emails), waiting for them (by reason), skipped (by
reason). Name your own mistakes plainly, with the fix (e.g. a duplicate application). Never report an
application as submitted without a confirmation page or email.
