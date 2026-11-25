"""Shared paths, configuration and secrets for the job applier.

Everything lives in one workspace folder: $JOB_APPLIER_HOME, or the folder this file sits in
(install.sh copies the scripts into the workspace, so that is normally the same place).

  config.json   how the system runs (email, caps, which sites may submit, notifications)
  search.json   what to look for (title tracks, locations, fit rules)
  facts.json    the candidate's confirmed form answers (name, contact, work authorization, EEO choices)
  profile.md    the candidate's master profile: the only source of truth for resumes and answers
  resume/master.json, resume/bank.json   master resume content and the approved bullet bank
"""
import json, os, pathlib, shutil, subprocess, sys

HOME = pathlib.Path(os.environ.get("JOB_APPLIER_HOME") or pathlib.Path(__file__).resolve().parent).expanduser()
STATE, LOGS, APPS = HOME / "state", HOME / "logs", HOME / "applications"
for _d in (STATE, LOGS, APPS):
    _d.mkdir(parents=True, exist_ok=True)
if str(HOME / "pylib") not in sys.path:
    sys.path.insert(0, str(HOME / "pylib"))       # vendored pypdf (install.sh)


def load_json(name, default=None):
    p = HOME / name
    if not p.exists():
        return {} if default is None else default
    return json.loads(p.read_text())


CONFIG = load_json("config.json")
FACTS = load_json("facts.json")
SEARCH = load_json("search.json")
PROFILE_PATH = HOME / CONFIG.get("profile_file", "profile.md")
JOBS = STATE / "jobs.jsonl"


def profile_text():
    return PROFILE_PATH.read_text() if PROFILE_PATH.exists() else ""


def candidate_name():
    return FACTS.get("full_name") or CONFIG.get("candidate_name") or "the candidate"


def node():
    return CONFIG.get("node") or shutil.which("node") or str(pathlib.Path.home() / ".local/node/bin/node")


def claude():
    return CONFIG.get("claude") or shutil.which("claude") or str(pathlib.Path.home() / ".local/bin/claude")


def secret(name="email_app_password"):
    """Look up a secret without ever storing it in the workspace:
    1. environment variable JOB_APPLIER_<NAME>
    2. macOS Keychain: service = config.secret_service (default "job-applier-email"), account = config.email
    3. a private file ~/.config/job-applier/<name> (chmod 600)"""
    env = os.environ.get("JOB_APPLIER_" + name.upper())
    if env:
        return env.strip()
    if sys.platform == "darwin" and shutil.which("security"):
        r = subprocess.run(["security", "find-generic-password", "-a", CONFIG.get("email", ""),
                            "-s", CONFIG.get("secret_service", "job-applier-email"), "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().replace(" ", "")
    f = pathlib.Path.home() / ".config/job-applier" / name
    if f.exists():
        return f.read_text().strip().replace(" ", "")
    return ""


def load_jobs():
    return [json.loads(l) for l in JOBS.open()] if JOBS.exists() else []
