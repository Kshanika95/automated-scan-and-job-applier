"""Apply worker: takes queued jobs (best first), checks fit, tailors the resume, answers the form, fills it,
submits only where config.live_ats allows, and records the outcome in state/jobs.jsonl.

  apply_worker.py                     # normal run (honours caps and the time budget)
  apply_worker.py --url URL --dry     # one queued job: fill everything, never submit (always safe to try)
  apply_worker.py --max 3 --budget 1200 --take-lock

Statuses: queued -> applied | manual (the person must finish it) | skipped (weak fit, closed, duplicate) | failed
"""
import json, re, sys, time, datetime, subprocess, html, traceback
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core, jobsrc, tailor, answer, llm

CFG = core.CONFIG
DAILY_CAP = CFG.get("daily_cap", 20)
PER_COMPANY_30D = CFG.get("per_company_30d", 2)
LIVE_ATS = set(CFG.get("live_ats", []))            # empty = dry runs only (the safe default)
FILLERS = {"greenhouse", "ashby", "lever"}
THROTTLED = set()
now = lambda: datetime.datetime.now().isoformat(timespec="seconds")
TODAY = datetime.date.today().isoformat()


def save(jobs):
    tmp = core.JOBS.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(j) + "\n" for j in jobs))
    tmp.replace(core.JOBS)


def update(url, **kw):
    """Re-read, patch one job, write back (a scan may have appended meanwhile)."""
    jobs = core.load_jobs()
    for j in jobs:
        if j["url"] == url:
            j.update(kw); j["updated_at"] = now()
    save(jobs)


def company_key(j):
    return re.sub(r"[^a-z0-9]", "", (j.get("company_display") or j["company"]).lower())


def title_key(j):
    t = re.sub(r"\(.*?\)", " ", j["title"].lower())
    t = re.sub(r"\bsr\.?\b", "senior", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def caps_ok(job, jobs):
    if sum(1 for j in jobs if j.get("status") == "applied" and j.get("applied_at", "").startswith(TODAY)) >= DAILY_CAP:
        return False, "daily cap reached"
    cut30 = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
    same = [j for j in jobs if j.get("status") == "applied" and company_key(j) == company_key(job) and j.get("applied_at", "") >= cut30]
    if len(same) >= PER_COMPANY_30D:
        return False, f"already applied to {len(same)} roles at this company in 30 days"
    cut60 = (datetime.datetime.now() - datetime.timedelta(days=60)).isoformat()
    if any(j.get("status") == "applied" and company_key(j) == company_key(job) and title_key(j) == title_key(job)
           and j.get("applied_at", "") >= cut60 and j["url"] != job["url"] for j in jobs):
        return False, "duplicate: already applied to this same role (re-posted)"
    return True, ""


def render_cover(text, outdir):
    paras = "".join(f"<p>{html.escape(p.strip())}</p>" for p in text.split("\n") if p.strip())
    F = core.FACTS
    contact = " | ".join(x for x in [F.get("location_text"), F.get("phone"), F.get("email"), F.get("website")] if x)
    doc = f"""<!doctype html><html><head><meta charset='utf-8'><style>
body {{ font-family: 'Aptos', 'Calibri', 'Inter', 'Helvetica Neue', Arial, sans-serif; font-size: 11.5pt; line-height: 1.45;
       margin: 0.6in 0.7in; color: #000; font-variant-ligatures: none; }}
h1 {{ color: {CFG.get('resume_accent', '#2F5496')}; font-weight: 400; letter-spacing: 1.5px; font-size: 22pt; margin: 0; }}
.c {{ color: {CFG.get('resume_accent', '#2F5496')}; font-size: 9.5pt; margin: 2px 0 22px; }} p {{ margin: 0 0 11px; }}</style></head><body>
<h1>{html.escape(core.candidate_name().upper())}</h1><div class='c'>{html.escape(contact)}</div>
<p>{datetime.date.today().strftime('%B %-d, %Y')}</p>{paras}</body></html>"""
    h = outdir / "cover.html"; h.write_text(doc)
    pdf = outdir / f"{core.candidate_name()} Cover Letter.pdf"
    subprocess.run([core.node(), str(core.HOME / "resume/render.mjs"), str(h), str(pdf)], check=True, capture_output=True)
    return str(pdf)


def run_filler(ats, plan, outdir, dry):
    pf, rf = outdir / "plan.json", outdir / "result.json"
    pf.write_text(json.dumps(plan, indent=1))
    if rf.exists():
        rf.unlink()
    cmd = [core.node(), str(core.HOME / f"apply/{ats}.mjs"), "--plan", str(pf), "--out", str(rf)] + (["--dry"] if dry else [])
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "filler timed out"}
    return json.loads(rf.read_text()) if rf.exists() else {"status": "error", "error": "filler produced no result"}


def outdir_for(job):
    slug = re.sub(r"[^\w-]+", "-", f"{job.get('company_display') or job['company']}-{job['title']}")[:70].strip("-")
    return core.APPS / f"{TODAY}-{slug}"


def ats_for(job):
    return jobsrc.ats_of(job["url"]) or {"greenhouse-full": "greenhouse", "ashby-full": "ashby", "lever-full": "lever"}.get(job.get("source"))


def confirmed_by_email(job, minutes=6):
    """Look for the employer's 'application received' email (used when no confirmation page was seen)."""
    try:
        import mailcheck
        name = (job.get("company_display") or job["company"]).lower().split()[0]
        end = time.time() + minutes * 60
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
        while time.time() < end:
            if any(name in (c["subject"] + " " + c["from"]).lower() for c in mailcheck.confirmations(since)):
                return True
            time.sleep(30)
    except Exception:
        pass
    return False


def process(job, dry=False):
    url, ats = job["url"], ats_for(job)
    outdir = outdir_for(job); outdir.mkdir(parents=True, exist_ok=True)
    try:
        src = jobsrc.fetch(job)
    except jobsrc.Closed as e:
        update(url, status="skipped", reason=f"posting closed ({e})"); return "closed"
    except jobsrc.RateLimited as e:
        update(url, status="queued", reason=f"site rate limit, retrying next run ({e})")
        THROTTLED.add(ats); return "throttled"
    except Exception as e:
        tries = job.get("tries", 0) + 1
        update(url, status="queued" if tries < 3 else "skipped", reason=f"could not read posting: {e}", tries=tries)
        return "failed"
    (outdir / "posting.json").write_text(json.dumps(src, indent=1))
    update(url, app_dir=str(outdir), apply_url=src.get("apply_url"))

    tres = tailor.tailor(job, src, outdir)                       # 1. fit + tailored resume
    fit, facts = tres["fit"], tres["facts"]
    job["company_display"] = facts.get("company_display_name") or job["company"]
    update(url, fit_score=fit["score"], fit_reason=fit["reason"][:400], company_display=job["company_display"])
    if fit["decision"] != "apply":
        update(url, status="skipped", reason="not a strong fit: " + (", ".join(fit["blockers"]) or fit["reason"][:200]))
        return "skipped"
    ok, why = caps_ok(job, core.load_jobs())
    if not ok:
        update(url, status="skipped" if why.startswith("duplicate") else "queued", reason=why); return "capped"
    pdf = tres["pdf"]
    update(url, resume_file=pdf, resume_tailored=tres.get("tailored"), tailor_notes=tres.get("notes", [])[:8])

    if ats not in FILLERS:
        why = {"indeed": "Indeed listing not found on a company application site (Indeed itself is never automated)",
               "workday": "Workday site: Workday refuses account sign-ups from automated browsers, so this one needs you"}.get(
            ats, f"{ats or 'this site'} applications aren't automated")
        update(url, status="manual", reason=why); return "manual"

    ans = answer.answer_form(job, src, tres, pdf)                # 2. answers
    (outdir / "answers.json").write_text(json.dumps(ans, indent=1))
    est = [n for n in ans.get("notes", []) if re.search(r"(?i)estimate", n)]
    if est:
        update(url, salary_note="; ".join(est)[:300])
    if ans["unknown_required"]:
        update(url, status="manual", reason="the form asks something the profile doesn't answer",
               open_questions=ans["unknown_required"])
        return "manual"
    cover_pdf = render_cover(ans["cover_letter"], outdir) if ans.get("cover_letter") else None

    plan = {"apply_url": src["apply_url"], "alt_apply_url": src.get("alt_apply_url"), "fields": src["fields"],   # 3. fill (+ submit)
            "answers": ans["answers"], "resume": pdf, "cover_letter_pdf": cover_pdf, "cover_letter_text": ans.get("cover_letter"),
            "dir": str(outdir), "company": job["company_display"], "title": src.get("title"),
            "education": core.FACTS.get("education", []),
            "facts": {k: core.FACTS.get(k) for k in ("location_search", "location_text", "city", "state", "state_code", "phone_country")}}
    res = run_filler(ats, plan, outdir, dry or ats not in LIVE_ATS)
    return finish(job, url, res, ats, dry or ats not in LIVE_ATS)


def finish(job, url, res, ats, dry):
    st, shots = res.get("status"), res.get("screenshots", [])
    ev = shots[-1] if shots else None
    if st == "unknown" and not dry and confirmed_by_email(job):
        st = "submitted"
    if st == "submitted":
        update(url, status="applied", applied_at=now(), evidence=ev, ats=ats); return "applied"
    if st == "dry_run_ok":
        update(url, status="dry_run_ok", dry_run_ok_at=now(), evidence=ev,
               reason="filled completely in a dry run; submission for this site is off (config.live_ats)")
        return "dry_ok"
    if st == "closed":
        update(url, status="skipped", reason="posting closed"); return "closed"
    reason = {"captcha": "the site showed a CAPTCHA",
              "code_not_received": "the site's email verification code never arrived",
              "code_failed": "the site's email verification code was not accepted",
              "fill_incomplete": "some fields couldn't be filled automatically: " + ", ".join((res.get("failed") or []) + (res.get("empty_required") or []))[:200],
              "validation_error": "the site rejected the submission (see the screenshot)",
              "spam_flagged": "the site flagged the automated submission",
              "unknown": "submitted, but no confirmation page or email appeared"}.get(st, f"automation error: {res.get('error', '')[:150]}")
    tries = job.get("tries", 0) + 1
    if st == "error" and tries < 2:
        update(url, status="queued", reason=reason, tries=tries); return "retry"
    update(url, status="manual", reason=reason, evidence=ev, tries=tries); return "manual"


def main():
    a = sys.argv[1:]
    dry = "--dry" in a
    lock = core.STATE / "run.lock"
    if "--take-lock" in a:
        try:
            lock.mkdir()
        except FileExistsError:
            print("another run holds the lock"); return
        import atexit
        atexit.register(lambda: lock.rmdir() if lock.exists() else None)
    if "--url" in a:
        url = a[a.index("--url") + 1]
        job = next((j for j in core.load_jobs() if j["url"] == url), None)
        print(process(job, dry=dry) if job else "not in queue"); return
    budget = int(a[a.index("--budget") + 1]) if "--budget" in a else 2400
    mx = int(a[a.index("--max") + 1]) if "--max" in a else 999
    t0, results = time.time(), {}
    recent = (datetime.datetime.now() - datetime.timedelta(minutes=50)).isoformat()
    while time.time() - t0 < budget and sum(results.values()) < mx:
        jobs = core.load_jobs()
        q = [j for j in jobs if j.get("status") == "queued" and ats_for(j) not in THROTTLED
             and not j.get("reason", "").startswith(("daily cap", "already applied"))
             and not (j.get("reason", "").startswith("could not read posting") and j.get("updated_at", "") > recent)]

        def newest(j):
            d = re.sub(r"\D", "", j.get("posted") or "")[:8]
            return -int(d) if d else 0
        q.sort(key=lambda j: (j.get("priority", 9), newest(j)))
        if not q:
            break
        job = q[0]
        ok, why = caps_ok(job, jobs)
        if not ok and why == "daily cap reached":
            break
        try:
            r = process(job, dry=dry)
        except llm.LLMError as e:
            update(job["url"], reason=f"Claude usage limit or error: {str(e)[:120]}")
            results["llm_error"] = results.get("llm_error", 0) + 1
            break
        except Exception as e:
            traceback.print_exc()
            update(job["url"], status="failed", reason=f"worker error: {e}"[:200], tries=job.get("tries", 0) + 1)
            r = "failed"
        results[r] = results.get(r, 0) + 1
    print(json.dumps(results))


if __name__ == "__main__":
    main()
