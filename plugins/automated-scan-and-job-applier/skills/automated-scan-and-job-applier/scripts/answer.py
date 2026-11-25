"""Answer an application form's fields: fixed rules from facts.json first, then one Claude call for the rest.

Never guesses a fact: a REQUIRED question the profile can't answer is returned in `unknown_required`, and the job
goes to the person's "submit these yourself" list instead.
"""
import json, re, datetime
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core, llm

F = core.FACTS
LOC = core.SEARCH.get("locations", {})


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def pick(options, prefs, avoid=None):
    """First option matching any regex in prefs (in priority order)."""
    for p in prefs:
        for o in options:
            if re.search(p, norm(o)) and not (avoid and re.search(avoid, norm(o))):
                return o
    return None


DECLINE = [r"prefer not", r"decline", r"don.?t wish", r"do not wish", r"choose not", r"not to (say|disclose|answer)", r"rather not"]
YES = [r"^yes\b", r"^y$", r"^true$"]
NO = [r"^no\b", r"^n$", r"^false$"]


def yes_no(f, val):
    if f["type"] in ("boolean", "checkbox"):
        return bool(val)
    return pick(f["options"], YES if val else NO)


def tri(f, val, yes_pats, no_pats):
    """facts value True / False / "decline" -> an option."""
    if val in (None, "decline"):
        return pick(f["options"], DECLINE)
    return pick(f["options"], yes_pats if val else no_pats)


GENDER = {"female": [r"^female$", r"^woman$", r"^female\b", r"^woman\b", r"\bfemale\b", r"\bwoman\b"],
          "male": [r"^male$", r"^man$", r"^male\b", r"^man\b", r"\bmale\b"],
          "non-binary": [r"non-?binary", r"genderqueer", r"third gender"]}
RACE = {"asian": [r"^asian\b", r"\basian\b"], "white": [r"^white\b", r"\bwhite\b"],
        "black": [r"^black\b", r"african american"], "hispanic": [r"hispanic", r"latin"],
        "native american": [r"american indian", r"alaska native", r"native american"],
        "pacific islander": [r"hawaiian", r"pacific islander"], "two or more": [r"two or more", r"multi"]}


def eeo_pick(f, kind):
    opts = f["options"]
    v = norm(str(F.get(kind, "decline")))
    if v in ("decline", "none", ""):
        return pick(opts, DECLINE)
    table = GENDER if kind == "gender" else RACE
    for k, pats in table.items():
        if k in v:
            avoid = r"two or more" if kind == "race" and k != "two or more" else None
            return pick(opts, pats, avoid=avoid)
    return pick(opts, [re.escape(v)]) or pick(opts, DECLINE)


def company_is_former(company):
    c = norm(company)
    return any(norm(p).split()[0] in c for p in F.get("previous_employers", []) if p)


def salary_answer(f, tf):
    """Policy: top of a posted range; else 'Negotiable' (text) or a market estimate the report logs (numeric)."""
    top = (tf or {}).get("salary_max")
    if f["type"] in ("text", "textarea"):
        return (f"${top:,}" if top else "Negotiable"), ("posted top" if top else "negotiable")
    if f["type"] == "number":
        return (str(top) if top else None), ("posted top" if top else "estimate-needed")
    if f["type"] in ("select", "radio") and f["options"]:
        if not top:
            return None, "estimate-needed"
        best = None
        for o in f["options"]:
            ns = [int(x.replace(",", "")) * (1000 if k else 1) for x, k in re.findall(r"\$?(\d[\d,]*)\s*(k)?", o.lower())]
            if ns and min(ns) <= top <= max(ns) + 1:
                best = o
        return (best or f["options"][-1]), "posted top"
    return None, "estimate-needed"


def need(key, f):
    """A fact the person hasn't given: unknown when required, skipped when optional."""
    return (F[key], "fact") if F.get(key) else (None, "unknown" if f["required"] else "skip")


def rule_answer(f, job, tf, resume_pdf):
    """(value, basis) for questions with a fixed answer; (None, None) when the rules don't cover it."""
    L = norm(f["label"]); k = norm(f["key"]); t = f["type"]; opts = f["options"]
    if t == "hidden" or k in ("resume_text", "cover_letter_text"):
        return None, "skip"
    if t == "file":
        if re.search(r"resume|cv", L + k):
            return resume_pdf, "resume"
        if re.search(r"cover", L + k):
            return ("__COVER_LETTER__", "cover") if f["required"] else (None, "skip")
        if re.search(r"portfolio|work sample|case stud", L):
            return need("portfolio_pdf", f)
        return (None, None) if f["required"] else (None, "skip")
    # names and contact
    if re.search(r"first and last name|full name|legal name", L) and "middle" not in L:
        return F.get("full_name"), "fact"
    if re.search(r"preferred (first )?name", L):
        return F.get("preferred_name") or F.get("first_name"), "fact"
    if "middle name" in L:
        return need("middle_name", f)
    if k == "first_name" or re.fullmatch(r"(legal )?first name\*?", L):
        return F.get("first_name"), "fact"
    if k == "last_name" or re.fullmatch(r"(legal )?(last name|surname|family name)\*?", L):
        return F.get("last_name"), "fact"
    if k in ("name", "_systemfield_name") or re.search(r"^(full|legal)? ?name\b|your name", L):
        return F.get("full_name"), "fact"
    if t == "email" or k in ("email", "_systemfield_email") or re.fullmatch(r"e-?mail( address)?\*?", L):
        return F.get("email"), "fact"
    if t == "phone" or k == "phone" or re.search(r"^(phone|mobile|cell)( number)?\b", L):
        return F.get("phone"), "fact"
    if "linkedin" in L + k:
        return need("linkedin", f)
    if "github" in L + k:
        return need("github", f)
    if re.search(r"twitter|x\.com|other url|other website|dribbble|behance", L + k) and not f["required"]:
        return None, "skip"
    if re.search(r"portfolio|personal (web)?site|website|work samples", L + k) and t in ("text", "textarea"):
        if "password" in L:
            if F.get("website") and (re.search(r"link|url|portfolio and|portfolio &", L) or (f["required"] and "portfolio" in L)):
                return f"{F['website']} (public site, no password needed)", "fact"
            return ("No password needed", "fact") if f["required"] else (None, "skip")
        return need("website", f)
    # work authorization / sponsorship: deterministic, from the person's own confirmed answers
    if re.search(r"sponsor", L):
        v = yes_no(f, bool(F.get("sponsorship_now") or F.get("sponsorship_future"))) if t in ("boolean", "select", "radio", "checkbox") else ("Yes" if (F.get("sponsorship_now") or F.get("sponsorship_future")) else "No")
        if t in ("select", "radio") and not v and not (F.get("sponsorship_now") or F.get("sponsorship_future")):
            v = pick(opts, [r"do not (need|require)", r"not (need|require)", r"\bno\b"])
        return (v, "policy") if v is not None else (None, None)
    if re.search(r"(legally )?(authori[sz]ed|eligible|permitted) to work", L):
        ok = bool(F.get("work_authorized"))
        v = yes_no(f, ok) if t in ("boolean", "select", "radio", "checkbox") else ("Yes" if ok else "No")
        if t in ("select", "radio") and not v and ok:
            v = pick(opts, [r"\bi am authori[sz]ed", r"authori[sz]ed to work", r"\byes\b"], avoid=r"\bnot\b")
        return (v, "policy") if v is not None else (None, None)
    # location
    if t == "location" or k in ("location", "candidate-location") or re.fullmatch(r"(current )?location( \(city\))?\*?", L):
        return F.get("location_search") or F.get("location_text"), "fact"
    if re.search(r"\b(street|address line|mailing address|home address)\b", L):
        return need("address_line1", f)
    if re.search(r"zip ?code|postal|post code|^zip\b", L):
        return need("postal_code", f)
    if re.search(r"what city|city do you live|^city\b", L) and t == "text":
        return F.get("city"), "fact"
    if re.search(r"state of residen|which state|state do you (currently )?(live|reside)|where are you located|current state", L) and opts:
        v = pick(opts, [rf"^{re.escape(norm(F.get('state', '')))}\b", rf"\b{re.escape(norm(F.get('state_code', '')))}\b"]) if F.get("state") else None
        if v:
            return v, "fact"
    if re.search(r"^country\b|country of residence", L) and opts and F.get("country"):
        v = pick(opts, [rf"^{re.escape(norm(F['country']))}( of america)?$", rf"^{re.escape(norm(F['country']))}"])
        if v:
            return v, "fact"
    if k == "org" or re.search(r"current (company|employer)|most recent (company|employer)", L):
        return need("current_company", f)
    if re.search(r"current (job )?title|most recent (job )?title", L):
        return need("current_title", f)
    if re.search(r"(at least|over|older than) 18|18 years|age of 18", L):
        return yes_no(f, bool(F.get("age_18_plus", True))), "fact"
    # voluntary self-identification (the person's own choices in facts.json; "decline" is always allowed)
    if re.search(r"hispanic|latin[oa]", L) and not re.search(r"race", L):
        if opts:
            return tri(f, F.get("hispanic_latino", "decline"), [r"^yes\b", r"\bhispanic\b"], [r"^no\b", r"not hispanic"]), "eeo"
        return (F.get("hispanic_latino") if isinstance(F.get("hispanic_latino"), bool) and t == "boolean" else None), "eeo"
    if re.search(r"\bgender\b|\bsex\b", L) and not re.search(r"orientation|transgender", L) and opts:
        return eeo_pick(f, "gender"), "eeo"
    if re.search(r"\brace\b|ethnicit", L) and opts:
        return eeo_pick(f, "race"), "eeo"
    if "veteran" in L and opts:
        return tri(f, F.get("veteran", "decline"), [r"identify as one or more", r"protected veteran", r"^yes\b", r"i am a veteran"],
                   [r"not a (protected )?veteran", r"i am not", r"^no\b", r"not .*veteran"]), "eeo"
    if "disabilit" in L and opts:
        return tri(f, F.get("disability", "decline"), [r"^yes,? i have", r"\bi have a disability"],
                   [r"^no,? i (do not|don.?t) have a disability", r"do not have a disability", r"don.?t have a disability", r"^no\b"]), "eeo"
    if re.search(r"sexual orientation|lgbt|transgender|\btrans\b", L) and opts:
        return pick(opts, DECLINE), "decline"
    if "pronoun" in L:
        if F.get("pronouns") and opts:
            v = pick(opts, [re.escape(norm(F["pronouns"]))])
            if v:
                return ([v] if t == "multiselect" else v), "fact"
        if opts:
            v = pick(opts, DECLINE)
            return (([v] if t == "multiselect" else v), "decline") if v else (None, None)
        return (F["pronouns"], "fact") if F.get("pronouns") else ((None, "unknown") if f["required"] else (None, "skip"))
    # sourcing / history
    if re.search(r"how did you (hear|find|learn)|where did you (hear|find|learn)|source of (your )?application|referral source", L):
        if opts:
            return pick(opts, [r"company (web)?site", r"career(s)? (page|site|website)", r"company career", r"^website$",
                               r"\bwebsite\b", r"job board", r"^other\b"]), "policy"
        return F.get("how_heard", "Company website"), "policy"
    if re.search(r"were you referred|referred by|referral\b|know anyone|employee referral", L) and not re.search(r"who|name", L):
        if t == "text":
            return ("No" if f["required"] else None), "policy"
        return (pick(opts, [r"^no\b", r"^nope", r"found it on my own", r"not referred"]) if opts else yes_no(f, False)), "policy"
    if re.search(r"who referred|referrer|name of (the )?(employee|person)", L):
        return ("N/A" if f["required"] else None), ("policy" if f["required"] else "skip")
    if re.search(r"(previously|ever|before) (been )?(employed|worked|work)|former employee|current or former|have you worked (for|at)", L):
        return yes_no(f, company_is_former(job.get("company_display") or job["company"])), "policy"
    if re.search(r"salary|compensation|pay expectation|desired pay|expected pay", L):
        v, why = salary_answer(f, tf)
        return (v, "salary:" + why) if v else (None, None)
    if re.search(r"start date|when can you start|earliest (possible )?start|available to start|availability", L):
        if t == "date":
            return datetime.date.today().isoformat(), "policy"
        if opts:
            return pick(opts, [r"immediate", r"asap", r"as soon as", r"2 weeks|two weeks", r"less than"]), "policy"
        return F.get("start_date", "Immediately"), "policy"
    if "notice period" in L:
        return (F.get("notice_period", "Available immediately") if not opts else pick(opts, [r"immediate", r"none|no notice|0", r"less than"])), "policy"
    if re.search(r"marketing|newsletter|promotional|job alerts?|talent community|future (job )?opportunit|receive (updates|communications|emails)", L):
        if t == "checkbox":
            return None, "skip"
        if opts:
            v = pick(opts, [r"^no\b", r"do not|don.?t|opt out|unsubscribe"])
            return (v, "policy") if v else (None, None)
        if t == "boolean":
            return False, "policy"
    if t == "checkbox" and re.search(r"consent|agree|acknowledg|certif|privacy|terms|confirm", L):
        return True, "consent"
    if re.search(r"consent|acknowledg|i agree|certify", L) and opts:
        v = pick(opts, [r"^(yes|i agree|agree|i consent|i acknowledge|accept)", r"\bagree\b|\bconsent\b|\backnowledge\b"],
                 avoid=r"\b(not|don.?t|do not|disagree)\b")
        if v:
            return v, "consent"
    if f.get("section") in ("demographic", "eeoc", "eeo", "survey") and opts:
        v = pick(opts, DECLINE)
        if v:
            return v, "decline"
    return None, None


ANS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["answers", "cover_letter"],
    "properties": {
        "answers": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                               "required": ["key", "value", "basis", "note"],
                                               "properties": {"key": {"type": "string"},
                                                              "value": {"type": ["string", "boolean", "array", "null"], "items": {"type": "string"}},
                                                              "basis": {"type": "string", "enum": ["profile", "policy", "essay", "decline", "skip", "unknown"]},
                                                              "note": {"type": "string"}}}},
        "cover_letter": {"type": ["string", "null"]}}}


def system_prompt():
    return f"""You fill job application forms for {core.candidate_name()}, truthfully. You never invent facts about them.
Answer each question from their profile and the fixed facts below.
- "profile"/"policy": answers that follow directly from the material below.
- "essay": short first-person answers to open questions (why this company, describe a project, etc.), built only from
  real profile facts and case studies, specific to this job, 60-150 words unless the question asks for less. Warm, plain,
  professional. No invented numbers, tools, employers or experiences.
- "decline": a voluntary demographic question answered with its decline option.
- "skip": an OPTIONAL question that isn't worth answering or can't be answered truthfully.
- "unknown": a REQUIRED question whose answer is not in the material (personal preferences, life facts not recorded,
  self-ratings, years with a specific tool or discipline the profile doesn't state). Never guess these.
If the profile clearly shows the candidate lacks something (people management, a clearance, a degree, a language),
answer truthfully with No / 0 / None rather than "unknown".
For select/radio/multiselect questions, "value" must be copied exactly from the given options. Booleans: true/false.
Preference questions (company stage, size, industry, employment type): use the candidate's stated preferences;
if they are open to all, select every option or the "any / no preference" option.
Office / relocation questions: onsite or hybrid is acceptable only in: {", ".join(LOC.get("onsite_keywords", [])[:12]) or "nowhere (remote only)"}.
If the candidate already lives near the office, prefer an option meaning "already local / no relocation needed".
Years of experience: use the profile's stated total; never round up, and never transfer it to a different discipline.

=== FIXED FACTS ===
{json.dumps({k: v for k, v in F.items() if not k.startswith('_')}, indent=0)}

=== CANDIDATE PROFILE ===
{core.profile_text()}
"""


def valid_value(f, v):
    t = f["type"]
    if v is None:
        return None
    if t in ("select", "radio"):
        if isinstance(v, list):
            v = v[0] if v else None
        if v is None:
            return None
        ex = [o for o in f["options"] if norm(o) == norm(v)]
        if ex:
            return ex[0]
        ex = [o for o in f["options"] if norm(v) and (norm(v) in norm(o) or norm(o) in norm(v))]
        return ex[0] if len(ex) == 1 else None
    if t == "multiselect":
        out = [valid_value({"type": "select", "options": f["options"]}, x) for x in (v if isinstance(v, list) else [v])]
        return [x for x in out if x] or None
    if t in ("boolean", "checkbox"):
        if isinstance(v, bool):
            return v
        return {"yes": True, "true": True, "no": False, "false": False}.get(norm(str(v)))
    if isinstance(v, list):
        v = " ".join(str(x) for x in v)
    return str(v).strip() or None


def answer_form(job, src, tailor_res, resume_pdf):
    fields = src["fields"]
    tf = (tailor_res or {}).get("facts") or {}
    answers, basis, unknown, notes, need_llm = {}, {}, [], [], []
    for f in fields:
        v, b = rule_answer(f, job, tf, resume_pdf)
        if b == "skip":
            continue
        if b == "unknown":
            unknown.append(f["label"] + " (not in the profile yet)")
            continue
        if v is not None and b:
            vv = v if (f["type"] == "file" or v == "__COVER_LETTER__") else (
                valid_value(f, v) if f["type"] in ("select", "radio", "multiselect", "boolean", "checkbox") else v)
            if vv is not None:
                answers[f["key"]] = vv; basis[f["key"]] = b
                continue
        need_llm.append(f)
    cover = None
    wants_cover = any(v == "__COVER_LETTER__" for v in answers.values())
    if need_llm or wants_cover:
        qs = [{"key": f["key"], "label": f["label"], "type": f["type"], "required": f["required"],
               "options": f["options"][:60], "description": f.get("description", "")[:300]} for f in need_llm]
        prompt = f"""JOB: {src.get('title')} at {tf.get('company_display_name') or src.get('company_name')} ({src.get('location')})
Work mode: {tf.get('work_mode')}; offices: {tf.get('office_locations')}; posted pay: {src.get('pay')}

JOB DESCRIPTION (for essay answers):
{src.get('jd', '')[:6000]}

QUESTIONS TO ANSWER (JSON):
{json.dumps(qs, indent=0)}

{"COVER LETTER: this application requires one. Write it (250-330 words, 4 short paragraphs, first person, addressed 'Dear Hiring Team,', signed with the candidate's name), using only real profile facts, specific to this role." if wants_cover else "cover_letter: null"}
Return one answer object per question key."""
        r = llm.ask_json(system_prompt(), prompt, ANS_SCHEMA, timeout=420)
        got = {a["key"]: a for a in r.get("answers", [])}
        allowed_nums = set(re.findall(r"\d[\d,\.]*\+?%?", core.profile_text().replace(",", "")))
        for f in need_llm:
            a = got.get(f["key"])
            if not a or a["basis"] in ("unknown", "skip") or a["value"] in (None, "", []):
                if f["required"]:
                    unknown.append(f["label"])
                continue
            vv = valid_value(f, a["value"])
            if vv is None:
                if f["required"]:
                    unknown.append(f["label"] + " (no valid option)")
                continue
            if isinstance(vv, str) and f["type"] in ("text", "textarea") and a["basis"] == "essay":
                bad = [n for n in re.findall(r"\d[\d,\.]*\+?%?", vv.replace(",", "")) if n not in allowed_nums]
                if bad:
                    if f["required"]:
                        unknown.append(f["label"] + f" (essay used numbers not in the profile: {bad[:3]})")
                    continue
            answers[f["key"]] = vv; basis[f["key"]] = a["basis"]
            if a.get("note"):
                notes.append(f"{f['label'][:60]}: {a['note'][:120]}")
        cover = r.get("cover_letter") if wants_cover else None
        if wants_cover and not cover:
            unknown.append("Cover letter (required)")
    return {"answers": answers, "basis": basis, "unknown_required": unknown, "notes": notes, "cover_letter": cover}
