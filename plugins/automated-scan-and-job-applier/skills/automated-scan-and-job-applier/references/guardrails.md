# Guardrails, and why each one exists

These are what make an unattended job applier something a person can trust and an employer won't resent.
Keep them on. If someone asks to remove one, explain the risk and offer the legitimate alternative.

| Guardrail | Where it lives | Why |
|---|---|---|
| Resume content only from the bullet bank; numbers can't change; unfamiliar skills or domains rejected; fallback to approved wording | `tailor.py` | Invented claims surface in interviews and background checks and can cost an offer. |
| Titles, companies, dates and education always come from `master.json` | `tailor.py` | These are verifiable facts. |
| Required question not covered by the profile → the person answers it | `answer.py`, worker | Guessing a fact on an application is misrepresentation. |
| Essays may only use numbers that appear in the profile | `answer.py` | Same reason as above. |
| Submission off by default; per-site opt-in (`live_ats`) | `config.json`, worker | The person should see dry runs before anything is sent in their name. |
| CAPTCHA, "verify you're human", or refused account sign-up → stop and hand off | fillers, worker | These are explicit humans-only checks. Defeating them is deceptive and can get the candidate blacklisted. |
| No stealth plugins, fingerprint spoofing, IP rotation, CAPTCHA services, or switching clients after a block | everywhere | Same reason. A blocked scanner waits; it doesn't disguise itself. |
| Honest User-Agent, slow scanners, stop for the hour on HTTP 429 / Signal Sciences 406 | scanners, `jobsrc.py` | Public job APIs are shared infrastructure; hammering them gets everyone blocked. |
| Daily cap, ≤2 roles per company per 30 days, no re-applying to a re-posted role | worker | Mass-applying hurts the candidate's reputation with recruiters and floods hiring teams. |
| Fit threshold enforced in code, not only by the model | `tailor.py` | Keeps applications to roles the person could realistically get. |
| Secrets outside the workspace (Keychain / env / 0600 file) | `core.py` | The workspace holds applications and logs that may be shared for debugging. |
| Reading the inbox only for verification codes and confirmations | `mailcheck.py` | Minimum necessary access to the person's email. |

## Things this skill deliberately does not do
- Log in to LinkedIn, Indeed or other job boards, or automate "Easy Apply". Their terms forbid it, and
  accounts get banned.
- Solve or outsource CAPTCHAs, or work around bot protection or rate limits.
- Create accounts on Workday sites (Workday refuses automated sign-ups; those jobs go to the person).
- Apply to roles the profile says to skip (wrong location, level, clearance, time zone) to "increase volume".

## The person's responsibilities (say this during setup)
They're responsible for complying with each site's terms of use, for the truth of their profile, and for the
applications sent in their name. They can pause everything with `python3 -I ~/job-applier/schedule.py remove`.
