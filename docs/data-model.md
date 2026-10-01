# ExamHub catalogue data model (v1)

This is the contract for what the pipeline *knows about* — which exams exist,
who runs them, and where their notices appear — as distinct from what any one
notice *says*. `docs/data-model-notes.md` remains the contract for the
page a candidate reads; this model feeds it.

The design goal is a model that still fits in ten years with no schema change,
that a crawler can keep current without an LLM, and that a maintainer can keep
honest in minutes a month.

---

## 1. Two layers, split by how fast they change

| Layer | Entities | Changes | Who writes it | Where |
|---|---|---|---|---|
| **Catalogue** (identity) | Jurisdiction, Body, Exam, Feed | a few times a year | a human, from crawler proposals | `data/catalogue/*.toml`, in git |
| **Observations** (facts) | Notice, Cycle, Event | daily | the crawler, deterministically | `data/harvest/*.jsonl`, regenerated |

Everything that rots quickly — dates, admit cards, URLs of individual PDFs —
lives in the observation layer, where it is re-derived on every run and never
hand-edited. Everything in the catalogue is a fact about an *institution*,
which is why it can be curated: UPSC has run the Civil Services Examination
since 1979, and it does not need re-checking nightly.

ExamHub's `content/exams/<slug>.md` is a **projection** of one Cycle plus its
Events plus its Exam and Body (§7). Nothing in this model is shaped by Hugo.

---

## 2. Identifiers — the part that has to last

Every catalogue entity has an `id`. The rules are what make the model durable:

1. **An id is never renamed and never reused.** When a body renames itself
   (TSPSC → TGPSC, CBSE's CTET unit → Central Testing Board), the id stays and
   the old name goes into `known_as`. When an exam is discontinued (KVPY,
   AIPMT) it gets `status = "discontinued"` and, where one exists,
   `successor = "<id>"`. It is not deleted: notices about it keep arriving for
   years.
2. **An id never contains a year, an operator, or an external code.** The year
   belongs to a Cycle. The operator changes (UGC-NET moved from CBSE to NTA in
   2018; JEE Advanced rotates between IITs; CAT's convenor IIM rotates yearly).
   External codes change too — ISO 3166-2 has renumbered Indian states twice
   since 2014. External codes are *attributes* (`iso_3166_2`, `wikidata`), never
   keys.
3. **Shape:** lowercase ASCII, `[a-z0-9-]`, prefixed by the jurisdiction id.
   `in-upsc`, `ka-kpsc`, `kl-kpsc` (two different Karnataka and Kerala
   commissions that share an acronym — the prefix is not decoration),
   `in-ssc-cgl`, `mh-mht-cet`.
4. **A Cycle id is `<exam id>/<cycle label>`** — `in-ssc-cgl/2026`,
   `in-ugc-net/2026-dec`, `in-ibps-po/crp-xvi`. The label is the body's own
   cycle name, normalised to the same character set.
5. **A Notice id is the SHA-256 of its canonical URL**, and its *content* is
   identified by the SHA-256 of its bytes. Two URLs serving one PDF are one
   document; one URL whose bytes change is a new version of a notice, and both
   versions are kept.

---

## 3. Jurisdiction

The 36 states and union territories, plus `in` for the Union. Static.

| key | type | notes |
|---|---|---|
| `id` | id | `in`, `mh`, `tg`, `dh`… Our code, never ISO's |
| `name` | text | |
| `kind` | enum | `union` \| `state` \| `union_territory` |
| `iso_3166_2` | text | Current ISO code, as an attribute |
| `languages` | list | Official languages, for OCR language packs and title matching |

## 4. Body

An organisation that **conducts** an exam, **owns** an exam scheme, or
**converts a result into something** (a seat, a post). Those are three roles
and one organisation can play any of them; §6 says how exams point at them.

| key | type | req | notes |
|---|---|---|---|
| `id` | id | ✓ | `<jurisdiction>-<short>` |
| `name` | text | ✓ | Full official English name |
| `short_name` | text | ✓ | What ExamHub puts in `bodies` (the taxonomy term) |
| `known_as` | list | | Former names, other-language names, acronyms |
| `jurisdiction` | id | ✓ | |
| `kind` | enum | ✓ | See `vocab.toml` → `body_kind` |
| `parent` | body id | | RRB Chennai → the RRB system; a district court → its High Court |
| `website` | url | ✓ | Canonical home page, with the exact host that works (`www.` matters) |
| `hosts` | list | | Every host the body publishes on: notice CDN, application portal, results host. A link on any of these is the body's own |
| `wikidata` | text | | `Q…`, for cross-reference only |
| `status` | enum | ✓ | `active` \| `merged` \| `defunct` |
| `successor` | body id | | Required when `status` is not `active` |
| `notes` | text | | Traps a maintainer must know. Not rendered |

## 5. Feed — how a machine reads a body

A Feed is one page (or API endpoint) where a body lists its notices, together
with the **declarative recipe** for reading it. There is no per-body code: a
Feed names one of a small, fixed set of *adapters* and fills in its
parameters. Adding a body is a TOML edit; a site redesign is a selector edit.

| key | type | req | notes |
|---|---|---|---|
| `id` | id | ✓ | `<body id>/<name>`, e.g. `in-upsc/active-exams` |
| `body` | body id | ✓ | |
| `url` | url | ✓ | |
| `adapter` | enum | ✓ | `html_links` \| `html_table` \| `json_api` \| `rss` \| `pdf_document` |
| `render` | enum | | `http` (default) \| `browser` — headless Firefox, for SPA sites |
| `yields` | enum | ✓ | `notices` \| `exam_list` \| `calendar` \| `results` \| `admit_cards` \| `answer_keys` |
| `item_selector` | css | | Scope: the element that holds one notice (a `tr`, an `li`). Default: every `a[href]` |
| `link_selector` | css | | Within an item, the link. Default `a[href]` |
| `title_selector` | css | | Within an item. Default: the link text, else the item text |
| `date_selector` | css | | Within an item, the element holding the published date |
| `include` | regex | | Keep a link only if URL or title matches |
| `exclude` | regex | | Drop a link if URL or title matches (applied after `include`) |
| `items_path` | text | | `json_api`: dotted path to the list, e.g. `data` |
| `fields` | table | | `json_api`: `{title = "examName", url = "navigationUrl", date = "…"}` |
| `url_template` | text | | `json_api`: builds an absolute URL from a field, e.g. `https://ssc.gov.in{url}` |
| `cadence_days` | int | | How often it is worth re-reading. Default 1 |
| `keep_chrome` | bool | | Keep links inside menus, headers and footers (for sites whose notice list *is* a menu) |
| `tier` | `hot` \| `warm` \| `cold` | | Pin the polling tier. Absent: derived from recent activity |
| `identity` | `url` \| `url_title` | | `url_title` for update lists that reuse one URL per category and change only a dated title |
| `match_scope` | `body` \| `all` | | `all` for aggregators: match against the exams of whichever bodies the notice names |
| `notify` | `matched` \| `all` | | `all` pushes this feed's unmatched notices too (titles that name a CEN, not an exam) |
| `status` | enum | ✓ | `active` \| `broken` \| `blocked` \| `retired` |
| `notes` | text | | |

`status` is a *curated* fact ("we know this one needs a browser", "robots
disallows this"). The crawler's per-run health — HTTP status, final URL, link
count — is written to `data/harvest/feed-health.jsonl`, never into the
catalogue. A feed that yielded 40 links yesterday and 0 today is how a site
redesign is detected, and that comparison needs the history in the harvest,
not a single overwritten field.

## 6. Exam — a recurring series

The thing a candidate names: "SSC CGL", "NEET-UG", "Kerala PSC LDC",
"CTET". Not an edition of it.

| key | type | req | notes |
|---|---|---|---|
| `id` | id | ✓ | `<jurisdiction>-<common short name>`. No year, no operator |
| `name` | text | ✓ | Official name without the year |
| `short_name` | text | | |
| `known_as` | list | | Search terms and former names. Feeds matching (below) |
| `jurisdiction` | id | ✓ | The geography whose candidates/posts it serves |
| `purpose` | enum | ✓ | `recruitment` \| `admission` \| `eligibility` \| `certification` \| `school_board` \| `scholarship` \| `departmental` |
| `conducted_by` | body id | ✓ | Who runs it **now**. Changes are allowed and expected |
| `owned_by` | body id | | Who owns the scheme when that is different: UGC for UGC-NET, CSIR for CSIR-NET, ICAR for AIEEA |
| `allocated_by` | list of body ids | | Who converts the result: JoSAA for JEE Main, MCC for NEET-UG |
| `frequency` | enum | | `annual` \| `biannual` \| `multiple` \| `irregular` \| `continuous` |
| `qualification` | enum | | The minimum level a candidate needs: `none` \| `class_8` \| `class_10` \| `class_12` \| `diploma` \| `graduate` \| `postgraduate` \| `professional` |
| `streams` | list | | Subject tags from `vocab.toml` → `stream`: `engineering`, `medical`, `law`, `teaching`, `banking`, `police`… |
| `official_url` | url | | The exam's own page, when it has a stable one |
| `match` | table | | `{ any = [regex…], none = [regex…] }` — see below |
| `wikidata` | text | | |
| `status` | enum | ✓ | `active` \| `discontinued` \| `merged` |
| `successor` | exam id | | |
| `notes` | text | | |

`purpose` is the axis ExamHub cares about; its `exam_kind` and `categories`
are *derived* from it (§7) so they can never disagree with each other.

### Matching a notice to an exam, without a model

`match.any` is a list of case-insensitive regular expressions tested against a
notice's title and URL; `match.none` vetoes. If no `match` is given, the
matcher builds one from `name`, `short_name` and `known_as` as whole-word
phrases. Matching is scoped: a notice is only matched against exams whose
`conducted_by` (or `owned_by`) is the notice's body, so "CGL" on
`ssc.gov.in` cannot collide with a state commission's "CGL".

A notice that matches **no** exam of its body is not dropped. It goes into
`data/harvest/unmatched.jsonl`, grouped by body, and that file is the
maintainer's entire worklist: each line is either a new exam series to add to
the catalogue, or a pattern to widen. A notice that matches **two** exams is a
defect in the patterns and is reported as such.

## 7. Observations

Written only by the pipeline, one JSON object per line, under
`data/harvest/` on the `harvest` branch. Never hand-edited; if one is wrong,
the fix is in the catalogue or in an adapter, and the file is regenerated.

| file | contents |
|---|---|
| `notices.jsonl` | every Notice ever seen (below) |
| `changes/YYYY-MM.jsonl` | append-only log: `change` = `new` \| `gone` \| `back`, `at`, and the notice's id, title, url, exam, cycle, doc_type |
| `feed.atom` | the 300 newest live matched notices; byte-stable until one is added |
| `unmatched.jsonl`, `ambiguous.jsonl` | worklists for pattern maintenance |
| `feed-health.jsonl` | per feed: `ok`, `status`, `count`, `since`, `alert`, `etag` / `last_modified` / `notices_sha` for conditional polling, `auto_browser` when only Firefox could read it |
| `url-health.jsonl` | per catalogue URL: `state`, `since` |
| `discovered-hosts.jsonl`, `discovered-feeds.jsonl`, `discovered-pages.jsonl` | candidate sources not yet in the catalogue |
| `ct-cursors.json` | Cert Spotter `after` cursor per body domain |
| `exam-proposals.jsonl`, `match-proposals.jsonl`, `source-proposals.jsonl` | discovery worklists: new exam series, missing match patterns, new feeds (see [pipeline.md](pipeline.md#new-exam-discovery)) |
| `documents/index.jsonl` | one line per notice whose PDF was tried: `status` (`ok`, `needs_ocr`, `not_pdf`, `too_large`, `failed`), `kind`, `summary`, `sha256`, `attempts` |
| `documents/<id[:2]>/<id>.json`, `.md` | the structured Document record (below), and the same rendered for people |
| `exams/<exam>.json` | the exam's Profile: per field the best value from all its documents, with `source`, `alternatives`, `carried_from` |
| `exams/gaps.jsonl` | per active exam: `cycle`, `documents`, `gaps` (expected fields still missing); drives the next fetch |

A feed's polling **tier** is not stored; it is derived from `notices.jsonl`
on every run (hot: activity in 21 days; warm: 120 days; cold otherwise),
unless the catalogue pins `tier`. Feeds may also set `match_scope = "all"`
for aggregators that publish on behalf of every body.

### Notice

| key | notes |
|---|---|
| `id` | sha256 of canonical URL |
| `url`, `title`, `published` | `published` only if the feed states one; never inferred from a filename |
| `body`, `feed` | ids |
| `exam` | matched exam id, or absent |
| `cycle` | `<exam>/<label>` when a year/session is stated in the title |
| `doc_type` | `notification` \| `corrigendum` \| `admit_card` \| `answer_key` \| `result` \| `calendar` \| `schedule` \| `press_release` \| `other` |
| `first_seen`, `gone_since` | RFC 3339 instants. `gone_since` is set when a feed that answered no longer lists the notice, and cleared if it returns. There is deliberately no `last_seen`: a per-run timestamp would change every line on every run, and a scheduled job whose diff is never empty cannot tell "nothing happened" from "something did" |
| `content_sha256` | when fetched |

### Event

One dated milestone of one Cycle, extracted from one Notice by
`candidates.py`. Events carry their evidence; ExamHub's `_status` sibling rule
comes from `status` here.

| key | notes |
|---|---|
| `cycle`, `kind` | `kind` from `vocab.toml` → `event_kind`: `registration_open`, `registration_close`, `fee_deadline`, `correction_window`, `admit_card`, `exam`, `answer_key`, `result`, `interview`, `document_verification`, `counselling` |
| `stage` | `primary` \| `secondary` \| `physical` \| `skill` \| `interview` \| `medical` \| `document_verification` (ExamHub's slots) |
| `start`, `end` | ISO dates. `end` only for a window |
| `granularity` | `day` \| `month` \| `quarter`. Only `day` may be projected into a date field |
| `status` | `confirmed` \| `provisional` |
| `notice`, `quote` | the notice id and the verbatim sentence the value came from |

When several notices give an event, the one from the highest `doc_type`
precedence wins (corrigendum > press_release > notification > calendar), then
the most recent `first_seen`. That rule is deterministic, and conflicts go to
review rather than being resolved silently.

### Document

What a notice's PDF says, read by `documents.py` with no model. Every value
carries the `page` it came from, and a key that could not be read is
**absent**, never guessed or defaulted. `schema` is bumped when a reader
changes enough that old records should be redone; the daily crawl then
re-fetches them.

| key | notes |
|---|---|
| `notice` | id, url, title, body, exam, feed, published, doc_type |
| `document` | `sha256`, `pages`, `chars`, `ocr` (true: read by OCR, check numbers against the PDF), `indic_share` |
| `kind` | `advertisement` \| `brochure` \| `corrigendum` \| `schedule` \| `result` \| `admit_card` \| `answer_key` \| `syllabus` \| `notice` |
| `advertisement_no` | "Advt. No. 03/2026", as printed |
| `summary` | the at-a-glance values: `vacancies`, `apply {from, until}`, `exam_date`, `fee {min, max}`, `age {min, max}`, `pay`, `education` (levels named), `selection` |
| `dates` | per key (`registration_open`, `registration_deadline`, `payment_deadline`, `exam_date`, `admit_card_from`, `result_date`, `correction_window`, `age_as_on`, ...): `date`, optional `until`, `provisional`, `evidence`, `page`, `from` = `table` \| `text` |
| `schedule` | every dated row of the notice's schedule tables, with its `key` when one applies |
| `vacancies` | `total`, `by_category` (`UR`, `EWS`, `OBC`, `SC`, `ST`, then horizontal `PwBD`, `ESM`, `Women`, ...), `rows` (one per post / discipline / state: `label`, `total`, `by_category`, `page`) |
| `fees` | `[{categories, except?, amount, for?, raw, page}]`. `amount` is rupees, `0` is exempt. `except: true` means everyone *but* the categories |
| `age` | `limits [{min, max, evidence, page}]`, `as_on`, `relaxations [{categories, years, raw, page}]` |
| `pay` | `[{levels?, grade?, low?, high?, initial?, text, evidence, page}]`: Pay Matrix levels, a scale range, a PSU grade |
| `eligibility` | `education_levels` (Doctorate … Class 10, the levels named), `clauses [{text, page}]` verbatim |
| `selection` | stages in the order the notice names them |
| `exam_pattern` | `[{paper, questions, marks, duration, page}]` |
| `exam` | `mode`, `negative_marking`, `duration` |
| `links` | `apply` (application portals), `other` |
| `warnings` | e.g. OCR, pages not read |

Categories are normalised (`General`/`Unreserved`/`Gen` → `UR`, `OBC-NCL`/`SEBC`/`BC` → `OBC`,
`PH`/`PwD`/`Divyang` → `PwBD`, `Ex-servicemen`/`EXS` → `ESM`); the words the notice used stay in
`raw` and `label`. **Superseded:** merging `OBC-NCL`, `SEBC` and `BC` into `OBC` is wrong, since
they are different classes. Only spellings of one class are mapped, to the values in
`docs/vocabulary.md` §1 (`Unreserved`, not `UR`).

#### Eligibility (schema 2, proposed)

`eligibility` today is a bag of matching sentences, headings included, with the education
levels guessed from anywhere in the PDF. It answers "what does the notice say near the word
qualification", not "can I apply". Schema 2 answers the second question, one heading at a
time, in the order a candidate checks them:

| key | shape | example |
|---|---|---|
| `applies_to` | `"all"` or post labels | a block per post when posts differ; otherwise one block |
| `nationality` | `{rule, also?}` | `Indian`; `also`: Nepal, Bhutan, Tibetan refugee (pre-1962), PIO |
| `domicile` | `{required, state?, other_state}` | `other_state`: `not_eligible` \| `as_unreserved` \| `eligible` |
| `age` | `{as_on, base {min, max}, by_class [{class, max}], stacking?}` | limits resolved per class from the relaxation table: `SC max 37` rather than "+5" |
| `education` | `{any_of [[requirement…]], final_year_may_apply?, min_percent?}` | `any_of` = alternatives, each an AND-list: `[[D.Pharm], [B.Pharm], [Pharm.D]]` |
| `registration` | `[{body, must_be_live?}]` | Tamil Nadu Pharmacy Council, Bar Council, Nursing Council |
| `experience` | `[{years, in, preferred?}]` | "3 years in a Government hospital" |
| `language` | `[{language, level, test?}]` | Tamil, SSLC standard, via the Tamil Eligibility Test |
| `physical` | `[{measure, value, applies_to}]` | height 168 cm (men, UR), chest 81+5 cm; per class and gender |
| `medical` | `[text]` | vision standards, colour blindness |
| `attempts` | `[{class, max}]` | `Unreserved 6`, `SC unlimited` |
| `other` | `[text]` | anything above did not claim, verbatim, headings removed |

Every leaf keeps `page` and `evidence` (the sentence), as every other value does. Two rules
make it readable rather than just structured:

* **Resolve, then show.** A relaxation table says "+5 for SC"; the candidate wants "SC: up to
  37". The record stores both (`by_class[].max` and the source `relaxations`), and renders the
  resolved one.
* **Absent is not "none".** A heading with nothing found is left out, and the rendered card
  says *not found in the notice* only for headings the exam's purpose expects (the same
  `EXPECTED` list that drives gaps), so a missing age limit on a recruitment notice is visible
  and a missing one on a board exam is not noise.

Classes come from the reservation vocabulary, credentials from the terms vocabulary; a phrase
that maps to neither stays in its heading as text, and is added to the unmapped worklist.

Rendered (`documents file <id>`, and in `exams/<id>.json` via the profile). Built by hand
from the facts the current record for TN MRB Advt. 04/MRB/2025 already holds, to show the
shape; the age limits for other classes are on a page the current reader does not
recognise, so the card says so:

```text
Who can apply: Pharmacist, TN MRB Advt. 04/MRB/2025
  Age           not found in the notice
                Ex-servicemen: below 55 (SC, SC(A), ST, MBC/DNC …)  p.20
  Education     one of: D.Pharm · B.Pharm · Pharm.D               p.22
  Registration  Tamil Nadu Pharmacy Council, kept renewed         p.4
  Language      Tamil: pass the Tamil Eligibility Test
                (SSLC standard, 50 marks)                         p.5
  Other         PSTM: studied in Tamil medium                     p.19
                Served in Govt. institutions in the COVID period  p.8
```

## 8. Projection to an ExamHub record

| ExamHub | from |
|---|---|
| `title` | Exam `name` + cycle label |
| `known_as` | Exam `known_as` |
| `bodies` | `[conducted_by.short_name]` |
| `exam_kind` | `purpose ∈ {recruitment, departmental}` → `job`; everything else → `admission` |
| `categories` | `job` → `Government`; otherwise `Academic` |
| `official_url` | Exam `official_url`, else Body `website` |
| `outcomes[].authority` | Exam `allocated_by` |
| date keys + `_status` | Events of the cycle with `granularity = day` |
| `[provenance]` | the winning Notice |

## 9. Versioning

`data/catalogue/vocab.toml` carries `schema_version`. The rules:

- **Adding** an optional key, an enum value or an adapter parameter is a minor
  change and needs no migration. Readers must ignore keys they do not know.
- **Renaming or removing** a key, or changing the meaning of a value, is a
  major change and never happens in place: add the new key, dual-write, then
  retire the old one in a later major version.
- Enum values are never repurposed. A value that turns out to be wrong is
  deprecated in `vocab.toml` and stays readable.

`schema/catalogue.schema.json` is the machine-checkable form of §§3–6, and
`python -m examhub_pipeline catalogue lint` enforces it plus the rules a JSON
Schema cannot express (referential integrity, id prefixes, unique ids,
`successor` required when not active).
