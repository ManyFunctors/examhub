---
name: examhub-data-check
description: Check an ExamHub schema idea against real data before offering it. Counts how often a case occurs in official notice texts, ExamHub's exam records and 51,516 harvested notice titles, with examples. Use it whenever you are about to propose, change or defend a field, value list, sentinel or block shape in examhub-pipeline (docs/exam-template.md, eligibility rules, vocabularies), and whenever the user asks "robust?", "enough?", "how common is", "check the data", "research this", or asks how some kind of exam (JEE, TETs, PSU GATE hiring) is handled. Run it even if you think you already know the answer.
---

# ExamHub data check

The user's standing rule: every proposal gets checked against the data
first, and the answer shows what the data says. A shape designed from memory
misses real cases (JEE Advanced's "top 2,50,000" rank cutoff was missed that
way) and adds fields for cases that never occur. Counts plus real examples
let the user decide in one glance.

## The data

| Source | What it is | Where | Watch out for |
|---|---|---|---|
| `notices` | Text of official notification PDFs; 101 usable of 185 | `work/corpus/text.json` (keys map to URLs in `urls.txt`) | Mostly recruitment. Entrance exams and TETs are thin, and Hindi scans extract as nothing |
| `examhub` | ExamHub's exam records (TOML front matter) | `site/content/exams/*.md` (read only here) | Written by earlier runs, so they summarise and sometimes guess. Good for coverage, weaker as proof |
| `titles` | Titles of every harvested notice | `data/harvest/notices.jsonl` | Short and noisy. Good for how often events happen (extended, postponed, cancelled) |

`work/` is git-ignored. If the corpus is missing, say so and ask before
rebuilding it. Don't quietly fall back to ExamHub alone.

## Running it

Use the bundled script rather than writing a new scan each time. If it lacks
something you need, extend it.

```bash
S=.claude/skills/examhub-data-check/scripts/scan.py

# named patterns, counted per document, with examples
python3 $S grep -p 'rank cutoff=top \d[\d,]*' -p 'valid score=valid GATE' -s notices,examhub
python3 $S grep -p 'backlog=backlog' -s examhub --fields eligibility,summary --list
python3 $S grep -p 'extended=extension|extend' -s titles

# what an ExamHub field already holds
python3 $S census .                # top-level keys across records
python3 $S census fee              # keys inside fee rows
python3 $S census fee --key note   # values of one key: free text hiding structure
```

## Method

1. **Write the idea as named patterns.** Include the case you're designing
   for, and also the cases that would break it: other units (months as well
   as years), other shapes (a single number or a range, per post or per
   group), and "none" (the notice says there is no such thing).
2. **Run across every source that could hold the case.** Notices are the
   evidence. Use ExamHub for exam types the notice sample lacks. Use titles
   for events.
3. **Read the examples before believing a count.** Regex noise is common:
   "either or both papers" also matches "debarred either permanently". Tighten
   the pattern and run it again. Report only counts whose examples you have
   looked at, and say when a number is noisy.
4. **Look up named exams directly when the sample is thin.** For JEE, CTET,
   GATE, NET or NDA, search ExamHub with `--fields eligibility,summary` and
   `--list`, and read the matching records.
5. **Census existing fields.** Free-text notes and sentence fields show what
   structure is missing (for example, 208 fee rows say "Exempt").

## Reporting

The user reads short messages, one item at a time. Report in this shape:

- one line on what you checked;
- a small table (case, count per source, one short example), noisy rows marked;
- what the proposal covers and what it misses, including counts of zero;
- the proposal, if you have one, then a single question.

Keep the scan output and long evidence out of the chat; put anything worth
keeping in the relevant doc (`docs/exam-template.md` decisions carry their
counts).
