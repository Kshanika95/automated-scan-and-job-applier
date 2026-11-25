// HTML -> PDF with Chromium (Letter, print backgrounds). Usage: node render.mjs in.html out.pdf
import { chromium } from 'playwright';
const [,, inp, out] = process.argv;
const exe = process.env.CHROME_PATH || undefined;
const b = await chromium.launch(exe ? { executablePath: exe } : {});
const p = await b.newPage();
await p.goto('file://' + inp); await p.evaluate(() => document.fonts.ready);
await p.pdf({ path: out, format: process.env.PAPER || 'Letter', printBackground: true, margin: { top: '0.3in', bottom: '0.3in', left: '0.4in', right: '0.4in' } });
await b.close();
