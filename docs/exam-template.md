# ExamHub exam page: canonical template (draft)

Being agreed field by field. When done, this moves to ExamHub as
`archetypes/exams.md` plus a machine-readable schema; the pipeline reads it
from there.

## Decisions

1. **One file per cycle.** A new file each cycle (`ibps-clerk-2026.md`).
   Once a cycle has run, its page comes off the site, as ExamHub's About page
   says ("Nothing is archived"). Past cycles are kept only in the pipeline's
   data (the harvest branch), never on the site; they feed history and the
   paid data plans.
2. **`exam_id` and `cycle` identify the file.** `exam_id` is the catalogue id,
   `cycle` the cycle label. The pipeline updates the page with that pair, and
   creates a new file when no page has it. Not shown to readers.
3. **Two names.** `title` is the short name people search for, with the
   cycle ("IBPS Clerk 2026"): lists, search, the browser tab. `title_official`
   is the notice's own name, without the cycle ("Customer Service Associate
   (Clerk)"), shown under the title on the page.
4. **Names, all of them.** Internal: `exam_id` + `cycle` (pipeline only).
   URL: `slug = 'ibps-clerk-2026'`, readable, no jurisdiction prefix. The
   filename stays the internal, always-unique name (`in-ibps-clerk-2026.md`).
   When two slugs clash, the pipeline adds the state name to one
   (`bihar-police-constable-2026`).
   Series: `title_series = 'IBPS Clerk'`, no year, links every cycle of one exam.
   Aliases: `title_aliases`, for search. A regional-language name comes later.
5. **Dates are grouped.** Each window is one line under `[dates]`, its start,
   end and status together:
   `application = { from = 2026-05-21, to = 2026-06-22, status = 'confirmed' }`.
   Replaces the flat `registration_open` / `registration_open_status` pairs.
   (Now written as one block per date, decision 25, with change fields,
   decision 38.)
6. **Every date line has one shape: `{ from, to, status }`.** One day is
   `from` = `to` (both written; the page shows one date). A vague date
   ("December 2026", "second week of March") is its whole range. Results too.
   Lines, in the order a candidate meets them: `application`, `fee_payment`
   (only when it closes after the application), `late_fee`, `correction`,
   `admit_card`, `exam`, `answer_key`, `result`. A line the notice does not
   give is left out.
   (Lines are never left out now: decision 14.)
7. **Date status is `confirmed` or `tentative`.** `tentative` replaces
   ExamHub's `provisional`: notices say "tentative schedule", and use
   "provisional" for other things (provisional admission, answer key, result),
   so `provisional` on a date would be ambiguous. Rename the 10 records and the
   theme's checks when the template lands.
8. **Stages, any number.** Applying (`application`, `fee_payment`,
   `late_fee`, `correction`) stays at the top of `[dates]`. Each stage is a
   `[[dates.stages]]` entry with its own `admit_card`, `exam`, `answer_key`,
   `result`, listed even before it has dates. A stage is a step you must pass
   to reach the next one; papers (parts of one sitting, or alternatives such as
   CTET Paper I/II) are not stages and belong to the exam-details block.
   Readers see only the official wording (`stage_name = 'Tier I'`). Internally a
   stage is identified by what it is, never by a borrowed word such as
   "prelims": `stage_number = 1` (its position), `stage_format` (written,
   physical, skill, interview, documents, medical) and `stage_purpose`
   (screening: only gets you through; merit: marks count; qualifying: pass or
   fail). Official wordings map onto
   these through a vocabulary file, built like `reservation.toml` (general
   wordings, plus body-scoped `[[alias]]` rules; unknown wordings go to a
   worklist).
   (Papers and their details are `stage_parts`: decisions 10 and 45.)
9. **`stage_posts`** on a stage lists the posts it applies to (SSC CHSL's
   Skill Test: `['Data Entry Operator']`). Missing means every post. The page
   shows "Data Entry Operator only" beside the stage.
10. **Parts inside a stage.** Things held together at one step (police PET
    and PST; UPSC Prelims' GS Paper I and CSAT Paper II) are one stage with
    `stage_parts = [{ part_name = ... }, ...]`, not two stages. `stage_number` stays unique,
    so "stage 2 admit card" means one thing. One rule: a stage is a step you
    pass; parts are what happens inside it. A part may carry its own dates when
    the notice gives them. Papers use the same `stage_parts` (details:
    decision 45).
11. **Maybe-stages.** `stage_conditional = 'yes'` plus `stage_condition`
    (the notice's condition in plain words) for a stage that may not happen
    ("a screening test if applications are many"). Missing means the stage will
    happen. The page shows "only if needed: ...".
    (Replaced by `stage_conditions`, decision 21.)
12. **City slip.** `city_slip` is a date line on each stage. A stage's lines
    run: `city_slip`, `admit_card`, `exam`, `answer_key`, `result`.
13. **`city_slip_separate`, once per exam** in `[dates]`, not per stage.
    `true`: a slip comes before the admit card (dates in each stage's
    `city_slip` line, or "not yet announced"). Missing or `false`: the page
    says "Exam city: shown on the admit card". Missing defaults to `false`
    because that is what the data shows: of 63 bodies with admit-card notices
    in the harvest, only NTA (156 city notices) and RRB (14) post separate
    slips (SSC also does). The pipeline sets it from the body's habit. Keep the
    schema at the coarsest level that works; don't go per stage when per exam
    will do.
    (Values are now `'yes' | 'no' | 'unknown'`, decision 14.)
14. **Every field on every exam.** Each exam file has every key, in the
    template's order, so a grep finds every gap and the quality loop can count
    them. Nothing is left out. TOML has no `null`, so empty is spelled out:
    * `'unknown'`: we have not found it yet (the pipeline works on these);
    * a date the body has not given yet: `{ status = 'not_announced' }`
      (a fact, not a gap); a date we have not found: `{ status = 'unknown' }`;
    * yes/no fields are `'yes' | 'no' | 'unknown'`, not booleans;
    * "applies to everyone" is `'all'`; "no condition" is `'none'`.
    This replaces "left out" and "missing means ..." in decisions 6, 9, 11 and
    13: `fee_payment` is written even when it equals `application`,
    `stage_posts = 'all'`, `stage_conditional = 'no'`, and
    `city_slip_separate` is `'yes' | 'no' | 'unknown'` (the pipeline sets it
    from the body's habit: only NTA, RRB and SSC post separate slips).
    | Value | Means | A gap? |
    |---|---|---|
    | `'unknown'` | we have not found it | yes: the quality loop digs |
    | `'not_announced'` | the body has not said yet | no: the crawler waits |
    | `'all'` | no restriction (not `[]`, which reads as "none") | no |
    | `'none'` | no condition, checked | no |
15. **Names are general-first.** A key starts with what it belongs to and ends
    with the detail, so related keys share a prefix, line up, and one grep
    finds them (`stage_*`). No `is_` / `has_` prefixes. Renamed:
    `official_name` → `title_official`, `series` → `title_series`, `known_as` →
    `title_aliases`, `has_separate_city_slip` → `city_slip_separate`, a stage's
    `name` → `stage_name`, `exam_stage` → `stage_number`,
    `stage_is_conditional` → `stage_conditional`, `only_for_posts` →
    `stage_posts`, `parts` → `stage_parts` (each `part_name`). `title` stays:
    Hugo uses it for the browser tab and lists, and it is the short name; the
    other names share its prefix (`title_official`, `title_series`,
    `title_aliases`), so `^title` finds every name.
16. **Order is logical.** General to specific, in the order a candidate
    asks: what it is and who runs it; the job (posts, pay, terms of
    service); dates and stages; who can apply; the fee and exam-wide rules;
    links; provenance last. Within dates, the order a candidate meets them.
17. **Eligibility: blocks, and 21 keys.** `[[eligibility]]` blocks, one per
    group of posts or papers with the same rules (`eligibility_posts = 'all'`
    and `eligibility_parts = 'all'` for most exams; decision 51). Each block has the same 21 keys, every one always present; the list,
    its order and the evidence behind it are in `docs/eligibility-rules.md`.
    Their shapes are agreed in decisions 18–35.
18. **Age, in three layers**, as its own section `[eligibility.age]`
    (TOML inline tables cannot span lines):
    * the base range: `age_as_of` (the date age is counted on), `age_min`,
      `age_max`, and the same limits as birth dates `age_born_from`, `age_born_to`
      (as printed when the notice gives them; otherwise one fixed rule);
    * `relaxations`, as the notice states them, `relaxation_category` and `relaxation`, in a
      fixed grammar checked by lint: `'+N'`, `'+N - <deduction>'` (deduction
      from a fixed list: `military_service`, `government_service`), `'= N'`
      (a fixed limit), `'no_limit'`, `'+N, max M'`. Combinations are their own
      rows (`'PwBD + SC'`), only those the notice prints;
    * `age_by_category`, the worked-out range per `age_category`, shown to readers
      ("SC: 18 to 37, born 2 Aug 1989 to 1 Aug 2008"), each row checked against
      the base plus its relaxation; `'none'` for no limit.
    Other-state candidates are handled once by `eligibility.domicile` ("treated
    as Unreserved"), not by doubling rows.
19. **Every eligibility rule has `applies`:** `'yes' | 'no' | 'unknown'`
    (the notice sets this rule / has no such rule / not found yet), the same
    three values as every yes/no field; `status` is used only for dates. Its
    content is structured fields, never a display sentence
    (decision 20). Rules that need several fields (age; probably education,
    domicile, physical, attempts) become their own section, agreed one at a
    time. `eligibility.other` is the only free text: a verbatim catch-all whose
    entries are reviewed to grow the fixed lists.
20. **Notice text is input, never stored for display.** The pipeline reads
    the notice's words and fills structured fields from them; the page writes
    its own sentences from those fields, so the two can never disagree. The
    notice's exact words are kept only as evidence, with the page number, in
    provenance, for checking against the PDF. Names are values, not display
    text, so `title_official`, `stage_name` and `part_name` stay as printed.
    `summary` is dropped (decision 22).
21. **`stage_conditions`, a list from a fixed vocabulary**, replaces
    `stage_conditional` + `stage_condition` (decision 11): `'none'` (always
    held) or e.g. `['if_many_applicants', 'if_post_needs_it']`; every listed
    condition must apply. A condition not on the list goes to a worklist and is
    added, like unmapped categories.
22. **No `summary`.** The site shows it only as one line under the title;
    cards do not use it, and the JSON index that carries it is read by nothing.
    The theme writes that line and the page's meta description from the
    fields ("Recruitment of 7,112 constables in Telangana, conducted by
    TSLPRB. Apply by 16 Sep 2026."). This also fixes search snippets: exam pages
    set no `.Description` today, so every one shows the site-wide description.
    Facts the old summaries held get fields in their own blocks: number of
    posts, selection on another exam's score (GATE), who gives the job or seat,
    cancelled or postponed dates, special recruitment drives, contract terms,
    grade.
23. **Education is options of qualifications.** In `[eligibility.education]`,
    `education_options` is a list of options; any one option is enough (or),
    and every qualification inside an option is needed (and):
    `[['D.Pharm'], ['B.Pharm'], ['Pharm.D']]`,
    `[['B.Sc (Physics, Mathematics)', 'B.Ed']]`. Qualification names come from a
    vocabulary file, `qualifications.toml`, built like `reservation.toml`: each
    entry holds its level (10th, 12th, ITI, diploma, bachelor, master,
    doctorate, professional), field and spellings; unknown spellings go to a
    worklist.
24. **Minimum marks are their own rows.** `[[eligibility.education.education_marks]]`,
    one block per qualification and category the notice prints:
    `marks_qualification`, `marks_category`, `marks_min` (a number, or a plain phrase for
    class and percentile: `'second class'`, `'top 20'`), `marks_unit`
    (`'percent' | 'cgpa' | 'class' | 'percentile'`), `marks_out_of` (CGPA
    scale), `marks_counted_on` (`'aggregate'`, `'each_subject'` or `'none'`, or
    a list of subjects: NEET's `['Physics', 'Chemistry', 'Biology']`, the same
    keyword-or-list shape as `stage_posts`; subject names from a fixed list). Lint checks every
    `marks_qualification` is in `education_options`. CGPA-conversion and rounding
    rules (about 5% of notices each) go to `eligibility.other`.
25. **Laid out for people.** Small blocks with one fact per line and `=`
    aligned, instead of long one-line tables: every date is its own block
    (`[dates.application]`, `[dates.stages.exam]`), every eligibility rule is
    its own section in candidate order (`[eligibility.age]`), list rows are
    blocks (`[[eligibility.age.relaxations]]`). Plain words over codes; extra
    descriptive keys are fine. Inside a section the header carries the prefix
    (`[eligibility.age]`, keys `age_min` ...); plain keys of a block keep theirs
    (`stage_*`, `eligibility_posts`). Nested blocks are indented two spaces.
26. **Nationality:** `nationality_allowed`, a list from a fixed vocabulary: Indian,
    Nepal, Bhutan, Tibetan refugee (before 1962), PIO, OCI, NRI, Foreign
    national. SSC and UPSC allow the first five; most state jobs Indian only;
    NEET all eight.
27. **Domicile:** `domicile_area` (`'state' | 'union_territory' | 'region' |
    'district' | 'village_or_ward'`), `domicile_places` (a list), and
    `domicile_other_states` (`'not_eligible' | 'as_unreserved' |
    'eligible'`). Checked against 304 residence sentences in 84 documents:
    areas run from state down to village or ward (Anganwadi) and border
    village (police); all three other-state rules occur (J&K and Maharashtra's
    Pavitra: not eligible; UP, Odisha: as Unreserved). How residence is defined
    (J&K's 15 years) appeared once in 304 and goes to `eligibility.other`.
28. **Gender, marital, children.** `gender_allowed` (`'all'` or a list);
    transgender appears in 17 documents but only as a category for fees and
    marks, so real restrictions (ANM, Mahila constable, some Agniveer intakes)
    are rare. `marital.marital_rules`, a list from `'unmarried_only'`,
    `'stay_unmarried_during_service_or_training'`, `'at_most_one_spouse'` (the
    last a common declaration). `children.children_max` and
    `children_counted_from` for the two-child norm (Rajasthan from 1 June 2002,
    Assam from 2021); none in the sample, but it is law.
29. **Education details:** `education_held_by` (the "crucial date", 12% of
    notices; decides final-year candidates), `education_final_year`,
    `education_passed_from` / `_to` (year of passing, entrance exams),
    `education_equivalent` ("or equivalent", 36%), `education_desirable`
    (27%). Recognition by AICTE, UGC etc. (56%, mostly boilerplate) lives in
    each qualification's vocabulary entry; medium of instruction (TN's PSTM is
    a category) and distance-mode rules go to `eligibility.other`.
30. **Prior exam** (an exam you must already have passed: GATE for PSUs,
    TET/CTET for teachers, NET for lecturers, UP PET for UP Group C): options,
    any one enough, each a block with `prior_exam` (catalogue id, so the pages
    link), `prior_exam_years` (tied to a year in 26 hits), `prior_exam_papers`
    (`'any'`, `'matching_discipline'`, or a list), `prior_exam_needs`
    (`'appeared' | 'qualified' | 'valid_score' | 'rank_within'`) and
    `prior_exam_rank_max`, with `rank_by_category` rows (`rank_category`,
    `rank_share` in percent) for JEE Advanced's "top 2,50,000", split by
    category. About 60 documents; valid score 13, qualified 3, rank 3; no
    minimum score or percentile found, so none is modelled.
31. **Certificates and licences** are qualifications, from the same
    `qualifications.toml`: `certificates_required` blocks, all required, each
    `certificate` plus `certificate_speed` (wpm, typing and shorthand). Held by
    the same date as education. Typing tested at a stage stays a stage. In the
    data: driving licence 17 (noisy), typing 15, computer knowledge 10, ITI 8
    (an education qualification), shorthand 6, NCC 6, sports 4; CCC, O level,
    CPCT, RS-CIT near 0 because UP, MP and Rajasthan notices are Hindi scans,
    but they are mandatory there.
32. **Registration, experience, language**, each a list of required blocks
    (shapes in the template), checked twice against the data. Registration
    (about 35 docs): `registration_with` (any one of a list: "State Council or
    NMC"), `registration_scope`, `registration_valid`, `registration_when`
    (some only by joining). Experience (about 25): `experience_years`,
    `experience_in` (any one; a field or a post, 13 name a post),
    `experience_sector`, `experience_counted`, `experience_desirable`,
    `experience_relaxable` (5). Language (about 20): `language` (any one:
    "Hindi or Urdu"), `language_level`, `language_passed_at` ("Matric with
    Hindi"), `language_script` (Devanagari, 6), `language_when` (test after
    selection, 3). To `eligibility.other`: "knowledge of Rajasthani culture",
    experience-certificate format, experience at a pay level.
33. **Physical standards are table rows.** `physical_standards` blocks, one
    per group and gender the notice prints: `physical_gender`, `physical_for`
    (`'all'` or communities, regions, categories: Garhwali, North-East, ST),
    `height_cm`, `chest_cm`, `chest_expanded_cm`, `weight` (kg, "proportionate
    to height and age", or `'none'`). Checked on 61 documents with physical
    standards (CAPF table: 170/80/85, hill groups 165/78/83, North-East
    162.5/77/82). Running, jumps and shot put are tests at the PET stage and
    belong to that stage's parts (decision 45); eyesight, knock knees and
    flat foot go to `eligibility.medical`.
34. **Medical and disability.** Medical (about 40 documents): vision per
    eye as printed (6/6, 6/9; 14), `vision_glasses_allowed`,
    `colour_blind_allowed` (12), `defects_barred` from a fixed list (knock
    knees, flat foot, squint; 10), `tattoos_allowed`, `medical_category`
    (SHAPE-1; 5), `medical_guidelines` (a named standard, when the notice only
    refers to one). Disability: `disability_suitable`, the RPwD Act codes the
    post is identified for ("B, LV, HH, OA, BA, OL ...", 7), `'none'` when not
    suitable; `disability_functional`. Scribe and compensatory-time rules (19)
    are about sitting the exam and go to `[exam_rules]`
    (decision 46).
35. **Employment, character, attempts, category proof.** Employment:
    `employment_noc_needed` (20 documents), `employment_via_employer` (proper
    channel, 5), `employment_resign_if_selected` (14),
    `employment_serving_only`, `employment_service_years`,
    `employment_service_in` (departmental exams, 7). Character: one list,
    `character_checks`, from `no_conviction`, `no_pending_case`,
    `not_dismissed`, `not_debarred`, `character_certificate`,
    `police_verification` (13, 11, 11, 5 ...). Attempts: `attempts_counted`
    (`'attempts' | 'consecutive_years'`) and `attempts_by_category` rows with
    `attempts_category` and `attempts_max` (a number or `'unlimited'`). Category proof:
    `category_certificates` rows, each `certificate_category`, `certificate_issued_after`
    (15), `certificate_income_year` (EWS, 4), `certificate_list`
    (`'central' | 'state'`, 12); non-creamy layer appears in 46.
36. **`purpose` and `streams` replace `categories`.** `categories`
    (`Government` 242, `Academic` 68) was too coarse and clashed with
    reservation categories and Hugo's built-in taxonomy. Both new fields are
    copied from the catalogue, which already sets them: `purpose` (7 values,
    all 375 exams), `streams` (42 values, 366 exams). The lowest qualification
    ("12th-pass jobs") is worked out from `eligibility.education`, not stored.
37. **Bodies with roles.** `[[bodies]]` blocks, each `body` (catalogue id,
    or a plain name such as "Participating public sector banks") and
    `body_role` from a fixed list: `conducts`, `owns`, `employs`,
    `allots_seats`, `counsels`, `convenes`. Chosen over three fixed fields
    because new roles only add a word. 44 of 310 ExamHub summaries name a body
    other than the conducting one (XAT on behalf of XAMI; JoSAA and CSAB allot
    JEE seats; banks hire through IBPS). ExamHub's body filter reads the
    `conducts` rows (a one-line theme change). The catalogue's `allocated_by`
    (7 exams) feeds `allots_seats`.
38. **Changes are recorded.** Date `status` adds `'postponed'` (off, no new
    date yet) and `'cancelled'`. Every date block has `change` (`'none' |
    'extended' | 'rescheduled' | 'brought_forward'`) and `changed_from` (the
    previous end date): "last date extended" is what candidates and alerts
    need. A re-exam is `change = 'rescheduled'` on that stage's exam date. A
    top-level `cycle_status` (`'active' | 'withdrawn' | 'cancelled'`) covers
    withdrawn advertisements. From 51,516 harvested titles: extended 984,
    rescheduled 231, postponed 225, cancelled 157 (noisy), re-exam 63,
    withdrawn 50.
39. **Selection on another exam's score is a stage.** `stage_format` adds
    `'external_score'` (PSUs shortlisting on GATE, 17 notices): stage 1 is
    "GATE 2027 score", then the interview. Its admit-card and exam lines stay
    `'not_announced'` and are hidden. The requirement itself stays in
    `eligibility.prior_exam`.
40. **Kind of job and kind of drive.** `recruitment_engagement`
    (`'permanent' | 'contract' | 'apprenticeship' | 'deputation' | 'none'`),
    `recruitment_drive` (`'regular' | 'special_drive' | 'backlog' | 'nca' |
    'sports_quota' | 'compassionate'`), `recruitment_drive_for` (`'all'` or
    the categories it is limited to). From harvested titles: contract 364,
    apprenticeship 90, special drive 46, compassionate 35, sports quota 20,
    backlog 18, ex-servicemen only 15, Kerala NCA 9.
41. **Posts and vacancies.** `[posts]` holds `vacancies_total` and
    `vacancies_status` (notices often say "tentative, may vary"), then one
    `[[posts.list]]` block per table row: `post_name` (the names
    `stage_posts` and `eligibility_posts` must use), `post_code`, `post_unit`
    (office, department or zone, when a post is split), `post_pay_level`
    (must equal a `pay_label`), `post_vacancies`, and `[posts.list.by_category]` with one
    line per category. Vertical classes add up to `post_vacancies`;
    horizontal ones (ESM, PwBD, Women) are counted inside them. Lint checks
    both sums. Built on the pipeline's existing vacancy-table reader.
    Hugo iterates maps alphabetically, so the theme orders category columns
    by the vocabulary (Unreserved, EWS, OBC-NCL, SC, ST, then horizontal),
    from a small data file the pipeline exports to ExamHub.
42. **One Markdown file per exam cycle, all data in front matter, empty
    body.** The pipeline writes the whole page as front matter; ExamHub's
    theme renders every part, including the vacancy and pay tables, from the
    data. No Markdown tables or prose in the body: generated tables stay
    consistent, sort and filter, and fit phones.
43. **Pay, complete.** One `[[pay]]` block per post and period:
    `pay_posts`, `pay_during` (`'service' | 'training' | 'probation'`),
    `pay_label` (notice wording, shown), `pay_system` (`'pay_matrix' |
    'scale' | 'pre_revised' | 'fixed' | 'ctc' | 'stipend'`),
    `pay_matrix_level`, `pay_grade_pay`, `pay_rupees` (always `[min, max]`;
    fixed pay is `[n, n]`, like a one-day date), `pay_initial`, `pay_per` (`'month' | 'year'`),
    `pay_allowances`. Nothing is merged away: every field is kept, even when
    another could be derived from it. `post_pay_level` must equal a
    `pay_label`; lint checks it. `[service]` holds `service_bond_months`,
    `service_bond_amount`, `service_probation_months`,
    `service_contract_months` (months, so six months is 6 and two years 24;
    notices use both units). From 101 notices: matrix level 11, rupee scale
    16, pre-revised with grade pay 4, fixed 18, CTC 1+, stipend or probation
    pay 14, bond 13; ExamHub's 44 pay records add `initial` (11) and PSU
    grades (7, kept as `pay_label`).
44. **Fee as rows.** `[fee]` holds `fee_refundable`, `fee_bank_charges_extra`,
    `fee_payment_modes`; then one `[[fee.rows]]` per charge: `fee_category`
    (vocabulary, never merged, or `'all'`), `fee_gender`, `fee_posts`,
    `fee_stage`, `fee_rupees` (0 = exempt), `fee_per` (`'application' |
    'post' | 'paper' | 'test_date' | 'attempt'`), `fee_includes`. No free-text
    notes: ExamHub's 296 notes become fields or extra rows ("Karnataka 2A,
    2B, 3A, 3B" is four rows; "Exempt" is 0). From ExamHub's 151 fee lists
    (666 rows) and 101 notices: exempt 208 rows, by gender 13, per test or
    post 4, one stage only 3, GST or charges included 8 notices,
    non-refundable 28, payment modes 36.
45. **How each stage is sat, and how it is marked.** Each stage adds
    `stage_mode` (`'cbt' | 'omr' | 'pen_paper' | 'in_person' | 'video' |
    'external'`; what the stage *is* stays in `stage_format`, so an interview
    is `format = 'interview'`, `mode = 'in_person'` or `'video'`),
    `stage_minutes`, `stage_languages`. Each part adds `part_questions`,
    `part_marks`, `part_minutes` (`'none'` when parts are not timed
    separately), `part_qualifying`, and one `[[...part_marking]]` block per
    question type: `marking_question_type` (`'mcq' | 'msq' | 'numerical' |
    'all'`), `marking_correct`, `marking_unanswered`, `marking_wrong`,
    `marking_partial`. Fractions become numbers (a quarter of 1 mark is
    -0.25). Replaces ExamHub's sentence fields `mode` (255), `duration` (102)
    and `negative_marking` (119). From data: fraction deducted 54, some
    question types with no negative marking 12, partial marks 2, skipped
    questions penalised 0; notices: CBT 32, OMR or offline 18, duration 39,
    sectional timing 7, qualifying papers 9, bilingual 13. `'video'` has no
    case yet but is allowed.
46. **Exam-wide rules.** `[exam_rules]`: centres as separate facts,
    `centre_places`, `centre_choice` (`'ranked' | 'single' | 'none'`),
    `centre_choices_max`, `centre_allotment` (`'availability' | 'first_come'
    | 'random'`), `centre_guaranteed`, `centre_change_allowed`; then
    `scribe_allowed`, `scribe_extra_minutes_per_hour`, `scores_normalised`,
    `tie_break_order` (ordered steps from a vocabulary). Replaces ExamHub's
    `venue` sentence (199 files). From data: ranked choice 10 notices plus
    ExamHub, body may move you 9, first come 2, random 1 (CBSE), no change
    later 3; scribe 15, compensatory time 13, normalisation 3, tie-break 3.
47. **Links.** `[links]` holds `link_official_page` and `link_apply` (both
    kept: equal in 171 of 292 ExamHub files), then one `[[links.documents]]`
    per official file for the cycle: `document_type` (the harvest's types
    plus `'syllabus' | 'brochure'`), `document_stage`, `document_published`,
    `document_url`, `document_archive` (Wayback). The page writes each
    label from type, stage and date. From the harvest's 51,516 links: result
    8,405, notification 8,263, answer key 4,797, schedule 2,362, press
    release 1,951, corrigendum 1,602, admit card 1,157; 36,379 are PDFs.
48. **Provenance per fact.** `[provenance]` holds `provenance_retrieved` and
    `provenance_last_checked`, then one `[[provenance.evidence]]` per filled
    field: `evidence_field` (dotted path), `evidence_document` (a
    `links.documents` URL), `evidence_page`, `evidence_words` (the notice's
    words, the only place they are kept), `evidence_method` (`'rule' |
    'table' | 'model' | 'manual'`, so model-filled facts are visible). Never
    rendered. Replaces ExamHub's one record per page (`source_url`,
    `source_doc` sentence, `source_tier`, two timestamps; 310 files).
49. **Codes use underscores; names keep their spelling.** A value from a
    fixed list is written with underscores (`'each_subject'`,
    `'before_applying'`, `'read_write_speak'`, `'flat_foot'`), like every
    other code. Names from a vocabulary, which readers see, keep their own
    spelling: qualifications, categories (`'PwBD + SC'`), posts, subjects,
    bodies. The page turns codes into words.
50. **Papers you choose.** Each stage adds `stage_parts_choose` (`'all'`, or
    `[min, max]` of its `'choice'` parts: JEE Main 1, 2A, 2B is `[1, 3]`,
    CTET I and II `[1, 2]`, CUET PG `[1, 4]`). Each part adds `part_taken`
    (`'compulsory' | 'choice'`) and `part_subjects` (a list to pick one from,
    such as NET Paper 2's 83 subjects or a UPSC optional; or `'none'`), so a
    long subject list is one part, not 83. From ExamHub: JEE and CTET files,
    CUET PG "up to four test papers", 8 compulsory-plus-optional cases; rare in
    the recruitment-heavy notice sample.
51. **Eligibility by paper.** Each `[[eligibility]]` block adds
    `eligibility_parts` (`'all'` or a list of `part_name` values) beside
    `eligibility_posts`, so an exam whose papers have different rules gets
    one complete block per paper: CTET Paper I (12th plus a diploma) and
    Paper II (a degree with 50%), JEE Main Paper 1 and 2A. About 10 ExamHub
    files: the TETs (CTET, UTET, Bihar STET, JTET, HP TET's ten papers,
    Manipur, Nagaland) and JEE Main. Differences by wing or programme with
    their own vacancies (NDA's Army and Air Force) are posts and use
    `eligibility_posts`.
52. **Gaps from the NICL AO test, closed** (list below; counts from
    notices / ExamHub records). Posts: each row adds `post_group` and
    `post_vacancy_kind` (`'regular' | 'backlog'`; backlog 8 / 5), and
    `[[posts.groups]]` hold a split given only for a group (`group_name`,
    `group_vacancies`, `[posts.groups.by_category]`); such rows have
    `by_category = 'in_group'`. `[posts]` adds `posts_per_candidate` (14 / 4),
    `posts_waiting_list_percent` (9 / 0) and `posts_join_in_batches`.
    Stages: `stage_number` orders every stage of the exam; a post's own
    steps are the stages whose `stage_posts` include it, so parallel tracks
    (Hindi Officers) need no new field and the page numbers each track's
    steps itself. Stages add `stage_centres` (`'as_exam'` or cities),
    `stage_shortlist_times` (candidates called per vacancy),
    `stage_merit_weight` (percent of final merit) and `stage_min_marks`.
    Parts add `part_posts`, `part_languages` and `part_min_marks` (sectional
    cut-off, 5 / 1). Marking adds `marking_unit` (`'marks' |
    'share_of_question'`, for "a quarter of the marks assigned" when marks
    per question are not printed) and question type `'descriptive'`. Date
    `status` adds `'none'`: the notice says there is no such window. Age
    adds `age_relaxation_cumulative` and `age_relaxation_max_age` (9 / 0).
    `registration_when` adds `'before_interview'`. Pay adds
    `pay_increments` (`[[step, times], ...]`), `pay_gross`,
    `pay_gross_where` (`'all' | 'metro'`) and `pay_benefits` (1 / 1 state
    a gross). Service adds `service_probation_extendable_months`,
    `service_probation_exam`, `service_bond_amount = 'one_year_gross'` as a
    value, `service_training_cost`, `service_first_posting_months`,
    `service_same_field_months` with `service_same_field_posts`, and
    `service_posting_area` (10 / 9). `[exam_rules]` adds
    `training_offered_for` (3 / 0); tie-break steps add
    `marks_in_stage:<stage_name>`. PwBD vacancy columns keep the notice's
    sub-categories as categories (`'PwBD (a)'` ... `'PwBD (d, e)'`), never
    merged; the vocabulary maps each letter to its RPwD codes (25 notices
    print both).

53. **Cut-offs, one row per published number** (1 Oct; checked against 12
    documents from RPSC, NICL, CGPSC, UGC NET, BHEL, SAIL, APSSB, TN MRB,
    BPSSC; 1,811 cut-off notices in the harvest). `[[cutoffs]]` in the cycle
    they belong to; the next cycle's page shows them from the previous record.
    Keys: `cutoff_stage`, `cutoff_purpose` (`'next_stage' |
    'document_verification' | 'medical' | 'final_selection'`), `cutoff_outcome`
    (`'all'` or as printed: UGC NET's JRF / Assistant Professor), `cutoff_list`
    (`'main' | 'reserve'`), `cutoff_kind` (`'threshold' | 'last_candidate'`),
    `cutoff_posts`, `cutoff_subject`, `cutoff_region` (NICL's state-wise),
    `cutoff_category` (vertical) and `cutoff_category_horizontal` (Women,
    PwBD (a), Widow, PSTM ...), never merged, `cutoff_gender`, `cutoff_part`
    (`'total'` or a `part_name`), `cutoff_standard` (`'general' | 'relaxed' |
    'same_as_unreserved'`: NICL's `*` and `$`), `cutoff_marks` (a number, or
    `'no_vacancy' | 'no_candidate' | 'not_applicable'`), `cutoff_marks_highest`
    (CGPSC), `cutoff_scale` (`'raw' | 'normalised' | 'percentage' |
    'percentile' | 'weighted'`), `cutoff_out_of`, `cutoff_birth_date` (the
    tie-break DOB RPSC, APSSB, MRB and BPSSC print), `cutoff_candidates`,
    `cutoff_published`, `cutoff_document`. One number on two scales (BHEL:
    out of 100 and 240) is two rows. Shown as where the last candidate
    landed, never as a mark you need.

## Gaps found by a real notice (closed in decision 52)

Test notice: NICL Administrative Officers (Scale I), advertisement dated
29 Dec 2023, 36 pages
(`https://nationalinsurance.nic.co.in/sites/default/files/NICL%20AO%20Recruitment%20Advertisment%202023-24.pdf`).
274 posts in 8 disciplines; Prelims, Mains and Interview, with a separate
single exam for Hindi Officers. All closed in decision 52; the template
example is rebuilt from this notice.

1. **Category split for a group of posts** (p.1). Vacancies by category are
   given for "Specialist" (142, across 7 disciplines) and "Generalist"
   (130), not per discipline; plus a "Backlog" row (2, ST).
2. **Parallel tracks** (p.7, 9). Hindi Officers skip Prelims and Mains and
   sit one exam, on the Mains date, then the common Interview.
   `stage_number` is unique and means position, so the tracks clash.
3. **Parts that differ by post** (p.7–8). Mains has 5 sections of 50 marks
   for Generalists and 6 of 40 (plus 50 professional) for Specialists.
4. **Language per part** (p.7). English Language sections are English only;
   the others are English or Hindi.
5. **Sectional cut-off** (p.7, 9). Candidates must pass each section; the
   marks are "decided by the Company" later.
6. **Weight in final merit and shortlisting** (p.7, 11). Mains and Interview
   count 80:20; Interview has a minimum mark; about 15 times the vacancies
   go from Prelims to Mains.
7. **A window that does not exist** (p.2). No correction window ("no change
   of application data will be permitted"): date status has no value for
   "none".
8. **Cumulative age relaxation with a cap** (p.4). Relaxations add up, to a
   maximum age of 45.
9. **Registration by interview** (p.3). Doctors must be registered with NMC
   or a State Medical Council "as on date of the scheduled interview";
   `registration_when` has only before applying or before joining.
10. **One post per candidate** (p.2, 19). "Apply for any ONE discipline only."
11. **Pay extras** (p.2–3). Gross about Rs 85,000 a month in metros; the
    scale's increments (50925-2500(14)-85925-2710(4)-96765); a 25%
    allowance (NPA) for doctors only.
12. **Terms of service** (p.2). Probation 12 months, extendable to 24; must
    pass the Licentiate exam during probation; bond of 48 months for one
    year's gross salary, plus Rs 25,000 if leaving during probation; at
    least 5 years at the first posting; specialists 10 years in their field;
    posting anywhere in India.
13. **Centres per stage** (p.12–14). Prelims: 33 states and UTs, about 90
    cities; Mains and the Hindi exam: 20 cities.
14. **Tie-break by stage marks** (p.11). Interview marks, then older first:
    the vocabulary needs `marks_in_stage` beside `marks_in_part`.
15. **Waiting list and batches** (p.9). Up to 50% of vacancies; selected
    candidates may join in batches.
16. **PwBD sub-categories** (p.1). Vacancies split by RPwD categories a, b,
    c, d and e, not by the codes used in `disability_suitable`.
17. **Pre-exam training** (p.14). Free training for SC, ST, OBC-NCL and PwBD
    candidates who ask for it when applying.

## Checked

* **Grouped dates render in Hugo** (tested on v0.166, 29 Sep 2026):
  `[dates] application = { from = 2026-05-21, to = ..., status = '...' }`
  formats with `time.Format`, compares with `now`, and pages filter and sort by
  `Params.dates.application.to`. ExamHub's theme reads the flat keys today, in
  about 8 layout files (`exam-status.html`, `milestones.html`,
  `admit-card.html`, `exam-card.html`, `dates.html`, `cal-key.html`,
  `home.html`, `page.html`, `section.exams.json`), so the switch is one change in
  ExamHub: records and layouts together.

## Template

Every key is always present (decision 14); laid out per decision 25.
Comments show the allowed values.

```toml
+++
# ═══ identity (pipeline) ═══════════════════════════════════════════
section      = 'exams'
exam_id      = 'in-ibps-clerk'             # catalogue id
cycle        = '2026'                      # cycle label
cycle_status = 'active'                    # 'active' | 'withdrawn' | 'cancelled'

# ═══ titles (readers) ══════════════════════════════════════════════
title          = 'IBPS Clerk 2026'         # short name + cycle: lists, search, tab
slug           = 'ibps-clerk-2026'         # URL
title_official = 'Customer Service Associate (Clerk)'   # the notice's own, no cycle
title_series   = 'IBPS Clerk'              # links every cycle of one exam
title_aliases  = ['IBPS CSA', 'Bank Clerk']             # for search; or 'none'

# ═══ who runs it, what it is ═══════════════════════════════════════
purpose = 'recruitment'                    # 'recruitment' | 'admission' | 'eligibility' | 'certification' | 'school_board' | 'scholarship' | 'departmental'
streams = ['banking', 'clerical']          # from the catalogue's stream list

recruitment_engagement = 'permanent'       # 'permanent' | 'contract' | 'apprenticeship' | 'deputation' | 'none'
recruitment_drive      = 'regular'         # 'regular' | 'special_drive' | 'backlog' | 'nca' | 'sports_quota' | 'compassionate'
recruitment_drive_for  = 'all'             # 'all' or the categories it is limited to

# one block per body, with its role
[[bodies]]
body      = 'in-ibps'                      # catalogue body id, or a plain name when there is no single body
body_role = 'conducts'                     # 'conducts' | 'owns' | 'employs' | 'allots_seats' | 'counsels' | 'convenes'

[[bodies]]
body      = 'Participating public sector banks'
body_role = 'employs'

# ═══ posts and vacancies ═══════════════════════════════════════════
[posts]
vacancies_total            = 7                       # or 'unknown' / 'not_announced'
vacancies_status           = 'tentative'             # 'confirmed' | 'tentative'
posts_per_candidate        = 'unknown'               # posts one candidate may apply for; or 'all' / 'unknown'
posts_waiting_list_percent = 'none'                  # reserve list, percent of vacancies; or 'none' / 'unknown'
posts_join_in_batches      = 'no'                    # 'yes' | 'no' | 'unknown'
groups                     = 'none'                  # or [[posts.groups]] blocks (group_name, group_vacancies, by_category)

  [[posts.list]]
  post_name         = 'Lower Division Clerk'  # stage_posts and eligibility_posts use these names
  post_code         = 'none'
  post_unit         = 'AIIMS Bhopal'          # office, department or zone the row is for; or 'all'
  post_group        = 'none'                  # the notice's group of posts (Specialist, Generalist); or 'none'
  post_vacancy_kind = 'regular'               # 'regular' | 'backlog'
  post_pay_level    = 'Level 2'               # must match a pay_label
  post_vacancies    = 4

    [posts.list.by_category]               # vertical classes add up to post_vacancies; or 'in_group';
    Unreserved = 2                         # horizontal ones (ESM, PwBD, Women) are inside them
    EWS        = 0
    OBC-NCL    = 2
    SC         = 0
    ST         = 0
    ESM        = 0
    PwBD       = 0

  [[posts.list]]
  post_name         = 'Lower Division Clerk'
  post_code         = 'none'
  post_unit         = 'AIIMS Raipur'
  post_group        = 'none'
  post_vacancy_kind = 'regular'
  post_pay_level    = 'Level 2'
  post_vacancies    = 3

    [posts.list.by_category]
    Unreserved = 1
    EWS        = 0
    OBC-NCL    = 2
    SC         = 0
    ST         = 0
    ESM        = 0
    PwBD       = 0

# ═══ pay ═══════════════════════════════════════════════════════════
[[pay]]
pay_posts        = ['Lower Division Clerk']  # or 'all'
pay_during       = 'service'                 # 'service' | 'training' | 'probation'
pay_label        = 'Level 2'                 # notice wording, shown; post_pay_level uses it
pay_system       = 'pay_matrix'              # 'pay_matrix' | 'scale' | 'pre_revised' | 'fixed' | 'ctc' | 'stipend'
pay_matrix_level = 2                         # 7th CPC level, or 'none'
pay_grade_pay    = 'none'                    # pre-revised grade pay in rupees, or 'none'
pay_rupees       = [19900, 63200]            # always [min, max]; fixed pay is [n, n]
pay_increments   = 'none'                    # [[step, times], ...] for a scale with increments; or 'none'
pay_initial      = 19900                     # starting basic, or 'unknown'
pay_per          = 'month'                   # 'month' | 'year'
pay_allowances   = ['DA', 'HRA', 'TA']       # or 'none' / 'unknown'
pay_gross        = 'unknown'                 # monthly gross in rupees as the notice states it; or 'none' / 'unknown'
pay_gross_where  = 'none'                    # 'all' | 'metro' | 'none'
pay_benefits     = 'unknown'                 # e.g. ['NPS', 'gratuity']; or 'none' / 'unknown'

# ═══ terms of service ══════════════════════════════════════════════
[service]
service_bond_months                 = 'none'            # months, or 'none' / 'unknown'
service_bond_amount                 = 'none'            # rupees, or 'none' / 'unknown'
service_probation_months            = 24                # months, or 'none' / 'unknown'
service_probation_extendable_months = 'none'            # months, or 'none' / 'unknown'
service_probation_exam              = 'none'            # exam to pass during probation; or 'none' / 'unknown'
service_training_cost               = 'none'            # rupees repaid on leaving in training; or 'none' / 'unknown'
service_contract_months             = 'none'            # contract length in months, or 'none'
service_first_posting_months        = 'none'            # minimum months at the first posting; or 'none' / 'unknown'
service_same_field_months           = 'none'            # months in one field, for service_same_field_posts
service_same_field_posts            = 'none'            # ['Post', ...] or 'none'
service_posting_area                = 'all_india'       # 'all_india' | 'all_india_and_abroad' | 'state' | 'unit' | 'unknown'

# ═══ dates ═════════════════════════════════════════════════════════
# status: 'confirmed' | 'tentative' | 'not_announced' | 'unknown' | 'postponed' | 'cancelled'
# change: 'none' | 'extended' | 'rescheduled' | 'brought_forward'; changed_from: the previous end date, or 'none'
[dates]
city_slip_separate = 'no'                  # 'yes' | 'no' | 'unknown'

# ── applying: once per exam ──
[dates.application]
from         = 2026-08-01
to           = 2026-08-21
status       = 'confirmed'
change       = 'none'
changed_from = 'none'

[dates.fee_payment]
from         = 2026-08-01
to           = 2026-08-21
status       = 'confirmed'
change       = 'none'
changed_from = 'none'

[dates.late_fee]
status       = 'not_announced'
change       = 'none'
changed_from = 'none'

[dates.correction]
from         = 2026-08-28
to           = 2026-08-30
status       = 'confirmed'
change       = 'none'
changed_from = 'none'

# ── stages: one per step you must pass, in the notice's order ──
[[dates.stages]]
stage_name            = 'Preliminary Examination'   # official wording, shown to readers
stage_number          = 1
stage_format          = 'written'       # 'written' | 'physical' | 'skill' | 'interview' | 'documents' | 'medical' | 'external_score'
stage_mode            = 'cbt'           # 'cbt' | 'omr' | 'pen_paper' | 'in_person' | 'video' | 'external'
stage_purpose         = 'screening'     # 'screening' | 'merit' | 'qualifying'
stage_posts           = 'all'           # 'all' or ['Post', ...]
stage_conditions      = 'none'          # 'none' or [codes from the fixed list]; all must apply
stage_minutes         = 60
stage_languages       = ['English', 'Hindi']
stage_centres         = 'as_exam'        # 'as_exam' or ['City', ...]; or 'unknown'
stage_shortlist_times = 'none'           # candidates called per vacancy; or 'none'
stage_merit_weight    = 'none'           # percent of final merit; or 'none'
stage_min_marks       = 'none'           # 'by_category', a number, or 'none' / 'not_announced'
stage_parts_choose    = 'all'           # 'all', or [min, max] of the 'choice' parts: JEE Main [1, 3], CUET PG [1, 4]

  [dates.stages.city_slip]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.admit_card]
  from         = 2026-09-24
  to           = 2026-10-12
  status       = 'tentative'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.exam]
  from         = 2026-10-04
  to           = 2026-10-12
  status       = 'confirmed'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.answer_key]
  status       = 'unknown'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.result]
  from         = 2026-10-25
  to           = 2026-11-10
  status       = 'tentative'
  change       = 'none'
  changed_from = 'none'

  [[dates.stages.stage_parts]]
  part_name       = 'English Language'
  part_posts      = 'all'                  # 'all' or ['Post', ...]
  part_taken      = 'compulsory'           # 'compulsory' | 'choice'
  part_subjects   = 'none'                 # pick one from this list, e.g. NET Paper 2; or 'none'
  part_questions  = 30
  part_marks      = 30
  part_minutes    = 20                     # or 'none' when parts are not timed separately
  part_languages  = ['English', 'Hindi']
  part_qualifying = 'no'                   # 'yes' = marks not counted in merit
  part_min_marks  = 'none'                 # sectional cut-off; or 'none' / 'not_announced'

    [[dates.stages.stage_parts.part_marking]]
    marking_question_type = 'all'          # 'mcq' | 'msq' | 'numerical' | 'descriptive' | 'all'
    marking_unit          = 'marks'        # 'marks' | 'share_of_question'
    marking_correct       = 1              # or 'as_evaluated' for descriptive answers
    marking_unanswered    = 0
    marking_wrong         = -0.25          # a quarter of the question's marks
    marking_partial       = 'no'

  [[dates.stages.stage_parts]]
  part_name       = 'Numerical Ability'
  part_posts      = 'all'
  part_taken      = 'compulsory'
  part_subjects   = 'none'
  part_questions  = 35
  part_marks      = 35
  part_minutes    = 20
  part_languages  = ['English', 'Hindi']
  part_qualifying = 'no'
  part_min_marks  = 'none'

    [[dates.stages.stage_parts.part_marking]]
    marking_question_type = 'all'
    marking_unit          = 'marks'
    marking_correct       = 1
    marking_unanswered    = 0
    marking_wrong         = -0.25
    marking_partial       = 'no'

  [[dates.stages.stage_parts]]
  part_name       = 'Reasoning Ability'
  part_posts      = 'all'
  part_taken      = 'compulsory'
  part_subjects   = 'none'
  part_questions  = 35
  part_marks      = 35
  part_minutes    = 20
  part_languages  = ['English', 'Hindi']
  part_qualifying = 'no'
  part_min_marks  = 'none'

    [[dates.stages.stage_parts.part_marking]]
    marking_question_type = 'all'
    marking_unit          = 'marks'
    marking_correct       = 1
    marking_unanswered    = 0
    marking_wrong         = -0.25
    marking_partial       = 'no'

[[dates.stages]]
stage_name            = 'Main Examination'
stage_number          = 2
stage_format          = 'written'
stage_mode            = 'cbt'           # 'cbt' | 'omr' | 'pen_paper' | 'in_person' | 'video' | 'external'
stage_purpose         = 'merit'
stage_posts           = 'all'
stage_conditions      = 'none'
stage_minutes         = 'not_announced'
stage_languages       = ['English', 'Hindi']
stage_centres         = 'as_exam'
stage_shortlist_times = 'none'
stage_merit_weight    = 'none'
stage_min_marks       = 'none'
stage_parts_choose    = 'not_announced'
stage_parts           = 'not_announced'   # or [[dates.stages.stage_parts]] blocks, as in stage 1

  [dates.stages.city_slip]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.admit_card]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.exam]
  from         = 2026-11-29
  to           = 2026-11-29
  status       = 'tentative'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.answer_key]
  status       = 'unknown'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.result]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

[[dates.stages]]
stage_name            = 'Language Proficiency Test'
stage_number          = 3
stage_format          = 'skill'
stage_mode            = 'unknown'       # 'cbt' | 'omr' | 'pen_paper' | 'in_person' | 'video' | 'external'
stage_purpose         = 'qualifying'
stage_posts           = 'all'
stage_conditions      = ['if_no_state_language']
stage_minutes         = 'not_announced'
stage_languages       = 'not_announced'
stage_centres         = 'as_exam'
stage_shortlist_times = 'none'
stage_merit_weight    = 'none'
stage_min_marks       = 'none'
stage_parts_choose    = 'none'
stage_parts           = 'none'

  [dates.stages.city_slip]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.admit_card]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.exam]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.answer_key]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

  [dates.stages.result]
  status       = 'not_announced'
  change       = 'none'
  changed_from = 'none'

# ═══ eligibility: one block per group of posts or papers with the same rules
# every rule: applies = 'yes' | 'no' | 'unknown'
[[eligibility]]
eligibility_posts = 'all'                  # 'all' or ['Post', ...]: post_name values
eligibility_parts = 'all'                  # 'all' or ['Paper I', ...]: part_name values

  # ── who you are ──
  [eligibility.nationality]
  applies             = 'yes'
  nationality_allowed = ['Indian']         # 'Indian' | 'Nepal' | 'Bhutan' | 'Tibetan refugee (before 1962)' | 'PIO' | 'OCI' | 'NRI' | 'Foreign national'

  [eligibility.domicile]
  applies               = 'no'
  domicile_area         = 'none'           # 'state' | 'union_territory' | 'region' | 'district' | 'village_or_ward' | 'none'
  domicile_places       = 'none'           # 'none' or ['Bihar'] / ['Yadgir'] / ...
  domicile_other_states = 'eligible'       # 'not_eligible' | 'as_unreserved' | 'eligible'

  [eligibility.gender]
  applies        = 'no'
  gender_allowed = 'all'                   # 'all' or ['Female'] / ['Male'] / ['Transgender', ...]

  [eligibility.marital]
  applies       = 'yes'
  marital_rules = ['at_most_one_spouse']   # 'unmarried_only' | 'stay_unmarried_during_service_or_training' | 'at_most_one_spouse'

  [eligibility.children]
  applies               = 'no'
  children_max          = 'none'           # a number, or 'none'
  children_counted_from = 'none'           # a date (Rajasthan: 2002-06-01), or 'none'

  [eligibility.age]
  applies                   = 'yes'
  age_as_of                 = 2026-08-01               # the date age is counted on
  age_min                   = 20
  age_max                   = 28
  age_born_from             = 1998-08-02               # the same limits as birth dates
  age_born_to               = 2006-08-01
  age_relaxation_cumulative = 'unknown'                # 'yes' | 'no' | 'unknown'
  age_relaxation_max_age    = 'none'                   # upper age after all relaxations; or 'none'

    [[eligibility.age.relaxations]]        # as the notice states them
    relaxation_category = 'OBC-NCL'
    relaxation          = '+3'

    [[eligibility.age.relaxations]]
    relaxation_category = 'SC'
    relaxation          = '+5'

    [[eligibility.age.relaxations]]
    relaxation_category = 'PwBD + SC'
    relaxation          = '+15'

    [[eligibility.age.relaxations]]
    relaxation_category = 'Ex-Servicemen'
    relaxation          = '+3 - military_service'   # '+N' | '+N - <deduction>' | '= N' | 'no_limit' | '+N, max M'

    [[eligibility.age.age_by_category]]    # worked out; shown to readers
    age_category  = 'Unreserved'
    age_min       = 20
    age_max       = 28
    age_born_from = 1998-08-02
    age_born_to   = 2006-08-01

    [[eligibility.age.age_by_category]]
    age_category  = 'SC'
    age_min       = 20
    age_max       = 33
    age_born_from = 1993-08-02
    age_born_to   = 2006-08-01

  # ── what you have done ──
  [eligibility.education]
  applies           = 'yes'
  education_options = [                    # any one option; everything inside it
    ['Graduation (any discipline)'],
  ]
  education_held_by     = 2026-08-21       # the "crucial date"; or 'unknown'
  education_final_year  = 'no'             # can final-year students apply? 'yes' | 'no' | 'unknown'
  education_passed_from = 'none'           # year of passing, from (JEE: 2024); or 'none'
  education_passed_to   = 'none'
  education_equivalent  = 'yes'            # "or equivalent" accepted? 'yes' | 'no' | 'unknown'
  education_desirable   = 'none'           # 'none' or [qualifications that help but are not required]

    [[eligibility.education.education_marks]]
    marks_qualification = 'Graduation (any discipline)'
    marks_category      = 'all'
    marks_min           = 'none'               # a number, or 'none'
    marks_unit          = 'none'               # 'percent' | 'cgpa' | 'class' | 'percentile' | 'none'
    marks_out_of        = 'none'               # CGPA scale (10, 4), or 'none'
    marks_counted_on    = 'none'               # 'aggregate' | 'each_subject' | 'none' | ['Physics', 'Chemistry', ...]

  [eligibility.prior_exam]
  applies            = 'no'
  prior_exam_options = 'none'              # 'none', or blocks as below
  # when it applies, one block per option (any one is enough):
  #   [[eligibility.prior_exam.prior_exam_options]]
  #   prior_exam          = 'in-jee-main'  # catalogue exam id: links to that exam's page
  #   prior_exam_years    = [2027]         # or 'any_valid'
  #   prior_exam_papers   = ['Paper 1']    # 'any' | 'matching_discipline' | ['CE', 'ME', ...]
  #   prior_exam_needs    = 'rank_within'  # 'appeared' | 'qualified' | 'valid_score' | 'rank_within'
  #   prior_exam_rank_max = 250000         # or 'none'
  #
  #     [[eligibility.prior_exam.prior_exam_options.rank_by_category]]
  #     rank_category = 'OBC-NCL'
  #     rank_share    = 27                 # percent of prior_exam_rank_max; one row per category, or 'none'

  [eligibility.certificates]
  applies               = 'no'
  certificates_required = 'none'           # 'none', or blocks as below
  # when it applies, one block per certificate; all are required:
  #   [[eligibility.certificates.certificates_required]]
  #   certificate       = 'CCC (NIELIT)'   # from qualifications.toml
  #   certificate_speed = 'none'           # words per minute (typing, shorthand), or 'none'

  [eligibility.registration]
  applies                = 'no'
  registrations_required = 'none'          # 'none', or blocks as below
  # when it applies, one block per registration; all are required:
  #   [[eligibility.registration.registrations_required]]
  #   registration_with  = ['State Medical Council', 'National Medical Commission']  # any one; from a councils list
  #   registration_scope = 'any_state'       # 'this_state' | 'any_state' | 'national'
  #   registration_valid = 'yes'             # must be kept valid / renewed?
  #   registration_when  = 'before_applying' # 'before_applying' | 'before_joining'

  [eligibility.experience]
  applies             = 'no'
  experience_required = 'none'             # 'none', or blocks as below
  # when it applies, one block per requirement; all are required:
  #   [[eligibility.experience.experience_required]]
  #   experience_years     = 3               # 0.5 allowed
  #   experience_in        = ['Teaching', 'Research']   # any one; a field or a post; growing list
  #   experience_sector    = 'any'           # 'any' | 'government' | 'psu' | 'private'
  #   experience_counted   = 'after_qualification'      # 'after_qualification' | 'any'
  #   experience_desirable = 'no'            # 'yes' = helps, not required
  #   experience_relaxable = 'unknown'       # relaxable for SC/ST, PwBD? 'yes' | 'no' | 'unknown'

  [eligibility.language]
  applies = 'yes'

    [[eligibility.language.languages_required]]
    language           = ['Hindi']           # any one
    language_level     = 'working_knowledge' # 'working_knowledge' | 'read_write_speak' | 'passed_as_subject'
    language_passed_at = 'none'              # '10th' | '12th' | 'none'
    language_script    = 'any'               # 'Devanagari' | ... | 'any'
    language_when      = 'before_applying'   # 'before_applying' | 'test_after_selection'

  # ── your body ──
  [eligibility.physical]
  applies            = 'no'
  physical_standards = 'none'              # 'none', or blocks as below
  # when it applies, one block per table row the notice prints (group × gender):
  #   [[eligibility.physical.physical_standards]]
  #   physical_gender   = 'Male'
  #   physical_for      = 'all'            # 'all' or ['Garhwali', 'Gorkha', 'North-East states', 'ST', ...]
  #   height_cm         = 170
  #   chest_cm          = 80               # or 'none'
  #   chest_expanded_cm = 85               # or 'none'
  #   weight            = 'proportionate_to_height_and_age'   # kg, this phrase, or 'none'

  [eligibility.medical]
  applies                = 'no'
  vision_better_eye      = 'none'          # e.g. '6/6', or 'none'
  vision_worse_eye       = 'none'
  vision_glasses_allowed = 'unknown'       # 'yes' | 'no' | 'unknown'
  colour_blind_allowed   = 'unknown'       # 'yes' | 'no' | 'unknown'
  defects_barred         = 'none'          # fixed list: ['knock_knees', 'flat_foot', 'squint', ...] or 'none'
  tattoos_allowed        = 'unknown'       # 'yes' | 'no' | 'restricted' | 'unknown'
  medical_category       = 'none'          # e.g. 'SHAPE-1', or 'none'
  medical_guidelines     = 'none'          # a named standard, or 'none'

  [eligibility.disability]
  applies               = 'yes'
  disability_suitable   = ['B', 'LV', 'HH', 'OA', 'OL', 'BL']   # RPwD Act codes; 'none' = not suitable
  disability_functional = 'none'           # functional needs (S sitting, W walking, ...), or 'none'

  # ── your record ──
  [eligibility.employment]
  applies                       = 'no'
  employment_noc_needed         = 'none'      # 'at_application' | 'at_interview' | 'none' | 'unknown'
  employment_via_employer       = 'no'        # apply through proper channel
  employment_resign_if_selected = 'no'
  employment_serving_only       = 'no'        # departmental exams
  employment_service_years      = 'none'      # years of service needed
  employment_service_in         = 'none'      # the post or cadre that service must be in

  [eligibility.character]
  applies          = 'unknown'
  character_checks = 'unknown'               # list from: 'no_conviction' | 'no_pending_case' | 'not_dismissed'
                                             # | 'not_debarred' | 'character_certificate' | 'police_verification'

  # ── your limits ──
  [eligibility.attempts]
  applies          = 'no'
  attempts_counted = 'none'                  # 'attempts' | 'consecutive_years' | 'none'

    [[eligibility.attempts.attempts_by_category]]
    attempts_category = 'all'
    attempts_max      = 'unlimited'         # a number, or 'unlimited'

  # ── proof ──
  [eligibility.category_proof]
  applies = 'yes'

    [[eligibility.category_proof.category_certificates]]
    certificate_category     = 'OBC-NCL'
    certificate_issued_after = 2026-04-01   # or 'none' / 'unknown'
    certificate_income_year  = 'none'       # e.g. '2025-26' for EWS
    certificate_list         = 'central'    # 'central' | 'state' | 'unknown'

    [[eligibility.category_proof.category_certificates]]
    certificate_category     = 'EWS'
    certificate_issued_after = 'unknown'
    certificate_income_year  = '2025-26'
    certificate_list         = 'central'

  # ── anything else ──
  [eligibility.other]
  applies     = 'no'
  other_rules = 'none'                     # the notice's words, verbatim; reviewed to grow the fixed lists

# ═══ fee ═══════════════════════════════════════════════════════════
[fee]
fee_refundable         = 'no'                # 'yes' | 'no' | 'unknown'
fee_bank_charges_extra = 'yes'               # gateway charges on top; or 'no' / 'unknown'
fee_payment_modes      = ['net_banking', 'card', 'upi']

  [[fee.rows]]
  fee_category = 'Unreserved'                # from the vocabulary, never merged; or 'all'
  fee_gender   = 'all'                       # 'all' | 'male' | 'female' | 'transgender'
  fee_posts    = 'all'
  fee_stage    = 'all'                       # or a stage_number
  fee_rupees   = 850                         # 0 = exempt
  fee_per      = 'application'               # 'application' | 'post' | 'paper' | 'test_date' | 'attempt' | 'correction'
  fee_includes = ['GST']                     # 'GST' | 'intimation_charges' | 'service_charges'; or 'none'

  [[fee.rows]]
  fee_category = 'SC'
  fee_gender   = 'all'
  fee_posts    = 'all'
  fee_stage    = 'all'
  fee_rupees   = 175
  fee_per      = 'application'
  fee_includes = ['GST']

# ═══ exam-wide rules ═══════════════════════════════════════════════
[exam_rules]
# ── centres ──
centre_places         = ['all_india']        # or states or cities from the vocabulary
centre_choice         = 'ranked'             # 'ranked' | 'single' | 'none' | 'unknown'
centre_choices_max    = 3                    # or 'none' / 'unknown'
centre_allotment      = 'availability'       # 'availability' | 'first_come' | 'random' | 'unknown'
centre_guaranteed     = 'no'                 # 'no' = the body may move you elsewhere
centre_change_allowed = 'no'                 # after applying

# ── sitting the exam, and merit ──
scribe_allowed                = 'yes'        # 'yes' | 'no' | 'unknown'
scribe_extra_minutes_per_hour = 20           # or 'none' / 'unknown'
scores_normalised             = 'yes'        # 'yes' | 'no' | 'unknown'
tie_break_order               = ['age_older', 'marks_in_part:Reasoning Ability']   # steps in order, from a vocabulary; or 'unknown'
training_offered_for          = 'none'         # categories offered pre-exam training; or 'none' / 'unknown'

# ═══ links ═════════════════════════════════════════════════════════
[links]
link_official_page = 'https://www.ibps.in/crp-clerks-xvi/'   # or 'unknown'
link_apply         = 'https://ibpsreg.ibps.in/crpcl16jun26/'  # or 'not_announced'

  [[links.documents]]
  document_type      = 'notification'        # 'notification' | 'corrigendum' | 'schedule' | 'admit_card' | 'answer_key'
                                             # | 'result' | 'press_release' | 'calendar' | 'syllabus' | 'brochure' | 'other'
  document_stage     = 'all'                 # or a stage_number
  document_published = 2026-08-01            # or 'unknown'
  document_url       = 'https://www.ibps.in/wp-content/uploads/CRP-CSA-XVI.pdf'
  document_archive   = 'not_archived'        # Wayback copy, or 'not_archived'

# ═══ provenance (never shown) ══════════════════════════════════════
[provenance]
provenance_retrieved    = 2026-09-27T19:36:16+05:30
provenance_last_checked = 2026-09-30T06:00:00+05:30

  [[provenance.evidence]]
  evidence_field    = 'dates.application.to'
  evidence_document = 'https://www.ibps.in/wp-content/uploads/CRP-CSA-XVI.pdf'   # a links.documents URL
  evidence_page     = 3
  evidence_words    = 'Closure of registration of application: 21.07.2026'
  evidence_method   = 'table'                # 'rule' | 'table' | 'model' | 'manual'
+++
```
