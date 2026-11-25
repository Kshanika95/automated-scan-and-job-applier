"""Find a job (company + title, e.g. from Indeed) on the employer's own ATS board.

Tries Greenhouse, Lever and Ashby board slugs derived from the company name. Returns {"ats", "url"} for a confident title match, else None.
"""
import json, re, urllib.request, urllib.parse, pathlib, difflib

UA = "Mozilla/5.0 (compatible; automated-scan-and-job-applier/1.0; personal job search)"
SUFFIX = {"inc", "llc", "corp", "corporation", "co", "company", "ltd", "technologies", "technology", "labs", "group",
          "holdings", "the", "hq", "ai", "io", "usa", "us", "international", "global", "systems", "solutions"}


def get(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json",
                                                         **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def slugs(company):
    w = re.sub(r"[^a-z0-9 ]", " ", company.lower().replace("&", " and ")).split()
    core = [x for x in w if x not in SUFFIX] or w
    c = ["".join(core), "-".join(core), "".join(w), core[0] if core else ""]
    return [s for i, s in enumerate(c) if s and s not in c[:i]]


def tnorm(t):
    t = re.sub(r"\(.*?\)", " ", t.lower())
    t = re.sub(r"\bsr\.?\b", "senior", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def same_title(a, b):
    a, b = tnorm(a), tnorm(b)
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def resolve(company, title):
    for s in slugs(company):
        d = get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs")
        for j in (d or {}).get("jobs", []):
            if same_title(j["title"], title):
                return {"ats": "greenhouse", "url": f"https://job-boards.greenhouse.io/{s}/jobs/{j['id']}", "board": s}
        d = get(f"https://api.lever.co/v0/postings/{s}?mode=json")
        for j in d or []:
            if isinstance(j, dict) and same_title(j.get("text", ""), title):
                return {"ats": "lever", "url": j.get("hostedUrl"), "board": s}
        d = get(f"https://api.ashbyhq.com/posting-api/job-board/{s}")
        for j in (d or {}).get("jobs", []):
            if same_title(j.get("title", ""), title) and j.get("jobUrl"):
                return {"ats": "ashby", "url": j["jobUrl"], "board": s}
    # (no Workday lookup: Workday applications need a human anyway)
    return None


if __name__ == "__main__":
    import sys
    print(resolve(sys.argv[1], sys.argv[2]))
