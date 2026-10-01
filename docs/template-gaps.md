# Template gaps found in the test exams

Moved from the retired `work/dummy` builder (the three test exams it wrote are in `site/content/exams/`). Not yet checked against the current template: some may be closed.

Found while writing three exams from real notices into the template:
NICL AO 2023-24, AP SLPRB SCT PC (Communications) 2026 and IBPS PO XVI.
Values I used as stand-ins are in `backticks`.

1. **Closed, kept as is (1 Oct):** full blocks are cheap and clearer than inheritance.
   **Eligibility blocks repeat everything.** NICL's file is 2,869 lines. About
   2,000 of them are 8 eligibility blocks that differ only in education.
2. **Closed in decision 53 (1 Oct):** `[[cutoffs]]` rows.
   **Cut-off marks published after the exam.** NICL publishes cut-offs per
   post, category and section (Jan 2025 notice). There is no field for them.
3. **Minimum marks by category.** AP's written exam needs 40% (OC, EWS), 35% (BC)
   and 30% (SC, ST); IBPS's interview needs 40% (35% for reserved). But
   `stage_min_marks` is a single value, with no unit. Stand-in: `'by_category'`.
4. **Horizontal quotas given as percentages.** AP: women 33⅓% in each category;
   Home Guards 10%, CPP 3%, ESM 2%, NCC 1%. `by_category` holds counts only.
5. **A mandatory stage that is not scored.** IBPS Personality Test: you must
   sit it, but it neither qualifies nor ranks. Stand-in: `stage_purpose = 'unknown'`.
6. **Descriptive marking.** `marking_correct` has no value for "marked by
   examiners". Stand-in: `'as_evaluated'`.
7. **Finished cycles.** `cycle_status` has no `'completed'`, and `link_apply` has
   no value for "applications closed". Stand-ins: `'active'`, `'none'`.
8. **Month-only dates.** IBPS gives "August 2026" for several events. Stand-in:
   1–31 Aug with `'tentative'`, but the page can't tell that from a real range.
9. **Partly cumulative relaxation.** IBPS: SC, ST or OBC relaxation adds to only
   one other. `age_relaxation_cumulative` is yes or no.
10. **Correction fee.** IBPS charges Rs 200 to use the edit window. Stand-in:
    `fee_per = 'correction'`.
11. **Relaxation forms beyond the grammar.** AP: `'+service, max 5'` (state
    employees) and `'+3 + military_service'`.
