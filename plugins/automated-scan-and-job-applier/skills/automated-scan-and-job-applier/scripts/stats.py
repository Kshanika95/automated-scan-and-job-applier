"""Counts for the run log and the phone notification.
  stats.py                                  -> one-line counts
  stats.py --pulse NEW WORKER_JSON MINUTES  -> notification text
"""
import datetime, json, sys
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core

TODAY = datetime.date.today().isoformat()
J = core.load_jobs()
applied = [j for j in J if j.get("status") == "applied" and j.get("applied_at", "").startswith(TODAY)]
manual = [j for j in J if j.get("status") in ("manual", "dry_run_ok") and j.get("updated_at", "").startswith(TODAY)]
queued = [j for j in J if j.get("status") == "queued"]

if "--pulse" in sys.argv:
    new, worker, mins = (sys.argv[sys.argv.index("--pulse") + 1:] + ["?", "{}", "?"])[:3]
    try:
        w = json.loads(worker or "{}")
    except Exception:
        w = {}
    names = ", ".join(j.get("company_display") or j["company"] for j in applied[-4:])
    lines = [f"Applied this run: {w.get('applied', 0)} · today: {len(applied)}/{core.CONFIG.get('daily_cap', 20)}" + (f" ({names})" if applied else ""),
             f"New matching roles: {new} · in queue: {len(queued)} · for you to submit today: {len(manual)}"]
    extra = []
    if w.get("skipped"):
        extra.append(f"{w['skipped']} skipped as weak fit")
    if w.get("llm_error"):
        extra.append("⚠️ Claude usage limit hit, applying paused")
    if extra:
        lines.append(" · ".join(extra))
    lines.append(f"{mins} min")
    print("\n".join(lines))
else:
    print(f"applied_today={len(applied)} manual_today={len(manual)} queued={len(queued)}")
