# Setup

## Contents
- Prerequisites
- Install / upgrade
- Email (app password)
- Phone notifications (ntfy)
- Indeed (optional)
- Browser notes
- The workspace layout

## Prerequisites
| Need | Why | Check |
|---|---|---|
| macOS or Linux, a machine that stays on | the hourly schedule runs locally | — |
| Claude Code, logged in | `claude -p` does fit checks, tailoring and form answers on the person's own plan | `claude --version` |
| Python 3.9+ | the worker, filters, email | `python3 --version` |
| Node.js 18+ and npm | Playwright browser automation and the career-ops scanner | `node --version` |
| git | fetches the career-ops scanner | `git --version` |
| A mailbox with IMAP/SMTP (Gmail works well) | sends reports; reads verification codes and confirmations | — |

Usage: each application takes about 2-3 Claude calls (more on big forms). A heavy day uses a fair share of a
Pro plan; the worker pauses cleanly and says so in the notification if the limit is reached.

## Install / upgrade
```bash
zsh <skill>/scripts/install.sh ~/job-applier
```
Re-running upgrades the scripts and keeps `config.json`, `search.json`, `facts.json`, `profile.md`,
`resume/*.json`, `state/` and `logs/`. It also installs pypdf into `~/job-applier/pylib`, Playwright and
Chromium, and clones career-ops (MIT, https://github.com/career-ops-hq/career-ops) into
`~/job-applier/career-ops`. Only career-ops's zero-token scanner is used; its own philosophy is human-in-the-loop,
so don't present this project as part of it.

## Email (app password)
Gmail: turn on 2-step verification → Google Account → Security → App passwords → create one ("job applier").
Turn on IMAP in Gmail settings. Then store the 16-character password **outside the workspace**, one of:

- macOS Keychain (recommended on a Mac). The person types it into their own terminal, so it never appears in a
  chat log:
  ```bash
  security add-generic-password -a you@gmail.com -s job-applier-email -w
  ```
  (`-s` must match `config.json` → `secret_service`; `-a` must match `email`.)
- Environment variable `JOB_APPLIER_EMAIL_APP_PASSWORD` (cron/systemd).
- File `~/.config/job-applier/email_app_password` with `chmod 600`.

Test: `python3 -I ~/job-applier/mailer.py` sends a test email; `python3 -I ~/job-applier/doctor.py` checks IMAP.
Other providers: set `imap_host`, `smtp_host`, `smtp_port` in `config.json`.

## Phone notifications (ntfy)
Install the ntfy app, subscribe to a long random topic (e.g. `job-applier-` + 16 random characters: anyone
who knows the topic can read it), and put it in `config.json` → `ntfy_topic`. Each run then sends one short
"run OK" summary; failures arrive as high priority.

## Indeed (optional)
Indeed isn't scraped and its login is never automated. If the person has the **Indeed connector** enabled in
their Claude account, set `"indeed": true`. Every 3 hours a headless Claude session searches Indeed through the
connector, and each new posting is matched to the employer's own Greenhouse/Lever/Ashby page so it can be
applied there. Postings that can't be matched go to the person's list with a tailored resume.

## Browser notes
- Playwright's bundled Chromium is used headless. Nothing is added to hide automation.
- Older macOS versions may not be supported by the newest Playwright browsers. Then set `config.json` →
  `chrome_path` (or env `CHROME_PATH`) to an existing Chrome/Chromium/Chrome-for-Testing binary.
- Fonts: the resume looks for Aptos or Calibri, then falls back to common sans-serif fonts. Set
  `resume_font_body` / `resume_font_heading` in `config.json` to change them; the layout check adapts.

## The workspace layout
```
~/job-applier/
  config.json  search.json  facts.json  profile.md      ← the person's settings and truth
  resume/master.json  resume/bank.json  resume/out/      ← approved resume, bullet bank, master PDF
  state/jobs.jsonl                                       ← every job and its status
  applications/<date>-<company>-<title>/                 ← posting, tailored resume, answers, screenshots
  logs/                                                  ← run log, scan logs, Claude call log
  run.sh  apply_worker.py  …                             ← the code (refreshed by install.sh)
```
