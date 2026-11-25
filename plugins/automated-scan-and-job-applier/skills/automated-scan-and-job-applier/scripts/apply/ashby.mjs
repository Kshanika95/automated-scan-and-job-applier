// Ashby (jobs.ashbyhq.com) filler. Uses Ashby's public theming classes (ashby-application-form-*).
// Usage: node ashby.mjs --plan plan.json --out result.json [--dry]
import fs from 'fs';
import { dismissBanners, launch, sleep, norm, cssId, log, shot, challengeVisible, emailCode, writeResult, clickOption, pageText, loadPlan } from './common.mjs';

const { plan, out, dry } = loadPlan();
const state = { log: [], shots: [], dir: plan.dir };
fs.mkdirSync(plan.dir, { recursive: true });
const { browser, page } = await launch();
const result = (status, extra = {}) => writeResult(out, state, { status, ...extra });
const ENTRY = '.ashby-application-form-field-entry, [class*="_fieldEntry_"]';

async function entryFor(f) {
  // by label[for=path] first, then by exact title text
  const lab = page.locator(`label[for="${f.key}"]`).first();
  if (await lab.count()) {
    const anc = lab.locator('xpath=ancestor::*[contains(@class,"_fieldEntry_") or contains(@class,"ashby-application-form-field-entry")][1]');
    if (await anc.count()) return anc.first();
  }
  const want = norm(f.label);
  const all = page.locator(ENTRY);
  const n = await all.count();
  for (let i = 0; i < n; i++) {
    const t = norm(await all.nth(i).locator('.ashby-application-form-question-title').first().innerText().catch(() => ''));
    if (t.replace(/\*$/, '').trim() === want) return all.nth(i);
  }
  for (let i = 0; i < n; i++) {
    const t = norm(await all.nth(i).locator('.ashby-application-form-question-title').first().innerText().catch(() => ''));
    if (t && (t.startsWith(want.slice(0, 50)) || want.startsWith(t.slice(0, 50)))) return all.nth(i);
  }
  return null;
}

async function fillField(f, value) {
  const box = await entryFor(f);
  if (!box) { log(state, `no entry for ${f.label}`); return false; }
  await box.scrollIntoViewIfNeeded().catch(() => {});
  if (f.type === 'file') {
    await box.locator('input[type="file"]').first().setInputFiles(value);
    await sleep(2500);
    return true;
  }
  if (f.type === 'boolean') {
    const btn = box.locator(`.ashby-application-form-input-yesno-option[data-option="${value ? 'yes' : 'no'}"]`);
    if (await btn.count()) {
      await btn.click();
      await sleep(200);
      return (await btn.getAttribute('aria-pressed')) === 'true' || (await btn.getAttribute('class') || '').includes('active') || true;
    }
    const cb = box.locator('input[type="checkbox"]').first();
    if (value) await cb.check({ force: true }); else await cb.uncheck({ force: true });
    return true;
  }
  if (f.type === 'select' || f.type === 'multiselect') {
    const vals = Array.isArray(value) ? value : [value];
    const radios = box.locator('.ashby-application-form-input-radio-group-option, .ashby-application-form-input-checkbox-group-option');
    if (await radios.count()) {
      for (const v of vals) {
        const opt = radios.filter({ has: page.locator('label', { hasText: v }) });
        const n = await opt.count();
        let target = null;
        for (let i = 0; i < n; i++) {
          if (norm(await opt.nth(i).innerText()) === norm(v)) { target = opt.nth(i); break; }
        }
        target = target || (n === 1 ? opt.first() : null);
        if (!target) { log(state, `option not found "${v}" for ${f.label}`); return false; }
        const input = target.locator('input').first();
        await target.locator('label').first().click();
        await sleep(150);
        if (!(await input.isChecked().catch(() => true))) await input.check({ force: true }).catch(() => {});
      }
      return true;
    }
    const combo = box.locator('input[role="combobox"], .ashby-application-form-input-autocomplete input').first();
    if (await combo.count()) {
      for (const v of vals) {
        await combo.click();
        await combo.fill('');
        await combo.pressSequentially(String(v).slice(0, 30), { delay: 30 });
        await sleep(900);
        if (!(await clickOption(page, page.locator('[role="listbox"]').last(), v))) { log(state, `combo option not found "${v}"`); return false; }
        await sleep(200);
      }
      return true;
    }
    const sel = box.locator('select').first();
    if (await sel.count()) { await sel.selectOption({ label: String(vals[0]) }); return true; }
    log(state, `no control for select ${f.label}`); return false;
  }
  if (f.type === 'location') {
    const want = String(value || plan.facts?.location_search || '');
    const city = want.split(',')[0].trim();
    const combo = box.locator('input').first();
    await combo.click(); await combo.fill('');
    await combo.pressSequentially(city, { delay: 40 });
    await sleep(2000);
    const lb = page.locator('[role="listbox"]:visible').last();
    return (await clickOption(page, lb, want)) || (await clickOption(page, lb, city));
  }
  if (f.type === 'checkbox') {
    const cb = box.locator('input[type="checkbox"]').first();
    if (value) await cb.check({ force: true });
    return true;
  }
  const input = box.locator('textarea, input:not([type="file"]):not([type="checkbox"]):not([type="radio"])').first();
  let v = String(value);
  if (f.type === 'date' && /^\d{4}-\d{2}-\d{2}$/.test(v)) { const [y, m, d] = v.split('-'); v = `${m}/${d}/${y}`; }
  await input.fill(v);
  await sleep(100);
  const got = await input.inputValue();
  return norm(got).replace(/\D/g, '') === norm(v).replace(/\D/g, '') || norm(got) === norm(v);
}

const filled = [], failed = [];
try {
  log(state, 'open ' + plan.apply_url);
  await page.goto(plan.apply_url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  try { await page.locator('#_systemfield_name, .ashby-application-form-container').first().waitFor({ timeout: 40000 }); }
  catch {
    const t = await pageText(page);
    await shot(page, state, 'no-form');
    if (/job not found|no longer|not accepting/i.test(t)) { result('closed'); await browser.close(); process.exit(0); }
    result('error', { error: 'application form not found' }); await browser.close(); process.exit(0);
  }
  await sleep(1500);
  // upload the resume first: Ashby may autofill other fields from it, which we then overwrite
  const order = [...plan.fields].sort((a, b) => (b.type === 'file') - (a.type === 'file'));
  for (const f of order) {
    if (!(f.key in plan.answers)) continue;
    let v = plan.answers[f.key];
    if (v === '__COVER_LETTER__') v = plan.cover_letter_pdf;
    try {
      (await fillField(f, v)) ? filled.push(f.key) : failed.push(f.label);
    } catch (e) { log(state, `fill ${f.label} failed: ${e.message.split('\n')[0]}`); failed.push(f.label); }
  }
  // verify: required entries still showing as empty
  const missing = await page.evaluate(() => [...document.querySelectorAll('.ashby-application-form-field-entry, [class*="_fieldEntry_"]')].filter(e => {
    if (e.parentElement && e.parentElement.closest('[class*="_fieldEntry_"], .ashby-application-form-field-entry')) return false;
    const t = e.querySelector('.ashby-application-form-question-title');
    if (!t || !/_required_/.test(t.className)) return false;
    const inp = e.querySelector('input:not([type=hidden]), textarea');
    if (e.querySelector('.ashby-application-form-input-yesno')) return !e.querySelector('[aria-pressed="true"]');
    if (e.querySelector('.ashby-application-form-input-radio-group, .ashby-application-form-input-checkbox-group')) return !e.querySelector('input:checked');
    if (inp && inp.type === 'file') return !/\.(pdf|docx?)/i.test(e.innerText);
    if (inp && inp.getAttribute('role') === 'combobox') return !inp.value && !e.querySelector('[class*="singleValue"], [class*="single-value"], [class*="selected"]');
    return inp ? !inp.value : false;
  }).map(e => e.querySelector('.ashby-application-form-question-title').innerText.slice(0, 80)));
  log(state, `filled ${filled.length}, failed ${failed.length}, missing required: ${missing.join(' | ')}`);
  await shot(page, state, 'filled');
  if (failed.length || missing.length) { result('fill_incomplete', { failed, empty_required: missing }); await browser.close(); process.exit(0); }
  if (dry) { result('dry_run_ok', { filled }); await browser.close(); process.exit(0); }

  const since = new Date(Date.now() - 60000).toISOString();
  await dismissBanners(page);
  await page.locator('.ashby-application-form-submit-button').first().click();
  log(state, 'clicked submit');
  let status = 'unknown';
  const tried = [];
  for (let i = 0; i < 60; i++) {
    await sleep(2000);
    const t = await pageText(page);
    if (/application (was )?(successfully )?submitted|thank(s| you) for (applying|your application|submitting)|we.ve received your application|your application has been (received|submitted)/i.test(t)) { status = 'submitted'; break; }
    if (/flagged as (possible )?spam|suspicious activity|couldn.?t verify/i.test(t)) { status = 'spam_flagged'; break; }
    if (await challengeVisible(page)) { status = 'captcha'; break; }
    const codeIn = page.locator('input[autocomplete="one-time-code"], input[name*="code" i], input[placeholder*="code" i]');
    if (/verification code|confirm your email|enter the code/i.test(t) && await codeIn.count()) {
      if (tried.length >= 2) { status = 'code_failed'; break; }
      const code = emailCode({ sinceIso: since, fromHint: 'ashby', pattern: '[A-Za-z0-9]{6,8}', timeoutSec: 240, exclude: tried });
      if (!code) { status = 'code_not_received'; break; }
      tried.push(code);
      await codeIn.first().fill(code);
      await page.locator('button:has-text("Verify"), button:has-text("Submit"), button[type="submit"]').first().click().catch(() => {});
      continue;
    }
    const errs = await page.locator('[class*="_error"]:visible, [role="alert"]:visible').allInnerTexts().catch(() => []);
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
