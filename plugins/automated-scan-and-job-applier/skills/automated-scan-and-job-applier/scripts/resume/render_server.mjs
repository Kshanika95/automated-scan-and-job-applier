// Persistent renderer: one Chromium for many HTML -> PDF jobs (much faster than one launch per attempt).
// stdin lines: "<in.html>\t<out.pdf>"  ->  stdout lines: "ok" | "err <message>"
import { chromium } from 'playwright';
import readline from 'readline';
const exe = process.env.CHROME_PATH || undefined;
const b = await chromium.launch(exe ? { executablePath: exe } : {});
const p = await b.newPage();
for await (const line of readline.createInterface({ input: process.stdin })) {
  const [inp, out] = line.split('\t');
  try {
    await p.goto('file://' + inp); await p.evaluate(() => document.fonts.ready);
    await p.pdf({ path: out, format: process.env.PAPER || 'Letter', printBackground: true, margin: { top: '0.3in', bottom: '0.3in', left: '0.4in', right: '0.4in' } });
    process.stdout.write('ok\n');
  } catch (e) { process.stdout.write('err ' + e.message.split('\n')[0] + '\n'); }
}
await b.close();
