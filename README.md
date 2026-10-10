# ExamHub

**Every Indian government exam, from the official notice, kept up to date automatically.**

ExamHub tracks recruitment, admission and eligibility exams: central and state, academic and government. It reads them from the bodies' own websites and turns each notice into one clear page: dates, vacancies by category, fees, age limits, eligibility, pay and links.

**Live site:** <https://manyfunctors.github.io/examhub/>

<!-- stats:start -->
| | |
|---|---|
| Exam pages | 307 |
| Exams in the catalogue | 1,017 |
| Conducting bodies | 462 |
| Feeds crawled daily | 467 |
| Notices seen so far | 56,000+ |
<!-- stats:end -->
<!-- Kept current by the nightly recheck workflow (readme_stats.py); don't hand-edit the numbers above. -->

---

## What makes it different

- **Official sources only.** Every value comes from a notice published by the body that runs the exam, and every page links back to it.
- **Nothing is guessed.** A fact the notice doesn't give is marked as not announced or unknown, never filled in. A day is never invented from a month, and an estimate is never stored as fact.
- **Every value cites its source.** Each fact keeps the document and page it came from, and documents are saved to the Wayback Machine in case the body takes them down.
- **Fully automatic.** GitHub Actions crawls, checks and fixes the records every day. Changes to exam pages arrive as pull requests that a person reviews.
- **Free to run.** Only free tools and services: no paid APIs and no accounts beyond GitHub.

---

## How it works

```
  official websites
         │
         ▼
  crawl ──────▶ match ──────▶ read ──────▶ check ──────▶ fix ──────▶ site
  467 feeds    notice to     notification  every link   links, names,  Hugo on
  (scrapy,     exam and      PDFs, OCR     on the       duplicates,    GitHub
  Firefox)     cycle         for scans     records      Wayback        Pages
```

1. **Crawl.** Scrapy reads each body's notice board, with headless Firefox for the sites that draw their pages with script. Discovery looks for new sources through certificate logs, RSS feeds and homepage links.
2. **Match.** Each notice is assigned to an exam and cycle by rules in the catalogue (`data/catalogue/`). A tie is reported, never guessed.
3. **Read.** Notification PDFs are turned into structured data: vacancies by category, fees, age, pay, eligibility and dates, each with its page number. Scanned PDFs go through OCR.
4. **Check.** Every link on every exam page is fetched to see what it really is: a document, an application portal, a page, or broken.
5. **Fix.** Nightly steps put each link in its right place, merge duplicate pages without losing a fact, drop wrong alternative names, fill short titles and link Wayback copies.
6. **Publish.** Hugo builds the site, and GitHub Pages serves it.

The design rule throughout: **deterministic code extracts; a model may only verify, never extract.** See [docs/how-it-works.md](docs/how-it-works.md).

---

## The workflows

All run on GitHub Actions, unattended.

| Workflow | When | What it does |
|---|---|---|
| `watch.yml` | every 10 minutes | polls the feeds in season, lists new notices |
| `crawl.yml` | daily, 02:43 IST | crawls every feed, reads new PDFs, checks every link, archives documents, discovers new sources |
| `recheck.yml` | nightly, 02:17 IST | re-checks sources with an exam date due soon first, applies what it learnt, opens a pull request if anything changed |
| `recheck-hourly.yml` | every hour | re-checks only a source with an exam date due within a day; a no-op almost every hour |
| `site.yml` | on a push to `site/`, and daily at 00:01 IST | builds the site and publishes it |
| `pr.yml` | on every pull request | tests, lint, and a schema check of every exam page |

Observations (notices, link checks, archive records) live on the `harvest` branch, so `main` only changes through reviewed pull requests.

---

## Run it locally

You need [Nix](https://nixos.org) (for the dev shell) or Python 3.12 with [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ManyFunctors/examhub
cd examhub
nix develop                                   # uv, Hugo, geckodriver, tesseract, poppler
uv sync --extra crawl --extra ocr --extra dev
```

Without Nix, install `geckodriver`, `tesseract` and `hugo` from your package manager.

**Preview the site**

```bash
cd site && hugo server                        # http://localhost:1313/examhub/
```

**Common commands**

```bash
uv run pytest -m "not model"                  # the test suite, offline
uv run scrapy crawl feeds                     # crawl every feed (-a jurisdiction=kl for one state)
uv run scrapy crawl links                     # check every link on the exam pages
uv run python -m examhub_pipeline links       # what the links step would change (add --apply to write)
uv run python -m examhub_pipeline dedupe      # duplicate pages it would merge
uv run python -m examhub_pipeline lint        # does every exam page match the template?
uv run python -m examhub_pipeline catalogue lint
```

Every step that edits exam pages is a dry run unless given `--apply`.

---

## Repository layout

```
site/                 the Hugo site; one exam per file in site/content/exams/
data/catalogue/       the curated catalogue: bodies, feeds and exams per state
src/examhub_pipeline/ the pipeline: crawler, extraction, fill steps, CLI
tests/                the test suite, including regressions from real notices
docs/                 the template, vocabulary, design notes and to-do list
.github/workflows/    the workflows above
```

---

## Documentation

| Read this | For |
|---|---|
| [docs/exam-template.md](docs/exam-template.md) | the exam page template: every field and why |
| [docs/vocabulary.md](docs/vocabulary.md) | the allowed words for each field |
| [docs/data-model.md](docs/data-model.md) | the catalogue: ids, bodies, feeds, exams |
| [docs/pipeline.md](docs/pipeline.md) | the crawl design and its measured numbers |
| [docs/how-it-works.md](docs/how-it-works.md) | in depth: the validator, politeness, extraction rules, what is tested |
| [docs/todo.md](docs/todo.md) | what's being worked on |
| [docs/day-to-day.md](docs/day-to-day.md) | the checks actually worth doing by hand, and how often |

---

## Politeness

The crawler identifies itself, keeps a delay between requests to each host, backs off on errors, and follows robots.txt. The one exception is the link check, which fetches each link on our pages once, exactly as a reader clicking it would. `EXAMHUB_CONTACT` can optionally hold a contact address for site operators; it is not needed.
