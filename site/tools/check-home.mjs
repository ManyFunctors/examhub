#!/usr/bin/env node
// Guard for the browse pages (home and /YYYY-MM/) in a built site.
//
// Checks what docs/site-perf.md promised:
//   - every exam page is reachable without JavaScript, by links on the browse pages
//   - the month arrows are links, and every one points at a page that exists
//   - no script-filled placeholders (&nbsp; headings) and no inline data-events
//   - index.json parses and lists every exam
//   - the home page stays under its byte ceiling (gzipped)
//   - the RSS feed is advertised in the head
//   - the /bodies/, /types/, /statuses/ and /kinds/ index pages exist and home links them
//
// Node standard library only. Run after `hugo --minify`:
//   node tools/check-home.mjs [public-dir]
// Exit code 1 if any check fails.

import { readdir, readFile, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join, resolve } from 'node:path';

const PUBLIC = resolve(process.argv[2] || 'public');
const HOME_GZ_CEILING = 40 * 1024;

const failures = [];
const fail = (msg) => { failures.push(msg); console.error(`FAIL ${msg}`); };
const ok = (msg) => console.log(`ok   ${msg}`);

// Attribute values, quoted or not (the minifier drops quotes where it can).
const attr = (tag, name) => {
  const m = tag.match(new RegExp(`\\s${name}=(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`));
  return m ? (m[1] ?? m[2] ?? m[3]) : null;
};

async function main() {
  if (!existsSync(join(PUBLIC, 'index.html'))) {
    console.error(`No built site at ${PUBLIC}; run hugo first.`);
    process.exit(2);
  }

  // The site's base path, from the home page's own links (e.g. /examhub/).
  const home = await readFile(join(PUBLIC, 'index.html'), 'utf8');
  const base = (home.match(/href=["']?(\/[^"'\s>]*?)index\.xml/) || [])[1] || '/';

  const months = (await readdir(PUBLIC)).filter((d) => /^\d{4}-\d{2}$/.test(d)).sort();
  const pages = [['home', home]];
  for (const m of months) pages.push([m, await readFile(join(PUBLIC, m, 'index.html'), 'utf8')]);
  ok(`${months.length} month pages found`);

  // Every exam page, reachable from the browse pages with JavaScript off.
  // A merged record's old URL is a redirect page (Hugo `aliases`), not an exam page.
  const exams = [];
  for (const d of await readdir(join(PUBLIC, 'exams'), { withFileTypes: true })) {
    const page = join(PUBLIC, 'exams', d.name, 'index.html');
    if (!d.isDirectory() || !existsSync(page)) continue;
    if (/http-equiv=["']?refresh/i.test(await readFile(page, 'utf8'))) continue;
    exams.push(`${base}exams/${d.name}/`);
  }
  const linked = new Set();
  for (const [, html] of pages) {
    for (const m of html.matchAll(/<a\s[^>]*>/g)) {
      const href = attr(m[0], 'href');
      if (href && href.startsWith(`${base}exams/`)) linked.add(href);
    }
  }
  const missing = exams.filter((u) => !linked.has(u));
  if (missing.length) fail(`${missing.length} of ${exams.length} exam pages not linked from any browse page, e.g. ${missing.slice(0, 3).join(', ')}`);
  else ok(`all ${exams.length} exam pages linked without JavaScript`);

  for (const [name, html] of pages) {
    // The month arrows: links, each to a page that exists, or marked as the end.
    for (const id of ['cal-prev', 'cal-next']) {
      const tag = (html.match(new RegExp(`<[a-z]+\\s[^>]*id=["']?${id}["'\\s>][^>]*>`)) || [])[0];
      if (!tag) { fail(`${name}: no #${id}`); continue; }
      if (!tag.startsWith('<a')) { fail(`${name}: #${id} is not a link`); continue; }
      const href = attr(tag, 'href');
      if (!href) {
        if (attr(tag, 'aria-disabled') !== 'true') fail(`${name}: #${id} has no href and isn't marked as the end`);
        continue;
      }
      const target = join(PUBLIC, href.slice(base.length), 'index.html');
      if (!existsSync(target)) fail(`${name}: #${id} points at ${href}, which doesn't exist`);
    }
    if (/data-events=/.test(html)) fail(`${name}: still carries data-events`);
    if (/>&nbsp;<\//.test(html) || /> <\//.test(html)) fail(`${name}: has an &nbsp; placeholder for script to fill`);
  }
  ok('month arrows and placeholders checked on every browse page');

  // The index pages: the no-JS stand-ins for the filters, each linked from the home page.
  for (const axis of ['bodies', 'types', 'statuses', 'kinds']) {
    if (!existsSync(join(PUBLIC, axis, 'index.html'))) { fail(`no /${axis}/ index page`); continue; }
    const n = (await readdir(join(PUBLIC, axis), { withFileTypes: true })).filter((d) => d.isDirectory()).length;
    if (!n) fail(`/${axis}/ has no pages under it`);
    if (!home.includes(`${base}${axis}/`)) fail(`home page does not link /${axis}/`);
  }
  ok('index pages for bodies, types, statuses and kinds, linked from home');

  // index.json: what the script fetches after first paint.
  try {
    const data = JSON.parse(await readFile(join(PUBLIC, 'index.json'), 'utf8'));
    if (!Array.isArray(data.events) || !data.events.length) fail('index.json has no events');
    if (!Array.isArray(data.cards) || data.cards.length !== exams.length) fail(`index.json lists ${data.cards?.length} records, the site has ${exams.length}`);
    else ok(`index.json lists all ${exams.length} records and ${data.events.length} dates`);
  } catch (err) {
    fail(`index.json unreadable: ${err.message}`);
  }

  // The home page's weight, gzipped (what a reader downloads).
  const gz = gzipSync(home, { level: 9 }).length;
  if (gz > HOME_GZ_CEILING) fail(`home page is ${gz} bytes gzipped, over the ${HOME_GZ_CEILING} ceiling`);
  else ok(`home page ${gz} bytes gzipped (ceiling ${HOME_GZ_CEILING})`);

  if (!/rel=["']?alternate["']?\s[^>]*application\/rss\+xml/.test(home)) fail('home page does not advertise its RSS feed');
  else ok('RSS feed advertised');

  if (failures.length) {
    console.error(`\n${failures.length} check(s) failed.`);
    process.exit(1);
  }
  console.log('\nAll browse-page checks passed.');
}

main().catch((err) => {
  console.error(`check-home crashed: ${err.stack || err}`);
  process.exit(2);
});
