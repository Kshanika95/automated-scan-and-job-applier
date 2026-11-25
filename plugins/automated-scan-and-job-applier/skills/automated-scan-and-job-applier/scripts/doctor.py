"""Check that the workspace is ready, and say exactly what to fix.   Usage: doctor.py [--quick]
--quick skips the network and Claude checks."""
import imaplib, os, pathlib, shutil, subprocess, sys
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core

ok_all = True


def check(name, ok, fix=""):
    global ok_all
    ok_all &= bool(ok)
    print(("  ✅ " if ok else "  ❌ ") + name + ("" if ok else f"\n      → {fix}"))


C, F, S = core.CONFIG, core.FACTS, core.SEARCH
quick = "--quick" in sys.argv
print(f"Workspace: {core.HOME}")
print("Files")
check("config.json has your email", bool(C.get("email")) and "example" not in C.get("email", ""), "set \"email\" in config.json")
check("facts.json filled in", bool(F.get("full_name")) and "Example" not in F.get("full_name", ""), "fill facts.json from the person's confirmed answers")
check("profile.md written", core.PROFILE_PATH.exists() and "EXAMPLE PROFILE" not in core.profile_text(), "write profile.md (references/profile-guide.md)")
check("resume/master.json and bank.json exist", (core.HOME / "resume/master.json").exists() and (core.HOME / "resume/bank.json").exists(),
      "create them from the profile (references/profile-guide.md)")
check("search.json has title tracks", bool(S.get("tracks")), "add tracks to search.json")
pdf = core.HOME / "resume/out" / f"{core.candidate_name()} Resume.pdf"
check("master resume PDF built", pdf.exists(), f"python3 -I {core.HOME}/resume/build_resume.py {core.HOME}/resume/master.json '{pdf}'")
print("Tools")
check("node", bool(shutil.which(core.node()) or os.path.exists(core.node())), "install Node.js 18+ or set config.node")
check("playwright installed in the workspace", (core.HOME / "node_modules/playwright").exists(), f"cd {core.HOME} && npm install")
check("pypdf vendored", (core.HOME / "pylib/pypdf").exists(), f"python3 -m pip install --target {core.HOME}/pylib pypdf")
co = pathlib.Path(C.get("career_ops_dir", "career-ops")); co = co if co.is_absolute() else core.HOME / co
check("career-ops scanner present", (co / "scan-ats-full.mjs").exists(), "re-run install.sh")
check("career-ops portals.yml generated", (co / "portals.yml").exists(), f"node {core.HOME}/mkportals.mjs")
check("claude CLI", bool(shutil.which(core.claude()) or os.path.exists(core.claude())), "install Claude Code, or set config.claude to its path")
print("Safety settings")
print(f"  ℹ️  live_ats = {C.get('live_ats', [])}  (empty = dry runs only)")
print(f"  ℹ️  daily_cap = {C.get('daily_cap', 20)}, per_company_30d = {C.get('per_company_30d', 2)}")
if not quick:
    print("Connections")
    pw = core.secret()
    check("email app password found", bool(pw), "see references/setup.md → Email")
    if pw:
        try:
            M = imaplib.IMAP4_SSL(C.get("imap_host", "imap.gmail.com"), 993)
            M.login(C["email"], pw); M.logout()
            check("IMAP login works", True)
        except Exception as e:
            check("IMAP login works", False, f"{e} (use an app password; turn on IMAP in the mailbox settings)")
    try:
        import llm
        r = llm.ask_json("Return the requested JSON.", 'Return {"ok": true}', {"type": "object", "properties": {"ok": {"type": "boolean"}},
                         "required": ["ok"], "additionalProperties": False}, timeout=120, tries=1)
        check("headless Claude answers", r.get("ok") is True)
    except Exception as e:
        check("headless Claude answers", False, f"{str(e)[:160]} (run `claude` once and log in)")
    if C.get("ntfy_topic"):
        r = subprocess.run(["curl", "-fsS", "-d", "job applier: test notification", f"{C.get('ntfy_server', 'https://ntfy.sh')}/{C['ntfy_topic']}"],
                           capture_output=True)
        check("ntfy notification sent", r.returncode == 0, "check ntfy_topic / ntfy_server")
print("\nAll good." if ok_all else "\nFix the ❌ items above, then run doctor.py again.")
sys.exit(0 if ok_all else 1)
