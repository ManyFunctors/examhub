# Day to day

Everything here runs on its own. This is what's actually worth a look.

## Weekly

- **Open pull requests** on [github.com/ManyFunctors/examhub/pulls](https://github.com/ManyFunctors/examhub/pulls).
  Each one is the nightly recheck's changes to exam pages (links fixed,
  duplicates merged, titles filled). Skim the diff, merge if it looks right.
- **Failed workflow runs**: [Actions tab](https://github.com/ManyFunctors/examhub/actions).
  A red run isn't urgent by itself (a government site timing out is normal),
  but a run failing the *same way* every day for a week means something broke.
- **`docs/todo.md`**: what's still open.

## Monthly

- **`git log data/harvest/unmatched.jsonl` on the `harvest` branch** — or just
  `python -m examhub_pipeline catalogue coverage -v` locally — lists exams
  the crawl never confirmed and notices it couldn't match to any exam.
  Worth a skim in case a body changed its site.
- **`docs/discovery/*-proposals.jsonl`** (via `catalogue discover`): new exam
  series, feeds or sources the crawler noticed but hasn't added — review and
  adopt or ignore.

## Only if something looks wrong on the site

- Open the exam's page, find the wrong value, then run (locally, never by
  hand-editing the record):
  ```
  uv run python -m examhub_pipeline links      # link placement
  uv run python -m examhub_pipeline dedupe     # duplicate pages
  uv run python -m examhub_pipeline aliases    # wrong alternate names
  ```
  without `--apply` first, to see what it would change.
- If the step doesn't fix it, the bug is in the step's rule, not the record —
  see `docs/exam-template.md` and the pipeline source. Never edit a file in
  `site/content/exams/` directly.

## You never need to

- Start a crawl, the recheck, or a site build by hand — they're all scheduled.
- Touch `data/harvest/` — it's machine-written, on its own branch.
- Renew anything. No paid APIs, no accounts beyond GitHub.
