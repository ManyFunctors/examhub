# Discovery notes

How we find exams, written as each persona would search for them rather than
from a list handed to us. Read these before researching — several record that
the obvious target is already covered under a different prefix, and that the
search provider starts returning HTTP 429 partway through a long run.

Each note records the **search queries that worked**, the official portal and
notice board for each body, and what could not be reached. The exam records
themselves live in `content/exams/`; the notes are the map.

| Note | Persona / angle | Slug prefix |
|---|---|---|
| [d1](d1-commerce-arts-grads.md) | BCom / BA / BSc fresh graduate hunting government exams | `d1-` |
| [d2](d2-engineering-psu.md) | BTech engineer, core PSU and public-sector technical recruitment | `d2-` |
| [d3](d3-medical-nursing-allied.md) | MBBS, nursing and allied health; qualification → recruitment map | `d3-` |
| [d4](d4-12th-pass-early-career.md) | 12th pass and early career; state-by-state hiring map | `d4-` |
| [d5](d5-law-mba-ca-cs.md) | Law, MBA, CA, CS; qualification → what-it-opens map | `d5-` |
| [d6](d6-teaching-research.md) | Teaching and research; state × test grid for TET and SET | `d6-` |
| [d7](d7-niche-local.md) | District courts, municipalities, panchayats, anganwadi | `d7-` |

## Where the general maps live

- [`link-inventory.md`](../link-inventory.md) — official URLs per conducting
  body, plus the traps: which bodies apply on a different domain from their
  portal, which are JS-only, which are image-only scans.
- [`../data-model-notes.md`](../data-model-notes.md) — the field schema.
- `tools/check-links.mjs` — link checker, run against the inventory and the
  records.

## What these notes are good for

Each was written by working around the same three failures, so the pattern is
worth knowing before starting a new pass:

1. **`websearch` returns HTTP 429** partway through a long run, and does not
   recover. Every note that hit this says so. When it happens, stop searching
   and write out what is already verified rather than retrying.
2. **Most Indian government portals render nothing to a fetcher.** The notice
   PDF is usually still reachable even when the HTML index is JavaScript-only.
   Go straight to the PDF.
3. **Aggregators contradict notices**, and they are often the only reachable
   copy. Use them to *find* an exam and its official link; never to source a
   number or a date.

## Duplicates are a real hazard

A full library can already cover the obvious target under a different prefix.
`d1` found the whole live September 2026 cycle already written. `d6` found six
of its own records duplicated existing ones. Before writing anything, dump the
current slugs and the titles, and check.
