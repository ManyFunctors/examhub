#!/usr/bin/env node
// Link checker for ExamHub.
//
// Walks content/exams/*.md and docs/link-inventory.md, pulls every URL out of
// the link-bearing front-matter keys plus every bare URL in the inventory, and
// reports on reachability.
//
// This is deliberately not a generic "broken link" script. A large share of the
// URLs this site depends on are Indian government domains (.gov.in, .nic.in,
// s3waas.gov.in) behind WAFs, stale certificate chains and bot challenges that
// answer a plain HTTP client with 403, 429, 503 or a TLS handshake failure. All
// of those open fine in a real browser. Reporting them as broken would train a
// maintainer to ignore the tool, so access control gets its own bucket and only
// genuine absence counts as a failure.
//
// Node standard library only. No npm dependencies.
//
// Usage:
//   node tools/check-links.mjs                  # check the whole corpus
//   node tools/check-links.mjs --fix            # add domain-correction hints
//   node tools/check-links.mjs --scope=records  # content/exams/*.md only
//   node tools/check-links.mjs --scope=inventory
//   node tools/check-links.mjs --list=urls.txt   # one URL per line, # comments
//   node tools/check-links.mjs --only=upsc      # substring filter on the URL
//   node tools/check-links.mjs --jobs=8 --timeout=25000
//   node tools/check-links.mjs --include-code   # also check backticked paths
//   node tools/check-links.mjs --json=out.json
//
// Verdicts, in the order they are printed:
//
//   ok          2xx, or a single cosmetic redirect (trailing slash, www)
//   redirected  reachable, but the final URL is a different page
//   blocked     401/403/406/405/429/5xx, or a TLS/browser barrier. NOT broken.
//   timeout     no response in time, or a connection that never completes
//   dead        404/410/451, DNS NXDOMAIN, connection refused
//   error       redirect loop, malformed redirect, or an unclassifiable failure
//
// Exit code is 0 unless there is at least one *definite* failure (dead or
// error), so it is safe to run in CI.

import { readdir, readFile, writeFile } from 'node:fs/promises';
import { resolve4 } from 'node:dns/promises';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// Government portals, and a few private exam sites, behave differently for a
// browser than for curl. Send a current-looking desktop UA plus the headers a
// real top-level navigation carries, or half the corpus comes back 403 and the
// report is noise.
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

const BASE_HEADERS = {
  'user-agent': UA,
  accept:
    'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,' +
    'image/webp,*/*;q=0.8',
  'accept-language': 'en-IN,en;q=0.9,en-US;q=0.8',
  'upgrade-insecure-requests': '1',
  'sec-fetch-dest': 'document',
  'sec-fetch-mode': 'navigate',
  'sec-fetch-site': 'none',
  'sec-fetch-user': '?1',
};

/**
 * Domain corrections: host pattern -> { to, why }.
 *
 * Only ever *suggested*, never applied. These fire when a host matching one of
 * these patterns appears anywhere in the corpus, because these are the cases
 * where a plausible-looking subdomain is a mirror, a student mirror or a
 * long-retired host, and nobody notices until a candidate fills a form on the
 * wrong page.
 */
const HOST_HINTS = [
  {
    from: /(^|\.)cat\.xlri\.ac\.in$/i,
    to: 'https://xatonline.in/',
    why: 'CAT applies on the CAT coordinating body host, not an XLRI college subdomain',
  },
  {
    from: /(^|\.)slat\.iitm\.ac\.in$/i,
    to: 'https://www.slat-test.org/',
    why: 'SLAT is run by Symbiosis, not IIT Madras; the official site is slat-test.org',
  },
  {
    from: /(^|\.)ctet\.nta\.nic\.in$/i,
    to: 'https://ctet.nic.in/',
    why: 'CTET is run by the Central Testing Board on ctet.nic.in, not on an NTA subdomain',
  },
  {
    from: /(^|\.)csirnet\.gov\.in$/i,
    to: 'https://csirnet.nta.nic.in/',
    why: 'CSIR-UGC NET is run by NTA; csirnet.gov.in is retired',
  },
  {
    from: /^ucanapply\.com$/i,
    to: 'https://wbpsc.ucanapply.com/',
    why: 'wbpsc.ucanapply.com is correct; the bare ucanapply.com host is a different site',
  },
  {
    from: /(^|\.)digialm\.com$/i,
    to: '(no stable body equivalent)',
    why: 'cdn.digialm.com serves a time-limited form snapshot, not a durable landing page',
  },
];

/** Front-matter keys whose value is a URL. */
const URL_KEYS = [
  'official_url',
  'apply_url',
  'syllabus_url',
  'admit_card_url',
  'result_url',
  'source_url',
  'cutoff_url',
  'seat_matrix_url',
  'vacancy_url',
  'notice_url',
];

// ---------------------------------------------------------------------------
// argument parsing
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const opts = {
    scope: 'all', only: null, jobs: 6, timeout: 25000, fix: false, json: null, list: null,
    includeCode: false,
  };
  for (const arg of argv) {
    if (arg === '--fix') opts.fix = true;
    else if (arg === '--include-code') opts.includeCode = true;
    else if (arg.startsWith('--scope=')) opts.scope = arg.slice(8);
    else if (arg.startsWith('--only=')) opts.only = arg.slice(7).toLowerCase();
    else if (arg.startsWith('--list=')) opts.list = arg.slice(7);
    else if (arg.startsWith('--jobs=')) opts.jobs = Math.max(1, Number(arg.slice(7)) || 6);
    else if (arg.startsWith('--timeout=')) opts.timeout = Number(arg.slice(10)) || 25000;
    else if (arg.startsWith('--json=')) opts.json = arg.slice(7);
  }
  return opts;
}

const opts = parseArgs(process.argv.slice(2));

// ---------------------------------------------------------------------------
// URL extraction
// ---------------------------------------------------------------------------

/**
 * Pull URLs out of a blob: TOML front-matter values and bare URLs. Returns
 * url -> Set of keys, so one URL referenced by twelve records is fetched once
 * but reported against all twelve.
 */
function extractUrls(text, keys) {
  const found = new Map();
  const add = (raw, key) => {
    if (!/^https?:\/\//i.test(raw)) return;
    const clean = raw.replace(/[),.'"`\]]+$/, '');
    if (!found.has(clean)) found.set(clean, new Set());
    if (key) found.get(clean).add(key);
  };
  if (keys) {
    for (const key of keys) {
      const re = new RegExp(`^\\s*${key}\\s*=\\s*['"]([^'"]+)['"]`, 'gm');
      let m;
      while ((m = re.exec(text)) !== null) add(m[1], key);
    }
  }
  // A URL written inside backticks is documentation, not an assertion: it is
  // usually a path template with a placeholder in it (`.../Notice_<stamp>.pdf`)
  // or a link this file deliberately lists as dead. Checking those produces
  // guaranteed-false failures. Skip fenced blocks and inline code spans unless
  // --include-code asks for them.
  const scannable = opts.includeCode ? text : text
    .replace(/```[\s\S]*?```/g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/`[^`\n]*`/g, (m) => ' '.repeat(m.length));
  const bare = /https?:\/\/[^\s|)\]"'`<>]+/g;
  let m;
  while ((m = bare.exec(scannable)) !== null) add(m[0], keys ? 'inline' : 'inventory');
  return found;
}

async function collect() {
  const index = new Map(); // url -> { url, refs, keys }

  const push = (file, urlMap) => {
    for (const [url, keys] of urlMap) {
      if (!index.has(url)) index.set(url, { url, refs: new Set(), keys: new Set() });
      const rec = index.get(url);
      rec.refs.add(file);
      for (const k of keys) rec.keys.add(k);
    }
  };

  if (opts.list) {
    const text = await readFile(resolve(opts.list), 'utf8');
    for (const line of text.split('\n')) {
      const s = line.trim();
      if (!s || s.startsWith('#')) continue;
      push(opts.list, extractUrls(s, null));
    }
    return [...index.values()];
  }

  const examsDir = join(ROOT, 'content', 'exams');
  if (opts.scope !== 'inventory' && existsSync(examsDir)) {
    const files = (await readdir(examsDir)).filter((f) => f.endsWith('.md')).sort();
    for (const f of files) {
      push(`content/exams/${f}`, extractUrls(await readFile(join(examsDir, f), 'utf8'), URL_KEYS));
    }
  }
  const inv = join(ROOT, '..', 'docs', 'link-inventory.md');
  if (opts.scope !== 'records' && existsSync(inv)) {
    push('docs/link-inventory.md', extractUrls(await readFile(inv, 'utf8'), null));
  }

  let list = [...index.values()];
  if (opts.only) list = list.filter((r) => r.url.toLowerCase().includes(opts.only));
  return list;
}

// ---------------------------------------------------------------------------
// classification
// ---------------------------------------------------------------------------

const V = {
  OK: 'ok', REDIRECTED: 'redirected', BLOCKED: 'blocked',
  TIMEOUT: 'timeout', DEAD: 'dead', ERROR: 'error',
};

function classifyStatus(status) {
  if (status >= 200 && status < 300) return V.OK;
  // Access control, not absence. 405 means HEAD was disallowed and GET usually
  // works; 5xx is typically a bot-challenge interstitial from a WAF.
  if ([401, 403, 405, 406, 407, 429].includes(status)) return V.BLOCKED;
  if (status >= 500) return V.BLOCKED;
  if ([404, 410, 451].includes(status)) return V.DEAD;
  return V.ERROR;
}

// Failure modes that a real browser shrugs off. Keeping these out of `dead` is
// the single most important behaviour in this file.
const BROWSER_TOLERATED = [
  [/UNABLE_TO_VERIFY_LEAF_SIGNATURE/, 'incomplete certificate chain (server does not send the intermediate); browsers still load it'],
  [/UNABLE_TO_GET_ISSUER_CERT_LOCALLY/, 'server sends no issuer certificate; browsers still load it'],
  [/DEPTH_ZERO_SELF_SIGNED_CERT/, 'self-signed chain on a .nic.in host'],
  [/SELF_SIGNED_CERT_IN_CHAIN/, 'self-signed certificate in the chain'],
  [/CERT_HAS_EXPIRED/, 'certificate expired on the server; browsers warn but load'],
  [/UNSAFE_LEGACY_RENEGOTIATION/, 'TLS legacy renegotiation; Chrome and Firefox allow it by default'],
  [/ERR_SSL_UNEXPECTED_MESSAGE/, 'server rejects the TLS handshake Node offers; browser negotiates a different version'],
  [/ERR_SSL_WRONG_VERSION_NUMBER/, 'server speaks TLS on a port expecting plain HTTP, or vice versa'],
  [/CERT_ALTNAME_INVALID/, 'certificate does not cover this hostname; a browser shows a warning and can proceed'],
  [/INVALID_PURPOSE/, 'HTTP/2 connection reuse quirk; browsers open a fresh connection and succeed'],
  [/ERR_HTTP2/, 'HTTP/2 framing complaint; browsers retry over HTTP/1.1'],
  [/PROTOCOL_ERROR/, 'malformed response that a browser retries over HTTP/1.1'],
  [/Response does not match the HTTP\/1\.1 protocol/, 'malformed response headers; browsers tolerate this'],
  [/ECONNRESET/, 'connection reset, normally a WAF dropping a non-browser client'],
  [/EPIPE/, 'connection closed early'],
];
const TRANSIENT = [
  // undici surfaces our own AbortController timeout as ABORT_ERR, and some
  // hosts simply close mid-transfer. Both mean "did not answer", not "broken".
  [/^ABORT_ERR$|ABORT_ERR/, 'request aborted (client-side timeout)'],
  [/UND_ERR_CONNECT_TIMEOUT/, 'TCP connect never completed'],
  [/UND_ERR_HEADERS_TIMEOUT/, 'server accepted the connection but never answered'],
  [/EAI_AGAIN/, 'temporary DNS failure; retry before concluding anything'],
  [/ECONNRESET/, 'connection reset mid-response'],
  [/ETIMEDOUT/, 'socket timed out'],
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Is this host genuinely absent, or did the authority fail to answer?
 *
 * `fetch` reports both SERVFAIL and NXDOMAIN as ENOTFOUND, which is a trap:
 * hssc.gov.in and apsc.gov.in both return SERVFAIL with
 * `EDE(22): No Reachable Authority` at every public resolver, and treating that
 * as "host does not exist" would have a maintainer delete a perfectly good link
 * from a record. Only a clean NXDOMAIN counts as dead.
 */
async function hostIsAbsent(url) {
  let host;
  try { host = new URL(url).hostname; } catch { return { absent: false, code: 'BADURL' }; }
  try {
    await resolve4(host);
    return { absent: false, code: 'NOERROR' };
  } catch (err) {
    const code = (err && err.code) || 'UNKNOWN';
    if (code === 'ENOTFOUND' || code === 'ENODATA') return { absent: true, code };
    // ESERVFAIL / EAI_AGAIN / anything else means the authority is unwell,
    // which is a reachability problem, not a missing domain.
    return { absent: false, code };
  }
}

function bucketFromMessage(msg) {
  for (const [re, why] of TRANSIENT) if (re.test(msg)) return { v: V.TIMEOUT, why };
  for (const [re, why] of BROWSER_TOLERATED) if (re.test(msg)) return { v: V.BLOCKED, why };
  if (/ENOTFOUND/.test(msg)) return { v: V.DEAD, why: 'DNS: host does not exist (NXDOMAIN)' };
  if (/ECONNREFUSED/.test(msg)) return { v: V.DEAD, why: 'connection refused' };
  if (/CERT_|SSL|TLS|self.signed|unable to verify/.test(msg)) return { v: V.BLOCKED, why: 'TLS failure' };
  return null;
}

async function fetchOnce(url, timeout) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    return await fetch(url, { method: 'GET', redirect: 'manual', signal: ctl.signal, headers: BASE_HEADERS });
  } finally {
    clearTimeout(timer);
  }
}

const norm = (s) => s.replace(/\/$/, '').replace(/^https?:\/\/(www\.)?/, '');

async function checkOne(url) {
  const started = Date.now();
  let res = null;
  let hops = 0;
  let current = url;
  const chain = [url];

  // Follow the chain by hand so a redirect is reported as `redirected` rather
  // than collapsing into `ok`. A 307 that silently drops the path to a bare
  // homepage looks like a 200 otherwise, and that is exactly the failure this
  // script exists to catch.
  while (hops < 6) {
    try {
      res = await fetchOnce(current, opts.timeout);
    } catch (err) {
      // The abort error carries a different shape from a network error, and
      // getting it wrong turns a flaky host into a reported CI failure.
      if (err && (err.name === 'AbortError' || err.name === 'TimeoutError')) {
        return { url, verdict: V.TIMEOUT, detail: `request aborted after ${opts.timeout}ms`, chain, ms: Date.now() - started };
      }
      const msg = String((err && err.cause && err.cause.code) || (err && err.cause && err.cause.message) || (err && err.message) || err);
      const b = bucketFromMessage(msg);
      const ms = Date.now() - started;
      if (b && b.v === V.DEAD && /host does not exist/.test(b.why)) {
        const dns = await hostIsAbsent(url);
        if (!dns.absent) {
          return {
            url, verdict: V.TIMEOUT, chain, ms,
            detail: `DNS ${dns.code} (broken or unreachable authority, not an absent host; retry from another network before changing the record)`,
          };
        }
      }
      if (b) return { url, verdict: b.v, detail: b.why, chain, ms };
      return { url, verdict: V.ERROR, detail: msg, chain, ms };
    }
    if (res.status >= 300 && res.status < 400) {
      const loc = res.headers.get('location');
      if (!loc) {
        // A 3xx with no Location is a malformed WAF challenge, not a moved
        // page: the origin is up and the client is being walled. IOCL does this
        // behind Sucuri. A browser paints an interstitial; a script has nowhere
        // to go. Blocked, never dead, and never a CI failure.
        return {
          url, verdict: V.BLOCKED, chain, ms: Date.now() - started,
          detail: `HTTP ${res.status} with no Location header (malformed WAF challenge; site is up, client is walled)`,
        };
      }
      let next;
      try { next = new URL(loc, current).toString(); } catch { next = loc; }
      if (chain.includes(next)) return { url, verdict: V.ERROR, detail: `redirect loop back to ${next}`, chain, ms: Date.now() - started };
      chain.push(next);
      current = next;
      hops += 1;
      continue;
    }
    break;
  }

  let status = res.status;
  let v = classifyStatus(status);

  // A first-pass 403 is often just an anti-bot response. One retry after a pause
  // flips a fair share of them to 200, so never call it dead on the first try.
  if (v === V.BLOCKED && status !== 405) {
    await sleep(500);
    try {
      res = await fetchOnce(current, opts.timeout);
      status = res.status;
      v = classifyStatus(status);
    } catch { /* keep the original verdict */ }
  }

  let detail = `HTTP ${status}`;
  if (chain.length > 1) {
    // A single hop that only adds or removes www or a trailing slash is
    // cosmetic. Flagging every one of those would bury the real breakage.
    const cosmetic = chain.length === 2 && norm(current) === norm(url);
    if (cosmetic) v = V.OK;
    else if (v === V.OK) v = V.REDIRECTED;
    detail += ` -> ${chain.join(' -> ')}`;
  }
  if (v === V.BLOCKED) detail += ' (blocked, not broken)';
  if (v === V.DEAD) detail += ' (definite failure)';
  return { url, verdict: v, detail, chain, ms: Date.now() - started, status };
}

// ---------------------------------------------------------------------------
// reporting
// ---------------------------------------------------------------------------

const C = process.stdout.isTTY
  ? {
      dim: (s) => `\x1b[2m${s}\x1b[0m`, red: (s) => `\x1b[31m${s}\x1b[0m`,
      yellow: (s) => `\x1b[33m${s}\x1b[0m`, blue: (s) => `\x1b[34m${s}\x1b[0m`,
      cyan: (s) => `\x1b[36m${s}\x1b[0m`, bold: (s) => `\x1b[1m${s}\x1b[0m`,
    }
  : new Proxy({}, { get: () => (s) => s });

const ORDER = [V.DEAD, V.ERROR, V.TIMEOUT, V.REDIRECTED, V.BLOCKED, V.OK];
const LABEL = {
  [V.OK]: '  ok        ', [V.REDIRECTED]: 'redirected ', [V.BLOCKED]: '  blocked  ',
  [V.TIMEOUT]: '  timeout  ', [V.DEAD]: '  DEAD     ', [V.ERROR]: '  error    ',
};
const PAINT = {
  [V.OK]: C.dim, [V.REDIRECTED]: C.blue, [V.BLOCKED]: C.yellow,
  [V.TIMEOUT]: C.cyan, [V.DEAD]: C.red, [V.ERROR]: C.red,
};

function group(results) {
  const by = new Map(ORDER.map((v) => [v, []]));
  for (const r of results) by.get(r.verdict).push(r);
  return ORDER.map((v) => [v, by.get(v)]);
}

function hintsFor(url) {
  let host;
  try { host = new URL(url).hostname; } catch { return []; }
  return HOST_HINTS.filter((h) => h.from.test(host));
}

function describeRefs(r) {
  const refs = [...r.refs];
  const where = refs.slice(0, 2).join(', ') + (refs.length > 2 ? ` +${refs.length - 2} more` : '');
  const keys = [...r.keys].filter((k) => k !== 'inventory');
  return `  [${keys.join(',') || 'inventory'}]  in ${where}`;
}

async function main() {
  const records = await collect();
  if (!records.length) {
    console.error('No URLs found. Nothing to check.');
    process.exit(0);
  }
  console.log(C.bold(`Checking ${records.length} unique URLs (concurrency ${opts.jobs}, timeout ${opts.timeout}ms)\n`));

  const results = [];
  let i = 0;
  const worker = async () => {
    while (i < records.length) {
      const rec = records[i++];
      const r = await checkOne(rec.url);
      r.refs = rec.refs;
      r.keys = rec.keys;
      results.push(r);
    }
  };
  await Promise.all(Array.from({ length: opts.jobs }, worker));

  const counts = {};
  for (const r of results) counts[r.verdict] = (counts[r.verdict] || 0) + 1;

  for (const [v, list] of group(results)) {
    if (!list.length) continue;
    // ok and blocked are only listed when small; every other bucket always is.
    const showAll = v !== V.OK && v !== V.BLOCKED ? true : list.length <= 40;
    if (!showAll) {
      console.log(C.dim(`\n${v}: ${list.length} (use --only= to inspect individually)`));
      continue;
    }
    console.log(C.bold(`\n--- ${v} (${list.length}) ---`));
    for (const r of list) {
      console.log(`${PAINT[v](LABEL[v])} ${r.url}`);
      console.log(C.dim(`           ${r.detail}`));
      console.log(C.dim(`           ${describeRefs(r)}`));
    }
  }

  if (opts.fix) {
    console.log(C.bold('\n--- suggested domain corrections ---'));
    let n = 0;
    for (const r of results) {
      for (const h of hintsFor(r.url)) {
        n += 1;
        console.log(`${C.yellow('~ ')} ${r.url}`);
        console.log(`    -> ${h.to}`);
        console.log(C.dim(`    ${h.why}`));
        console.log(C.dim(`    ${describeRefs(r)}`));
      }
    }
    if (!n) console.log(C.dim('none found in the current corpus'));
  }

  console.log(C.bold('\n--- summary ---'));
  for (const v of ORDER) if (counts[v]) console.log(`${v.padEnd(12)} ${counts[v]}`);
  const definite = (counts[V.DEAD] || 0) + (counts[V.ERROR] || 0);
  console.log(
    C.dim(
      `distinct URLs ${results.length}  |  definite failures ${definite}  |  ` +
      `needs a browser ${(counts[V.BLOCKED] || 0) + (counts[V.TIMEOUT] || 0)}  |  ` +
      `redirected ${counts[V.REDIRECTED] || 0}`,
    ),
  );

  if (opts.json) await writeFile(opts.json, JSON.stringify(results, null, 2));
  process.exit(definite > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});
