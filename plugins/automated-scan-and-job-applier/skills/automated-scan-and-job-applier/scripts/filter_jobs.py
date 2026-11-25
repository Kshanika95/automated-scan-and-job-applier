"""Second-stage filter: scan output -> queue (state/jobs.jsonl).

Reads career-ops-style scan lines:
  + [ashby-full] 2026-11-23 | company | Title | Location
    https://...
Applies search.json (title tracks, exclusions, locations, aggregators), dedupes by URL, appends new
matches with status "queued", and prints a JSON summary.  Usage: filter_jobs.py SCAN_LOG
"""
import json, re, sys, datetime
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core

S = core.SEARCH
LOC = S.get("locations", {})
TRACKS = sorted(S.get("tracks", []), key=lambda t: t.get("priority", 9))
EXCLUDE = S.get("exclude_title_regex") or r"$^"
AGGREGATORS = {a.lower() for a in S.get("aggregator_blocklist", [])}


def classify(title):
    t = title.lower()
    if re.search(EXCLUDE, t):
        return None
    for tr in TRACKS:
        if re.search(tr["title_regex"], t):
            if tr.get("title_must_also_match") and not re.search(tr["title_must_also_match"], t):
                return None
            return tr.get("priority", 9), tr["name"]
    return None


def place(loc):
    l = " " + loc.lower() + " "
    if any(k.lower() in l for k in LOC.get("onsite_keywords", [])):
        return "onsite-ok"
    if not LOC.get("remote", True):
        return None
    remote = "remote" in l or "anywhere" in l
    countries = [k.lower() for k in LOC.get("remote_country_keywords", [])]
    if remote and any(k.lower() in l for k in LOC.get("remote_exclude_keywords", [])) and not any(c in l for c in countries):
        return None
    if remote and (any(c in l for c in countries) or l.strip() == "remote"):
        return "remote"
    return None


def main(scan_log):
    seen = {j["url"] for j in core.load_jobs()}
    lines = open(scan_log, errors="ignore").read().splitlines()
    found = new = 0
    rej = {"track": 0, "location": 0, "aggregator": 0, "dupe": 0}
    with core.JOBS.open("a") as out:
        for i, line in enumerate(lines):
            m = re.match(r"\s*\+ \[([^\]]+)\] (\S+) \| ([^|]+) \| ([^|]+) \| (.*)$", line)
            if not m or i + 1 >= len(lines):
                continue
            url = lines[i + 1].strip()
            if not url.startswith("http"):
                continue
            found += 1
            src, date, company, title, loc = [x.strip() for x in m.groups()]
            if company.lower() in AGGREGATORS:
                rej["aggregator"] += 1; continue
            c = classify(title)
            if not c:
                rej["track"] += 1; continue
            p = place(loc)
            if not p:
                rej["location"] += 1; continue
            if url in seen:
                rej["dupe"] += 1; continue
            seen.add(url); new += 1
            out.write(json.dumps({"url": url, "company": company, "title": title, "location": loc, "where": p,
                                  "track": c[1], "priority": c[0], "posted": date, "source": src, "status": "queued",
                                  "found_at": datetime.datetime.now().isoformat(timespec="seconds")}) + "\n")
    print(json.dumps({"scanned_matches": found, "new_queued": new, "rejected": rej}))


if __name__ == "__main__":
    main(sys.argv[1])
