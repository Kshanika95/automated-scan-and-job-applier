// Lever (jobs.lever.co) filler.
// Usage: node lever.mjs --plan plan.json --out result.json [--dry]
import fs from 'fs';
import { dismissBanners, launch, sleep, norm, log, shot, challengeVisible, writeResult, pageText, loadPlan } from './common.mjs';

const { plan, out, dry } = loadPlan();
const state = { log: [], shots: [], dir: plan.dir };
fs.mkdirSync(plan.dir, { recursive: true });
const { browser, page } = await launch();
const result = (status, extra = {}) => writeResult(out, state, { status, ...extra });
const byName = (n) => page.locator(`[name="${n.replace(/"/g, '\\"')}"]`);

async function setLocation() {
  const inp = page.locator('#location-input, input[name="location"]').first();
  if (!(await inp.count())) return true;
  const F = plan.facts || {};
  const city = String(F.city || (F.location_search || '').split(',')[0] || '').trim();
  const region = norm(F.state || ''), code = norm(F.state_code || '');
  await inp.click(); await inp.fill('');
  await inp.pressSequentially(city, { delay: 50 });
  await sleep(2500);
  const items = page.locator('.dropdown-location, .dropdown-results div');
  const n = await items.count();
  for (let i = 0; i < n; i++) {
    const t = norm(await items.nth(i).innerText().catch(() => ''));
    if (t.startsWith(norm(city)) && (!region || t.includes(region) || (code && new RegExp('\\b' + code + '\\b').test(t)))) {
      await items.nth(i).click(); await sleep(500); return true;
    }
  }
  await inp.fill(F.location_text || city);   // free text is accepted when no suggestion list appears
  return true;
}

async function fillOne(f, value) {
  const k = f.key;
  if (f.type === 'file') {
    await page.locator('input[type="file"][name="resume"], #resume-upload-input').first().setInputFiles(value);
    // wait for Lever's resume parser to finish
    for (let i = 0; i < 20; i++) {
      await sleep(1000);
      const t = norm(await page.locator('.resume-upload-label, .application-question.resume').first().innerText().catch(() => ''));
      if (/success|\.pdf|uploaded/.test(t)) break;
    }
    return true;
  }
  if (k === 'location') return setLocation();
  const els = byName(k);
  const n = await els.count();
  if (!n) { log(state, `not on page: ${k}`); return !f.required; }
  const first = els.first();
  const tag = await first.evaluate(e => e.tagName.toLowerCase());
  const type = (await first.getAttribute('type')) || '';
  if (tag === 'select') {
    const opts = await first.locator('option').allInnerTexts();
    const want = opts.find(o => norm(o) === norm(value)) || opts.find(o => norm(o).includes(norm(value)));
    if (!want) { log(state, `select option not found ${value} for ${k}`); return false; }
    await first.selectOption({ label: want });
    return true;
  }
  if (type === 'radio' || type === 'checkbox') {
    const vals = Array.isArray(value) ? value : (value === true ? [null] : [value]);
    for (const v of vals) {
      let target = null;
      for (let i = 0; i < n; i++) {
        const el = els.nth(i);
        const val = await el.getAttribute('value');
        const lab = await el.evaluate(e => (e.closest('label')?.innerText || '').trim());
        if (v === null || norm(val) === norm(v) || norm(lab) === norm(v)) { target = el; break; }
      }
      if (!target) { log(state, `option not found "${v}" for ${k}`); return false; }
      await target.check();
    }
    return true;
  }
  await first.fill(String(value));
  return norm(await first.inputValue()) === norm(String(value));
}

const filled = [], failed = [];
try {
  log(state, 'open ' + plan.apply_url);
  await page.goto(plan.apply_url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  try { await page.locator('form#application-form, .application-form, input[name="name"]').first().waitFor({ timeout: 30000 }); }
  catch {
    await shot(page, state, 'no-form');
    const t = await pageText(page);
    if (/no longer|not found|closed/i.test(t)) { result('closed'); await browser.close(); process.exit(0); }
    result('error', { error: 'application form not found' }); await browser.close(); process.exit(0);
  }
  await dismissBanners(page);
  // resume first (Lever's parser pre-fills fields, which we then overwrite with the checked values)
  const order = [...plan.fields].sort((a, b) => (b.type === 'file') - (a.type === 'file'));
  for (const f of order) {
    if (!(f.key in plan.answers)) continue;
    try { (await fillOne(f, plan.answers[f.key])) ? filled.push(f.key) : failed.push(f.label); }
    catch (e) { log(state, `fill ${f.key} failed: ${e.message.split('\n')[0]}`); failed.push(f.label); }
  }
  const missing = await page.evaluate(() => {
    const out = [];
    for (const li of document.querySelectorAll('li.application-question, .application-question')) {
      if (!li.querySelector('.required')) continue;
      const inputs = [...li.querySelectorAll('input:not([type=hidden]), textarea, select')];
      if (!inputs.length) continue;
      const ok = inputs.some(i => (i.type === 'radio' || i.type === 'checkbox') ? i.checked : (i.type === 'file' ? i.files.length > 0 || /success|\.pdf/i.test(li.innerText) : !!i.value));
      if (!ok) out.push((li.querySelector('.application-label, .text')?.innerText || '?').slice(0, 80));
    }
    return out;
  });
  log(state, `filled ${filled.length}, failed ${failed.length}, missing required: ${missing.join(' | ')}`);
  await shot(page, state, 'filled');
  if (failed.length || missing.length) { result('fill_incomplete', { failed, empty_required: missing }); await browser.close(); process.exit(0); }
  if (dry) { result('dry_run_ok', { filled }); await browser.close(); process.exit(0); }

  await dismissBanners(page);
  let sub = page.locator('#btn-submit:visible, button[data-qa="btn-submit"]:visible').first();
  if (!(await sub.count())) sub = page.getByRole('button', { name: /submit application/i }).first();
  await sub.scrollIntoViewIfNeeded();
  await sub.click({ timeout: 20000 });
  log(state, 'clicked submit');
  let status = 'unknown';
  for (let i = 0; i < 45; i++) {
    await sleep(2000);
    const t = await pageText(page);
    if (/\/thanks/.test(page.url()) || /application submitted|thanks for applying|thank you for applying|we.ve received your application/i.test(t)) { status = 'submitted'; break; }
    if (await challengeVisible(page)) { status = 'captcha'; break; }
    const errs = await page.locator('.error-message:visible, .application-error:visible, [class*="error"]:visible').allInnerTexts().catch(() => []);
    if (i > 4 && errs.some(e => e.trim())) { status = 'validation_error'; log(state, 'errors: ' + errs.join(' | ').slice(0, 400)); break; }
  }
  await shot(page, state, 'after-submit');
  result(status, { filled, final_url: page.url() });
} catch (e) {
  log(state, 'fatal: ' + e.message.split('\n')[0]);
  await shot(page, state, 'fatal');
  result('error', { error: e.message.split('\n')[0] });
}
await browser.close();
