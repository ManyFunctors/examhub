/*
 * WCAG AA contrast audit.
 *
 * Walks every leaf text node on each page in both colour modes and
 * composites the real backdrop stack before measuring, so translucent
 * surfaces and color-mix() tints are handled. Chrome serialises
 * color-mix() as `color(srgb r g b / a)` with 0-1 floats — reading those
 * as 0-255 makes every tint look black and produces confident nonsense,
 * so parseColor() handles both notations.
 *
 * Needs playwright-core and a Chromium binary, neither of which is a
 * dependency of the site (it has no build step beyond Hugo). Install
 * them wherever you like, then point PLAYWRIGHT at the browser:
 *
 *   npm i playwright-core
 *   PLAYWRIGHT_BROWSER=/path/to/chrome node tools/check-contrast.js
 *
 * With no browser available it exits 0 and says so, so it can sit in a
 * pipeline without failing on a machine that has not set it up.
 */
let chromium;
try {
  ({ chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core'));
} catch (e) {
  console.log('contrast: skipped — playwright-core not installed');
  process.exit(0);
}

const EXECUTABLE = process.env.PLAYWRIGHT_BROWSER || undefined;

// Chrome serialises color-mix() results as `color(srgb r g b / a)` with
// 0-1 floats, and plain colours as `rgb(r, g, b)`. Handle both, and
// composite any alpha over an opaque backdrop.
function parseColor(c) {
  if (!c) return null;
  const nums = c.match(/[\d.]+/g);
  if (!nums) return null;
  const alpha = nums.length > 3 ? parseFloat(nums[3]) : 1;
  let r, g, b;
  if (c.startsWith('color(')) { r = nums[0]*255; g = nums[1]*255; b = nums[2]*255; }
  else { r = +nums[0]; g = +nums[1]; b = +nums[2]; }
  return [r, g, b, alpha];
}
const over = (fg, bg) => [0,1,2].map(i => fg[i]*fg[3] + bg[i]*(1-fg[3])).concat([1]);
const lum = ([r,g,b]) => { const f = v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055,2.4); };
  return 0.2126*f(r) + 0.7152*f(g) + 0.0722*f(b); };
const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05); };

let failCount = 0;

(async () => {
  const b = await chromium.launch({ executablePath: EXECUTABLE, args: ['--no-sandbox'] });
  // Hardcoded on purpose: a sample has to be chosen, and a sample chosen
  // by walking the output would silently stop covering whatever the
  // templates stopped rendering. Two things to keep in mind when editing
  // it. The all-exams list is / — /exams/ is the section index, so /
  // covers the card grid and the stat band, and /exams/ covers the index
  // list. And the sample exam must be one that actually has a
  // provisional date in it, or the provisional tint is never measured:
  // civil-services-prelims-2027 is all confirmed, mgt-cmat-2027 is not.
  // A new page type needs a path here or it goes unaudited.
  const pages = [
    '/',
    '/exams/',
    '/exams/civil-services-prelims-2027/',
    '/exams/mgt-cmat-2027/',
    '/about/',
    '/bodies/upsc/',
  ];
  const fails = [];
  for (const mode of ['light','dark']) {
    for (const path of pages) {
      const p = await b.newPage({ viewport: { width: 1300, height: 900 } });
      await p.goto('http://localhost:1313' + path, { waitUntil: 'networkidle' });
      await p.evaluate(() => document.fonts.ready);
      if (mode === 'dark') { await p.click('#theme-toggle').catch(()=>{}); await p.waitForTimeout(350); }
      const items = await p.evaluate(() => {
        const root = getComputedStyle(document.documentElement);
        const base = getComputedStyle(document.body).backgroundColor;
        const out = [];
        for (const el of document.querySelectorAll('body *')) {
          if (!el.textContent.trim()) continue;
          if ([...el.children].some(c => c.textContent.trim())) continue;
          const cs = getComputedStyle(el);
          if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') continue;
          // Collect the full backdrop stack, innermost first
          const stack = [];
          let n = el;
          while (n) { const c = getComputedStyle(n).backgroundColor; if (c) stack.push(c); n = n.parentElement; }
          stack.push(base);
          out.push({
            sel: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
            color: cs.color, stack,
            size: parseFloat(cs.fontSize), weight: Number(cs.fontWeight),
            text: el.textContent.trim().slice(0,30)
          });
        }
        return out;
      });
      for (const it of items) {
        const fg = parseColor(it.color);
        if (!fg) continue;
        // composite backdrop from outermost to innermost
        let bg = parseColor(it.stack[it.stack.length-1]) || [255,255,255,1];
        for (let i = it.stack.length - 2; i >= 0; i--) {
          const c = parseColor(it.stack[i]);
          if (c && c[3] > 0) bg = over(c, bg);
        }
        const fgc = fg[3] < 1 ? over(fg, bg) : fg;
        const large = it.size >= 24 || (it.size >= 18.66 && it.weight >= 700);
        const need = large ? 3.0 : 4.5;
        const r = ratio(fgc, bg);
        if (r < need) fails.push({ mode, path, sel: it.sel.slice(0,54), r, need, text: it.text, size: it.size, color: it.color });
      }
      await p.close();
    }
  }
  failCount = fails.length;
  if (!fails.length) console.log(`PASS — no contrast failures across ${pages.length} pages x light/dark`);
  else {
    console.log(`${fails.length} failures:\n`);
    for (const f of [...new Map(fails.map(x=>[x.sel+x.mode,x])).values()].sort((a,b)=>a.r-b.r))
      console.log(`  ${f.r.toFixed(2)} (need ${f.need}) [${f.mode}] ${f.path}\n      ${f.sel}  ${f.color} @${f.size}px  "${f.text}"`);
  }
  await b.close();
})()
  .then(() => {
    if (failCount) process.exitCode = 1;
  })
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  });
