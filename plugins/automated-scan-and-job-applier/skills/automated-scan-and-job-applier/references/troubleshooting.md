# Troubleshooting and what each site actually does

## Contents
- What to expect per site
- Common problems
- Debugging a single form

## What to expect per site (observed in real use)
| Site | Automated submit | Notes |
|---|---|---|
| **Greenhouse** (`job-boards.greenhouse.io`) | Works reliably | After Submit, it often emails an 8-character **security code** and asks for it. The filler reads it from the person's inbox (matching the company name in the subject) and enters it. Code extraction requires at least two digits, so words like "resubmit" are never mistaken for the code. Its job-board API rate-limits heavy scanning with HTTP **406** plus an `x-sigsci-tags: …rate-limit…` header; treat that as "retry next run". Some boards host the form only on the embed URL `job-boards.greenhouse.io/embed/job_app?for=<board>&token=<id>`. |
| **Ashby** (`jobs.ashbyhq.com`) | Sometimes | Uses reCAPTCHA Enterprise. Many organizations show an **image challenge** to automated browsers, so those jobs go to the person, already filled in and with the answers emailed. Others submit cleanly. The form schema comes from the public GraphQL endpoint (`ApiJobPosting`). |
| **Lever** (`jobs.lever.co`) | Rarely | hCaptcha usually challenges automated submissions, so expect these to go to the person. Cookie banners can cover the Submit button; the filler dismisses them. |
| **Workday** (`*.myworkdayjobs.com`) | No | Applying needs an employer account, and Workday silently refuses sign-ups from automated browsers (it redirects to the login page and no account is created). Workday jobs therefore go to the person with a tailored resume. Its job search API is rate-limited: the scanner uses 2 workers, pauses between requests, and stops for the hour on the first HTTP 429. **Never** speed it up or switch HTTP clients after a block; the block will lift. |
| **Indeed** | Never directly | Discovery only, through the Indeed connector in the person's Claude account. The connector rate-limits frequent sessions, so the scan runs every 3 hours and retries once. Postings are matched to the employer's own ATS when possible. |

## Common problems
| Symptom | Likely cause | Fix |
|---|---|---|
| Notification says "run had a problem", or nothing arrives | the scheduled shell can't find `python3`/`node`/`claude` | set `node`/`claude` paths in `config.json`; check `logs/run.err.log`; run `zsh run.sh` by hand |
| "previous run still applying" every hour | a run hangs | check `logs/worker.err`; a lock older than 2 hours is cleared automatically |
| Lots of `manual` with "the form asks something the profile doesn't answer" | missing facts (address, ZIP, middle name, pronouns, portfolio file) | ask the person once, add to `facts.json`, re-queue those jobs |
| Tailored resumes fall back to the master | the layout check keeps failing (overflow/underfill/orphans) | look at `tailor.json` notes; adjust bank `min`/`max`, bullet lengths, or `resume_pages` |
| Summary always "kept from master" | proposed summaries use numbers or words not in the profile | read the note in `tailor.json`; add the real wording to the profile if it's true |
| Fit scores feel too strict or too loose | `min_fit` / `fit_rules` | tune `search.json`, re-queue skipped jobs if needed |
| "Claude usage limit hit, applying paused" | plan limit reached | it resumes on the next run; reduce volume (`daily_cap`) or upgrade the plan |
| A company re-posts the same role | different URL, same title | handled: same company + same title within 60 days is skipped as a duplicate |
| Scanner returns 429/406 for hours | rate limit after too many requests | wait it out; run big backfills at most once a day |

## Debugging a single form
1. `node WORKSPACE/apply/inspect.mjs URL /tmp/form.json /tmp/form.png`: every control with its label and type.
2. `python3 -I WORKSPACE/apply_worker.py --url URL --dry` (the job must be in `state/jobs.jsonl`).
3. Open the folder in `applications/`: `result.json` → `log` shows each step; `filled.png` shows the form state.
4. Fix the rule in `answer.py` (deterministic answers) or the filler (`apply/<site>.mjs`), never by special-casing
   one company. Then re-run the dry run.
