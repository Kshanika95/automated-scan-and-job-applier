// Shared browser helpers for the ATS fillers. Plain Playwright Chromium:
// no stealth plugins, no fingerprint spoofing, no CAPTCHA solving. If a site challenges
// us, the run stops and the job goes to the manual list.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execFileSync } from 'child_process';
import { chromium } from 'playwright';

export { chromium };
export const A = process.env.JOB_APPLIER_HOME || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CFG = (() => { try { return JSON.parse(fs.readFileSync(path.join(A, 'config.json'), 'utf8')); } catch { return {}; } })();
export const CHROME = process.env.CHROME_PATH || CFG.chrome_path || undefined;

// A normal headless Chromium: no stealth plugins, no fingerprint changes, no CAPTCHA solving.
export async function launch() {
  const browser = await chromium.launch({ ...(CHROME ? { executablePath: CHROME } : {}), headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 1000 }, locale: 'en-US', timezoneId: CFG.timezone || 'America/Los_Angeles',
  });
  ctx.setDefaultTimeout(15000);
  const page = await ctx.newPage();
  return { browser, ctx, page };
}

export const sleep = (ms) => new Promise(r => setTimeout(r, ms));
export const norm = (s) => String(s ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
export const cssId = (id) => '#' + String(id).replace(/([^a-zA-Z0-9_-])/g, '\\$1').replace(/^(\d)/, '\\3$1 ');

export function log(state, msg) {
  state.log.push(`${new Date().toISOString().slice(11, 19)} ${msg}`);
}

export async function shot(page, state, name) {
  const p = path.join(state.dir, `${name}.png`);
  try { await page.screenshot({ path: p, fullPage: true, timeout: 30000 }); state.shots.push(p); } catch (e) { log(state, 'screenshot failed ' + e.message); }
  return p;
}

// Visible CAPTCHA challenge (not the invisible badge): an hCaptcha/reCAPTCHA challenge frame on screen.
export async function challengeVisible(page) {
  for (const f of page.frames()) {
    const u = f.url();
    if (/recaptcha\/(api2|enterprise)\/bframe|hcaptcha\.com\/captcha\/v1\/.*(challenge|frame=challenge)|challenges\.cloudflare\.com/.test(u)) {
      try {
        const el = await f.frameElement();
        const box = await el.boundingBox();
        if (box && box.width > 100 && box.height > 100) {
          const vis = await el.evaluate(e => { const s = getComputedStyle(e); let n = e; while (n) { const st = getComputedStyle(n); if (st.visibility === 'hidden' || st.display === 'none' || +st.opacity === 0) return false; n = n.parentElement; } return true; });
          if (vis) return true;
        }
      } catch {}
    }
  }
  const t = await page.evaluate(() => document.body?.innerText || '');
  return /verify you are human|are you a robot|complete the security check|press and hold/i.test(t);
}

// Poll Gmail (IMAP, app password in Keychain) for a verification code sent after `sinceIso`.
export function emailCode({ sinceIso, fromHint = '', pattern = '', timeoutSec = 180, exclude = [], subjectHint = '' }) {
  try {
    const out = execFileSync('python3', ['-I', path.join(A, 'mailcheck.py'), 'code', '--since', sinceIso,
      '--from', fromHint, '--pattern', pattern, '--timeout', String(timeoutSec), '--exclude', exclude.join(','), '--subject', subjectHint], { encoding: 'utf8', timeout: (timeoutSec + 30) * 1000 });
    return out.trim() || null;
  } catch { return null; }
}

export function writeResult(file, state, extra) {
  const res = { ...extra, log: state.log, screenshots: state.shots };
  fs.writeFileSync(file, JSON.stringify(res, null, 1));
  return res;
}

// Generic: pick an option in an open listbox by exact (normalized) text, falling back to a unique "contains" match.
export async function clickOption(page, scope, text, { exactOnly = false } = {}) {
  const want = norm(text);
  const opts = scope.locator('[role="option"]');
  await opts.first().waitFor({ state: 'visible', timeout: 8000 }).catch(() => {});
  const n = await opts.count();
  let exact = -1, partial = [];
  for (let i = 0; i < n; i++) {
    const t = norm(await opts.nth(i).innerText().catch(() => ''));
    if (t === want) { exact = i; break; }
    if (!exactOnly && (t.includes(want) || want.includes(t)) && t) partial.push(i);
  }
  const idx = exact >= 0 ? exact : (partial.length === 1 ? partial[0] : (partial.length ? partial[0] : -1));
  if (idx < 0) return false;
  await opts.nth(idx).click();
  return true;
}

// Close cookie / privacy banners that can sit on top of the submit button.
export async function dismissBanners(page) {
  const btn = page.locator('button, a[role="button"], [role="button"]').filter({ hasText: /^\s*(dismiss|accept|accept all|accept cookies|got it|ok|okay|i agree|agree|close)\s*$/i });
  const n = await btn.count().catch(() => 0);
  for (let i = 0; i < Math.min(n, 3); i++) {
    const b = btn.nth(i);
    const inBanner = await b.evaluate(e => !!e.closest('[id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i], [class*="privacy" i], [id*="privacy" i], [aria-label*="cookie" i]')).catch(() => false);
    if (inBanner && await b.isVisible().catch(() => false)) await b.click({ timeout: 3000 }).catch(() => {});
  }
}

// Body text after submit, to classify the outcome.
export async function pageText(page) {
  return page.evaluate(() => document.body?.innerText || '').catch(() => '');
}

export function loadPlan() {
  const args = process.argv.slice(2);
  const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
  const plan = JSON.parse(fs.readFileSync(opt('--plan'), 'utf8'));
  return { plan, out: opt('--out'), dry: args.includes('--dry') };
}
