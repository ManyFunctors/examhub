# How the pipeline works, in depth

The detail behind the [README](../README.md): the design rule, the catalogue and crawler, the per-record commands, the validator measurements, politeness, and what is tested. Moved here from the README on 1 Oct 2026; counts and dates are as measured then.

## The architecture rule

> **Deterministic code extracts; the model verifies; never the reverse.**

This is the whole design, and it is not a style preference:

- A 322M-parameter non-autoregressive classifier cannot pull a date out of a
  60-page notification. Asking one to is how a hallucinated date ends up in
  front matter that a site then renders as fact.
- Regex and heuristics *can* find a date, because notices print dates in a
  small number of shapes. So `candidates.py` finds them, records the sentence
  each one came from, and refuses to guess a day from a month.
- The model then answers a **typed question about a closed set of options**.
  That is the shape it is good at, and its answer is a distribution over
  labels rather than generated text, so there is nothing to parse and nothing
  to hallucinate.

There is no LLM anywhere in the extraction path. There is no prompt in
`candidates.py`. There is no regex in `validate.py`.

```
   discover ──▶ fetch ──▶ extract ──▶ candidates ──▶ validate ──▶ review ──▶ propose
   (link          (cache,  (HTML/PDF/   (regex, the    (Laya,    (one-    (git
    filter)       robots,   OCR ->      find layer)   verify)   screen)  branch)
                 throttle)  text)                   │
                                                     └── absence is decided HERE,
                                                         deterministically
```

---

## The exam catalogue and the crawler

Alongside the per-record pipeline, this repository keeps a catalogue of Indian
exams, academic and government, central and state, and a crawler that keeps
it honest. The full specification is [`docs/data-model.md`](data-model.md).

**Two layers.** The *catalogue* is curated TOML in git and changes rarely.
*Observations* are JSONL that only machines write.

| layer | where | what |
|---|---|---|
| catalogue | `data/catalogue/vocab.toml` | every enum (body kinds, exam purposes, doc types, ...) |
| catalogue | `data/catalogue/jurisdictions.toml` | India plus 36 states and UTs |
| catalogue | `data/catalogue/<jur>.toml` | the `[[bodies]]`, `[[feeds]]` and `[[exams]]` of one jurisdiction |
| observations | `data/harvest/notices.jsonl` | every notice seen, with the exam and cycle it matched |
| observations | `data/harvest/unmatched.jsonl` | notices from a known body that match no exam: the maintainer's worklist |
| observations | `data/harvest/feed-health.jsonl`, `url-health.jsonl` | per feed and per URL state, with `since` |
| observations | `data/harvest/*-proposals.jsonl` | discovery: new exam series, match patterns and feeds, for a maintainer to adopt |
| observations | `data/harvest/documents/` | each notification PDF, structured (vacancies by category, fees, age, pay, eligibility, dates; with page numbers) and rendered as Markdown |

**Ids are forever.** They are kebab-case and jurisdiction-prefixed
(`in-ssc-cgl`, `kl-kpsc-ldc`, `up-uppsc-pcs`). An id never contains a year,
an operator or anyone else's code, and it is never reused. If a series is
renamed, the id stays. If a series is replaced, the old one gets
`status = "merged"` and a `successor`. A cycle is `<exam>/<label>`, e.g.
`in-ugc-net/2026-jun`. A notice id is the sha256 of its canonical URL.

**No LLM, minimal upkeep.** A feed is declarative: a URL, one of five adapters
(`html_links`, `html_table`, `json_api`, `rss`, `pdf_document`), optional CSS
selectors, and `render = "browser"` for the few JS-only sites. Headless Firefox
is used for those only, via selenium and geckodriver; Playwright is not used.
A notice is assigned to an exam by regexes (`match.any` / `match.none`) scoped
to the body that published it. The longest match wins, and a tie is reported
as ambiguous rather than guessed. When a site is redesigned, the upkeep is
one selector:

```bash
python -m examhub_pipeline.crawl.probe in-upsc/active-exams   # what does the adapter extract now?
```

```bash
uv pip install -e '.[crawl,ocr]'                 # ocr: tesseract for scanned PDFs
python -m examhub_pipeline catalogue lint        # ids, enums, references, regexes
python -m examhub_pipeline catalogue stats
python -m examhub_pipeline catalogue coverage -v # which exams have live evidence, and which do not
scrapy crawl feeds                               # all feeds; -a jurisdiction=kl / -a body=in-nta / -a feed=...
scrapy crawl feeds -a tier=hot                   # only feeds in season (what watch.yml runs)
scrapy crawl verify                              # every body website and exam page
scrapy crawl discover                            # sources the catalogue does not know yet
python -m examhub_pipeline catalogue discover    # propose new exams / patterns / feeds from the harvest
python -m examhub_pipeline catalogue adopt <proposal-id> --dry-run
scrapy crawl documents                           # fetch new notification PDFs
python -m examhub_pipeline documents build       # structure them into data/harvest/documents/
python -m examhub_pipeline documents file some.pdf   # structure one local PDF, print Markdown
python -m examhub_pipeline.crawl.notify --dry-run
```

**Stable diffs.** Nothing in `data/harvest` carries a per-run timestamp. A
notice has `first_seen` and, once it leaves its feed, `gone_since`; it is never
deleted. Health records carry `since`, which moves only when the state changes.
An unchanged world is therefore an empty diff, and the workflows commit to
the `harvest` branch only when something actually happened. New notices are
also appended to `changes/YYYY-MM.jsonl` and published as `feed.atom`.

**What the catalogue is, honestly.** The catalogue was seeded from knowledge of
the bodies, not scraped. The crawl is what confirms it: `catalogue coverage`
lists the exams that have at least one live, matched notice, and the exams
that have none. An exam with no evidence is either one whose feed is missing
or broken, or one that is wrong.

**User agents and WAFs.** Most Indian government WAFs (NIC-hosted sites,
UPSC, NTA) answer **403** to anything bot-shaped: the word "bot", a URL in
parentheses, or a contact inside the UA string. The crawler therefore sends a
plain `examhub-pipeline/0.2` and puts the contact in the `From:` header, the
header RFC 9110 defines for exactly this. With that, the hosts in the table
under *Politeness* answer 200, including their robots.txt.

---
### The model path is optional

If `laya` is not installed, every field comes back `not_validated` and the
review banner says so:

```
! Laya was NOT available. Nothing below is model-verified; every value is a
  regex candidate.
```

The crawl, the extraction, the diff and the git branch all still work. A run
that cannot verify produces a review bundle full of flags rather than a
commit full of guesses.

## Usage

```bash
# what is out there?
python -m examhub_pipeline sources
python -m examhub_pipeline discover --source ugcnet --source nta

# fetch (polite, cached, OCR'd where needed)
python -m examhub_pipeline fetch --source ugcnet --limit 8

# what did we get, without touching the network
python -m examhub_pipeline extract

# what does the model make of it
python -m examhub_pipeline validate --url public-notice-for-schedule

# the thing a human actually reads
python -m examhub_pipeline review

# put it on a branch (never on main, never pushed)
python -m examhub_pipeline propose
python -m examhub_pipeline propose --commit   # commits on the new branch only
```

`run` does fetch → extract → validate → review in one go.

Two subcommands need no run in front of them:

```bash
# offline, read-only: does every record still parse and satisfy the schema?
python -m examhub_pipeline lint                  # checks site/ by default
python -m examhub_pipeline lint --strict         # warnings too

# reproduce the numbers in "What the validator can and cannot do"
python -m examhub_pipeline eval
python -m examhub_pipeline bench
```

### Exit codes

| code | meaning | what the scheduled job does |
|---|---|---|
| 0 | ran, and something changed | open a pull request |
| 2 | ran, nothing changed | **do nothing** |
| 3 | ran, but some documents failed | open a pull request, mention the failures |
| 1 | error the operator must fix (`lint` found schema violations) | fail the job |
| 1 | error the operator must fix | fail the job |

Exit 2 is the whole point of the scheduled workflow. A job that opens a pull
request every night gets ignored within a fortnight.

---

## The review output

`review` prints one screen, and writes a bundle next to it:

```
examhub-pipeline review  2026-09-27 12:04 UTC
2 record(s) would change of 8 checked  |  verified 6  undecided 1  disputed 1  unvalidated 0  absent(omitted) 3
! 2 document(s) had no text layer and were OCR'd. Every value from those pages can be wrong.

content/exams/ugc-nta-ugc-net-june-2025.md
  ~ dates.stages[1].exam: 2025-06-25 (confirmed) -> 2025-06-26 (tentative)
  ! 1 unverified  needs a human read
  ~ result_date: - -> 2025-07-21             (model 0.68, publishes p=0.63)

3/14 fields model-verified against the source. Nothing has been written to the
site and nothing is published by this tool.
```

| symbol | verdict | what it means |
|---|---|---|
| `✓` | `verified` | the document publishes the field and the model picked our value. **This is the only verdict that writes.** |
| `!` | `disputed` | the document appears to give a different value. Our value is *not* written. |
| `?` | `undecided` | the model is not confident enough either way. A human decides. |
| `—` | `not_validated` | Laya unavailable, or no window could be read. Never written. |
| `·` | `absent` | no candidate found, so the key is omitted. Deterministic. |
| `!` | `heuristic` | came from a non-official tier. Discovery only. |

Bundle layout:

```
work/reviews/<timestamp>/
  summary.txt      the one screen
  report.json      every field, every verdict, every probability
  review.patch     unified diff
  propose.patch    the same diff, ready for `git apply`
  before/*.md      the record as committed
  after/*.md       the record this run would write
  proposal.json    branch, files, commit (if any)
```

---

## What the validator can and cannot do

This section is the honest part. The numbers below are measured, not quoted
from a paper. Reproduce them with `python -m examhub_pipeline eval`.

### The dev set

`data/devset/devset.jsonl`, 26 hand-labelled examples built from documents this
tool actually fetched, plus a few short synthetic positives and negatives:

| source | document | text layer |
|---|---|---|
| UGC-NET | admit-card release notice (25 June 2025) | yes |
| UGC-NET | admit-card release notice (26 June 2025) | yes |
| UGC-NET | provisional answer key + challenge window | yes |
| UGC-NET | results press release | **no — OCR** |
| NTA | examination calendar, December 2026 cycle onwards | **no — OCR** |
| AIIMS | key-dates landing page (Next.js, dates not in the HTML) | n/a |
| synthetic | fee table; a boilerplate clause with no dates | n/a |

9 of the 26 label a field as **present with a value**; 17 label it **absent**.

### Existence: does the document publish this field at all?

**It does not work, so the pipeline does not use it to decide.**

Four phrasings were tried on both checkpoints. Best achievable accuracy over a
threshold sweep, and AUC (the number to read first — with a probability that
barely moves, accuracy at any single threshold is a coin flip dressed up as a
result):

| formulation | multilingual | typed-decisions |
|---|---|---|
| `noul`, generic presence | 0.61 / AUC 0.59 | 0.65 / AUC 0.78 |
| `noul`, specific claimed value | 0.50 / AUC 0.58 | — |
| two-option `choice`, yes/no | 0.67 / AUC 0.69 | — |
| `noul`, terse "is X written" | 0.61 / AUC 0.59 | — |

The `multilingual` checkpoint returns **P(true) = 1.000 for every single
example**, present or absent: 21 of 26 fell in the 0.8–1.0 bin and its
calibration error was **0.51**. That is not a threshold that needs tuning; it
is a signal that is not there.

So absence is decided where the architecture says it should be — in
deterministic code. If `candidates.py` found no candidate for a field, the
field is absent, full stop. The model's probability is still computed, still
recorded in `report.json` and still shown to the reviewer, and it does one
useful thing: a *low* presence probability next to a found candidate is a
tripwire (usually a date attached to the wrong label) and escalates the field
to `undecided`. It never removes a key on its own.

### Value: is our value the one the document gives?

**This works, on one checkpoint.**

| checkpoint | accuracy | mean confidence when right | median latency |
|---|---|---|---|
| `multilingual` (322M) | **2/7** | 0.90 | 3.0 s |
| `typed-decisions` (421M) | **7/7** | 0.64 | 2.4 s |

`multilingual` is the 2.2x-faster model and the obvious choice on a CPU-only
box. It is wrong: it answered "none of these" with near-uniform probabilities
(0.61, 0.76, 0.86, 1.00) for four different documents. `typed-decisions` is
ModernBERT-large, slower on CPU, and is the one fine-tuned for typed
decisions. Hence the default. **The Router will not select it automatically**
— Laya's own docs say it is specialised to four synthetic workflows and should
not be a silent fallback — so the pipeline asks for it by name.

n=7 is a small sample. 7/7 is a reason to trust the direction, not a reason to
skip the review gate. The gate stays.

Reproduce: `python -m examhub_pipeline eval`

### Latency on this machine

AMD Ryzen 7 PRO 6850U, 8 cores / 16 threads, no CUDA, no ROCm, 27 GB RAM.
`torch 2.14.0+cpu`, 8 threads, `max_len=1024`, ~2000 characters per window,
two questions per call:

| | typed-decisions | multilingual |
|---|---|---|
| cold load | 26 s | 1 s (already cached) |
| median / call | 2.4 s | 3.0 s |
| max / call | 7.2 s | 16.6 s |

The published 33 ms figure is a **T4 GPU** number and is off by a factor of
~80 here. The published 8192-token window is not usable at all: `max_len`
applies *per question*, so two questions at 8192 means ~16k tokens, and a
direct measurement took **45 seconds** for a single call. Hence `max_len=1024`
(the checkpoint's ceiling) and chunking to ~4000 characters.

Measured scaling (`python -m examhub_pipeline bench`):

| characters | median ms | ms/char |
|---|---|---|
| 512 | 3546 | 6.93 |
| 1024 | 1411 | 1.38 |
| 2048 | 2366 | 1.16 |
| 4096 | 4800 | 1.17 |
| 8192 | 5037 | 0.62 |

Essentially linear above the warm-up, which is what a transformer on CPU does.
Budget **2–3 seconds per candidate per window**. A 60-page notification with 8
candidate fields across 2 windows each is ~17 calls, about a minute. Fine for a
nightly run, unacceptable for an interactive loop — which is what the cache is
for.

### What is not measured

- **Text fields** (`fee`, `eligibility`, `duration`, `venue`,
  `negative_marking`) are extracted deterministically and gated by the same
  confidence check, but the dev set does not label prose values, so **their
  verification accuracy is unmeasured**. They are stored verbatim from the
  source clause, which means they are at least traceable to a quote, and
  `report.json` carries the evidence string for each one.
- **Pay** is extracted and structured but no dev example covers it.
- **Real OCR accuracy** is not measured. The OCR path demonstrably fires on
  real scanned notices and produces usable text (the NTA calendar's
  "Proposed Date(s)" table came out readable), but nobody has scored it
  against a ground-truth transcription. Every value from an OCR'd page is
  marked in `provenance.ocr` and shown with `[OCR page]` in the review.
- **Conflict adjudication across documents** — when two notices disagree, or a
  corrigendum supersedes a notification — is implemented in `adjudicate` and
  flagged, but not exercised on a real conflict.

---
## Politeness

Non-negotiable, and the defaults are conservative on purpose:

| | default | flag |
|---|---|---|
| `robots.txt` | consulted before every request, including before robots.txt itself | `--ignore-robots` exists and is never set in this repo |
| per-host delay | **5 s** | `--host-delay` |
| concurrency per host | **2** | `--max-per-host` |
| per-run request budget | 400 | `--max-requests` |
| 429 / 5xx | exponential backoff with jitter, honours `Retry-After` | — |
| `Crawl-delay` | adopted if robots.txt states one | — |
| user agent | identifies the tool and a contact address | `EXAMHUB_CONTACT` |

**The disk cache is the important one.** It is keyed by URL and the body is
stored under its own content hash:

```
work/cache/meta/<sha256(url)>.json     url -> {etag, last_modified, content_hash, checked}
work/cache/blobs/<content_hash>        the bytes, shared between URLs
```

A re-run inside the TTL does **zero network requests**. Past the TTL it sends
a conditional GET, so a page that has not changed costs one 304 and no
transfer. The tool re-checks the same notices constantly; this is what makes
that affordable and rude-free at the same time.

### Set a real contact address

`EXAMHUB_CONTACT` defaults to `examhub-maintainer@example.invalid`, which is a
placeholder. Several government hosts block unidentified clients, and it is
reasonable for them to. Before running this against a host that matters:

```bash
export EXAMHUB_CONTACT="you@example.org"
```

### Hosts that will not work, and why

Measured, not assumed. These are on the seed registry and are **refused** at
runtime:

| host | why |
|---|---|
| `upsc.gov.in` | returns **403 for robots.txt** to a non-browser user-agent. Per RFC 9309 that means disallow-all, so the tool disallows it. |
| `neet.nta.nic.in` | same 403 on robots.txt |
| `jeemain.nta.nic.in` | same 403 on robots.txt |
| `www.pfrda.org.in` | publishes `User-agent: * / Disallow: /` with `Allow: /` for Googlebot only |
| `mcc.nta.ac.in` | DNS does not resolve from here |
| `ssc.gov.in` | robots.txt is a 404 (allowed) but the notice board is an ASP.NET dashboard whose content is JS-rendered: **0 links and 0 characters** from a plain fetch. Needs a browser or a maintainer-supplied URL list. |
| `aiimsexams.ac.in` | Next.js; the key-dates page renders its calendar links client-side, so the static HTML has no notice URLs |

> **Correction (measured with the catalogue crawler).** These 403s are caused
> by the user-agent string, not by a robots policy. A plain UA with the contact
> in a `From:` header gets 200 from upsc.gov.in and the NTA hosts, robots.txt
> included, and SSC and AIIMS are handled by feeds with `render = "browser"`.
> RFC 9309 also treats *any* 4xx robots.txt as "unavailable, crawl allowed"; the
> "401/403 means disallow" rule is Google's legacy behaviour, not the RFC's.
> This fetcher (`http.py`) keeps its stricter rule. See
> *The exam catalogue and the crawler*.

The 403s are the robots policy working as intended. The right response is to
ask the body for permission, or to have a maintainer paste in the URL — which
is what `--direct-url` is for — not to work around the block.

---

## Which notices are the same exam

A run over UGC-NET in one fortnight finds five notices: the examination
schedule, two admit-card releases, a city-allotment intimation, an extension
of the last date, and a provisional answer key. All five are about one exam. A
slug derived from the notice title turns that into five records for it.

Whether two notices describe the same examination is a judgement call, and
regex cannot make it, so a human makes it once in
[`data/record-map.toml`](../data/record-map.toml):

```toml
[[record]]
match     = "ugcnet.nta.ac.in"
slug      = "ugc-ugc-net-june-2025"
title     = "UGC NET, June 2025"
exam_kind = "job"
primary   = "public-notice-for-schedule-of-ugc-net"
```

Two things happen. Notices are **merged** into one record, with a corrigendum
superseding a notification, a press release superseding a notification, and
within a tier the most recently fetched document winning. And `primary` decides
**which document may write**: the others are read for cross-checks and their
values are reported, never stored.

`primary` is not decoration. Without it, the merge took whichever notice had
the last verified value and rendered the answer-key *challenge* window
(08 July 2025) as the last date to *apply*. Both dates are true, about
different things, and nothing in either notice's text says which one belongs
in the record. That is a human's call.

## Tables, and the ambiguity rule

A PDF text layer prints a date table as one line per cell, with no delimiters.
Soft-wrapping those into paragraphs put the word "examination" from the *fee*
row next to the fee row's date, and produced `exam_date = 2025-05-08` for an
exam held on 25 June 2025. The model then verified it at 0.61 confidence,
because it was being asked about a value the regex layer had already got
wrong.

So:

- A line boundary beside a table cell is a **hard** break. A boundary beside a
  date inside a running sentence is still a soft wrap — "will be held on
  15.06.2026 at / 10:00 AM" is a sentence that happens to wrap after a date.
- A clause whose label is followed by bare date cells is a **row label**. A
  value is read from the rightmost cell (in an `Earlier | Extended` table the
  extended date is the current one) and marked **ambiguous**.
- Three or more full dates in one clause is **ambiguous** regardless.
- An **ambiguous candidate is reported and never written**, however confident
  the model is about it. Verification confirms the document says a value; it
  cannot rescue a value the extractor attributed to the wrong field.

Every one of these has a regression test in `tests/test_regressions.py`,
against verbatim excerpts of the real notices.

## The schema it writes

`docs/exam-template.md` is the contract: its `## Template` TOML block is the
full record, with the allowed words for each field in its comments.
`template.py` derives the checks from that block, so there is no second copy
of the schema to drift. `record.py` reads, updates and writes records;
`convert/emit.py` lays them out.

Enforced, not hoped for (`python -m examhub_pipeline lint`, and the tests):

1. **Every template key is present.** A fact the notice does not give takes a
   sentinel: `not_announced` before a notice exists, `unknown` when it is
   silent, `none` when it says there is none.
2. **Words come from the template's lists.** `purpose = 'Recruitment'` is an
   error; `'recruitment'` is not.
3. **A date window has both ends or neither.** An end nobody has stated is
   `'unknown'`. A hedged date is stored `tentative`, never `confirmed`.
4. **A day is never invented from a month**, and an estimate is never stored
   as fact.
5. **Every written value cites its source** in `[[provenance.evidence]]`, and
   the source document is listed in `[[links.documents]]`.
6. **Dates are bare TOML dates**, never quoted.

The validator's fields map onto the template in `record.DATE_FIELDS`. Free-text
fields it reads (fee, marking, duration, venue, eligibility) have no single
structured place, so they are logged and not written.

## Where output goes

**Into `site/content/exams/`, on a branch.** `propose` creates a branch in a
**git worktree** so your checkout is never switched under you, refuses `main`
and `master` as a branch name, and never pushes. The `gh pr create` command is
*printed*.

```bash
python -m examhub_pipeline run --source ugcnet
python -m examhub_pipeline propose              # branch worktree, uncommitted
python -m examhub_pipeline propose --commit     # committed on the branch
(cd site && hugo server)                        # preview the site
```

Everything else lands in `work/`: `docs/` holds extracted text and chunks,
`reviews/` holds bundles, `cache/` holds HTTP bodies, `state/` holds the run
ledger.

---

## Layout

```
src/examhub_pipeline/
  config.py      settings, paths, every tunable and the measurement behind it
  record.py      site records: load, write, update, diff; a new exam's skeleton
  template.py    the checks, derived from docs/exam-template.md
  sources.py     seed registry of 28 bodies; deterministic link classification
  http.py        cached, polite fetcher: robots, throttle, backoff, disk cache
  fetch.py       orchestrator: discover -> fetch -> extract -> work directory
  extract.py     HTML/PDF/scan -> text, with chunking and the OCR flag
  candidates.py  the "find" layer: regex and heuristics. No model.
  validate.py    the "verify" layer: Laya. No extraction.
  review.py      field-level diff, review bundle, the one-screen summary
  propose.py     git branch, never main, never pushed
  cli.py         argparse
data/
  devset/        26 hand-labelled examples, from documents this tool fetched
  record-map.toml  which notices are the same exam, and which one may write
tests/           486 tests; the deterministic layers, the CLI, and the
                 regressions from real notices
site/            the Hugo site; records in site/content/exams/
.github/workflows/
  recheck.yml    nightly; opens a pull request only when something changed
  pr.yml         tests + schema check on a pull request; read-only
  site.yml       build the site and publish it to GitHub Pages
  watch.yml      every 10 minutes: poll in-season feeds, list new notices
  crawl.yml      daily: crawl every feed, then discover new sources
```

---

## What is tested, and what is not

Stated plainly, because "tests pass" is worth very little without it.

| area | status |
|---|---|
| `candidates.py` — date parsing, granularity, hedging, clause scoping, soft-wrap joining, pay, fee, vacancy, adjudication | **unit tested** |
| `record.py` / `template.py` — round-trip of all 313 site records, template checks, updates | **unit tested**; every site record round-trips byte-for-byte |
| `sources.py` — link classification, tier inference, filename date hints | **unit tested** |
| `extract.py` — HTML text/table/link extraction, PDF text layer, chunking, OCR trigger | **unit tested** |
| `http.py` — cache round-trip, robots 404/403/5xx handling, throttle arithmetic, URL canonicalisation | **unit tested** |
| `review.py` — field diff kinds, no-op detection, summary rendering | **unit tested** |
| `propose.py` — branch-name sanitisation, protected-branch refusal, a commit into `site/` of a throwaway repo | **unit tested** |
| `validate.py` — question construction, verdict logic, thresholds, the ambiguity rule | **unit tested with a stub model** |
| `cli.py` — every subcommand offline, including the exit-code contract | **unit tested** |
| regressions from real notices (date tables, provisional answer keys, OCR) | **unit tested against verbatim excerpts** |
| `validate.py` — accuracy against real documents | **measured**, see above: 7/7 value, existence does not work |
| OCR quality | **not measured** |
| prose-field verification accuracy | **not measured** |
| `run` + `propose --commit` end to end | **run** 2026-09-30 on UGC NET in a throwaway clone: 6 notices fetched (3 by OCR), 12 model calls, 2 values verified, a branch committed, the patch applied with `git apply --directory=site`, and the new record passed `lint`. One verified value was wrong (the notice's issue date taken as the exam date), which is what the human review is for. |
| `propose`'s on-disk-skip path (a file that changed under us) | **not exercised** against a real git repository; the unit tests cover the matching logic only |
| the template check against the site | **run**: `lint` passes all 313 records. |
| round-trip of every site record through the writer | **run**: all 313 records come back byte-for-byte. |
