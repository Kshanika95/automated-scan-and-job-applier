"""Fetch a posting's description and application-form schema from the ATS's public API.

Normalized field: {key, label, type, required, options:[str], description, section, ats:{...raw}}
types: text, textarea, email, phone, file, select, multiselect, boolean, date, number, location, hidden
"""
import json, re, html, urllib.request, urllib.parse, urllib.error
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core

UA = "Mozilla/5.0 (compatible; automated-scan-and-job-applier/1.0; personal job search)"


class Closed(Exception):
    """The posting no longer exists or no longer accepts applications."""


class RateLimited(Exception):
    """The ATS is throttling us (HTTP 429, or Greenhouse's Signal Sciences 406). Try again next run."""


def _get(url, data=None, headers=None, timeout=30):
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise Closed(f"HTTP {e.code}")
        if e.code == 429 or (e.code == 406 and "rate-limit" in (e.headers.get("x-sigsci-tags") or "")):
            raise RateLimited(f"{urllib.parse.urlparse(url).netloc} HTTP {e.code}")
        raise


def html_to_text(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


# ---------------------------------------------------------------- Greenhouse
def gh_ids(job):
    u = job["url"]
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", u)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"[?&](?:gh_jid|token)=(\d+)", u)
    board = re.search(r"for=([\w-]+)", u)
    if m:
        return (board.group(1) if board else job["company"]), m.group(1)
    raise ValueError("not a greenhouse url: " + u)


def greenhouse(job):
    board, jid = gh_ids(job)
    txt, _ = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}?questions=true&pay_transparency=true")
    d = json.loads(txt)
    fields = []

    def add_q(q, section):
        for f in q.get("fields", []):
            t = {"input_text": "text", "textarea": "textarea", "input_file": "file", "input_hidden": "hidden",
                 "multi_value_single_select": "select", "multi_value_multi_select": "multiselect"}.get(f["type"], f["type"])
            fields.append({"key": f["name"], "label": html_to_text(q.get("label", "")), "type": t,
                           "required": bool(q.get("required")), "options": [v["label"] for v in f.get("values", [])],
                           "option_values": [v.get("value") for v in f.get("values", [])],
                           "description": html_to_text(q.get("description") or "")[:600], "section": section})

    for q in d.get("questions", []):
        add_q(q, "main")
    for q in d.get("location_questions") or []:
        add_q(q, "location")
    for c in d.get("compliance") or []:
        for q in c.get("questions", []):
            add_q(q, "eeoc")
    dq = d.get("demographic_questions") or {}
    for q in (dq.get("questions") or []) if isinstance(dq, dict) else []:
        fields.append({"key": str(q.get("id")), "label": html_to_text(q.get("label", "")),
                       "type": "multiselect" if q.get("type") == "multi_value_multi_select" else "select",
                       "required": bool(q.get("required")), "options": [a["label"] for a in q.get("answer_options", [])],
                       "description": "", "section": "demographic"})
    pay = [f"{p.get('title','')}: ${p['min_cents']//100:,}–${p['max_cents']//100:,} {p.get('currency_type','')}"
           for p in d.get("pay_input_ranges") or [] if p.get("min_cents")]
    return {"ats": "greenhouse", "board": board, "job_id": jid, "title": d.get("title"),
            "company_name": d.get("company_name") or board, "location": (d.get("location") or {}).get("name", ""),
            "apply_url": f"https://job-boards.greenhouse.io/{board}/jobs/{jid}",
            "alt_apply_url": f"https://job-boards.greenhouse.io/embed/job_app?for={board}&token={jid}",
            "jd": html_to_text(html.unescape(d.get("content", ""))), "pay": pay, "fields": fields}


# ---------------------------------------------------------------- Ashby
ASHBY_Q = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
 jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
  id title locationName workplaceType employmentType descriptionHtml compensationTierSummary isListed
  applicationForm { id sections { title descriptionHtml fieldEntries { id isRequired descriptionHtml field } } }
  surveyForms { id sections { title fieldEntries { id isRequired descriptionHtml field } } } } }"""


def ashby_ids(job):
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", job["url"])
    if not m:
        raise ValueError("not an ashby url: " + job["url"])
    return urllib.parse.unquote(m.group(1)), m.group(2)


def ashby(job):
    org, jid = ashby_ids(job)
    body = json.dumps({"operationName": "ApiJobPosting", "query": ASHBY_Q,
                       "variables": {"organizationHostedJobsPageName": org, "jobPostingId": jid}}).encode()
    txt, _ = _get("https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting", data=body,
                  headers={"Content-Type": "application/json"})
    d = json.loads(txt)
    jp = (d.get("data") or {}).get("jobPosting")
    if not jp:
        raise Closed("posting not found")
    fields = []
    tmap = {"String": "text", "Email": "email", "Phone": "phone", "File": "file", "LongText": "textarea",
            "Boolean": "boolean", "ValueSelect": "select", "MultiValueSelect": "multiselect", "Date": "date",
            "Number": "number", "Location": "location", "SocialLink": "text", "Score": "select"}

    def add(sections, section):
        for s in sections:
            for e in s.get("fieldEntries", []):
                f = e.get("field") or {}
                fields.append({"key": f.get("path") or f.get("id"), "label": html_to_text(f.get("title") or ""),
                               "type": tmap.get(f.get("type"), (f.get("type") or "text").lower()),
                               "required": bool(e.get("isRequired")),
                               "options": [v.get("label") for v in (f.get("selectableValues") or [])],
                               "description": html_to_text(e.get("descriptionHtml") or "")[:600], "section": section,
                               "ats": {"type": f.get("type"), "id": f.get("id")}})

    add(jp["applicationForm"]["sections"], "main")
    for sf in jp.get("surveyForms") or []:
        add(sf.get("sections", []), "survey")
    return {"ats": "ashby", "board": org, "job_id": jid, "title": jp.get("title"), "company_name": org,
            "location": jp.get("locationName", ""), "workplace": jp.get("workplaceType"),
            "apply_url": f"https://jobs.ashbyhq.com/{urllib.parse.quote(org)}/{jid}/application",
            "jd": html_to_text(jp.get("descriptionHtml", "")),
            "pay": [jp["compensationTierSummary"]] if jp.get("compensationTierSummary") else [], "fields": fields}


# ---------------------------------------------------------------- Lever
def lever_ids(job):
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", job["url"])
    if not m:
        raise ValueError("not a lever url: " + job["url"])
    return m.group(1), m.group(2)


def lever(job):
    site, jid = lever_ids(job)
    txt, _ = _get(f"https://api.lever.co/v0/postings/{site}/{jid}")
    d = json.loads(txt)
    page, _ = _get(f"https://jobs.lever.co/{site}/{jid}/apply", headers={"Accept": "text/html"})
    if "application-form" not in page and "application-question" not in page:
        raise Closed("no application form")
    fields = []
    # standard fields
    for key, label, t, req in [("resume", "Resume/CV", "file", True), ("name", "Full name", "text", True),
                               ("email", "Email", "email", True), ("phone", "Phone", "phone", False),
                               ("location", "Current location", "location", False), ("org", "Current company", "text", False)]:
        if f'name="{key}"' in page or key == "resume":
            r = req
            m = re.search(r'name="%s"[^>]*' % re.escape(key), page)
            if m and "required" in m.group(0):
                r = True
            fields.append({"key": key, "label": label, "type": t, "required": r, "options": [], "description": "", "section": "main"})
    for m in re.finditer(r'name="(urls\[[^\]]+\])"([^>]*)', page):
        lab = m.group(1)[5:-1]
        fields.append({"key": m.group(1), "label": lab + " URL", "type": "text", "required": "required" in m.group(2),
                       "options": [], "description": "", "section": "main"})
    # custom question cards: hidden baseTemplate JSON describes each card's fields
    for m in re.finditer(r'<input[^>]*name="(cards\[[0-9a-f-]+\])\[baseTemplate\]"[^>]*>', page):
        v = re.search(r'value="([^"]*)"', m.group(0))
        if not v:
            continue
        card, tpl = m.group(1), json.loads(html.unescape(v.group(1)))
        for i, f in enumerate(tpl.get("fields", [])):
            t = {"multiple-choice": "radio", "multiple-select": "multiselect", "dropdown": "select",
                 "text": "text", "textarea": "textarea"}.get(f.get("type"), "text")
            fields.append({"key": f"{card}[field{i}]", "label": html_to_text(f.get("text", "")), "type": t,
                           "required": bool(f.get("required")), "options": [o.get("text") for o in f.get("options", [])],
                           "description": html_to_text(f.get("description") or "")[:600], "section": "card"})
    for m in re.finditer(r'<select[^>]*name="(eeo\[[a-z]+\])"[^>]*>(.*?)</select>', page, re.S):
        opts = [html.unescape(o).strip() for o in re.findall(r"<option[^>]*>([^<]*)</option>", m.group(2))]
        fields.append({"key": m.group(1), "label": "EEO " + m.group(1)[4:-1], "type": "select", "required": False,
                       "options": [o for o in opts if o and not o.lower().startswith("select")], "description": "", "section": "eeo"})
    if 'name="comments"' in page:
        fields.append({"key": "comments", "label": "Additional information", "type": "textarea", "required": False,
                       "options": [], "description": "", "section": "main"})
    for m in re.finditer(r'<input[^>]*type="checkbox"[^>]*name="(consent\[[^\]]+\]|[^"]*consent[^"]*)"', page):
        fields.append({"key": m.group(1), "label": "Consent: " + m.group(1), "type": "checkbox", "required": False,
                       "options": [], "description": "", "section": "consent"})
    sal = d.get("salaryRange") or {}
    pay = [f"${sal['min']:,}–${sal['max']:,} {sal.get('currency','')} {sal.get('interval','')}"] if sal.get("min") else []
    jd = "\n".join([d.get("descriptionPlain", "")] + [f"{l.get('text','')}:\n{html_to_text(l.get('content',''))}" for l in d.get("lists", [])]
                   + [d.get("additionalPlain", "")])
    return {"ats": "lever", "board": site, "job_id": jid, "title": d.get("text"), "company_name": site,
            "location": (d.get("categories") or {}).get("location", ""), "workplace": d.get("workplaceType"),
            "apply_url": f"https://jobs.lever.co/{site}/{jid}/apply", "jd": jd, "pay": pay, "fields": fields}


# ---------------------------------------------------------------- Workday (description only: Workday applications
# need an employer account, which Workday refuses to create for automated browsers, so they go to the person)
def workday(job):
    m = re.match(r"https://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+)$", job["url"])
    if not m:
        raise ValueError("not a workday url: " + job["url"])
    tenant, inst, site, path = m.groups()
    txt, _ = _get(f"https://{tenant}.{inst}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}",
                  headers={"Content-Type": "application/json"})
    d = json.loads(txt)
    i = d.get("jobPostingInfo") or {}
    if i.get("canApply") is False:
        raise Closed("canApply=false")
    org = ((d.get("hiringOrganization") or {}).get("name") or tenant)
    org = re.sub(r"^\d+\s+", "", org)
    return {"ats": "workday", "board": f"{tenant}|{inst}|{site}", "job_id": i.get("jobReqId"), "title": i.get("title"),
            "company_name": org, "location": "; ".join([x for x in [i.get("location")] + (i.get("additionalLocations") or []) if x]),
            "apply_url": f"https://{tenant}.{inst}.myworkdayjobs.com/en-US/{site}{path}/apply",
            "jd": html_to_text(i.get("jobDescription", "")), "pay": [], "fields": []}


def indeed(job):
    k = job["url"].split("#indeed=")[-1]
    rec = json.loads((core.STATE / "indeed" / f"{k}.json").read_text())
    j = rec["indeed"]
    return {"ats": "indeed", "board": "indeed", "job_id": j.get("job_id"), "title": j.get("title"), "company_name": j.get("company"),
            "location": j.get("location", ""), "apply_url": job["url"].split("#indeed=")[0],
            "jd": rec.get("jd") or "", "pay": [j["compensation"]] if j.get("compensation") else [], "fields": []}


def ats_of(url):
    if "#indeed=" in url:
        return "indeed"
    if "greenhouse.io" in url or "gh_jid=" in url:
        return "greenhouse"
    if "ashbyhq.com" in url:
        return "ashby"
    if "lever.co" in url:
        return "lever"
    if "myworkdayjobs.com" in url:
        return "workday"
    return None


def fetch(job):
    a = ats_of(job["url"]) or {"greenhouse-full": "greenhouse", "ashby-full": "ashby", "lever-full": "lever"}.get(job.get("source"))
    fn = {"greenhouse": greenhouse, "ashby": ashby, "lever": lever, "workday": workday, "indeed": indeed}.get(a)
    if not fn:
        raise ValueError("unsupported ATS for " + job["url"])
    return fn(job)


if __name__ == "__main__":
    import sys
    j = {"url": sys.argv[1], "company": sys.argv[2] if len(sys.argv) > 2 else ""}
    s = fetch(j)
    print(json.dumps({k: v for k, v in s.items() if k != "jd"}, indent=1)[:6000])
    print("JD chars:", len(s["jd"]))
