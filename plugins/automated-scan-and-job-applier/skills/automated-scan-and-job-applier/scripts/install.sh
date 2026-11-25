#!/bin/zsh
# Install or upgrade the job applier into a workspace folder (default ~/job-applier).
# Safe to re-run: scripts are refreshed; your config, profile, resume files, state and logs are never overwritten.
#   zsh install.sh [WORKSPACE]
set -e
SKILL_DIR="${0:A:h:h}"                    # .../skills/automated-scan-and-job-applier
W="${1:-${JOB_APPLIER_HOME:-$HOME/job-applier}}"
echo "Workspace: $W"
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1. $2"; exit 1; }; }
need python3 "Install Python 3.9 or newer."
need node "Install Node.js 18 or newer (https://nodejs.org)."
need npm "Install Node.js 18 or newer (npm comes with it)."
need git "Install git."
command -v claude >/dev/null 2>&1 || echo "Note: the 'claude' CLI was not found on PATH. Set config.json \"claude\" to its full path."

mkdir -p "$W"/{state,logs,applications,resume/out}
rsync -a --exclude 'node_modules' "$SKILL_DIR/scripts/" "$W/"
chmod +x "$W/run.sh" "$W/install.sh" 2>/dev/null || true
for f in config.json search.json facts.json profile.md; do
  [ -f "$W/$f" ] || cp "$SKILL_DIR/templates/$f" "$W/$f"
done
for f in master.json bank.json; do
  [ -f "$W/resume/$f" ] || cp "$SKILL_DIR/templates/resume/$f" "$W/resume/$f"
done

echo "Installing Python dependency (pypdf) into $W/pylib ..."
python3 -m pip install --quiet --upgrade --target "$W/pylib" pypdf >/dev/null
echo "Installing Playwright into $W/node_modules ..."
(cd "$W" && npm install --silent --no-audit --no-fund >/dev/null)
if [ -z "$CHROME_PATH" ]; then
  (cd "$W" && npx --yes playwright install chromium >/dev/null 2>&1) || echo "Note: 'npx playwright install chromium' failed. On older macOS, set config.json \"chrome_path\" to a Chrome/Chromium binary."
fi
CO=$(python3 -c "import json,os; d=json.load(open('$W/config.json')).get('career_ops_dir','career-ops'); print(d if os.path.isabs(d) else os.path.join('$W', d))")
if [ ! -d "$CO" ]; then
  echo "Fetching the career-ops scanner (MIT, https://github.com/career-ops-hq/career-ops) ..."
  git clone --quiet --depth 1 https://github.com/career-ops-hq/career-ops "$CO"
fi
[ -d "$CO/node_modules" ] || (cd "$CO" && npm install --silent --no-audit --no-fund >/dev/null)

cat <<MSG

Installed. Next steps (Claude walks you through them; see the skill's SKILL.md):
  1. Build your profile:   $W/profile.md, facts.json, resume/master.json, resume/bank.json
  2. Set your search:      $W/search.json, then:  node $W/mkportals.mjs
  3. Configure email etc.: $W/config.json (and store the app password: see references/setup.md)
  4. Check everything:     python3 -I $W/doctor.py
  5. Dry runs first; switch on submission per site with config.json "live_ats" only after reviewing them.
MSG
