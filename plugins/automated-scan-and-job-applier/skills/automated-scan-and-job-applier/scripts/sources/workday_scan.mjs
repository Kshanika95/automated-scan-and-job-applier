// Workday scan, polite and time-boxed. Workday career sites sit behind a rate limiter: stay slow, stop at the
// first HTTP 429 for this run, and never switch clients or disguise traffic to get around a limit.
//
// Workday sits behind Cloudflare and rate-limits bursts (HTTP 429), so we never
// list whole boards. Per tenant we run a few keyword searches and fetch details
// only for matching titles. Each run spends a fixed time budget:
//   1. "hot" tenants every run: big employers plus any tenant that has posted a
//      matching role before (state/workday_hot.json grows automatically);
//   2. the rest of the ~12k tenants in rotation (state/workday_cursor.json).
// Prints career-ops-style scan lines for filter_jobs.py:
//   + [workday] 2026-11-24 | Company | Title | Location
//     https://tenant.wdN.myworkdayjobs.com/site/job/...
// Usage: node workday_scan.mjs [--since DAYS] [--budget SECONDS] [--concurrency N] [--hot-only]
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DIR = process.env.JOB_APPLIER_HOME || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DATA = path.join(DIR, 'sources/workday_tenants.json');
const SEED_HOT = path.join(DIR, 'sources/workday_hot_seed.txt');
const HOT = path.join(DIR, 'state/workday_hot.json');
const HEALTH = path.join(DIR, 'state/workday_health.json');
const CURSOR = path.join(DIR, 'state/workday_cursor.json');
const DATASET = 'https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/workday_companies.json';
const UA = 'Mozilla/5.0 (compatible; automated-scan-and-job-applier/1.0; personal job search)';
const SEARCH = (() => { try { return JSON.parse(fs.readFileSync(path.join(DIR, 'search.json'), 'utf8')); } catch { return {}; } })();
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const SINCE = +opt('--since', 2);
const BUDGET = +opt('--budget', 480) * 1000;
const conc = +opt('--concurrency', 2);
const HOT_ONLY = args.includes('--hot-only');
// Keyword searches per tenant (Workday's own search) and a loose title pre-filter; filter_jobs.py does the real filtering.
const QUERIES = (SEARCH.workday_queries || SEARCH.scan_keywords || []).slice(0, 3);
const TITLE_RX = new RegExp((SEARCH.tracks || []).map(t => t.title_regex).join('|') || '.', 'i');
const SKIP_RX = new RegExp(SEARCH.exclude_title_regex || '$^', 'i');
const today = new Date();
const iso = (d) => d.toISOString().slice(0, 10);
const readJson = (f, d) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return d; } };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function loadTenants() {
  let st = null;
  try { st = fs.statSync(DATA); } catch {}
  if (!st || Date.now() - st.mtimeMs > 7 * 864e5) {
    try {
      const r = await fetch(DATASET, { signal: AbortSignal.timeout(60000), headers: { 'user-agent': UA } });
      if (r.ok) fs.writeFileSync(DATA, await r.text());
    } catch {}
  }
  return readJson(DATA, []);
}

function postedDays(s) {
  if (!s) return 99;
  if (/today/i.test(s)) return 0;
  if (/yesterday/i.test(s)) return 1;
  const m = s.match(/(\d+)\+?\s+Days?/i);
  return m ? +m[1] : 99;
}

let throttled = false, n429 = 0;
// Polite client: few workers, a pause after every request, and on the first HTTP 429
// the whole Workday pass stops for this hour (no retries, no switching clients).
async function getJson(url, body) {
  if (throttled) { const e = new Error('throttled'); e.status = 429; throw e; }
  const r = await fetch(url, {
    method: body ? 'POST' : 'GET',
    headers: { 'content-type': 'application/json', accept: 'application/json', 'accept-language': 'en-US', 'user-agent': UA },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(20000),
  });
  if (r.status === 429) { n429++; throttled = true; const e = new Error('HTTP 429'); e.status = 429; throw e; }
  if (!r.ok) { const e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
  await sleep(400);
  return r.json();
}

const health = readJson(HEALTH, {});
const hot = readJson(HOT, {});
const out = [];
let ok = 0, dead = 0, errs = 0, hits = 0, done = 0;

async function scanTenant(key) {
  const [tenant, inst, site] = String(key).split('|');
  if (!tenant || !inst || !site) return;
  const h = health[key];
  if (h && h.dead_until && Date.parse(h.dead_until) > Date.now()) return;
  const host = `https://${tenant}.${inst}.myworkdayjobs.com`;
  const api = `${host}/wday/cxs/${tenant}/${site}`;
  const seen = new Set();
  try {
    for (const q of QUERIES) {
      const d = await getJson(`${api}/jobs`, { appliedFacets: {}, limit: 20, offset: 0, searchText: q });
      for (const j of d.jobPostings || []) {
        if (!j.externalPath || seen.has(j.externalPath)) continue;
        seen.add(j.externalPath);
        if (!TITLE_RX.test(j.title) || SKIP_RX.test(j.title)) continue;
        hot[key] = new Date().toISOString().slice(0, 10);       // employer hires for these roles
        if (postedDays(j.postedOn) > SINCE) continue;
        let loc = j.locationsText || '', posted = iso(new Date(today - postedDays(j.postedOn) * 864e5)), company = tenant;
        try {
          const det = await getJson(`${api}${j.externalPath}`);
          const i = det.jobPostingInfo || {};
          if (i.canApply === false) continue;
          loc = [i.location, ...(i.additionalLocations || [])].filter(Boolean).join('; ') || loc;
          if (i.remoteType) loc += `; ${i.remoteType}`;
          if (i.startDate) posted = i.startDate;
          const org = (det.hiringOrganization || {}).name;
          if (org) company = org.replace(/^\d+\s+/, '').replace(/,?\s+(Inc|LLC|Corp|Corporation|Ltd)\.?$/i, '').trim();
        } catch {}
        hits++;
        out.push(`  + [workday] ${posted} | ${company.replace(/\|/g, '/')} | ${j.title.replace(/\|/g, '/')} | ${loc.replace(/\|/g, '/')}\n    ${host}/${site}${j.externalPath}`);
      }
    }
    ok++;
    if (h) delete health[key];
  } catch (e) {
    if ([404, 410, 422].includes(e.status)) {
      dead++;
      const n = (h?.fails || 0) + 1;
      health[key] = { fails: n, dead_until: n >= 2 ? new Date(Date.now() + 14 * 864e5).toISOString() : null };
    } else if (e.status !== 429) errs++;
  } finally { done++; }
}

const t0 = Date.now();
const all = await loadTenants();
const seedHot = fs.existsSync(SEED_HOT) ? fs.readFileSync(SEED_HOT, 'utf8').split('\n').map(s => s.trim()).filter(s => s && !s.startsWith('#')) : [];
const hotList = [...new Set([...seedHot, ...Object.keys(hot)])];
const hotSet = new Set(hotList);
const cur = readJson(CURSOR, { i: 0 });
const rest = all.filter(k => !hotSet.has(k));
const queue = [...hotList];
if (!HOT_ONLY) for (let k = 0; k < rest.length; k++) queue.push(rest[(cur.i + k) % rest.length]);
let idx = 0, restDone = 0;
await Promise.all(Array.from({ length: conc }, async () => {
  while (idx < queue.length && Date.now() - t0 < BUDGET && !throttled) {
    const k = queue[idx++];
    if (!hotSet.has(k)) restDone++;
    await scanTenant(k);
  }
}));
if (!HOT_ONLY && rest.length) fs.writeFileSync(CURSOR, JSON.stringify({ i: (cur.i + restDone) % rest.length, at: new Date().toISOString() }));
fs.writeFileSync(HEALTH, JSON.stringify(health));
fs.writeFileSync(HOT, JSON.stringify(hot, null, 0));
console.log(out.join('\n'));
console.error(`workday: ${done} tenants scanned (${hotList.length} hot, ${restDone} in rotation, cursor ${cur.i}→${(cur.i + restDone) % Math.max(1, rest.length)} of ${rest.length}), ${ok} ok, ${dead} dead, ${errs} errors, ${throttled ? 'STOPPED: Workday rate limit (429), resumes next hour,' : ''} ${hits} matches, ${Math.round((Date.now() - t0) / 1000)}s`);
