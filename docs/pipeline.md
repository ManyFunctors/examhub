# The end-to-end pipeline on GitHub Actions

What runs, how often, what "instant" can honestly mean on GitHub's
infrastructure, and what no crawler can reach. Everything below was measured
from this repository in September 2026 unless it cites a source.

## Shape

```
                 data/catalogue/*.toml  (curated, on main)
                           |
     +---------------------+----------------------+
     |                     |                      |
 watch.yml             crawl.yml             crawl.yml (daily)  
 every 10 min          daily 02:43 IST       discover spider
 hot/warm feeds        all feeds + URL check CT logs, RSS, sitemaps,
     |                     |                 homepage links
     +----------+----------+                      |
                |                                 |
       data/harvest/ on the `harvest` branch  <---+
         notices.jsonl       every notice, exam + cycle attached
         changes/YYYY-MM.jsonl   append-only: new / gone / back
         feed.atom           newest 300 matched notices
         unmatched.jsonl     worklist: notice from a known body, no exam
         feed-health.jsonl   worklist: a feed that broke, with `since`
         url-health.jsonl    worklist: a catalogue URL that moved or died
         discovered-*.jsonl  worklist: sources not in the catalogue yet
         *-proposals.jsonl   worklist: new exams, patterns, feeds (discovery)
         documents/          each notification PDF, structured + rendered
                |
        notify.py -> a table of new notices on the run page
```

Two branches, two kinds of data. `main` holds code and the catalogue, and
changes only by reviewed pull request. `harvest` holds observations and is
written only by the workflows. Nothing is ever pushed to `main`.

## "Instant", honestly

| constraint | value | source |
|---|---|---|
| shortest `schedule` interval | 5 minutes | [GitHub docs: events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) |
| schedule under load | "can be delayed ... High load times include the start of every hour"; "some queued jobs may be dropped" | same |
| inactive public repo | schedules disabled after 60 days without activity | same (the `harvest` commits count as activity) |
| job time limit | 6 hours | [GitHub docs: limits](https://docs.github.com/en/actions/reference/limits) |
| concurrent jobs, Free plan | 20 | same |
| minutes | unlimited for public repos; 2,000/month for private repos on Free | GitHub billing |

The fast loop is therefore a `*/10` schedule, at off-minutes on purpose, and
has two escape hatches:

1. **Firm cadence.** An external scheduler such as cron-job.org calls
   `POST /repos/{owner}/{repo}/dispatches` with `{"event_type": "watch"}`
   every 5 minutes. It needs a fine-grained token with *Contents: write* on
   this repository only. `watch.yml` already listens for it. GitHub's own
   schedule stays as the fallback.
2. **Stay public.** A */10 loop costs roughly 3 minutes per run, about
   13,000 minutes a month; a private repository gets 2,000 on Free. The
   repository is public for that reason (the data is public notices).

Expected latency from a notice going up to it being in the harvest is 10–25 minutes for
a hot feed, the length of a warm cycle (≤ 30 min) for a warm feed, and up to
a day for a cold one. The tiers are why this is affordable:

* **Hot** is a feed whose body published something in the last 21 days,
  judged by the notice's published date, or by `first_seen` after the feed's
  first crawl, so a bootstrap backlog does not count.
* **Warm** is a feed active in the last 120 days.
* **Cold** is everything else.

Tiers cool off by themselves, so the loop follows the exam calendar with no
one tuning it. `tier = "hot"` in the catalogue pins a feed.

## Cheap polling

* **Conditional GET.** The ETag / Last-Modified from the previous run are
  sent back. Measured over the catalogue: 301 of 373 plain-HTTP feeds
  answered 200. Of those, 68 sent an ETag and 84 a Last-Modified, and 73
  answered a revalidation with **304** (about a quarter). Validators are
  stored only when the notice set changes, so a host that rotates ETags
  never causes churn.
* **Change is the notice set, not the page bytes.** Notice boards embed
  visitor counters, CSRF tokens and "last updated" clocks, so a byte hash
  changes on every fetch. The adapter's extracted `(url, title)` set is
  what is compared, and an unchanged world is an empty git diff.
* **Size.** The median feed page is 91 KB, so a full sweep of 410 feeds is
  about 36 MB. The cost of a sweep is slow hosts, not bytes: the full crawl
  takes ~45 minutes, most of it in 45-second timeouts on a dozen dead
  hosts. The fast loop uses a 30-second timeout and one retry.

## Coverage: sources, and how each is reached

| source | how | where |
|---|---|---|
| body notice boards, result pages, calendars | `html_links` / `html_table` adapters | 410 feeds in the catalogue |
| client-rendered boards (SSC, AIIMS, several state portals) | headless Firefox via selenium; **automatic** retry in Firefox when an HTTP page yields nothing and looks like a script shell | `render = "browser"`, or `auto_browser` in feed-health |
| JSON APIs behind JS boards | `json_api` adapter | e.g. SSC |
| RSS / Atom | `rss` adapter; the discover spider finds `<link rel=alternate>` feeds | e.g. `keralapsc.gov.in/rss.xml` |
| PDFs | every notice link is kept with its URL; the existing `extract` path (pymupdf, OCR extra) reads text layers and dates | `pdf_document` adapter for PDF-only feeds |
| new exam portals | Certificate Transparency: a new `*.body-domain` certificate appears days before the notification links to it | `scrapy crawl discover -a only=ct` |
| pages no feed covers | homepage links named notice board / recruitment / results / what's new | `discovered-pages.jsonl` |
| cross-body aggregators | `match_scope = "all"`: a notice is matched only against the exams of the bodies it names | see below |

Certificate Transparency is the one genuinely early signal. A query on
`nta.nic.in` returned `cmat`, `csirnet`, `cuet`, `exams`, `jeemain`, `neet`
and `ugcnet`, which is every NTA exam portal. crt.sh is free but often
overloaded: during testing its robots.txt returned 502, which RFC 9309 treats
as "disallow for now", so a failed domain waits for the next run. With a
`CERTSPOTTER_API_KEY` secret the spider uses
[Cert Spotter](https://sslmate.com/help/reference/ct_search_api_v1) instead,
incrementally, with a per-domain `after` cursor. Its unauthenticated tier is
for "personal or evaluation purposes" only, so it is not used without a key.

**Sources the discover spider found on its first run** (three
jurisdictions, `in`, `kl`, `tn`): 63 feeds and sitemaps, and 1,606 candidate
pages across 123 bodies. Three sources were adopted straight away:

* **WordPress feeds** (`/feed/`) were found on CISCE, IBPS, EPFO, BEL, NHB,
  NISM, BEML and more; CISCE's and IBPS's are now in the catalogue. The
  CISCE feed gives dated items that all match an exam (ICSE / ISC
  re-evaluation results, timetables). EPFO's and AAI's were empty, and the
  rest wait in `discovered-feeds.jsonl`.
* **The unified RRB portal.** Every regional RRB site now redirects to
  `rrb.indianrailways.gov.in/<region>`, whose update block lists each CEN
  and category with the date of its last change: "(03/2026) Application
  (Special Notice) (16-09-2026)". The category link is the same across
  updates, so the feed uses `identity = "url_title"`. The titles name a CEN,
  not an exam, so it uses `notify = "all"`. The `getdata` detail pages are
  behind an F5 WAF that answers "Request Rejected" to a direct request. They
  work with the region page's session cookie and Referer, but render their
  document list client-side, so they are not followed yet.

**Aggregators investigated and not adopted:**

* **PIB.** `RssMain.aspx?...&Lang=1` now answers with a 302 to the Hindi
  feed (`Lang=2&reg=48`) for every request, cookies or not. English exam
  patterns cannot match it.
* **Employment News.** The landing page sends a script redirect to
  `/NewEmp/Home.aspx`, which answered 404.
* **eGazette.** The TLS certificate chain does not verify with curl, and
  the site is a search form.

The mechanism (`match_scope = "all"`) is in place and tested for when any of
these becomes usable, or for state gazettes.

**Seeds for growing the catalogue.** The body list was seeded by hand; the
coverage report says which entries the crawl confirms. To grow it:

* [igod.gov.in](https://igod.gov.in/), NIC's directory of every
  government website at every level, is the authoritative seed for bodies.
* The discover spider's `discovered-hosts` and `discovered-pages` are the
  seed for feeds.

## New exam discovery

`python -m examhub_pipeline catalogue discover` runs after every daily crawl.
It reads only the harvest, needs no network, and writes three worklists:

| worklist | what it proposes | evidence it needs |
|---|---|---|
| `exam-proposals.jsonl` | a new exam series of a known body, e.g. `CGPSC Assistant Geologist Examination` | the same series name (words before *Examination / Exam / Test / Entrance*) in two unmatched notices, or in one notification |
| `match-proposals.jsonl` | an extra `match.any` pattern for an existing exam whose notices go unmatched | unmatched notices that carry the exam's distinctive words |
| `source-proposals.jsonl` | a new feed: a page or RSS feed the discover spider found **and trial-read** with the real adapter | at least two notices on it that match the body's exams (one for RSS) |

Series names are grouped per body. An acronym and its expansion merge
(`DUET` and `Delhi University Entrance Test`), a name that is really another
body's exam becomes a scope note instead of a new exam, and phrasing that is
never an exam (`basis of the Written Examination`, `Form of ...`) is listed in
`data/catalogue/discovery-ignore.toml` so it does not come back.

Nothing is adopted automatically. A maintainer runs

    python -m examhub_pipeline catalogue adopt <proposal-id> ... [--dry-run]

which writes the entries into the right jurisdiction file, refuses an id that
exists, and writes nothing unless the whole catalogue still lints clean. The
change then goes through a pull request like any other catalogue edit.

**First run (September 2026).**
* **Exams.** Adoption went in two passes. The first adopted 38 series. The
  second adopted 12 more: seven CGPSC post-series, NIFT, the NTA-run
  Biomedical Research Eligibility Test, PPSC Joint Competitive, RPSC
  Librarian & PTI, and Puducherry B.Sc. Nursing. The catalogue now has
  1,017 exams.
* **Feeds.** The full discover run found 2,514 candidate pages and 103 RSS
  feeds. Trial-reading them gave 392 source proposals, and the 54 strongest
  were adopted: PSC result and answer-key boards, several High Court
  recruitment pages, JKBOPEE, PSSSB, TN MRB, BCECEB, HPBOSE, and the
  Indian Bank, Union Bank and IOB career pages. The catalogue now has 467
  feeds.

## Reading the PDFs

A notification's title says little; its PDF says how many posts there are,
for whom, what they pay, who may apply, what it costs and by when.
`documents.py` reads that out deterministically:

1. **Fetch.** `scrapy crawl documents` picks matched notices whose URL is a
   PDF, or whose type is a notification. It skips results, answer keys,
   admit cards and lists of candidates, takes the newest first, and saves
   the PDFs to `work/documents/`. An HTML landing page is recorded as
   `not_pdf` and never tried again. A failure is retried once a day, at
   most three times. A run takes at most three documents per host. After a
   host's first timeout or DNS failure, its remaining requests that run fail
   at once. The spider also has a hard time limit (25 minutes daily, 4 in
   the watch loop). All three limits exist because, measured, one
   unresponsive host (nta.ac.in) otherwise held a run for 15 minutes.
2. **Structure.** `python -m examhub_pipeline documents build` reads each PDF:
   * **Tables** are found with pymupdf's table finder, and each is classified
     by its header row: a vacancy matrix (UR/EWS/OBC/SC/ST columns), a fee
     table, an age-relaxation table, a schedule, or an exam pattern.
   * **Prose** is read by the existing `candidates.py` date and pay readers,
     plus readers for fees ("Rs. 850/- for all candidates other than
     SC/ST/PwBD"), age limits, relaxations, qualification clauses and
     selection stages.
   * **Scanned PDFs** are OCR'd with tesseract (`eng+hin` on the runner, the
     first 20 pages).
3. **Store.** Each document is written to `documents/<id>.json` (schema in
   [data-model.md](data-model.md#document)) and `documents/<id>.md`, a page a
   person can read, and gets a line in `documents/index.jsonl`.

Every value carries its page number. A value that could not be read is
absent, not guessed, and an OCR'd document says so at the top. Categories
are normalised (`General`/`Gen`/`Unreserved` → `UR`, `PH`/`PwD` → `PwBD`,
`EXS` → `ESM`). "Other than SC/ST" is stored as `except: true`, never as
SC/ST.

**Where it runs.**
* **The 10-minute watch** reads up to six new PDFs from their text layer, so
  the run page can say what the notice says, for example `500 posts · apply by
  2026-11-11 · fee ₹100–850 · age 21–30`. Scans are marked `needs_ocr`.
* **The daily crawl** installs tesseract and picks up those scans, along with
  up to 150 other documents.

### Filling each exam, run after run

Documents are also merged per exam into a **profile** (`exams/<exam>.json`),
one field at a time, and every exam's missing fields go into
`exams/gaps.jsonl`. The gap list steers the next fetch, so each run does
the most it can within its budget:

1. **New notices first**, newest first, at most two per exam. A new
   feed's first crawl makes its whole archive look new, and without the
   cap one exam would take the whole budget.
2. **Then gap-filling.** The remaining budget goes to the exams missing
   the most, one document per exam per round. Each takes its newest
   untried document of any age. Exams with no documents yet go first.
3. **Then redos:** records made by an older reader version.

Every exam's backlog is therefore read in time, the emptiest first, and no
single run fetches more than its limit (150 daily, 6 in the watch loop),
three per host.

The merge rule is fixed, so the same documents always give the same
profile:

* **Per-cycle fields come only from the exam's newest cycle.** Dates,
  vacancies, fees and age limits are never filled from an earlier cycle: a
  2024 fee is not this year's fee.
* **Stable facts carry over, marked.** Education level, selection stages,
  exam pattern and pay may come from an earlier cycle when the current one
  has none. They are marked `carried_from`.
* **Among candidates, for terms:** an advertisement or brochure beats a
  corrigendum, which beats other notices. A table beats prose, and a text
  layer beats OCR.
* **Among candidates, for dates:** the newest document wins. That is what a
  corrigendum is for.

Each field keeps its source (notice, URL, page) and how many other
documents offered a value (`alternatives`), so a disagreement is visible.

The limit is series that the catalogue models as one generic exam, such as
`in-union-bank-recruitment`. There, "the current cycle" is every recruitment
that year, so the profile describes the newest one best. Splitting such a
series into its recurring posts is a catalogue change. Discovery does not
propose it, because those notices are already matched.

**What it cannot do.** Per-post details in a long multi-post advertisement,
such as the UPSC ORA with many posts in running prose, come out as lists of
the pay levels and qualification clauses found, not as one row per post.
Hindi-only PDFs typed in legacy fonts such as Kruti Dev have a text layer of
Latin gibberish, and are read as nothing. Numbers in an OCR'd table can be
misread, which is why OCR is flagged.

## What the first full crawl found, and what was fixed

The first sweep of all 409 feeds:

* 224 yielded notices: 13,712 notices, 5,463 matched to an exam.
* 114 answered and yielded nothing.
* The rest failed: 18 × 404, 15 DNS, 14 timeouts, 11 disallowed by the
  site's robots.txt, and a handful of 5xx.

The 114 empty feeds had three causes:

1. **Chrome filtering was substring-based.** It treated
   `<body class="home page-template ...">`, and whole-page `<header>`
   wrappers, as site navigation. Supreme Court: 330 PDFs dropped; India
   Post GDS: 152. Now only whole class/id tokens count, `<html>`/`<body>`
   never do, and an element holding over 40% of a page's documents is
   content, not chrome. Replaying the cached pages: 237 feeds yield
   (was 224) and 6,617 notices match (was 5,463).
2. **zstd.** 18 responses came back zstd-encoded and Scrapy had no
   decoder installed. `zstandard` and `brotli` are now in the `crawl`
   extra.
3. **Client-rendered pages** (34 feeds with almost no text or links). These
   are now retried in Firefox automatically.

A quadratic regex (`\s*` over thousand-space table padding) also made eight
pages take over 10 seconds each. It is now linear.

## What no crawler here can reach

* **Candidate-only channels.** Admit cards behind a login, SMS and e-mail
  sent to registered candidates, and captcha-gated result lookups. The
  pipeline records the public notice that says they are out, not the
  personal document.
* **Image-only PDFs.** OCR (the `ocr` extra) reads them; the text can be
  wrong, and every such value is flagged for review.
* **Social media and newspapers.** Some bodies announce on X or in print
  first. Neither has a stable, permitted, key-free machine interface, so
  neither is used.
* **Sites that block by robots.txt.** They are honoured (11 feeds). The
  answer is to ask the body, or have a maintainer paste the URL.

## Operating it

Secrets, all optional:

* `CERTSPOTTER_API_KEY`: CT discovery via Cert Spotter.

Daily maintainer loop, all on the `harvest` branch:

* `feed-health.jsonl` lines with an `alert` or `auto_browser`: fix the
  feed with `python -m examhub_pipeline.crawl.probe <feed-id>`.
* `unmatched.jsonl`: add a `match.none` for noise, or add the missing exam.
* `*-proposals.jsonl`: `catalogue adopt <id>` the real ones (a PR to main),
  add the noise to `data/catalogue/discovery-ignore.toml`.
* `exams/gaps.jsonl`: exams whose gaps do not close over a week have no
  document that states the field; usually the body's advertisement lives on
  a page no feed reads yet.
* `documents/index.jsonl` lines with `status = "failed"`: usually a host that
  times out; `python -m examhub_pipeline documents show <id>` prints a record.

Consumers read `feed.atom` or `changes/*.jsonl` straight from the branch:
`https://raw.githubusercontent.com/<owner>/<repo>/harvest/data/harvest/feed.atom`.

GitHub keeps at most one *pending* run per concurrency group, and a newer
pending run replaces it. The daily crawl is scheduled at :13, just after a
watch run starts, so it is running, not pending, by the time the next watch
run queues.
