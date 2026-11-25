"""Daily report email (scheduled in the evening): what was applied since the last report, with each tailored
resume attached; what needs the person (each also arrives as its own email from manual_emails.py); what was skipped
and why; what is still queued; and run health.   Usage: daily_report.py [--dry]
"""
import datetime, html, pathlib, re, sys
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core, mailer

TODAY = datetime.date.today().isoformat()


def runs_since(since_dt):
    p = core.LOGS / "hourly.log"
    ok = bad = 0
    if p.exists():
        for l in p.open():
            try:
                t = datetime.datetime.strptime(l[:24], "%a %b %d %H:%M:%S %Y")
            except ValueError:
                continue
            if t >= since_dt:
                ok += " rc=0 " in l
                bad += (" rc=" in l and " rc=0 " not in l)
    return ok, bad


def name(j):
    return html.escape(j.get("company_display") or j["company"])


def link(j):
    return f"<a href='{html.escape(j.get('apply_url') or j['url'].split('#')[0])}'>{html.escape(j['title'])}</a>"


def table(rows, head):
    if not rows:
        return "<p style='color:#777'><i>None.</i></p>"
    return ("<table cellpadding=6 cellspacing=0 style='border-collapse:collapse;font-size:13px;border:1px solid #ddd'>"
            "<tr style='background:#f3f5f9'>" + "".join(f"<th align=left>{h}</th>" for h in head) + "</tr>"
            + "".join(f"<tr style='border-top:1px solid #eee'>{r}</tr>" for r in rows) + "</table>")


def td(*cells):
    return "".join(f"<td valign=top>{c}</td>" for c in cells)


def main(dry=False):
    J = core.load_jobs()
    hour = int(core.CONFIG.get("report_hour", 21))
    since_dt = datetime.datetime.combine(datetime.date.today(), datetime.time(hour, 0)) - datetime.timedelta(days=1)
    since = since_dt.isoformat()
    applied = [j for j in J if j.get("status") == "applied" and j.get("applied_at", "") >= since]
    manual = [j for j in J if j.get("status") in ("manual", "dry_run_ok") and j.get("updated_at", "") >= since]
    skipped = [j for j in J if j.get("status") == "skipped" and j.get("updated_at", "") >= since]
    found = [j for j in J if j.get("found_at", "") >= since]
    queued = [j for j in J if j.get("status") == "queued"]
    ok, bad = runs_since(since_dt)
    conf = []
    try:
        import mailcheck
        conf = mailcheck.confirmations(since_dt.astimezone())
    except Exception:
        pass

    def conf_for(j):
        n = (j.get("company_display") or j["company"]).lower().split()[0]
        return any(n in (c["subject"] + c["from"]).lower() for c in conf)

    by_src = {}
    for j in found:
        s = j.get("source", "").split("-")[0].split("→")[0]
        by_src[s] = by_src.get(s, 0) + 1
    a_rows = [td(name(j), link(j), html.escape(j.get("location", ""))[:60], f"{j.get('fit_score', '')}/10",
                 "tailored" if j.get("resume_tailored") else "master",
                 "✅ email received" if conf_for(j) else "confirmation page seen") for j in applied]
    m_rows = [td(name(j), link(j), html.escape(j.get("reason", "")) +
                 ("<br><span style='color:#555'>Needs: " + html.escape("; ".join(j.get("open_questions", []))) + "</span>" if j.get("open_questions") else ""))
              for j in manual]
    s_rows = [td(name(j), link(j), html.escape(j.get("reason", ""))[:220]) for j in skipped]
    q_rows = [td(name(j), link(j), html.escape(j.get("track", "")), html.escape(j.get("reason", "") or "waiting"))
              for j in sorted(queued, key=lambda x: (x.get("priority", 9), x["company"]))[:30]]
    est = [j for j in applied if j.get("salary_note")]
    n = len(applied)
    body = f"""<div style='font-family:-apple-system,Helvetica,Arial;font-size:14px;max-width:900px'>
<h2 style='margin-bottom:4px'>Applied to {n} role{'s' if n != 1 else ''} since the last report, with tailored resumes</h2>
<p style='color:#555;margin-top:0'>{datetime.date.today().strftime('%A, %B %-d, %Y')} · scheduled runs: {ok} OK{f', {bad} with problems' if bad else ''} ·
{len(found)} new matching roles ({', '.join(f'{k}: {v}' for k, v in sorted(by_src.items())) or 'none'}) · {len(queued)} waiting in queue</p>
<h3>Applied ({n})</h3>
{table(a_rows, ['Company', 'Role', 'Location', 'Fit', 'Resume', 'Confirmation'])}
<h3>For you to submit ({len(manual)})</h3>
<p style='color:#555'>Each one also arrives as its own email with the link, the tailored resume and the answers to copy in.</p>
{table(m_rows, ['Company', 'Role', 'Why it needs you'])}
<h3>Skipped ({len(skipped)})</h3>
{table(s_rows, ['Company', 'Role', 'Reason'])}
<h3>Still in queue ({len(queued)})</h3>
{table(q_rows, ['Company', 'Role', 'Track', 'Status'])}
{"<h3>Salary answers that used an estimate</h3><ul>" + "".join(f"<li>{name(j)}: {html.escape(j['salary_note'])}</li>" for j in est) + "</ul>" if est else ""}
</div>"""
    subject = f"Applied to {n} role{'s' if n != 1 else ''} with tailored resumes · {len(manual)} for you to submit"
    att = [(j["resume_file"], f"{re.sub(r'[^A-Za-z0-9]+', ' ', j.get('company_display') or j['company']).strip()} - {pathlib.Path(j['resume_file']).name}")
           for j in applied if j.get("resume_file") and pathlib.Path(j["resume_file"]).exists()]
    if dry:
        print(subject); print(re.sub(r"<[^>]+>", " ", body)[:3000]); return
    mailer.send(subject, body, att)
    print("sent:", subject)


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
