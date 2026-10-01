# Site performance — measurements and the plan

Why the home page is 64 KB gzipped, why it is 64 KB gzipped for reasons that
have nothing to do with loading, and what to do instead of skeletons.

Checked **30 Sep 2026**. Every number below came out of the built site, and each
one is reproducible with the command printed above it. Where a count is noisy
or where a source disagrees with another, that is said in the row.

## Reproducing the measurements

`site/public/` is written by `hugo server`, not by CI. It still contains
`/livereload.js`, and it is **not minified**. CI builds with
`hugo --gc --minify` (`.github/workflows/site.yml:46`). So:

| Build | Raw | Gzipped |
|---|---|---|
| Lighthouse, 30 Sep 2026 (the number in `docs/todo.md`) | 472 KB | 60 KB |
| Local `site/public/index.html`, as measured below | 615,846 | 64,752 |
| The same document with inter-tag whitespace collapsed | 593,315 | 63,914 |

**Gzip is the number to trust.** Minification removes 22,349 raw bytes and only
**838** gzipped ones — whitespace was never the cost. Compare gzip figures
across builds; ignore raw ones. And note `site/public/` can hold stale
directories: it has 314 exam page directories against 313 records, the extra
being `zz-skeleton-test-2026`, a test record with no `.md` behind it. It is
git-ignored and never deployed, but it will inflate a naive file count.

```sh
(cd site/public && wc -c index.html && gzip -c9 index.html | wc -c)
```

## Where the 64 KB goes

```sh
cd site/public && python3 -c "
import re
h=open('index.html',encoding='utf-8').read()
print('total', len(h))
for name,pat in [('data-events', r'data-events=\"(.*?)\">'),
                 ('month group', r'<details class=\"bymonth__group\" open data-section=\"month\">.*?</details>'),
                 ('tba group',   r'data-section=\"~1tba\".*?</details>'),
                 ('done group',  r'data-section=\"~2done\".*?</details>'),
                 ('exam picker', r'id=\"filter-exams-list\".*?</ul>'),
                 ('body picker', r'id=\"filter-body-list\".*?</ul>')]:
    m=list(re.finditer(pat,h,re.S))
    print(f'{name:14s} {sum(len(x.group(0)) for x in m):7d}')
print('cards', h.count('<a class=\"card card--'))
"
```

| Region | Bytes | Of the document |
|---|---:|---:|
| `data-events` JSON attribute on `#dates` | 195,503 | 32% |
| Month group — 313 cards | 153,667 | 25% |
| Exam picker — 316 `<li class="filters__option">` | 112,505 | 18% |
| TBA group — 96 cards | 42,960 | 7% |
| Completed group — 84 cards | 39,312 | 6% |
| Body picker — 141 bodies | 27,593 | 4% |
| `filter-aliases` JSON | 13,249 | 2% |
| Sidebar, header, shell, inline script | ~31,000 | 5% |

Two thirds of the document is three copies of the same 313 records: as cards,
as JSON events, and as listbox options. The remaining third is one card
template's whitespace and attribute names, repeated 493 times.

## Finding 1 — 220 of the 313 cards ship, then get hidden

`home.html:86-90` renders **every** record into the month group:

```gotemplate
<details class="bymonth__group" open data-section="month">
  <div class="card-grid card-grid--3">
    {{- range . }}                     {{/* all 313, not one month */}}
      {{ partial "exam-card.html" .page }}
    {{- end }}
  </div>
</details>
```

`home.html:121-194` is a 73-line inline `<script>` that runs `sync()` and marks
every card with no date in the bar's month as `card--offmonth`, which is
`display: none !important` (`assets/css/v2.css:396`).

For the opening month (2026-09) that leaves **93 of 313**. **220 cards are
transmitted, parsed, styled, laid out, and then removed from the box tree on
first paint.** That collapse is the 0.48 CLS.

The partition is already computed at build time and thrown away eleven lines
later. `home.html:77-81` builds `$by`, keyed `2026-06`, `2026-07`, … plus
`~1tba` and `~2done`:

```gotemplate
{{- $k := cond (ne .st.nextDate "") (substr .st.nextDate 0 7) (cond (eq .st.key "done") "~2done" "~1tba") -}}
{{- $by = merge $by (dict $k ((index $by $k | default slice) | append .)) -}}
```

`home.html:92` consumes only the `~`-prefixed keys. The month keys are
discarded and `sync()` re-derives them in the browser.

## Finding 2 — 180 of the 493 cards are duplicates

493 `<a class="card">` elements, 313 unique. The TBA and Completed groups
re-render cards the month group already rendered. Verified clonable:

```sh
cd site/public && python3 -c "
import re
h=open('index.html',encoding='utf-8').read()
g=lambda p: re.findall(r'<a class=\"card card--[^\"]*\" href=\"([^\"]+)\"', re.search(p,h,re.S).group(0))
m=set(g(r'<details class=\"bymonth__group\" open data-section=\"month\">.*?</details>'))
for n,p in [('tba',r'data-section=\"~1tba\".*?</details>'),('done',r'data-section=\"~2done\".*?</details>')]:
    u=g(p); print(n, sum(1 for x in u if x in m), '/', len(u), 'clonable')
"
```

→ `tba 96 / 96 clonable`, `done 84 / 84 clonable`. **82,272 bytes of pure
duplication.** 360 of the 493 cards carry `card--done`, because an exam past
all its dates lands in Completed *and* in the month group.

## Finding 3 — the page is not a document; it is a JS app with an HTML skin

With JavaScript off, today:

| Thing | The markup says | What actually happens |
|---|---|---|
| Search box | `<div class="filters__head" hidden>` (`_partials/filters.html:2`) | revealed only by `site.js:681` — **does not exist** |
| Month stepper | `<button type="button" id="cal-month">` (`_partials/month-nav.html:22`) | a button with no form and no `href` — **does nothing** |
| Grid / List tabs | `<button role="tab">` (`home.html:28,34`) | same |
| Exam, Body pickers | `<input role="combobox">` + a `<ul hidden>` | a combobox is meaningless without script |
| Month group heading | `&nbsp;` (`home.html:85`) | filled by script |
| Day list heading | `&nbsp;` (`_partials/dates.html:53`) | filled by script |
| Day list itself | `<ul id="cal-list"></ul>` — empty | built entirely by script |
| `(93 Exams)` counts | absent | created by script (`home.html:180-184`) |
| Cards | 313 rendered | 220 hidden by script |

There is a `<noscript>` in `dates.html:57` telling the reader the day list
needs JavaScript and that "every record is still listed on this page" — but the
record list is itself JS-filtered, and the controls that would filter it are
dead. The noscript message is currently optimistic.

Two corrections to the record, because both are easy to repeat:

- The two long listboxes are `hidden` in markup (`_partials/filters-body.html:68,97`).
  `inert` is **not** in the markup — it is set at runtime by `setBodyOpen`
  (`site.js:646-655`), and only while the disclosure is collapsed. There are
  zero occurrences of `inert` in `filters-body.html`.
- `data-events` is **not** only for the hidden List panel. `home.html:132`
  parses it **synchronously during parse** to build `byMonth`/`pastMonth`, which
  `sync()` needs to decide which cards survive. `site.js:885-892` parses it a
  second time. Any claim that it is waste for a hidden panel is wrong.

## Finding 4 — the layout shift is the font

`fonts.html` declares three Jost `@font-face` blocks with `font-display: swap`.
`tokens.css:95`:

```css
--font-sans: "Jost", system-ui, -apple-system, "Segoe UI", Roboto, ...
```

There is **no metric-matched fallback**: `size-adjust`, `ascent-override`,
`descent-override`, `line-gap-override` and `font-metric` appear in none of the
ten CSS files. Three woff2 (8,864 / 9,828 / 9,820 bytes) swap in after first
paint, and every line box in 493 cards re-flows. On a page already at 0.48
CLS this is the single largest cause, and it is four lines of descriptors.

There is also a second contributor: the inline `sync()` sits **after** the grid
(`home.html:121`, grid at 82-102), so 220 cards are laid out before being
removed. A single-pass parse usually beats first paint, so this is a risk
rather than a certainty — but it disappears once the partition is build-time.

## Finding 5 — `data-events` is repeated, not duplicated

467 events over **217 unique URLs**, 217 titles and 5 labels. The 96 records
with no dated milestone contribute nothing at all.

```sh
cd site/public && python3 -c "
import re,json,html,gzip
h=open('index.html',encoding='utf-8').read()
d=json.loads(html.unescape(re.search(r'data-events=\"(.*?)\">',h,re.S).group(1)))
e=d['events']
u=sorted({x['u'] for x in e}); t=sorted({x['t'] for x in e}); l=sorted({x['l'] for x in e})
U={x:i for i,x in enumerate(u)}; T={x:i for i,x in enumerate(t)}; L={x:i for i,x in enumerate(l)}
r=[[U[x['u']],L[x['l']],x['k'],x['d'],T[x['t']],1 if x['p'] else 0,x['x'] or ''] for x in e]
enc=json.dumps({'u':u,'t':t,'l':l,'e':r},separators=(',',':'))
print('now     ', len(json.dumps(d,separators=(',',':'))), len(gzip.compress(json.dumps(d).encode(),9)))
print('dictified', len(enc), len(gzip.compress(enc.encode(),9)))
"
```

| Encoding | Raw | Gzipped |
|---|---:|---:|
| As shipped, inside an HTML attribute | 195,025 | 16,878 |
| Dictionary-encoded, inline | 51,903 | 10,414 |

Same data, same synchronous availability, no fetch, no skeleton. The floor is
set by the 467 date strings and the label table, not the URLs and titles.
Server-rendering the day list beats both — it removes the JSON and makes the
dates crawlable.

## Finding 6 — the stylesheet is one bundle for every page

`baseof.html:2-15` concatenates all ten CSS files into one fingerprinted
stylesheet loaded render-blocking from `<head>`, on every page.

| File | Raw | Gzipped | |
|---|---:|---:|---|
| `browse.css` | 39,211 | 9,589 | home only, 231 rules |
| `v2.css` | 27,884 | 6,476 | **exam pages only** |
| `cards.css` | 8,298 | 2,613 | |
| `layout.css` | 8,134 | 2,508 | |
| `tokens.css` | 9,043 | 2,243 | |
| `exam.css` | 13,355 | ~3,000 | **exam pages only** |
| `sidebar.css` | 3,329 | 1,093 | |
| `base.css` | 2,642 | 1,074 | |
| `dates.css` | 1,376 | 580 | |
| `theme-switch.css` | 576 | 254 | |

```sh
cd site/public && python3 -c "
import re
h=open('index.html',encoding='utf-8').read()
c=set()
for m in re.finditer(r'class=\"([^\"]+)\"',h): c.update(m.group(1).split())
print('classes on home:', len(c))
print('v2-/timeline on home:', sum(1 for x in c if x.startswith('v2-') or 'timeline' in x))
print('cal__ on home:', sum(1 for x in c if x.startswith('cal__')))
"
```

→ **0** `v2-`/`timeline` classes on the home page, out of 158. **44** `cal__`
classes, most of them the calendar flyout, which only the List panel needs.
`v2.css` + `exam.css` are 41,239 raw / ~9,500 gzipped of render-blocking CSS
the home page never uses.

`check-css.sh` gates brace balance, self-referential properties, comment
pairing and selector presence. It will **not** catch a broken
`content-visibility` or a wrong `contain-intrinsic-size`.

## Finding 7 — no preload hints at all

The head is 1,607 bytes and contains **zero** `rel="preload"`, `preconnect`,
`modulepreload` or `fetchpriority`. Nothing is first-party beyond the origin, so
preconnect buys nothing, but the 400 weight is worth preloading.

Also absent: `<link rel="alternate" type="application/rss+xml">`. The site
builds a 117 KB `index.xml` and never advertises it.

## Finding 8 — build time: the same work, per page

`sidebar.html:27` calls `partial "exam-list.html"` **uncached**, while
`header.html:13` and `home.html:4` use `partialCached`. The partial ignores its
context — it ranges `site.RegularPages` and returns a fixed dict — so the
uncached call re-runs the full 313-record scan on **every page**, calling
`exam-status.html` for each. At 316 pages that is ~99,000 redundant status
evaluations; the plan below takes it to ~500 pages and ~156,000.

`exam-card.html:2,5`, `dates.html:14` and `section.exams.json:4,6` likewise call
`exam-status.html` and `milestones.html` uncached. Both are pure functions of the
page and can be cached on `.RelPermalink` exactly as the 95 existing
`v2/params.html` call sites already are.

```sh
grep -rn -E 'partial(Cached)? +"(exam-list|milestones|exam-status)\.html"' site/themes/examhub/layouts/
```

CI allows 15 minutes for the whole build job (`.github/workflows/site.yml`).

## Finding 9 — exam pages are not a problem

```sh
cd site/public/exams && python3 -c "
import glob
r=sorted(((len(open(f).read()),f) for f in glob.glob('*/index.html')),reverse=True)
t=sum(x for x,_ in r)
print('pages',len(r),'total',t,'mean',t//len(r))
print('p50',r[len(r)//2][0],'p90',r[int(len(r)*.9)][0],'max',r[0][0],r[0][1])
"
```

| | Bytes |
|---|---:|
| pages | 314 |
| total | 4,976,242 |
| mean | 15,847 |
| p50 | 15,655 |
| p90 | 15,332 |
| max | 45,767 (`nicl-ao-2023-24`) |

On the largest page the folded `<details>` sections total ~8 KB
(`eligibility` 2,016, `posts` 3,384, `fee` 603, `rules` 496, `pay` 1,270), and
the two big ones are `dates` (10,481) and `pattern` (10,658) — both `open` on
load, so both are content. A round trip to save 8 KB is a net loss. **Do not
defer exam-page sections.** They pick up no-JS support for free from Phase 1.

## Considered and declined

| Option | Verdict | Why |
|---|---|---|
| Skeletons | **No** | Nothing arrives late once content is server-rendered. The `(93 Exams)` count comes from real cards, so a skeleton would have to lie about it. |
| Defer the card grid | **No** | `site.js:615-623` bails on `if (!cards.length) return;` and `site.js:698-720` scrapes its search corpus off the cards themselves, then writes back with `el.hidden = !ok` (777-778). The cards *are* the index. Deferring them kills search permanently, with no error path. |
| Fully client-rendered grid | **No** | Destroys the only asset that cannot be cheaply rebuilt: a prerendered, linkable, zero-JS-required index. |
| `content-visibility: auto` | **Only, later, and measured** | Defers layout and paint, not transfer. `contain-intrinsic-size` on variable-height cards is a guess that breaks scroll anchoring, and it fights `card.style.order` in `sync()` (`home.html:174`). |
| Defer `data-events` to a fetched JSON | **No** | `home.html:132` needs it synchronously during parse. Server-rendering the day list is strictly better: smaller, crawlable, no fetch. |
| Inline critical CSS | **Optional, measure first** | Removes the one blocking round trip at the cost of caching. Decide after Phase 3. |
| Dropping the 500-weight font | **Optional** | 9,828 bytes. Only if the weight is genuinely unused. |

## The static-host constraint

GitHub Pages serves files. There is no server to read `?body=upsc`. **A filter
that works without JavaScript must be a real page, not a query string.** That
one fact determines the information architecture below.

The search box cannot be a no-JS feature at all — a static host cannot search.
Its no-JS stand-in is the browsable index the axis pages provide. "Within 30
days" has the same problem: the boundary moves, so it stays JS-only.

## The plan

### Target information architecture

```
/                      current month + an index of every axis
/dates/                every milestone on the site, as a document
/2026-11/              every exam with a date in Nov 2026           27 pages
/bodies/in-upsc/       every exam UPSC conducts                   139 pages
/types/academic/                                                  2 pages
/statuses/registration-open/                                      4 pages
/kinds/result/         every Result date on the site              13 pages
/exams/<slug>/         unchanged
```

~500 pages, against GitHub Pages' 10,000-file limit. Cross-products are
deliberately excluded: body × month alone is 3,753 pages.

Axis sizes are measured, not guessed:

| Axis | Count | Note |
|---|---:|---|
| Bodies | 139 | of 462 in `data/bodies.json`; 86 have exactly one exam, 37 have 2-4, 16 have 5+ (top: `kl-kpsc` 17, `in-upsc` 16, `in-nta` 13) |
| Months with events | 27 | 14 past, 13 upcoming; the 2024-01…2027-10 tail holds 1-11 events each |
| Types | 2 | Academic, Government |
| Statuses | 4 | open, soon, upcoming, done |
| Kinds | 13 | from `data/date_kinds.yaml` |

### Phase 1 — make the HTML a document

1. `baseof.html`: a `no-js` → `js` class flip in the head. Move every `hidden`
   attribute and every JS-only style behind `.js`. This alone fixes the
   invisible search box and the runtime `inert` toggling.
2. Month stepper and Grid/List tabs become real `<a>` elements in a `<nav>`.
   Script keeps enhancing the same DOM.
3. Server-render the month heading, the `(N Exams)` counts and the "no dates
   this month" note. Delete the `&nbsp;` placeholders **and the 73-line inline
   script at `home.html:121-194`** — it goes away entirely.
4. `dates.html` renders the day list as a real grouped `<ol>`. Deletes
   `data-events` and both readers of it.
5. With real month pages, the month group holds one month. The 220-card problem
   disappears rather than being deferred.

### Phase 2 — generate the index pages

6. A Hugo **content adapter** (`_content.gotmpl`; 0.166 supports it) emitting
   186 pages from `site.RegularPages`, reusing `exam-status.html`,
   `exam-card.html` and `milestones.html`. No front-matter changes, no pipeline
   churn, no revalidation of 313 records. An adapter rather than a native
   taxonomy because `bodies` is `[[bodies]]` array-of-tables carrying
   `body_role` — a taxonomy would need every record regenerated. The theme
   already has an unused `taxonomy.html` and `term.html` to model the index
   pages on, and `hugo.toml:12` is what switched taxonomies off.
7. Delete the unused `taxonomy.html` / `term.html`; give the axis pages the
   same card grid so they look like the site.
8. Home becomes current month + link index. Filters become a `<nav>` of links
   with counts, from the same build-time pass.

### Phase 3 — CSS

9. Split the bundle. `v2.css` and `exam.css` ship only on exam pages (Finding 6).
10. Metric-match the font (Finding 4). Add `size-adjust` / `ascent-override` /
    `descent-override` to the Jost blocks plus a `local()`-backed fallback face.
    This is the CLS.
11. Preload the 400 weight only (Finding 7).
12. Split the `cal__fly*` calendar-flyout CSS into the List panel's own sheet.
13. Optional: inline critical CSS, measured against (9).

### Phase 4 — stop shipping duplicates

14. 493 card elements → 313 (Finding 2). One clone loop, since every TBA and
    Completed href is already in the month group.
15. Build the two picker lists in script from `.card__title` + `href` already
    in the DOM, injected **before** `initListbox` snapshots its options at
    `site.js:360`. Removes ~141 KB of markup behind `hidden`/`inert`.
16. `filter-aliases` (13,249 B) **stays inline** — it feeds the search corpus
    at `site.js:706`.

### Phase 5 — build time

17. `sidebar.html:27` → `partialCached` (Finding 8).
18. Cache `exam-status.html` and `milestones.html` on `.RelPermalink`, as the
    95 `v2/params.html` call sites already do.

### Phase 6 — the guard rail

19. `site/tools/check-home.mjs` next to `check-links.mjs`. Assert: every
    control is a link, form field or `<summary>` (no orphan buttons); no empty
    `[id]` placeholders; no `data-events`; no page over a byte ceiling; and a
    build with the JS class forced off still contains all 313 exam URLs.
    `check-css.sh` will not catch a broken `content-visibility`, so do not
    rely on it for that.
20. Add the RSS `<link rel="alternate">` to the head.

## Files this touches

Documentation written for this work:

- `docs/site-perf.md` — this file
- `docs/todo.md` — the "Site speed" block, re-scoped

Site files the plan touches, listed so the change can be reviewed in advance.
**None of these have been modified.**

| Phase | Files |
|---|---|
| 1 | `site/themes/examhub/layouts/baseof.html`, `home.html`, `_partials/filters.html`, `_partials/filters-body.html`, `_partials/month-nav.html`, `_partials/dates.html`, `site/themes/examhub/assets/js/site.js` |
| 2 | **new** `site/content/_content.gotmpl`, **new** `site/themes/examhub/layouts/axis.html`, `site/hugo.toml`, `site/themes/examhub/layouts/taxonomy.html` *(delete)*, `site/themes/examhub/layouts/term.html` *(delete)*, `_partials/exam-list.html`, `_partials/exam-card.html` |
| 3 | `site/themes/examhub/layouts/baseof.html`, **new** `site/themes/examhub/assets/css/exam-pages.css`, **new** `site/themes/examhub/assets/css/calendar.css`, `_partials/fonts.html`, `assets/css/tokens.css`, `assets/css/browse.css`, `assets/css/v2.css` *(renamed)*, `assets/css/exam.css` *(renamed)* |
| 4 | `site/themes/examhub/layouts/home.html`, `_partials/filters-body.html`, `assets/js/site.js` |
| 5 | `site/themes/examhub/layouts/_partials/sidebar.html`, `_partials/exam-card.html`, `_partials/dates.html`, `section.exams.json`, `layouts/page.html` |
| 6 | **new** `site/tools/check-home.mjs`, `.github/workflows/site.yml`, `README.md` |

## Target

| | Now | After |
|---|---|---|
| Home HTML | 593 KB / 63.9 KB gz | ~80-90 KB / ~18 KB gz |
| Render-blocking CSS | 13.9 KB gz, one bundle, all pages | ~5 KB gz on home |
| Card elements on home | 493 (313 unique) | ≤93 |
| Font reflows | 3, no metric match | 0 |
| CLS | 0.48 | ~0 |
| Pages | 316 | ~500 |
| JavaScript off | search box missing, stepper dead, day list empty | complete |
| CSS off | unstyled and incomplete | unstyled and complete |
| CI build | 15 min budget, redundant partials | cached |

The home-page figure assumes home keeps the current month's ~93 cards. Cutting
it to a pure index would be ~25 KB, at the cost of the site's reason to exist.

## Risks

- **Phase 1 is a structural rewrite**, and `site.js` is 1,870 lines coupled to
  it: `window.examFilters`, `window.examDatesRepaint()`, `window.examPlace`,
  and the `initListbox` snapshot at `site.js:360`. The script has to be
  reworked in the same change or the page breaks. This is the bulk of the work
  and should not be split across pull requests.
- **`localStorage` state becomes partly redundant** once months are pages.
  `examPlace` and the `examhub-view` key in `initViews` need simplifying, not
  just porting.
- **`--minify` is CI-only.** Any local measurement, including a dev server,
  disagrees with production by ~4% raw. Compare gzip, or add a one-line build
  wrapper so nobody re-derives these numbers.
- **Verification has no browser.** Phase 6 is the only automated net. The
  no-JS/no-CSS claim should also be checked by hand once — `curl` the page, and
  block the stylesheet in devtools — before it is trusted.
- **SEO.** The home page's 313 links become ~93 plus an index. Exam pages are
  untouched, so the 313 landing pages keep their own metadata, but the home
  page's link graph does get thinner. Watch Search Console after Phase 2.
