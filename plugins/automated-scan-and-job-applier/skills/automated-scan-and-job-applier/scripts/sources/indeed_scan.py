"""Indeed discovery through the Indeed connector (claude.ai MCP), run headless.

Claude.ai connectors finish connecting a few seconds after a headless session starts, so we
keep one session open (stream-json input): turn 1 is a warm-up, turn 2 runs the searches,
turn 3 fetches full descriptions for the postings that are new.

Indeed is used for DISCOVERY only. We don't log in to Indeed or automate it. Each new posting is
matched to the employer's own Greenhouse / Lever / Ashby / Workday board when possible (then it is
auto-applied there); otherwise it goes to the manual list with a tailored resume.

Prints scan lines for filter_jobs.py; saves descriptions to state/indeed/<id>.json
"""
import json, re, subprocess, sys, time, pathlib, hashlib, datetime, os, select

A = pathlib.Path(os.environ.get("JOB_APPLIER_HOME") or pathlib.Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(A)); sys.path.insert(0, str(A / "sources"))
import core
CLAUDE = core.claude()
OUTDIR = A / "state/indeed"; OUTDIR.mkdir(parents=True, exist_ok=True)
SEEN = A / "state/indeed_seen.json"
QUERIES = core.SEARCH.get("indeed_queries") or (core.SEARCH.get("scan_keywords") or [])[:4]
LOCATIONS = core.SEARCH.get("indeed_locations") or ["remote"]
TOOLS = "mcp__claude_ai_Indeed__search_jobs,mcp__claude_ai_Indeed__get_job_details"


def env():
    e = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k != "CLAUDECODE"}
    e["PATH"] = os.pathsep.join([os.path.dirname(CLAUDE), "/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin"])
    return e


class Session:
    def __init__(self):
        self.p = subprocess.Popen([CLAUDE, "-p", "--model", "haiku", "--tools", "", "--allowedTools", TOOLS,
                                   "--system-prompt", "You relay Indeed connector results as exact JSON. Never invent jobs or fields.",
                                   "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                                   "--no-session-persistence"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                  env=env(), cwd=str(A / "state"))

    def ask(self, text, timeout=600):
        self.p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
        self.p.stdin.flush()
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.p.stdout], [], [], 5)
            if not r:
                continue
            line = self.p.stdout.readline()
            if not line:
                break
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "result":
                return d.get("result") or ""
        return ""

    def close(self):
        try:
            self.p.stdin.close(); self.p.wait(timeout=30)
        except Exception:
            self.p.kill()


def parse_json_block(text):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def key(j):
    return hashlib.sha1(f"{j.get('company','').lower()}|{j.get('title','').lower()}|{j.get('location','').lower()}".encode()).hexdigest()[:16]


def main():
    since_days = int(sys.argv[sys.argv.index("--since") + 1]) if "--since" in sys.argv else 3
    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
    jobs, new, details = [], [], {}
    for attempt in range(2):
        if attempt:
            time.sleep(60)                       # connector rate limit: wait, then one more try
        s = Session()
        try:
            s.ask("Reply with just: ready", timeout=120)
            time.sleep(15)                       # let the claude.ai connectors finish connecting
            searches = [{"search": q, "location": l} for q in QUERIES for l in LOCATIONS]
            txt = s.ask(
                "Call the Indeed search_jobs tool once for EACH of these searches (country_code \"US\"):\n"
                + json.dumps(searches) +
                "\nThen output ONE JSON array with every job returned, deduplicated, each as "
                '{"job_id": "...", "title": "...", "company": "...", "location": "...", "posted": "YYYY-MM-DD", '
                '"compensation": "...", "url": "..."}. Copy values exactly from the tool output. Output only the JSON array. '
                'If the Indeed tool is not available, output exactly: UNAVAILABLE',
                timeout=900)
            if "UNAVAILABLE" in txt or not txt.strip().startswith("["):
                print(f"indeed: connector unavailable (attempt {attempt + 1}): {txt[:160]!r}", file=sys.stderr)
                continue
            jobs = parse_json_block(txt)
            cutoff = (datetime.date.today() - datetime.timedelta(days=since_days)).isoformat()
            new = [j for j in jobs if j.get("title") and j.get("company") and key(j) not in seen and (j.get("posted") or "9") >= cutoff]
            if new:
                want = [j["job_id"] for j in new][:25]
                txt2 = s.ask(
                    "Call get_job_details for each of these job ids: " + json.dumps(want) +
                    '. Output ONE JSON array of {"job_id": "...", "description": "<the full description text>"}, copied '
                    "exactly from the tool output (plain text). Output only the JSON array.", timeout=900)
                for d in parse_json_block(txt2):
                    details[d.get("job_id")] = d.get("description", "")
            break
        finally:
            s.close()
    import resolve_ats
    lines = []
    for j in new:
        k = key(j)
        seen[k] = datetime.date.today().isoformat()
        jd = details.get(j["job_id"], "")
        rec = {"indeed": j, "jd": jd, "resolved": None}
        try:
            rec["resolved"] = resolve_ats.resolve(j["company"], j["title"])
        except Exception as e:
            rec["resolve_error"] = str(e)[:200]
        (OUTDIR / f"{k}.json").write_text(json.dumps(rec, indent=1))
        url = (rec["resolved"] or {}).get("url") or f"{j.get('url') or 'https://www.indeed.com/'}#indeed={k}"
        src = "indeed→" + rec["resolved"]["ats"] if rec["resolved"] else "indeed"
        lines.append(f"  + [{src}] {j.get('posted','')} | {j['company'].replace('|','/')} | {j['title'].replace('|','/')} | {j.get('location','').replace('|','/')}\n    {url}")
    SEEN.write_text(json.dumps(seen))
    print("\n".join(lines))
    print(f"indeed: {len(jobs)} results, {len(new)} new, {sum(1 for l in lines if 'indeed→' in l)} matched to an ATS", file=sys.stderr)


if __name__ == "__main__":
    main()
