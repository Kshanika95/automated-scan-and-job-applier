"""Install or remove the schedule.   schedule.py install | remove | show
macOS: LaunchAgents (hourly run, evening report, per-job emails 5 minutes later, monthly reminder).
Linux: prints crontab lines to add with `crontab -e`.
The person must be logged in for LaunchAgents to run; keep the machine awake (or schedule on a server)."""
import os, pathlib, plistlib, subprocess, sys
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core

W = str(core.HOME)
H = int(core.CONFIG.get("report_hour", 21))
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"
JOBS = {
    "run": (["/bin/zsh", f"{W}/run.sh"], {"Minute": 0}),
    "report": ([PY, "-I", f"{W}/daily_report.py"], {"Hour": H, "Minute": 0}),
    "manual": ([PY, "-I", f"{W}/manual_emails.py"], {"Hour": H, "Minute": 5}),
    "monthly": ([PY, "-I", f"{W}/monthly_reminder.py"], {"Day": 1, "Hour": 10, "Minute": 0}),
}
PREFIX = "com.job-applier." + core.HOME.name.lower().replace(" ", "-")
LA = pathlib.Path.home() / "Library/LaunchAgents"


def install_mac():
    LA.mkdir(parents=True, exist_ok=True)
    for name, (args, when) in JOBS.items():
        label = f"{PREFIX}.{name}"
        p = LA / f"{label}.plist"
        plistlib.dump({"Label": label, "ProgramArguments": args, "StartCalendarInterval": when,
                       "EnvironmentVariables": {"JOB_APPLIER_HOME": W, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                       "StandardOutPath": f"{W}/logs/{name}.out.log", "StandardErrorPath": f"{W}/logs/{name}.err.log"},
                      p.open("wb"))
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
        subprocess.run(["launchctl", "load", str(p)], check=True)
        print("loaded", label)


def remove_mac():
    for name in JOBS:
        p = LA / f"{PREFIX}.{name}.plist"
        if p.exists():
            subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
            p.unlink()
            print("removed", p.name)


def cron_lines():
    spec = {"run": "0 * * * *", "report": f"0 {H} * * *", "manual": f"5 {H} * * *", "monthly": "0 10 1 * *"}
    return "\n".join(f"{spec[n]} JOB_APPLIER_HOME={W} {' '.join(a)} >> {W}/logs/{n}.cron.log 2>&1" for n, (a, _) in JOBS.items())


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["show"])[0]
    if sys.platform == "darwin" and cmd == "install":
        install_mac()
    elif sys.platform == "darwin" and cmd == "remove":
        remove_mac()
    else:
        print("Add these lines with `crontab -e`:\n" + cron_lines())
