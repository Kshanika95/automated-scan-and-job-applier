# Operating the job applier

## Daily rhythm
- **Every hour (minute 0):** `run.sh` scans (career-ops for Greenhouse/Lever/Ashby, the Workday scanner, Indeed
  every 3 hours if enabled), queues new matches, then the worker processes the queue until minute 55, and an ntfy
  notification summarizes the run ("Applied this run: 2 · today: 5/20 … for you to submit today: 3").
- **Evening (`report_hour`, default 9 PM):** `daily_report.py` emails what was applied since the last report (with
  each tailored resume), what needs the person, what was skipped and why, and what's still queued.
- **Five minutes later:** `manual_emails.py` sends one email per job that needs the person: the link, the reason,
  the tailored resume, and every answer for that form, with the questions only they can answer flagged.
- **Monthly (1st, 10 AM):** a reminder to review the profile and master resume.

## Commands (WORKSPACE = ~/job-applier by default)
| Task | Command |
|---|---|
| Health check | `python3 -I WORKSPACE/doctor.py` |
| One full run now | `zsh WORKSPACE/run.sh` |
| Process the queue only | `python3 -I WORKSPACE/apply_worker.py --take-lock --budget 1200` |
| One job, never submit | `python3 -I WORKSPACE/apply_worker.py --url URL --dry` |
| Rebuild the master PDF | `python3 -I WORKSPACE/resume/build_resume.py WORKSPACE/resume/master.json "WORKSPACE/resume/out/<Name> Resume.pdf"` |
| Regenerate scanner filters after editing search.json | `node WORKSPACE/mkportals.mjs` |
| Look at a form's fields | `node WORKSPACE/apply/inspect.mjs URL out.json shot.png` |
| Backfill older postings once | `cd WORKSPACE/career-ops && node scan-ats-full.mjs --since 21 --ats greenhouse,lever,ashby > WORKSPACE/logs/backfill-<name>.log` (picked up by the next run; run it at most once a day, because big scans trip rate limits) |
| Preview tonight's emails | `python3 -I WORKSPACE/daily_report.py --dry` · `python3 -I WORKSPACE/manual_emails.py --dry` |
| Schedule on / off | `python3 -I WORKSPACE/schedule.py install` · `… remove` |

## Job statuses (`state/jobs.jsonl`, one JSON object per line)
| Status | Meaning |
|---|---|
| `queued` | waiting for the worker (also used for retry-later cases like a site rate limit) |
| `applied` | submitted; `evidence` is the confirmation screenshot |
| `manual` | needs the person; `reason` and `open_questions` say why |
| `dry_run_ok` | filled completely, but submission is off for that site |
| `skipped` | weak fit, closed, duplicate, or outside the tracks (see `reason`) |
| `failed` | worker error after retries |

To re-run a job after fixing the profile, set its `status` back to `"queued"` (and clear `open_questions`). Do this
with a small Python edit, between runs (the worker holds `state/run.lock` while it runs).

## Answering "how many applied vs. how many need me?"
```bash
python3 -I - <<'EOF'
import json, collections
J=[json.loads(l) for l in open('WORKSPACE/state/jobs.jsonl')]
print(collections.Counter(j['status'] for j in J))
for j in J:
    if j['status'] in ('applied','manual'): print(j['status'], j.get('company_display') or j['company'], '|', j['title'], '|', j.get('reason',''))
EOF
```
Check claimed applications against confirmation emails (subjects like "Thank you for applying to …") before
reporting them.

## Per-application folder
`applications/<date>-<company>-<title>/` holds `posting.json` (description + form schema), `tailor.json` (fit
score, reasons, layout notes), the tailored resume PDF, `answers.json`, `plan.json`, `result.json` (filler log) and
screenshots (`filled.png`, `after-submit.png`, `code-requested.png`).
