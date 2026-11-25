"""One email per posting that needs the person (a CAPTCHA, an unsupported site, a question only they can answer,
or a site where submission is switched off): the apply link, why it needs them, the tailored resume (and cover
letter) attached, and the exact answer to paste for every field on that form.   Usage: manual_emails.py [--dry]
"""
import datetime, html, json, pathlib, re, sys
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core, mailer

SENT = core.STATE / "manual_emailed.json"


def fmt(v):
    if v is True:
        return "Yes"
    if v is False:
        return "No"
    if isinstance(v, list):
        return "; ".join(map(str, v))
    return str(v)


def form_rows(j):
    d = pathlib.Path(j.get("app_dir") or "/nonexistent")
    try:
        post = json.loads((d / "posting.json").read_text())
        ans = json.loads((d / "answers.json").read_text())
    except Exception:
        return None
    a, unknown = ans.get("answers", {}), ans.get("unknown_required", [])
    rows = []
    for f in post.get("fields", []):
        if f["type"] == "hidden" or f["key"] in ("resume_text", "cover_letter_text", "latitude", "longitude"):
            continue
        lab = f["label"] + (" *" if f["required"] else "")
        if f["type"] == "file":
            v = "Attach the resume from this email" if "resume" in (f["label"] + f["key"]).lower() else \
                ("Attach the file from this email" if f["key"] in a else "(optional, leave empty)")
            cell = html.escape(v)
        elif f["key"] in a:
            cell = html.escape(fmt(a[f["key"]]))
        elif any(u.startswith(f["label"][:40]) for u in unknown):
            cell = "<b style='color:#b00'>⚠️ only you can answer this</b>"
        else:
            cell = "(optional, leave empty)"
        rows.append(f"<tr><td style='padding:4px 12px 4px 0;color:#444' valign=top>{html.escape(lab)}</td><td>{cell}</td></tr>")
    return "".join(rows)


def main(dry=False):
    jobs = core.load_jobs()
    sent = json.loads(SENT.read_text()) if SENT.exists() else {}
    n = 0
    for j in jobs:
        if j.get("status") not in ("manual", "dry_run_ok") or j["url"] in sent:
            continue
        att = []
        if j.get("resume_file") and pathlib.Path(j["resume_file"]).exists():
            att.append((j["resume_file"], pathlib.Path(j["resume_file"]).name))
        d = pathlib.Path(j.get("app_dir") or "/nonexistent")
        for extra in d.glob("*Cover Letter.pdf"):
            att.append((str(extra), extra.name))
        rows = form_rows(j)
        answers = (f"<p><b>Answers for this form</b> (copy in; * = required):</p><table style='font-size:13px;border-collapse:collapse'>{rows}</table>"
                   if rows else "<p>Use the standard answers from your profile.</p>")
        need = ("<p><b>Only you can answer:</b></p><ul>" + "".join(f"<li>{html.escape(q)}</li>" for q in j["open_questions"]) + "</ul>"
                if j.get("open_questions") else "")
        name = j.get("company_display") or j["company"]
        url = j.get("apply_url") or j["url"].split("#")[0]
        body = f"""<div style='font-family:-apple-system,Helvetica,Arial;font-size:14px;max-width:760px'>
<h3 style='margin-bottom:2px'>{html.escape(j['title'])}, {html.escape(name)}</h3>
<p style='color:#555;margin-top:0'>{html.escape(j.get('location', ''))} · posted {html.escape(j.get('posted', ''))}{f" · fit {j['fit_score']}/10" if j.get('fit_score') is not None else ''}</p>
<p><a href="{html.escape(url)}" style='font-size:16px'><b>Open the application →</b></a></p>
<p><b>Why it needs you:</b> {html.escape(j.get('reason', 'blocked'))}</p>
<p><b>Resume:</b> {'tailored for this role, attached' if att else 'no tailored version was made; use your master resume'}</p>
{need}{answers}</div>"""
        if dry:
            print(f"[dry] Apply manually: {j['title']} at {name} | attachments: {[x[1] for x in att]}"); continue
        mailer.send(f"Apply manually: {j['title']} at {name}", body, att)
        sent[j["url"]] = datetime.datetime.now().isoformat(timespec="seconds")
        SENT.write_text(json.dumps(sent, indent=0))
        n += 1
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M} manual emails sent: {n}")


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
