# To do

In order. Data and cleaning first.

## Now: data and cleaning

- [ ] Exam page template, agreed block by block (`docs/exam-template.md`)
  - [ ] Check the 11 gaps in `docs/template-gaps.md` against the current template
  - [ ] Cut-offs (decision 53): classify cut-off notices, fetch them in the documents crawl,
        a `cutoffs` step that reads their tables into rows, filled each night
  - [x] One file per cycle; `exam_id` + `cycle`; `slug`; `title` + `official_name`; `series`; `known_as`
  - [x] Duplicate records merged each night by `dedupe --apply` (recheck), only when
        no fact is lost; the old URL redirects. 7 pairs merge on its first run; 5 disagree
        (a date, a link, post names) and are left apart in its log
  - [x] Short names, filled automatically each night by `names --apply` (265 set 1 Oct).
        45 left as is, and 14 likely duplicate pairs to merge, in `docs/short-names.md`
  - [x] Conducting body: a body site on one folder of a shared host (NTA's
        `exams.nta.nic.in/jipmat/`) no longer claims every exam on that host; 6 records fixed
  - [x] Dates, including the application correction window (decisions 5–12)
  - [x] Eligibility, exam details, links, fee, pay, provenance (decisions 17–48)
  - [x] Decision 35 fields written into the template body
- [ ] More sources (asked 29 Sep 2026). In the catalogue as bodies but with
      **no feeds**, so nothing is harvested: ISI, CMI, Institute of Actuaries
      of India, and the banks BoB, PNB, Canara, BoI, Central Bank, UCO, Bank of
      Maharashtra, EXIM, NHB, IPPB, ECGC. **Not in the catalogue at all:** NBHM
      (National Board for Higher Mathematics) and IFoA (Institute and Faculty
      of Actuaries, UK; exams sat in India). Also check bank bodies not yet
      listed (Punjab & Sind, IDBI, RRBs, state co-operative banks).
- [ ] Eligibility schema 2 and a golden set of real notices, scored per field
- [ ] Quality as a feedback loop: targets per field; a run below target spends more effort where the shortfall is
- [x] Wayback Machine archiving of every PDF read: `archive` runs in the daily crawl
      (40 a run), after the PDFs are read. First run 1 Oct: 3 of 10 archived; the other 7
      hosts (Punjab SSSB, TN MRB) refuse the archive's crawler (520/523), so failures back
      off 7 → 14 → 28 → 90 days. Snapshots in `data/harvest/archived.jsonl`
- [x] Publish dates: each harvest now fills a missing date from the title ("05-02-2025 - …",
      "dated 15.03.2023"; 94% match printed dates) or the file name (71%), marked
      `published_from`. Fills 4,387 of 18,622 on the next run
- [x] Document types (`docs/vocabulary.md` §3, agreed 1 Oct): `application_status`,
      `counselling`, `walk_in`, `syllabus` added, and interviews/PET/DV count as `schedule`.
      5,106 of the 22,853 `other` notices get a type; each harvest reclassifies the rest.
      Subtypes not done
- [x] `links.documents.document_archive` filled each night (recheck) from `archived.jsonl`;
      the crawl archives the 320 documents records link to first, then the harvest's PDFs
- [ ] Local models where they help: embeddings first, then GLiNER2, then NuExtract (`docs/model-options.md`)

## Site speed

Measured 30 Sep 2026 (Lighthouse, throttled): 472 KB of HTML, 60 KB gzipped.
**Read [`docs/site-perf.md`](site-perf.md) first** — it has the byte-by-byte
breakdown, the reproductions, and why the plan below is not the one originally
written here. The short version: the home page is 64 KB gzipped because of
duplication and a font swap, not because of a loading strategy, and the 0.48
CLS is `font-display: swap` with no metric-matched fallback.

- [x] **Phase 1** — make the HTML a document: a `no-js`/`js` class flip, real
      links in place of the dead `<button>`s, server-rendered headings and
      counts, a server-rendered day list. The page then works with JavaScript
      off, and 220 of the 313 cards stop shipping to be hidden. Done 1 Oct,
      option B: the page ships its own month (cards, chips, counts, day list,
      calendar caption); `/index.json` (every date, the other cards, aliases)
      is fetched when the page is idle or the bar is touched. The inline
      script and `data-events` are gone; `_partials/events.html` is the one
      source for dates. After the data loads the page is identical to before
      (visible-layout diff, 20 flows, two widths). Home 60.2 → 27.7 KB gz
- [x] **Phase 2** — generate the index pages (~186: 139 bodies, 27 months, 2
      types, 4 statuses, 13 kinds, 1 all-dates) with a Hugo content adapter.
      On a static host a no-JS filter has to be a page, not a query string.
      Months done 1 Oct: `content/_content.gotmpl` makes /YYYY-MM/ for every
      month from 2024-01 to 2027-10 (46 pages, `layouts/month.html`). The
      adapter can't read other pages, so it finds the range from the records'
      `from =`/`to =` lines. Rest done 1 Oct: the same adapter makes /bodies/<id>/ (140),
      /types/ (2), /statuses/ (4), /kinds/ (14) and a list page for each (`axis.html`,
      `axis-list.html`). A no-JS home page shows "Browse By" links to them; an exam
      page's "Conducted by" links its body. `check-home` checks they exist and are
      linked. Unused `taxonomy.html`/`term.html` deleted
- [x] **Phase 3** — split the CSS bundle so `v2.css`/`exam.css` load only on
      exam pages, and metric-match the font fallback. Done 30 Sep: split by
      rule, not by file (`v2.css` was half home rules). Every page loads
      `examhub.css` (5.2 KB gz, cached across pages) plus `home.css` (6.7 KB)
      or `exam-page.css` (3.9 KB); before, one 13.9 KB bundle everywhere. New
      files: `shared.css`, `chips.css`, `v2-home.css`. Checked with zero
      computed-style differences on 30 page states. "Jost Fallback" (Arial
      reshaped: size-adjust 94.9%, ascent 112.7%, descent 39.5%) and a
      preload of the 400 weight. Left: the `cal__fly*` split (item 12) and
      inline critical CSS (item 13), both optional
- [x] **Phase 4** — stop shipping duplicates: 493 card elements down to 313,
      and the two picker lists built in script from data already in the DOM.
      Done 1 Oct: home ships 191 cards (the month, TBA, Completed); the
      script copies TBA/Completed cards into the month section rather than
      fetching them again, and builds the Exam and Body lists from index.json
- [x] **Phase 5** — cache `exam-list.html` in `sidebar.html` and cache
      `exam-status.html` / `milestones.html` on `.RelPermalink`. Done 30 Sep:
      build 24.4 s → 1.7 s, output byte-identical
- [x] **Phase 6** — `site/tools/check-home.mjs`, including an assertion that a
      build with the JS class forced off still contains all 313 exam URLs.
      Done 1 Oct, run in CI after the build: every exam linked from the
      browse pages, month arrows are links to pages that exist, no `&nbsp;`
      placeholders or `data-events`, index.json complete, home under 40 KB
      gz, RSS advertised in the head

Dropped, with reasons in `docs/site-perf.md`:

- ~~Skeletons~~ — nothing arrives late once content is server-rendered, and the
  `(N Exams)` counts come from real cards, so a skeleton would have to lie
- ~~Defer the card grid~~ — the cards *are* the search index
  (`site.js:615-623` bails on `if (!cards.length) return;`)
- ~~Defer below-the-fold parts of exam pages~~ — measured: mean 15,847 B, p90
  15,332 B, max 45,767 B. The folded sections total ~8 KB on the largest page,
  so a round trip costs more than it saves. They pick up no-JS support free
  from Phase 1
