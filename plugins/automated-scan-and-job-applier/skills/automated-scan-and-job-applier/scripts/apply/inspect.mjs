// Dev tool: open an application page and dump every form control with its label.
// Usage: node inspect.mjs URL out.json [screenshot.png]
import { chromium, CHROME } from './common.mjs';
const [,, url, out, shot] = process.argv;
const b = await chromium.launch({ ...(CHROME ? { executablePath: CHROME } : {}), headless: true });
const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: 'en-US', timezoneId: 'America/Los_Angeles' });
const p = await ctx.newPage();
await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
await p.waitForTimeout(+process.env.WAIT || 6000);
const fields = await p.evaluate(() => {
  const lab = (el) => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText.trim(); }
    const al = el.getAttribute('aria-labelledby');
    if (al) return al.split(' ').map(i => document.getElementById(i)?.innerText || '').join(' ').trim();
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const c = el.closest('label, fieldset, .field, .application-question, [class*="question"], [class*="field"]');
    return c ? c.innerText.trim().slice(0, 200) : '';
  };
  return [...document.querySelectorAll('input, select, textarea, button, [role="combobox"], [role="radio"], [role="checkbox"], iframe')].map(el => ({
    tag: el.tagName.toLowerCase(), type: el.type || '', id: el.id, name: el.name || '', role: el.getAttribute('role') || '',
    required: el.required || el.getAttribute('aria-required') === 'true', label: lab(el).slice(0, 200),
    visible: !!(el.offsetWidth || el.offsetHeight), value: (el.value || '').slice(0, 60), cls: (el.className || '').toString().slice(0, 80),
    src: el.tagName === 'IFRAME' ? el.src.slice(0, 120) : undefined,
    options: el.tagName === 'SELECT' ? [...el.options].map(o => o.text).slice(0, 30) : undefined,
  }));
});
const fs = await import('fs');
fs.writeFileSync(out, JSON.stringify({ url: p.url(), title: await p.title(), fields }, null, 1));
if (shot) await p.screenshot({ path: shot, fullPage: true });
await b.close();
console.log(fields.length, 'controls');
