"""Fit check + resume tailoring for one posting.

Two Claude calls share one cached system prompt (profile + bullet bank):
  1. fit: score 0-10, apply/skip, hard blockers, and facts from the posting (pay range, work mode...)
  2. only when applying: tailored resume content chosen from resume/bank.json
Then deterministic checks, so the model cannot add facts:
  * titles, companies, dates and education always come from resume/master.json;
  * every bullet names its source bullet; its numbers must be the source's numbers, and it may only add
    ordinary English words (no new tools, skills or domains that the profile doesn't contain);
  * the summary may only use numbers that the master summary uses, and must keep the years-of-experience phrase;
  * skills only from the approved vocabulary;
  * the page-count layout check in resume/build_resume.py, trimming or padding bullets until it passes.
Anything that fails falls back to the source wording, and as a last resort to the approved master resume.
"""
import json, re, sys, copy
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core

sys.path.insert(0, str(core.HOME / "resume"))
import llm
import build_resume

MASTER_PATH = core.HOME / "resume/master.json"
BANK_PATH = core.HOME / "resume/bank.json"
MASTER = json.loads(MASTER_PATH.read_text()) if MASTER_PATH.exists() else {}
BANK = json.loads(BANK_PATH.read_text()) if BANK_PATH.exists() else {"jobs": {}, "order": []}
PROFILE = core.profile_text()
MASTER_PDF = core.HOME / "resume/out" / f"{core.candidate_name()} Resume.pdf"
FORBIDDEN = BANK.get("forbidden_phrases", [])          # e.g. retired metrics, a degree never completed

STOP = set("""a an the and or of for to in on with by from as at into across their its it this that these those
our your her his them they was were is are be been being per via over within than more most also such using use used
while where which who whom whose through out up down off about after before during under same each both other
""".split())
VERBS = set("""led drove ran conducted designed partnered delivered shaped informed built created facilitated translated
synthesized improved uncovered identified defined mapped owned planned scoped executed developed analyzed measured
produced prioritized aligned guided mentored researched applied combined surfaced reduced recovered raised increased
boosted cutting cut supported advocated launched shipped approved generated enable enabled strategic end-to-end team
teams stakeholders stakeholder cross-functional workshops workshop studies study experience experiences digital
platform platforms workflow workflows decisions decision strategy roadmap leaders leadership partners customer
customers user users product products insights findings recommendations""".split())
# Skills, tools, credentials and domains people often lack. Flagged only when the profile doesn't mention them.
NEVER = set("""sql python sas spss stata matlab javascript typescript html css react swift kotlin java kubernetes aws gcp
azure snowflake databricks hadoop spark tableau phd doctorate mba cpa automotive gaming retail ecommerce e-commerce
logistics edtech crypto blockchain web3 telecom media entertainment travel hospitality legal manufacturing energy
utilities defense aerospace pharma pharmaceutical biotech sports nonprofit hardware robotics semiconductor security
cybersecurity statistics statistical regression econometrics""".split())
WORDNUM = r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|dozen|hundred|thousand)\b"
try:
    DICT = set(w.strip().lower() for w in open("/usr/share/dict/words"))
except OSError:
    DICT = set()        # no system word list: only profile words are allowed (stricter, still safe)


def words(s):
    return [w for w in re.findall(r"[a-z][a-z0-9\-']+", s.lower().replace("**", "")) if w not in STOP and len(w) > 2]


PROFILE_WORDS = set(words(PROFILE)) | set(words(json.dumps(BANK))) | set(words(json.dumps(MASTER))) | VERBS


def common(w):
    if "-" in w:
        return all(common(p) for p in w.split("-") if p)
    for suf, add in (("", ""), ("s", ""), ("es", ""), ("ed", ""), ("ed", "e"), ("d", ""), ("ing", ""), ("ing", "e"),
                     ("ly", ""), ("er", ""), ("ers", ""), ("ies", "y"), ("ied", "y"), ("ying", "y")):
        if w.endswith(suf) and (w[:len(w) - len(suf)] + add) in DICT:
            return True
    return False


def flagged(text):
    """Words that are neither in the profile nor ordinary English, or that name a skill/domain the profile lacks."""
    return [w for w in words(text) if w not in PROFILE_WORDS and (w in NEVER or not common(w))]


def novel(text):
    return [w for w in words(text) if w not in PROFILE_WORDS]


def nums(s):
    s = s.replace("**", "")
    found = {x.replace(",", "") for x in re.findall(r"\d[\d,\.]*\+?%?", s)}
    found |= set(re.findall(WORDNUM, s.lower()))
    return found


def job_ids():
    return BANK.get("order") or [j.get("id") for j in MASTER.get("experience", [])]


SYSTEM = f"""You tailor resumes and screen job fit for one candidate, {core.candidate_name()}. You never invent facts.
Every claim must come from the candidate profile or the bullet bank below. If a job wants something the candidate
doesn't have (a skill, tool, degree, domain, clearance), leave it out; never imply it.

=== CANDIDATE PROFILE (source of truth) ===
{PROFILE}

=== BULLET BANK (choose from these; ids are fixed) ===
{json.dumps(BANK.get("jobs", {}), indent=0)}

=== ALLOWED RESUME TITLES (pick one for the header) ===
{json.dumps(BANK.get("titles", [MASTER.get("title", "")]))}

=== ALLOWED SKILL CATEGORIES ===
{json.dumps(BANK.get("skill_categories", []))}

=== ALLOWED SKILL ITEMS (use these exact strings only) ===
{json.dumps(BANK.get("skills_vocab", []))}
"""

FIT = {"type": "object", "additionalProperties": False, "required": ["score", "decision", "reason", "blockers"],
       "properties": {"score": {"type": "integer"}, "decision": {"type": "string", "enum": ["apply", "skip"]},
                      "reason": {"type": "string"}, "blockers": {"type": "array", "items": {"type": "string"}}}}
FACTS_SCHEMA = {"type": "object", "additionalProperties": False,
                "required": ["salary_min", "salary_max", "work_mode", "office_locations", "timezone_requirement",
                             "clearance_or_citizenship_required", "min_years", "level", "company_display_name"],
                "properties": {"salary_min": {"type": ["integer", "null"]}, "salary_max": {"type": ["integer", "null"]},
                               "work_mode": {"type": "string", "enum": ["remote", "hybrid", "onsite", "unclear"]},
                               "office_locations": {"type": "array", "items": {"type": "string"}},
                               "timezone_requirement": {"type": ["string", "null"]},
                               "clearance_or_citizenship_required": {"type": "boolean"},
                               "min_years": {"type": ["integer", "null"]}, "level": {"type": "string"},
                               "company_display_name": {"type": "string"}}}
FIT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["fit", "facts"],
              "properties": {"fit": FIT, "facts": FACTS_SCHEMA}}
RESUME_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["resume"], "properties": {"resume": {
    "type": "object", "additionalProperties": False, "required": ["title", "headline", "summary", "bullets", "skills"],
    "properties": {
        "title": {"type": "string"}, "headline": {"type": "string"}, "summary": {"type": "string"},
        "bullets": {"type": "object", "additionalProperties": False, "required": job_ids(),
                    "properties": {k: {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                   "required": ["src", "text"],
                                                                   "properties": {"src": {"type": "string"}, "text": {"type": "string"}}}}
                                   for k in job_ids()}},
        "skills": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["category", "items"],
                                              "properties": {"category": {"type": "string"},
                                                             "items": {"type": "array", "items": {"type": "string"}}}}}}}}}


def master_len():
    return sum(len(b) for j in MASTER.get("experience", []) for b in j["bullets"]) + len(MASTER.get("summary", ""))


def thresholds():
    return {t["name"]: t.get("min_fit", 6) for t in core.SEARCH.get("tracks", [])}


def prompt_for(job, src):
    th = thresholds()
    rules = core.SEARCH.get("fit_rules", "")
    yrs = core.FACTS.get("years_experience_text", "")
    return f"""JOB
Title: {src.get('title') or job['title']}
Company: {src.get('company_name') or job['company']}
Location: {src.get('location') or job['location']}  (scanner classified: {job.get('where')})
Track: {job.get('track')} (apply only at fit score {th.get(job.get('track'), 6)}+)
Posted pay: {'; '.join(src.get('pay') or []) or 'not posted'}

JOB DESCRIPTION
{src.get('jd', '')[:14000]}

TASK 1: FIT. Decide whether the candidate should apply. Score 0-10 for how strongly their real background
matches this posting. Score thresholds by track: {json.dumps(th)}.
Candidate's search rules (follow them strictly; any hard blocker means "skip"):
{rules}

TASK 2: FACTS from the posting: top and bottom of the posted base salary (annual USD, or null), work mode,
office cities, any time-zone requirement, clearance/citizenship requirement, minimum years, level, and the
company's display name (e.g. "Acme Health", not "acmehealth").

TASK 3: RESUME. Use the bullet bank:
- For each job key ({', '.join(job_ids())}) pick between its min and max bullets, most relevant first.
  Each item: src = the bank id, text = that bullet, optionally lightly reworded to echo the posting's language.
  Keep **bold** markup on the key phrase. Keep every number exactly as in the source and add no new numbers,
  tools, skills, domains or outcomes. Use at most one bullet per "group".
- Keep total bullet + summary length close to {master_len()} characters (within 5%) so the resume keeps its
  exact page count.
- title: one of the allowed titles that fits the role.
- headline: a short phrase like the master headline "{MASTER.get('headline', '')}" (no numbers).
- summary: 3-4 sentences, about the master summary's length, built from the profile.
  {f'Must say "{yrs}". ' if yrs else ''}Use no numbers other than the ones in the master summary. Bold 3-4 key phrases with **...**.
- skills: the same number of rows as the master resume, categories and items only from the allowed lists,
  most relevant first.
"""


def check_bullet(key, item, used_groups):
    src = next((b for b in BANK["jobs"][key]["bullets"] if b["id"] == item.get("src")), None)
    if not src:
        return None, "unknown source id"
    if src.get("group") and src["group"] in used_groups:
        return None, "duplicate metric group"
    t = item.get("text", "").strip() or src["text"]
    why = ""
    if not nums(t) <= nums(src["text"]):
        t, why = src["text"], "numbers changed, reverted"
    else:
        bad, new = flagged(t), novel(t)
        if bad or len(new) > 4:
            t, why = src["text"], f"new words {(bad or new)[:4]}, reverted"
    for f in FORBIDDEN:
        if re.search(f, t):
            t, why = src["text"], "forbidden phrase, reverted"
    if src.get("group"):
        used_groups.add(src["group"])
    return {"id": src["id"], "text": t}, why


def assemble(r):
    """Model output -> content dict in master.json shape, with all checks applied."""
    notes = []
    c = copy.deepcopy(MASTER)
    if r.get("title") in BANK.get("titles", []):
        c["title"] = r["title"]
    h = (r.get("headline") or "").strip()
    if h and len(h) <= 70 and not re.search(r"\d", h):
        c["headline"] = h
    s = (r.get("summary") or "").strip()
    yrs = core.FACTS.get("years_experience_text", "")
    allowed = nums(MASTER.get("summary", ""))
    base = len(MASTER.get("summary", "")) or 550
    why = [w for w, bad_ in ((f"missing '{yrs}'", bool(yrs) and yrs not in s),
                             (f"numbers {sorted(nums(s) - allowed)}", not nums(s) <= allowed),
                             ("forbidden phrase", any(re.search(f, s) for f in FORBIDDEN)),
                             (f"unknown words {flagged(s)[:5]}", bool(flagged(s))),
                             (f"{len(novel(s))} words not in profile", len(novel(s)) > 14),
                             (f"length {len(s)}", not 0.75 * base <= len(s) <= 1.4 * base)) if bad_]
    if s and not why:
        c["summary"] = s
    else:
        notes.append("summary kept from master: " + "; ".join(why))
    used = set()
    for job in c["experience"]:
        key = job.get("id")
        if key not in BANK["jobs"]:
            continue
        lim = BANK["jobs"][key]
        out = []
        for it in r.get("bullets", {}).get(key, []):
            b, w = check_bullet(key, it, used)
            if w:
                notes.append(f"{key}/{it.get('src')}: {w}")
            if b and b["id"] not in [x["id"] for x in out]:
                out.append(b)
        if not (lim["min"] <= len(out) <= lim["max"]):
            notes.append(f"{key}: {len(out)} bullets, using master set")
            out = [{"id": b["id"], "text": b["text"]} for b in lim["bullets"] if b.get("master")]
        job["bullets"] = [b["text"] for b in out]
        job["_ids"] = [b["id"] for b in out]
    vocab = {v.lower(): v for v in BANK.get("skills_vocab", [])}
    rows = []
    for row in r.get("skills", []):
        cat = row.get("category")
        items = [vocab[i.lower()] for i in row.get("items", []) if i.lower() in vocab]
        if cat in BANK.get("skill_categories", []) and len(items) >= 3:
            rows.append([cat, ", ".join(dict.fromkeys(items))])
    if len(rows) == len(MASTER.get("skills", [])):
        c["skills"] = rows
    else:
        notes.append("skills kept from master")
    return c, notes


def adjust(c, direction):
    """Trim (overflow) or pad (underfill) one bullet, oldest roles first. False when nothing is left to change."""
    jobs = [j for j in c["experience"] if j.get("id") in BANK["jobs"]]
    if direction == "overflow":
        for job in reversed(jobs):
            if len(job["bullets"]) > BANK["jobs"][job["id"]]["min"]:
                job["bullets"].pop(); job["_ids"].pop()
                return True
        return False
    for job in jobs:
        lim = BANK["jobs"][job["id"]]
        if len(job["bullets"]) < lim["max"]:
            groups = {b.get("group") for b in lim["bullets"] if b["id"] in job["_ids"]}
            for b in lim["bullets"]:
                if b["id"] not in job["_ids"] and (not b.get("group") or b["group"] not in groups):
                    job["bullets"].append(b["text"]); job["_ids"].append(b["id"])
                    return True
    return False


def render(c, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    pdf = outdir / f"{core.candidate_name()} Resume.pdf"
    notes = []
    for attempt in range(6):
        cj = outdir / "content.json"
        cj.write_text(json.dumps(c, indent=1))
        rc = build_resume.build(str(cj), str(pdf))
        info = build_resume.LAST or {}
        if rc == 0:
            return pdf, info, notes
        reason = info.get("reason", "")
        notes.append(f"layout attempt {attempt + 1}: {reason}")
        if reason.startswith("text-check"):
            m = re.search(r"orphan word line: '([^']+)'", reason)
            fixed = False
            if m:
                for job in c["experience"]:
                    for i, b in enumerate(job.get("bullets", [])):
                        if job.get("id") in BANK["jobs"] and b.replace("**", "").rstrip().endswith(m.group(1)):
                            src = next(x for x in BANK["jobs"][job["id"]]["bullets"] if x["id"] == job["_ids"][i])
                            if b != src["text"]:
                                job["bullets"][i] = src["text"]
                            else:
                                job["bullets"].pop(i); job["_ids"].pop(i)
                            fixed = True
                            break
                    if fixed:
                        break
            if not fixed:
                break
        elif not adjust(c, "overflow" if reason == "overflow" else "underfill"):
            break
    return None, {}, notes


def tailor(job, src, outdir):
    """Returns dict: fit, facts, pdf, tailored (bool), content, notes."""
    p = prompt_for(job, src)
    fp = p.split("TASK 3: RESUME.")[0] + "Do TASK 1 and TASK 2 only."
    r = llm.ask_json(SYSTEM, fp, FIT_SCHEMA, timeout=420)
    need = thresholds().get(job.get("track"), 6)
    if r["fit"]["decision"] == "apply" and r["fit"]["score"] < need:       # thresholds enforced in code too
        r["fit"]["decision"] = "skip"
        r["fit"]["blockers"] = [f"fit score {r['fit']['score']} is below {need} for a {job.get('track')} role"] + r["fit"].get("blockers", [])
    res = {"fit": r["fit"], "facts": r["facts"], "notes": []}
    if r["fit"]["decision"] != "apply":
        return res
    r2 = llm.ask_json(SYSTEM, p + "\nThe fit is already decided (apply). Do TASK 3 only.", RESUME_SCHEMA, timeout=600)
    c, notes = assemble(r2["resume"])
    res["notes"] += notes
    pdf, info, n2 = render(c, outdir)
    res["notes"] += n2
    if not pdf:
        outdir.mkdir(parents=True, exist_ok=True)
        pdf = outdir / f"{core.candidate_name()} Resume.pdf"
        pdf.write_bytes(MASTER_PDF.read_bytes())
        res["notes"].append("tailored layout failed QA; used the master resume")
        res["tailored"] = False
    else:
        res["tailored"] = True
        res["layout"] = {k: info.get(k) for k in ("font_pt", "spacing", "pages")}
    res["pdf"] = str(pdf)
    res["content"] = c
    (outdir / "tailor.json").write_text(json.dumps(res, indent=1))
    return res
