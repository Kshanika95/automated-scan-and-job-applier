// Greenhouse (job-boards.greenhouse.io) filler.
// Usage: node greenhouse.mjs --plan plan.json --out result.json [--dry]
// plan: {apply_url, alt_apply_url, fields:[{key,label,type,required,options}], answers:{key:value},
//        resume, cover_letter_pdf, cover_letter_text, dir}
import fs from 'fs';
import { dismissBanners, launch, sleep, norm, cssId, log, shot, challengeVisible, emailCode, writeResult, clickOption, pageText, loadPlan } from './common.mjs';

const { plan, out, dry } = loadPlan();
const state = { log: [], shots: [], dir: plan.dir };
fs.mkdirSync(plan.dir, { recursive: true });
const { browser, page } = await launch();
const result = (status, extra = {}) => { const r = writeResult(out, state, { status, ...extra }); return r; };

async function openForm() {
  for (const u of [plan.apply_url, plan.alt_apply_url].filter(Boolean)) {
    log(state, 'open ' + u);
    await page.goto(u, { waitUntil: 'domcontentloaded', timeout: 60000 });
    try { await page.locator('#first_name').waitFor({ state: 'attached', timeout: 25000 }); return true; } catch {}
    const t = await pageText(page);
    if (/no longer (accepting|available)|job not found|this job has been closed|position has been filled/i.test(t)) return 'closed';
  }
  return false;
}

// The listbox that belongs to this combobox (other dropdowns, e.g. the phone-country list, stay in the DOM).
async function listboxFor(input) {
  const ctl = await input.getAttribute('aria-controls').catch(() => null);
  if (ctl) { const lb = page.locator(cssId(ctl)); if (await lb.count()) return lb; }
  return page.locator('[role="listbox"]:visible').last();
}

// react-select combobox: open, type to filter, pick the option.
async function selectCombo(id, value) {
  const input = page.locator(cssId(id)).first();
  await input.scrollIntoViewIfNeeded().catch(() => {});
  await input.click({ timeout: 8000 }).catch(async () => { await input.focus(); });
  await sleep(400);
  let ok = await clickOption(page, await listboxFor(input), value);
  if (!ok) {
    await input.fill('').catch(() => {});
    await input.pressSequentially(String(value).slice(0, 40), { delay: 25 });
    await sleep(1000);
    ok = await clickOption(page, await listboxFor(input), value);
  }
  await page.keyboard.press('Escape').catch(() => {});
  return ok;
}

async function comboValue(id) {
  // the chosen value(s) render inside the select container next to the input
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const box = el.closest('[class*="select__control"], [class*="-control"], [class*="control"]') || el.parentElement?.parentElement;
    const vals = [...(box?.querySelectorAll('[class*="single-value"], [class*="singleValue"], [class*="multi-value__label"], [class*="multiValue__label"]') || [])].map(e => e.innerText);
    return vals.length ? vals.join(' | ') : (box?.innerText || '');
  }, cssId(id)).catch(() => null);
}

async function fillLocation(value) {
  const input = page.locator('#candidate-location');
  if (!(await input.count())) return false;
  const want = String(value || plan.facts?.location_search || '');
  const city = want.split(',')[0].trim();
  await input.click();
  await input.fill('');
  await input.pressSequentially(city, { delay: 40 });
  await sleep(2500);
  const lb = await listboxFor(input);
  return (await clickOption(page, lb, want)) || (await clickOption(page, lb, city));
}

async function setPhoneCountry() {
  const c = page.locator('#country');
  if (!(await c.count())) return true;
  const country = plan.facts?.phone_country || 'United States';
  if (norm(await comboValue('country')).includes(norm(country))) return true;
  await c.scrollIntoViewIfNeeded().catch(() => {});
  await c.click().catch(() => {});
  await c.fill('').catch(() => {});
  await c.pressSequentially(country, { delay: 30 });
  await sleep(800);
  // exact country first ("United States +1"), not a longer name that merely starts with it
  const rx = new RegExp('^\\s*' + country.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\+\\d+\\s*$', 'i');
  const opt = page.locator('[role="option"]').filter({ hasText: rx }).first();
  if (await opt.count()) await opt.click(); else await page.keyboard.press('Enter');
  await sleep(400);
  await page.keyboard.press('Escape').catch(() => {});
  const v = norm(await comboValue('country'));
  log(state, 'phone country shows: ' + v);
  return v.includes(norm(country)) || /^\W*\+\d+\b/.test(v);
}

async function checkboxGroup(key, values) {
  // multi-select rendered as checkboxes named "question_N[]": match each value to its label
  const boxes = page.locator(`input[type="checkbox"][name="${key.endsWith('[]') ? key : key + '[]'}"]`);
  const n = await boxes.count();
  let done = 0;
  for (const v of values) {
    for (let i = 0; i < n; i++) {
      const b = boxes.nth(i);
      const lab = await b.evaluate(e => (document.querySelector(`label[for="${CSS.escape(e.id)}"]`)?.innerText || e.closest('label')?.innerText || '').trim());
      if (norm(lab) === norm(v)) { await b.check({ force: true }); done++; break; }
    }
  }
  return n > 0 && done === values.length;
}

async function fillEducation() {
  // Greenhouse's optional/required education block: school, degree, discipline (async comboboxes), years
  if (!(await page.locator('#school--0, #degree--0, #discipline--0').count())) return true;
  const ed = plan.education || [];
  const e0 = ed[0];
  if (!e0) return false;
  let ok = true;
  const school = page.locator('#school--0');
  if (await school.count()) {
    await school.click(); await school.pressSequentially(e0.school.slice(0, 22), { delay: 40 }); await sleep(2500);
    if (!(await clickOption(page, await listboxFor(school), e0.school))) {
      await school.fill(''); await school.pressSequentially('Other', { delay: 40 }); await sleep(2000);
      ok = (await clickOption(page, await listboxFor(school), 'Other')) && ok;
    }
    await page.keyboard.press('Escape').catch(() => {});
  }
  if (await page.locator('#degree--0').count()) {
    const d = (await selectCombo('degree--0', e0.degree_level)) || (await selectCombo('degree--0', "Master's Degree")) || (await selectCombo('degree--0', 'Master of Arts')) || (await selectCombo('degree--0', 'Masters'));
    if (!d) { log(state, 'degree option not found'); ok = false; }
  }
  if (await page.locator('#discipline--0').count()) {
    ok = (await selectCombo('discipline--0', e0.discipline)) || (await selectCombo('discipline--0', 'Design')) || (await selectCombo('discipline--0', 'Other')) || false;
  }
  const [sy, sm] = (e0.start || '').split('-'); const [ey, em] = (e0.end || '').split('-');
  for (const [id, v] of [['start-year--0', sy], ['end-year--0', ey]]) { const el = page.locator('#' + id); if (v && await el.count()) await el.fill(v); }
  const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  for (const [id, v] of [['start-month--0', sm], ['end-month--0', em]]) { if (v && await page.locator('#' + id).count()) await selectCombo(id, MONTHS[+v - 1]).catch(() => {}); }
  return ok;
}

const filled = [], failed = [];
try {
  const okForm = await openForm();
  if (okForm === 'closed') { await shot(page, state, 'closed'); result('closed'); await browser.close(); process.exit(0); }
  if (!okForm) { await shot(page, state, 'no-form'); result('error', { error: 'application form not found' }); await browser.close(); process.exit(0); }
  await sleep(1500);
  if (!(await setPhoneCountry())) failed.push('phone country');
  const byKey = Object.fromEntries(plan.fields.map(f => [f.key, f]));
  for (const [key, value] of Object.entries(plan.answers)) {
    const f = byKey[key] || { key, type: 'text', label: key };
    try {
      if (f.type === 'file') {
        const sel = key === 'resume' ? '#resume' : key === 'cover_letter' ? '#cover_letter' : cssId(key);
        const file = value === '__COVER_LETTER__' ? plan.cover_letter_pdf : value;
        await page.locator(`input[type="file"]${sel}`).first().setInputFiles(file);
        await sleep(1500);
        filled.push(key); continue;
      }
      if (key === 'location' || key === 'candidate-location') { (await fillLocation(value)) ? filled.push(key) : failed.push(key); continue; }
      if (['latitude', 'longitude'].includes(key)) continue;
      if (f.type === 'multiselect' && (await page.locator(`input[type="checkbox"][name="${key.endsWith('[]') ? key : key + '[]'}"]`).count())) {
        (await checkboxGroup(key, Array.isArray(value) ? value : [value])) ? filled.push(key) : failed.push(key); continue;
      }
      const el = page.locator(cssId(key)).first();
      if (!(await el.count())) {
        if (f.type === 'multiselect') { (await checkboxGroup(key, Array.isArray(value) ? value : [value])) ? filled.push(key) : failed.push(key); continue; }
        if (f.type === 'checkbox' && value === true) {
          const cb = page.locator(`input[type="checkbox"][name*="${key}"]`).first();
          if (await cb.count()) { await cb.check(); filled.push(key); continue; }
        }
        log(state, `field not on page: ${key} (${f.label})`);
        if (f.required) failed.push(key);
        continue;
      }
      const role = await el.getAttribute('role');
      if (role === 'combobox' || ['select', 'multiselect', 'boolean'].includes(f.type)) {
        const vals = Array.isArray(value) ? value : [value === true ? 'Yes' : value === false ? 'No' : value];
        let ok = true;
        for (const v of vals) ok = (await selectCombo(key, v)) && ok;
        const shown = norm(await comboValue(key));
        if (!ok || !vals.every(v => shown.includes(norm(v).slice(0, 25)))) { log(state, `combo ${key} shows "${shown}" wanted ${JSON.stringify(vals)}`); failed.push(key); }
        else filled.push(key);
        continue;
      }
      const tag = await el.evaluate(e => e.tagName.toLowerCase());
      if (tag === 'select') { await el.selectOption({ label: String(value) }); filled.push(key); continue; }
      if (f.type === 'checkbox') { if (value) await el.check(); filled.push(key); continue; }
      await el.fill(String(value));
      if ((await el.inputValue()) !== String(value)) failed.push(key); else filled.push(key);
    } catch (e) {
      log(state, `fill ${key} failed: ${e.message.split('\n')[0]}`);
      failed.push(key);
    }
  }
  if (!(await fillEducation())) failed.push('education');
  // Anything required still empty on the page?
  const emptyRequired = await page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll('input[aria-required="true"], input[required], textarea[required], textarea[aria-required="true"]')) {
      if (el.type === 'hidden' || el.type === 'file' || !(el.offsetWidth || el.offsetHeight)) continue;
      if (el.getAttribute('role') === 'combobox') {
        const ctl = el.closest('[class*="control"]');
        const has = ctl && ctl.querySelector('[class*="single-value"], [class*="singleValue"], [class*="multi-value"], [class*="multiValue"]');
        if (!has && !el.value && (el.id || el.name)) out.push(el.id || el.name);
        continue;
      }
      if (!el.value && (el.id || el.name)) out.push(el.id || el.name);
    }
    const res = document.querySelector('#resume');
    const resOk = document.body.innerText.match(/\.pdf/i);
    if (res && !resOk) out.push('resume');
    return out;
  });
  log(state, `filled ${filled.length}, failed ${failed.length}, empty required: ${emptyRequired.join(',')}`);
  await shot(page, state, 'filled');
  if (failed.length || emptyRequired.length) {
    result('fill_incomplete', { failed, empty_required: emptyRequired });
    await browser.close(); process.exit(0);
  }
  if (dry) { result('dry_run_ok', { filled }); await browser.close(); process.exit(0); }

  // ---- submit
  const since = new Date(Date.now() - 60000).toISOString();
  await dismissBanners(page);
  const submit = page.locator('button[type="submit"]:has-text("Submit"), button:has-text("Submit application")').first();
  await submit.scrollIntoViewIfNeeded();
  await submit.click();
  log(state, 'clicked submit');
  let status = 'unknown';
  const tried = [];
  for (let i = 0; i < 60; i++) {
    await sleep(2000);
    const url = page.url();
    const t = await pageText(page);
    if (/\/confirmation|thank you for applying|application (has been )?(submitted|received)|we.ve received your application|thanks for applying/i.test(url + ' ' + t)) { status = 'submitted'; break; }
    if (await challengeVisible(page)) { status = 'captcha'; break; }
    if (/too many attempts/i.test(t)) { status = 'code_failed'; break; }
    const codeBoxes = page.locator('input[id^="security-input"], input[autocomplete="one-time-code"]');
    if (/security code|verification code|8-character code/i.test(t) && (await codeBoxes.count())) {
      if (tried.length >= 2) { status = 'code_failed'; break; }
      log(state, 'email verification code requested');
      await shot(page, state, 'code-requested');
      const code = emailCode({ sinceIso: since, fromHint: 'greenhouse', pattern: '[A-Za-z0-9]{8}', timeoutSec: 240, exclude: tried, subjectHint: String(plan.company || '').split(/\s+/)[0] });
      if (!code) { status = 'code_not_received'; break; }
      tried.push(code);
      log(state, `got code from email (${code.length} chars)`);
      const boxes = page.locator('input[id^="security-input"]');
      if ((await boxes.count()) >= code.length) { for (let k = 0; k < code.length; k++) await boxes.nth(k).fill(code[k]); }
      else await codeBoxes.first().fill(code);
      await sleep(600);
      await page.locator('button[type="submit"]:has-text("Submit"), button:has-text("Submit application")').first().click({ timeout: 10000 }).catch(() => {});
      await sleep(4000);
      continue;
    }
    const errs = await page.locator('[class*="error"]:visible, [aria-invalid="true"]').allInnerTexts().catch(() => []);
    if (i > 5 && errs.filter(e => e.trim()).length) { status = 'validation_error'; log(state, 'errors: ' + errs.join(' | ').slice(0, 400)); break; }
  }
  await shot(page, state, 'after-submit');
  result(status, { filled, final_url: page.url() });
} catch (e) {
  log(state, 'fatal: ' + e.message.split('\n')[0]);
  await shot(page, state, 'fatal');
  result('error', { error: e.message.split('\n')[0] });
}
await browser.close();
