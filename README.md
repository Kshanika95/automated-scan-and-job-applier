# Automated Scan and Job Applier

A Claude Code skill that keeps your job search running in the background, **honestly**.

Every hour it scans company job boards, throws out roles that don't fit you, writes a resume tailored to each strong
match using only facts from your own profile, fills in the application, and submits it on the sites that allow
it. Every evening you get one email with everything it applied to (tailored resumes attached), plus one email per
job that needs you, with the link, the resume and every answer for that form ready to paste.

```
hourly:  scan Greenhouse · Lever · Ashby · Workday (· Indeed via connector)
           → filter by your tracks + locations → fit check (Claude) → tailored resume (2-page layout check)
           → answer the form (your confirmed facts first, Claude for the rest; never guesses)
           → fill in a browser → submit where you've switched it on → capture the confirmation
evening: report email + "apply manually" emails · ntfy ping after every run
```

## What to expect
| Site | Submits on its own? |
|---|---|
| Greenhouse | ✅ Yes, including the emailed security-code step (read from your inbox) |
| Ashby | ⚠️ Sometimes. Many employers show image CAPTCHAs to automated browsers, and those come to you pre-filled |
| Lever | ⚠️ Rarely (hCaptcha) |
| Workday | ❌ No. Workday refuses automated account sign-ups, so those come to you with a tailored resume |
| Indeed | Discovery only (through Claude's Indeed connector), matched to the employer's own site when possible |

In a first real week of use, about a third of strong-fit applications went out fully automatically. The rest
arrived as ready-to-paste emails that take about 2 minutes each.

## Guardrails (built in, on by default)
- **Truth only:** resume bullets come from an approved bank, numbers can't change, and unfamiliar skills and domains are
  rejected in code; anything doubtful falls back to approved wording.
- **Never guesses:** a required question your profile can't answer comes to you instead.
- **No CAPTCHA solving, no bot evasion, no stealth tricks**, an honest User-Agent, polite scanning that stops at
  rate limits.
- **Caps:** daily limit, at most 2 roles per company per 30 days, no re-applying to re-posted roles, fit
  thresholds enforced in code.
- **Dry runs first:** submission is off until you switch it on per site.

## Install
**As a plugin (recommended):**
```
/plugin marketplace add Kshanika95/automated-scan-and-job-applier
/plugin install automated-scan-and-job-applier@job-applier
```
**Or as a plain skill:** copy `plugins/automated-scan-and-job-applier/skills/automated-scan-and-job-applier` into
`~/.claude/skills/`.

Then open Claude Code and say something like:
> Set up the automated job applier for me. My resumes are in ~/Documents/resumes.

Claude installs the workspace (`~/job-applier`), builds your profile with you (it asks about anything unclear),
helps you write your search rules, sets up email and notifications, runs dry runs for you to review, and only then
schedules it.

### Requirements
macOS or Linux on a machine that stays on · Claude Code (logged in) · Python 3.9+ · Node.js 18+ · git · a mailbox with
IMAP/SMTP (a Gmail app password works well). Uses your own Claude plan: roughly 2-3 Claude calls per application.

## Privacy
Everything runs on your computer. Your profile and job data live in your workspace folder. Claude calls go
through your own Claude Code login. Your email app password is kept in the macOS Keychain, an environment
variable, or a private file, never in the workspace. Nothing is sent anywhere else except the job sites you
apply to and your own email and ntfy topic.

## Disclaimer
You're responsible for the applications sent in your name, for the truth of your profile, and for following each
website's terms of use. This project isn't affiliated with Greenhouse, Lever, Ashby, Workday, Indeed, LinkedIn or
career-ops. Use it to apply carefully to roles you want, not to spam employers.

## Credits
Job-board discovery uses the zero-token ATS scanner from [career-ops](https://github.com/career-ops-hq/career-ops)
(MIT), fetched at install time. career-ops itself is a human-in-the-loop tool and never submits applications. The
submission layer here is separate and adds the guardrails above.

## License
MIT. See [LICENSE](LICENSE).
