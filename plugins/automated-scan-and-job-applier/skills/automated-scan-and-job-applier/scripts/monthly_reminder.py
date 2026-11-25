"""Monthly nudge to review the master resume and profile (scheduled on the 1st)."""
import subprocess
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core, mailer

msg = ("Time for the monthly review of your master resume and profile: new projects, metrics, skills or "
       "preferences? Update profile.md, resume/master.json and resume/bank.json, then rebuild the master PDF.")
mailer.send("Monthly review: master resume and profile", f"<p>{msg}</p>")
if core.CONFIG.get("ntfy_topic"):
    subprocess.run(["curl", "-fsS", "-H", "Title: Monthly master resume review", "-d", msg,
                    f"{core.CONFIG.get('ntfy_server', 'https://ntfy.sh')}/{core.CONFIG['ntfy_topic']}"], capture_output=True)
print("reminder sent")
