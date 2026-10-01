# ExamHub — exam record field reference

Canonical schema for one exam per page. This file is the agreement: what a
record may contain, what each key means, and where each one renders.

Scope: **upcoming Indian exams**. This is a reference for what is happening
with an exam right now — not an archive, not a preparation portal.

Replaces an earlier brainstorm list in which the same fields appeared four or
five times across appended drafts, several section headings had been swallowed
into body text, and the closing advice ("aim for 25–30 canonical fields rather
than endlessly adding fields") contradicted the 40-plus field lists around it.
The reasoning behind the current decisions is kept in §10 so it does not have to
be re-derived.

---

## 1. Conventions

**Absent means absent.** A key that is not present is not rendered. No blanks,
no `TBA`, no "Not applicable". If a body does not publish something, the field
simply is not there. This is what lets one schema cover a national commission
and a single-post district notice without either looking broken.

**Dates are `YYYY-MM-DD`.** Anything coarser than a day (`Autumn 2026`) is not
a date and does not go in a date field. It goes in prose. Dotted forms
(`2026.10.04`) are not valid TOML dates and are never stored; the display
format is `2026, October 04`, with a zero-padded day so a column of dates
aligns. One display format only — a short form was considered and dropped as a
second format with no consumer.

**Every date has an explicit status.** Each date key has a sibling
`<key>_status` holding `confirmed` or `provisional`. There are no nulls and no
empty values: a stored date always states whether the body has fixed it.

```toml
exam_date = 2026-10-04
exam_date_status = 'provisional'
```

A *provisional* date is one the body has published but not fixed — an NTA
"proposed" calendar, a state's "Tentative Schedule of Examinations". It renders
as `Provisional: 2026, October 04` in the provisional colour, and its countdown
is suppressed: a live ticking number implies a settled plan.

**A date the body has not published at all is simply absent.** The two cases are
different and the difference matters. "13 December, provisional" is real
information a candidate wants. "No date yet" is not a date.

**Free text is Markdown**, rendered through `markdownify`. Multi-line values use
TOML `'''` blocks.

**Labels match what people search for.** Users search "last date to apply", not
"registration deadline". Field *keys* are snake_case; field *labels* are the
words shown on the page, and those follow portal convention.

**Timestamps are RFC 3339 with an offset**, `2026-09-27T14:32:11+05:30`, unlike
the date fields above which are plain `YYYY-MM-DD`. The distinction is
deliberate: a date is a fact about the world, while a timestamp is a fact about
our having looked at it, and only the second one needs an instant and a zone.
See §2.8.

**Never store an estimate as a fact.** Cut-offs and vacancies carry a source
tier. See §8.

---

## 2. Field reference

`Status` — `live` renders today, `planned` is agreed but not yet built.

### 2.1 Identity

| Label | Key | Type | Status | Notes |
|---|---|---|---|---|
| Exam name | `title` | string | live | Required. Plural, full official form |
| Also known as | `known_as` | list | live | `['NEET', 'NEET UG']`. Fed into the search index and the filter bar's text match |
|

**The key is `known_as` and not `aliases`, which is a trap.** `aliases` is Hugo's
own front-matter key for URL redirect stubs, so a record carrying
`aliases = ['NEET']` does not store a search term — it makes Hugo emit a
redirect page for `/exams/<slug>/neet/`. Adding the key to 178 records silently
produced 314 stub pages while the page count stayed at 639, which is exactly the
kind of thing a count-based check does not catch. The field is spelled out here
so the next person does not have to rediscover it.
| Summary | `summary` | string | live | One line, under the title |
| Description | `description` | string | live | Meta description for the page head |
| Conducting body | `bodies` | taxonomy | live | The body that runs the exam, not the one that hires you. See §3 |
| Category | `categories` | taxonomy | live | `Government`, `Private`, `Academic`… |
| Type | `exam_kind` | enum | planned | `job` \| `admission`. Decides which outcome shape applies |
| Official website | `official_url` | url | live | |

Exam level (national / state / university) is deliberately **not** a field. The
conducting body already implies it — "Bihar State PSC" is the scope. If
browse-by-level is ever wanted, add a value to `categories` and the taxonomy
page appears for free.

### 2.2 What the exam leads to

One exam can lead to a job, to an admission, to an eligibility, or to a
fellowship — and sometimes to a choice between several. A flat "leads to" list
cannot express any of that, so outcomes are typed.

```yaml
outcomes:
  - type: post              # job | admission | eligibility_only | fellowship
    authority: UPSC         # the body that converts your score. May be null
    self_allocated: true    # true when the exam body does it itself
    posts: [IAS, IPS, IFS]  # type: post
    vacancies: 933
  - type: admission
    authority: JoSAA        # NOT the exam body — NTA does not admit you
    rank_consumed: CRL
    seat_total: 67323
    institute_count: 127
    seat_matrix_url: '...'  # the real rows live here, never in front matter
  - type: eligibility_only
    grants: [Assistant Professor]
  - type: fellowship
    grants: [JRF, Rs 37,000/month]
    exclusive_tiers: true   # see below
```

| Label | Key | Type | Status | Notes |
|---|---|---|---|---|
| Type | `exam_kind` | enum | planned | |
| Outcomes | `outcomes` | list | planned | The block above |
| Vacancies | `vacancies` | int | planned | |
| Vacancies final? | `vacancies_final` | bool | planned | Boards often publish "tentative only" |
| Posts | `posts` | list | planned | For notices covering several posts at once |
| Selection process | `selection_method` | enum | planned | See below |

`selection_method`:
`written` · `written+interview` · `merit_marks` · `lottery` · `skill_test` ·
`walk_in` · `merit+interview`

The last four exist because a meaningful number of "exams" have no written test.
India Post GDS is merit on Class 10 marks. Rajasthan's Safai Karmachari drive is
a lottery on work experience. A page titled as an exam with an empty
`exam_dates` is misleading, so `has_written_exam` gates that.

**`exclusive_tiers`** matters for exams that award bundles rather than a single
outcome. UGC NET Dec 2025 assigned candidates to one of three mutually
exclusive tiers — JRF + Assistant Professor (5,108), Assistant Professor + PhD
(54,713), or PhD only (117,058) — decided by a per-subject cut-off. A list
would wrongly suggest you get all three.

**`authority: null` is a real value, not missing data.** CAT has no central
counselling: each of 21 IIMs and 1,200 other institutions sets its own
shortlist. Writing "IIM Calcutta" as an outcome would be a category error — CAT
is *conducted by* a rotating convenor IIM, which is not the same thing.

### 2.3 Eligibility

| Label | Key | Type | Status | Notes |
|---|---|---|---|---|
| Eligibility criteria | `eligibility` | text | live | Prose. Category detail goes here |
| Age as on | `age_as_on` | date | planned | Required with any age limit |
| Attempts allowed | `attempts` | text | planned | `6` · `unlimited (SC/ST)` · `not applicable` |
| Domicile / residency | `domicile` | text | planned | Hard gate at state level |
| Out-of-state treatment | `other_state_treatment` | text | planned | |

**`age_as_on` is not optional decoration.** Bodies use different reference dates
— Mizoram 1 Aug 2026, MP Police SI 23 Sep 2026, UP Anganwadi 1 Jul 2026, NIFT
`<24 as on 1 August of the admission year`. "18–40" without the reference date
is not a usable statement.

**`other_state_treatment`** appears in one buried clause and changes who should
apply: "Applicants from outside Madhya Pradesh can apply only under the
Unreserved category", "Candidates belonging to States outside Telangana will be
treated as General Category irrespective of their reservation".

Age limits vary by category and often stack, so age stays prose inside
`eligibility` rather than becoming a structured table. Reservation percentages
likewise stay prose for now — see §9.

### 2.4 Application

| Label | Key | Type | Status | Notes |
|---|---|---|---|---|
| Registration opens | `registration_open` | date | live | |
| Last date to apply | `registration_deadline` | date | live | |
| Fee | `[[fee]]` | list | live | One row per category. See below |
| Fee basis | `fee_basis` | enum | live | `per_form` \| `per_group` \| `per_post` \| `per_paper` |
| Fee caveats | `fee_note` | text | live | Refunds, methods, late fees, domicile gates |
| Payment deadline | `payment_deadline` | date | planned | Genuinely separate from the apply deadline |
| Correction window | `correction_window` | `{from, to}` | planned | One range. Distinct from the list rule |
| Deadline revisions | `deadline_revisions` | list | planned | `{date, notice_url, kind}` |
| Application mode | `application_mode` | enum | planned | `online` \| `offline` |

**Use "Last date to apply" as the label.** It is the most-searched phrase in
this niche. "Registration deadline" is a Western job-board mistranslation and
almost nobody here searches it.

**`payment_deadline` earns its own key** because candidates get burned by it
constantly. SSC CGL 2025 closed applications 04 Jul with fees due 05 Jul. JoSAA
closes choice filling at 17:00 but takes fee payment until a later hour.

**`deadline_revisions` is a list, not a value.** Roughly 30% of large exams
extend, and extension always arrives as a *separate dated notice* — often
printing an `Earlier Date | Extended Date` table, sometimes on the closing day
itself. Overwriting the date silently loses the fact that it moved, which is
the thing candidates most want to know.

Every date in this group carries a `_status` sibling: `registration_open_status`,
`registration_deadline_status`, `admit_card_from_status`,
`admit_card_to_status`, `result_date_status`, `exam_date_status`.

#### 2.4a The fee matrix

A fee is a mapping from candidate category to amount, so it is stored as one
and rendered as a table — always, even when the notice states a single rate,
in which case it is one row. A sentence doing that job at once is exactly why
candidates misread it.

```toml
fee_basis = 'per_form'
fee_note = 'Haryana domicile is required for the reduced rate.'

[[fee]]
category = 'General'
amount = 1000

[[fee]]
category = 'PwBD'
amount = 0
note = 'Exempt'
```

| Key | Type | Notes |
|---|---|---|
| `category` | enum | From the controlled list below. Omit if the class is not national |
| `label` | text | The notice's own wording, used when `category` is absent or differs |
| `amount` | integer | Rupees. `0` renders as `Nil` |
| `gender` | enum | `Male` \| `Female`, only where the notice splits by gender |
| `note` | text | "Exempt", "Of Haryana", and similar per-row qualifiers |

**One row per category, never a lumped row.** A notice reading "Rs 850 for all
others, Rs 175 for SC/ST/PwBD/ESM" becomes four rows. The point of the table is
that a candidate can find their own row.

**The controlled category list.** Values are the ones in use, not every value
conceivable:

| Value | Meaning |
|---|---|
| `General` | Unreserved. Aliases in notices: UR, Gen, General/Unreserved |
| `OBC` | Other Backward Classes, as the notice's body uses the term. See the note below — this does **not** imply a creamy-layer exclusion |
| `OBC-NCL` | Other Backward Classes not in the creamy layer. A distinct value, not a synonym of `OBC` |
| `EWS` | Economically Weaker Sections |
| `SC` | Scheduled Castes |
| `ST` | Scheduled Tribes |
| `PwBD` | Persons with Benchmark Disabilities. The current statutory term; notices and reservation certificates still say PwD, which is a legacy alias, not a separate value |
| `Ex-Servicemen` | Note the notice spelling varies; DESM is a sub-class, not a peer |
| `All candidates` | A single rate for everyone, whatever it is called |
| `Women` | A rate that applies to women candidates as such. Distinct from `gender`, which qualifies a row rather than naming a group |
| `Transgender` | |

**`OBC` and `OBC-NCL` are two values, and the site must not merge them.**

They look like a redundancy, and for a central body they are one: the Central
OBC List already excludes the creamy layer, so a UPSC or NTA notice that says
"OBC" means non-creamy layer, and "OBC-NCL" there says the same thing at more
length. That is why an earlier draft of this document merged them.

The merge is wrong, and the corpus shows why. Of the 65 records carrying a fee
row for this class, **16 belong to central or university bodies and 49 to state
bodies or district courts** — Bihar STET, Jharkhand, Karnataka, Kerala, UP,
Haryana, Himachal, and a large share of district-court recruitment. Several of
those jurisdictions grant OBC benefits *including* the creamy layer, and several
do not apply a creamy-layer restriction to lower-service or district posts at
all. So for those 49 records "OBC" is not a synonym for "OBC-NCL"; the two
denote different populations, and which one applies is a fact about the
notifying body.

Collapsing them had two costs. It lost the ability to say "non-creamy layer
only" at all, since `OBC` was by then the only spelling. And it made the 49
state records ambiguous: a candidate reading "OBC ₹600" on a Bihar notice had
no way to tell whether a creamy-layer OBC candidate is covered, because the
vocabulary no longer contained the distinction. Normalising a jurisdiction-
dependent term into a single value is worse than storing the two spellings.

**What the site does instead:** store what the notice said. `OBC` means that
body's OBC, whatever that body means by it; `OBC-NCL` means it drew the
line. Where a state body splits its own backward class further, that is a
different problem and `label` handles it — Haryana's BC-A/BC-B is recorded as
`OBC-NCL` with a note naming the Haryana classes, because it *is* a
non-creamy-layer class; Rajasthan's Backward Classes is recorded as a `label`,
because it is a sibling of Rajasthan's OSC rather than a sub-class of it, and
asserting more than the notice says would be a guess.

`PwD` remains a normalisation, and on different grounds: it is not a second
category but the pre-2016 abbreviation of one, superseded by "benchmark
disability" in the current statute. `All` becomes `All candidates` because a
bare "All" in a Category column reads as a value rather than as "everyone".

`DESM`, `Minorities` and `EBC` are legitimate fee-relevant classes and are
available, but no current record charges them separately.

**Never use `PwBC` or `PwH`.** Neither is an Indian reservation class. `PwBC`
("Backward Class" persons with disabilities) is not a category in any
central or state roster, and `PwH` ("Physically Handicapped") is the pre-2016
wording, superseded by benchmark disability. Both were briefly present in the
vocabulary, unused, and have been removed rather than left as empty entries
waiting for a record to misuse them.


**`label` is how a state class is recorded.** Rajasthan's Economically Backward
Class is a class of its own, distinct from Other Backward Classes, and carries
a different rate; the same is true of Rajasthan's Backward Classes and of
Haryana's BC-A/BC-B against its OSC. Collapsing those into `OBC` produces a
table where two different rates both sit under the heading "OBC", which is
worse than useless. So:

```toml
[[fee]]
category = 'OBC'
amount = 600

[[fee]]
label = 'Rajasthan Economically Backward Class'
amount = 400
```

A row may set both `category` and `label`, when a state class is close enough
to a national one to be worth filtering on but not close enough to be shown
under the national name. A row with neither fails the build.

### 2.4b Admit card

An admit card is not a date, it is a **state**. That is the whole design
decision, and it comes from counting the records: only 16 of 310 carry an
`admit_card_from`, none carry an `admit_card_to`, and none carry an
`admit_card_url` — but 83 mention an admit card somewhere in prose. A
schema built out of dates therefore answers the question for 16 records
and stays silent on the other 294, when in fact most of them have
something to say ("the admit card is issued two days before the
examination") and a few have something urgent to say (it is out, or it was
withdrawn).

```toml
admit_card_status = 'announced'      # not_announced | announced | released | delayed | withdrawn
admit_card_from = 2027-04-20         # only when a real day exists
admit_card_from_status = 'confirmed' # the same convention as every other date
admit_card_to = 2027-05-15
admit_card_to_status = 'confirmed'
admit_card_url = 'https://…'         # a plain URL, only while the card is live
admit_card_note = 'Issued 2-3 days before each candidate own exam date'
```

| Label | Key | Type | Status | Notes |
|---|---|---|---|---|
| Admit card state | `admit_card_status` | enum | live | Always present when the block renders |
| Available from | `admit_card_from` | date | live | First day the card can be downloaded |
| Available to | `admit_card_to` | date | live | Closes. Rare — most cards do not expire |
| Rule / limit | `admit_card_note` | text | live | Where a published rule goes when no day does |

**Five states, and they are not a progression.**

| State | Means |
|---|---|
| `not_announced` | the body has said nothing about the card for this cycle |
| `announced` | it has published when the card comes out |
| `released` | the card is out; `admit_card_url` normally points at it |
| `delayed` | a published card, or a published date, has been pushed back |
| `withdrawn` | a card was issued and then cancelled or declared invalid |

`delayed` and `withdrawn` have no records yet, which is a fact about the
data rather than about the model. NEET (UG) 2026 is the case the last one
exists for: the examination of 3 May 2026 was cancelled over a paper leak,
a fresh admit card was issued, and the re-examination was held on 21 June
2026 with the original card explicitly declared invalid.

**`not_announced` is what an absent key means, and is never written.** The
first rule of this document — absent means absent — points the other way
here just as firmly. Stamping `not_announced` on all 310 records would put
a block on every page in the site announcing the absence of a thing, which
is the same mistake as rendering `TBA`. A record that says nothing about
its admit card says nothing, and renders nothing.

**The date is optional; the state is not.** A great many bodies publish a
rule or a window instead of a day — "seven days before the date of
examination", "four days before each paper", "in the month of November",
"two weeks before the test". Those records get `announced`, **no date keys
at all**, and the rule in `admit_card_note`. The day is never derived from
the rule. A window that coarse is not a date, and §1 already says a
coarser-than-a-day fact does not go in a date field; inventing 2026-10-09
from "seven days before" when the exam date is itself a range would be
false precision in a field whose whole point is that it is not.

**A body's "tentative" is `provisional`.** RUHS's Information Booklet
records a tentative date of 8 December 2026 for printing the admit card;
that is `admit_card_from_status = 'provisional'` and it renders through
`date.html` like any other provisional date, so it keeps the literal
`Provisional:` word and the dashed treatment instead of leaning on a pill.

**A card is not a milestone, so it is not in the timeline.** The two dates
still appear in `key-dates.html` under the labels "Admit card available"
and "Admit card closes", where `exam-status.html` can use them to compute
the page's status. The state renders in its own block directly beneath,
because "not issued yet" is a fact about now and the timeline can only
express milestones that are still ahead.

### 2.5b Pay

Pay is a labelled section on the page, not prose, because 154 of the 209
records are job exams and pay is one of the first things a candidate checks.
Only 21 records have it populated so far — that is a gap, not a design limit.

```toml
[pay]
system = 'pay_matrix'    # 'pay_matrix' | 'scale'
level = [2, 3]           # pay_matrix; a list, because one exam can span levels
grade = 'E1'             # PSU grade, optional
low = 69250              # rupee lower bound
high = 134200            # rupee upper bound
initial = 60000          # starting basic pay, where the notice separates it

[[pay.posts]]            # only when a notice sets a different scale per post
name = 'Police Constable'
low = 21700
high = 69100
```

**Three vocabularies are in play and all three are real.** Central bodies use
7th CPC **Pay Matrix levels** ("Level 7"). States use **rupee ranges**
("₹69,250 to ₹1,34,200"). PSUs use a **grade plus a range plus an initial
basic pay** ("E-1 Grade on ₹60,000-1,80,000 with an initial basic pay of
₹60,000"). A pre-7th-CPC form also turns up occasionally ("Pay Scale Rs 6 to
Rs 11, Grade Pay 4,200").

**`level` is a list, not a scalar**, because one exam can span levels — RRB
NTPC carries "Pay Level 2 and 3". **Pay is per-post, not per-exam**: one SSC
CGL notice covers posts at Level 4 and Level 7, and Odisha Police sets
₹21,700–69,100 for constables against ₹35,400–1,12,400 for sub-inspectors in
the same advertisement. `posts[]` carries that; a single figure would be wrong.

The verbatim sentence stays in `eligibility`. This is the filterable summary of
it, not a replacement.

### 2.5 Stages and exam structure

Most exams are not one sitting. Prelims, Mains and Interview each have their own
admit card, result and cut-off. Admission exams add allocation rounds — but
those belong to `outcomes`, because a different body runs them.

```yaml
stages:
  - slot: primary
    official_name: 'Preliminary Examination'
    exam_dates: ['2027-05-23']
    admit_card_from: 2027-04-20
    admit_card_to: 2027-05-15
    result_date: 2027-06-05
    duration: '2 days, 2 papers of 3 hours each'
    negative_marking: '1/3 of the marks assigned for each wrong answer'
    max_marks: 400
    total_questions: 200
  - slot: interview
    official_name: 'Personality Test'
```

| Label | Key | Type | Status | Notes |
|---|---|---|---|---|
| Exam date | `exam_date` | date | live | Scalar today. Superseded by `exam_dates` |
| Exam date | `exam_dates` | list | planned | **Replaces the scalar above**, once templates change |
| Shifts per day | `num_shifts` | int | planned | SSC 4 · CAT 3 · most NTA exams 1–2 |
| Exam mode | `mode` | text | live | `Offline`, `CBT`, `OMR` |
| Exam duration | `duration` | text | live | |
| Negative marking | `negative_marking` | text | live | |
| Venue / centres | `venue` | text | live | |
| Stages | `stages` | list | planned | The block above |
| Date notes | `date_notes` | map | live | Milestone label → note, shown under the timeline row |

`exam_date` stays live until `exam_dates` is built — the scalar is still what
`exam-status.html`, `exam-card.html` and the JSON search index read, so a record
cannot be migrated one key at a time. Migrate it with the stage work, not
before.

**Canonical slots:** `primary` · `secondary` · `physical` · `skill` ·
`interview` · `medical` · `document_verification`

Every body names its own stages — Tier I, Prelims, Oral Test, Main Written
Examination, and Tamil Nadu's "PCV". So each stage carries **both** a canonical
`slot` for filtering and an `official_name` preserved verbatim for display.
Filter by slot; show the body's words.

Mapping used when assigning a slot: Tier I / Prelims / "Common Preliminary
Examination Stage I of III" → `primary`. Mains / Main Written Examination →
`secondary`. Physical Standards Test, Physical Efficiency Test → `physical`.
Data Entry Speed Test, typing, shorthand → `skill`. Oral Test, Personality
Test → `interview`. PCV, document verification → `document_verification`.

**Allocation rounds are not stages.** JoSAA Round 1–5 and MCC rounds are
consumed under `outcomes`, since JoSAA — not NTA — runs them. A JEE candidate
tracks roughly 50 dated counselling deadlines, which is a different thing from
an exam stage and should not pollute `stages`.

**Negative marking stays text**, deliberately. It is not a scalar. PSSSB Clerk
2026 has none in Part A and −1/4 in Part B. SSC MTS is zero in Session I and −1
in Session II. MPPSC introduced negative marking for the first time in 2026.
The prose is what candidates need, and it changes without notice.

### 2.6 Results

| Label | Key | Type | Status | Notes |
|---|---|---|---|---|
| Result date | `result_date` | date | live | |
| Cut-off | `cutoff` | list | planned | `{value, category, stage, year}` |

`cutoff` holds the **previous cycle's official** cut-off, labelled with the year
and category it came from. Not a prediction, not a coaching estimate.

Coaching portals guess wrong by large margins on this. For SSC CGL 2025 Tier I
General, portals predicted 154–157 against an actual 136.83. One recurring
error publishes a *college seat* cut-off as though it were the *qualifying*
cut-off — 670–680 against a real qualifying mark of 144. Neither is the same
number as the other, which is why estimated values are not stored at all.

**A published cut-off is not a threshold.** UPSC's own cut-off PDF describes
"the minimum qualifying standards/marks secured by the last recommended
candidate". It is a description of where the last person happened to land, not
a line you must clear. Do not render it as "you need 92.66".

### 2.7 Official links

Link the specific document, not a homepage. A candidate wants the notification
PDF, not the portal.

| Label | Key | Status |
|---|---|---|
| Official notification | `official_url` | live |
| Application / registration | `apply_url` | live |
| Syllabus | `syllabus_url` | live |
| Admit card | `admit_card_url` | live |
| Result / scorecard | `result_url` | live |

`syllabus_url` should usually point at a notification PDF. Portals routinely
have no syllabus for an upcoming exam and copy the prior year's — the official
document is the honest link.

**Some exams have no linkable official source.** District notices often live on
the government CDN at timestamped filenames that get replaced, some exist only
as a newspaper advertisement, and some as a notice photographed on a district
office board. When no URL exists, record the source in `provenance` with
`source_type` and no `source_url`. Do not invent one.

### 2.8 Provenance

What makes this site trustworthy where others are not: every record says where
its data came from and when it was last checked, so a stale entry looks stale
rather than quietly wrong.

```toml
[provenance]
source_url = 'https://upsc.gov.in/examinations/active-exams'
source_doc = 'UPSC Active Examinations page'
timestamp_retrieved = '2026-09-20T14:32:11+05:30'
timestamp_last_checked = '2026-09-27T09:04:52+05:30'
source_tier = 'notification_pdf'
```

| Key | Type | Notes |
|---|---|---|
| `source_url` | url | Absent when no linkable official source exists. Never invented |
| `source_doc` | text | What the document is, precisely enough to find it again |
| `timestamp_retrieved` | date \| datetime | When the source was fetched |
| `timestamp_last_checked` | date \| datetime | When a human last compared the record against it |
| `source_tier` | enum | See below |

#### Timestamps: precision must be earned

`timestamp_retrieved` and `timestamp_last_checked` accept **either** a bare
date (`2026-09-27`) **or** a full RFC 3339 datetime with an offset
(`2026-09-27T14:32:11+05:30`). A bare date means exactly one thing: *the day
is known and the time of day was not recorded.*

**All 310 records currently hold bare dates**, all of them `2026-09-27`, and
that is the whole of what is known. This is not a formatting shortcut. It was
tried the other way round first — every record was migrated to
`T00:00:00+05:30` on the argument that midnight is a conventional day-start
marker — and that was wrong, for a reason worth recording.

A field where all 310 values are identical and equal to midnight carries
**one bit of information: the timezone.** It looks like a machine-readable
instant and is not one, and it is strictly worse than the bare date it
replaced, because a bare date is honestly day-shaped and a midnight timestamp
implies an hour that was never measured. The only per-record time evidence that
existed was file modification time, and that was destroyed: the schema
migrations, the fee rewrite, the admit-card backfill and the vocabulary work
all rewrote all 310 files on the same day the records were authored, so every
mtime now says "today" regardless of when the source was actually fetched. The
pipeline had never run against them either — it has only ever run a 26-row
field-extraction dev set, with no time fields in it.

So the rule is: **the site records the precision it has, and the pipeline must
earn the rest.** When the re-checker actually fetches a source it writes a full
RFC 3339 instant, because then it knows the instant. Nothing in the site
fabricates one, and a `T00:00:00` appearing in future output is a bug in
whichever component wrote it, not a legacy value to be tolerated.

**Why the key names carry a `timestamp_` prefix when the value is often just a
date.** They are prefixed to mark these as machine-readable provenance about
*our having looked*, distinct from the exam's own dated fields, which are facts
about the world. The exam date fields are strict `YYYY-MM-DD`; these are not,
and the prefix is what tells a reader which is which before they look at the
value.

**Why RFC 3339 rather than Unix time, for the records that do get a real
instant.** These files are read and reviewed by people, and a reviewer is the
bottleneck in this pipeline, not a parser. A git diff of `1789245131` tells a
reviewer nothing; a diff of `2026-09-27T14:32:11+05:30` tells them exactly what
changed. Unix is the right answer for a machine log and the wrong one here.

**Why the offset is explicit when an instant is present.** A bare date cannot
express that two same-day checks are hours apart, and the site sets
`timeZone = 'Asia/Kolkata'`, so an instant should agree with it rather than
leave the zone to be inferred. ISO 8601 offsets also sort correctly as plain
strings, which matters because `exam-list.html` compares "the most recent day
we checked anything" by string comparison; it truncates to the date part
first, so both forms compare correctly and two records in different offsets
cannot be ordered by offset instead of by instant.

**Both forms must keep working.** `parseDate` in `site.js` takes the date part
before any `T`, and `time.AsTime` parses a bare date and an RFC 3339 string
alike, so the freshness text, the staleness flags and the provenance line are
unaffected by which form a record uses. The staleness rule is
`staleAfterDays`, a day count, and day granularity is all it ever consumed.


`source_tier` has five values, and distinguishes *what kind of document* this
is from *how much we trust it*:

| Tier | Meaning | Present on |
|---|---|---|
| `notification_pdf` | The official notification or advertisement | 174 |
| `official_portal` | A portal or notice page, not a dated document | 24 |
| `press_release` | A press note or release announcing a change | 7 |
| `corrigendum` | A corrigendum, which **supersedes** a notification | 4 |
| `other` | Anything else | 0 |

A corrigendum is its own tier because it replaces a notification rather than
sitting beside it. When a date moves twice, the tier is what tells you the
later document won.

**One value survives review, never several.** Where sources disagree — a portal
showing an old deadline, an aggregator contradicting a notice — the record
stores one adjudicated value plus its `source_tier`, and the disagreement is
resolved during review rather than encoded as a list. Current distribution:
174 / 24 / 7 / 4 / 0.

Records go stale after 14 days (`staleAfterDays` in `hugo.toml`). Aggregator
and YouTube values are never stored as fact.

---

## 3. Conducting body vs admitting authority

The single most important structural fact about Indian exams: **they are
usually not the same organisation.**

UPSC runs the exam and allocates IAS itself — simple. NTA runs JEE Main and
ranks you; **JoSAA** turns that rank into a seat. NTA runs NEET; **MCC** does
the counselling. GATE feeds CCMT, COAP, CCMN and PSU recruitment simultaneously.

So `bodies` is who *runs the exam*, and `outcomes[].authority` is who *gives
you the thing*. For UPSC these are the same and `self_allocated: true`. For
JEE Main they are not, and pretending otherwise is how a site ends up claiming
NTA admits you to an NIT.

---

## 4. Browsing surfaces

Three views answer three different questions, and none of them is a second
copy of the record list.

| Surface | Question | Sorts by | Needs JS |
|---|---|---|---|
| `/` | What needs my attention? | Urgency, then next date | No (filters are the enhancement) |
| `/calendar/` | What falls in a given month? | Date | Yes for the grid; the list is not generated |
| `/exams/` | What does the corpus contain? | Taxonomy counts | No |

**The filter bar** on `/` narrows the cards already in the page: free text over
title, body and category, plus type, status, an exam-date window, and a
confirmed-dates-only toggle. Controls are ANDed, which is the least surprising
reading and the one that degrades sanely. The status and type option lists are
generated from the data, so a choice nobody can select cannot appear. The status
values are the same `exam-status.html` keys the pills use, so the filter cannot
describe a state the grid does not show.

An exam with no published date is excluded by any date window. That is the
honest result: the reader asked for exams in the next 30 days, and an exam with
no date is not one that can be placed in that window.

**The calendar** lays out every dated milestone — 467 across the corpus — on a
month grid, filterable by kind (exam, deadline, window, admit card, result). It
opens on the earliest month holding an event that has not happened yet, because
a calendar that opens on a month of past deadlines is one nobody opens. A day
lists at most three events and then says how many more there are, and the month
is repeated underneath as a list, so the cap hides nothing.

Two renderings exist deliberately: a **grid** for scanning a dense month and a
**list** for reading it. A candidate looking for "what closes this week" and one
reading a specific exam's deadlines want different shapes, and the month list is
also the accessible path to every event the grid truncated.

Past events keep their kind word but drop their kind colour, taking the neutral
fill and a muted rule. A green "open" chip on a deadline three weeks gone invites
the reader to act on it. This is computed against the reader's clock, not at
build time, for the same reason the countdowns are: a page built three weeks ago
and opened today should dim what has since passed.

The grid is a real `<table>` with column headers, because a month calendar is
tabular data and a grid of divs with ARIA labels is strictly worse to navigate
by keyboard or screen reader.

---

## 5. Status

Status is **computed from dates, never stored.** A stored status rots the
moment a deadline passes and nobody edits the file. A computed one cannot be
wrong.

Earliest future dated milestone wins. This table is verified against the built
site, not aspirational:

| Earliest future milestone | Label | Key | Sort |
|---|---|---|---|
| `registration_open` | Upcoming | `upcoming` | 45 |
| `registration_deadline`, more than 14 days out | Registration open | `open` | 20 |
| `registration_deadline`, 14 days or less | Registration closes in N days | `soon` | 10 |
| `admit_card_from` | Admit card available | `soon` | 30 |
| `admit_card_to` | Admit card closes | `soon` | 30 |
| `exam_date` | Exam upcoming | `upcoming` | 50 |
| `result_date` | Result awaited | `upcoming` | 70 |
| every milestone past | Completed | `done` | 99 |
| no milestones at all | Upcoming | `upcoming` | 60 |

Note that **"Registration open" appears when the deadline is the next
milestone, not when the open date is.** An exam whose registration has not
opened yet reads "Upcoming".

**Known gap: there is no "Registration closed" state.** Once the deadline
passes, the next milestone becomes the admit card, so the page jumps straight to
"Admit card available" and never says registration is closed. Someone asking
"did I miss the deadline?" gets no direct answer. Worth adding as an explicit
state rather than leaving it implied.

**But status is checked manually.** Computation gets it right for the ordinary
case; it cannot express an exam that was postponed, cancelled, or whose
registration was extended. Those are real: NEET UG 2026 was held on 3 May
2026, cancelled over a paper leak, and re-run on 21 June with the original
admit card explicitly declared invalid. UGC NET June 2024 took **14 months**
from exam to result.

So: compute, then have a human confirm. A disagreement between the computed
status and the record is a bug to fix, not a display quirk. Until this is
automated, treat `status` as *derived but unaudited*.

**Not every exam supports a date-derived status.** A state commission may
publish an exam date as "To be announced" for months, or a result window as a
quarter. Where the only available fact is coarser than a day, it stays prose
and the record shows as upcoming with no false precision.

---

## 6. Worked example

A complete record, using only keys that records actually carry. `[stages]` and
`[outcomes]`, documented in §2.2 and §2.5b, are marked *planned* there and are
deliberately absent here: no record uses them yet, and a worked example is the
thing a new record gets copied from, so it should not show a schema that does
not exist yet.

```toml
+++
section = 'exams'
title = 'Common Recruitment Examination-5 (CRE-5), 2026'
bodies = ['AIIMS']
categories = ['Government']
summary = 'AIIMS common test for Group B and Group C non-faculty posts.'

registration_open = 2026-06-13
registration_open_status = 'confirmed'
registration_deadline = 2026-07-03
registration_deadline_status = 'confirmed'

eligibility = '''Post-wise conditions across roughly sixty group codes, ranging from matriculation
through Class 12, diploma, degree, engineering, nursing and pharmacy qualifications, set out
in the detailed recruitment advertisement and its annexures.'''
mode = 'Online (Computer Based Test), then a skill test where prescribed'
venue = 'Examination centres at AIIMS institutes and other participating institutes'

official_url = 'https://aiimsexams.ac.in/'
apply_url = 'https://aiimsexams.ac.in/'

fee_basis = 'per_group'
fee_note = 'Candidates applying for more than one group must apply separately for each.'

[[fee]]
category = 'General'
amount = 3000

[[fee]]
category = 'SC'
amount = 3000

[[fee]]
category = 'PwBD'
amount = 0
note = 'Exempt'

[pay]
system = 'pay_matrix'
level = [4, 5, 6]
low = 35000
high = 56000

[provenance]
source_url = 'https://aiimsexams.ac.in/'
source_doc = 'AIIMS Notice No. 93/2026 dated 13/06/2026, Detailed Recruitment Advertisement for CRE-5'
timestamp_retrieved = '2026-09-27'
timestamp_last_checked = '2026-09-27T14:32:11+05:30'
source_tier = 'notification_pdf'
+++
```

Four things in that record are load-bearing and easy to get wrong.

**Every date carries a `_status` sibling.** A date without one is a build error,
not a default. The two dates above are both `confirmed`; a body that has
published a window but not fixed its closing date would carry
`registration_deadline_status = 'provisional'`.

**`PwBD` is an `amount = 0` row with `note = 'Exempt'`,** not a fourth amount
and not an absent row. The exemption is the fact a candidate needs, and a zero
in the amount column is how the table shows it.

**`fee_basis = 'per_group'`** is load-bearing, because the record says the fee
is charged per group code applied for. Without it, one row per category reads as
the total cost — for a candidate applying to three groups, three times the
number shown.

**`level` is a list even where one level dominates,** and `low`/`high` are the
pay-matrix bounds, not the post's basic pay.

---

## 7. What is deliberately not here

Preparation resources. Recommended books. Previous-year question analysis.
Coaching. Subject-wise weightage breakdowns. This is a reference for facts about
an exam, not a route through one.

Nor is there history. Previous vacancies, previous cut-off tables, year-on-year
trends. If that proves useful it can be added as its own page; it does not
belong on an upcoming-exam record. The single exception is the previous
cut-off, which is a reference figure rather than a trend, and is labelled with
its year.

---

## 8. Source tiers

| Tier | Source | May a value be stored? |
|---|---|---|
| 1 | Official notifications, conducting bodies, official calendars | Yes |
| 2 | Curated aggregators (Testbook, Adda247, Careers360) | Discovery only, never as a number |
| 3 | YouTube | Only as a lead, labelled with the channel |
| 4 | Newspaper-only, notice-board | Recorded in `provenance`; no URL exists |

Tier 2 is discovery-only because aggregators contradict official notices on
matters of fact — live pages still asserted that MPPSC has no negative marking
for the 2026 exam that introduced −1 per wrong answer.

---

## 9. Not yet built

Agreed, specified enough to build later, deliberately out of the first version.

**Rank and cut-off depth.** A `rank_namespace` enum — `CRL`, `category_rank`,
`pwd_within_category`, `state_rank`, `aiq_rank`, `preparatory` — because a
single scorecard carries four different rank namespaces and official bodies
state the basis explicitly. Almost every aggregator conflates them, and it is
the most common factual error in Indian admissions. Also per-post cut-off
tables, sectional cut-offs, and marks-vs-rank mapping.

**Normalisation.** Needs a typed field where `unpublished` is a real value, not
a null. NEET has none, JEE Main uses percentile equivalence, SSC publishes a
full formula (and has changed method mid-family since June 2025), and CAT
publishes nothing about its slot scaling. Store the method name and a document
link, never the coefficients.

**Reservation.** A structured representation, because the schema differs by
state: Bihar's EBC/BC/WBC split, Karnataka's Cat I/IIA/IIB/IIIA/IIIB, Assam's
ST Plains 10% against ST Hills 5%, and horizontal reservations that stack with
vertical ones. CGPSC publishes a 16-row cut-off matrix crossing category with
gender.

**Physical and medical standards.** The most consequential field in police and
forest recruitment and nobody models it. HPPSC awards 0–5 marks by height band;
Telangana awards 100 down to 30 marks by 1600m time.

**Merit weightings.** How a final list is actually built — SEBI 85:15,
ISRO 50:50, JIPMAT varying by institute. The field candidates most want and no
exam page publishes.

**Counselling detail.** Per-round choice filling, locking, mock allotment,
willingness vocabulary, fee forfeiture, withdrawal windows. Roughly 50–150
dated milestones for a single admission candidate, and it needs to be a
queryable sub-entity rather than fields on the page.

**Other deferred:** tie-break chains · syllabus depth beyond a link ·
documents required · helpline contacts · exam-centre lists · application
process steps · re-evaluation policy · category and gender-specific
requirements · fees by category as a table rather than prose · statistics
(registered, appeared, qualified, selected).

---

## 10. Change log

Decisions taken while building this, so the reasoning survives:

- **Omit absent fields** rather than rendering "TBA". One schema has to cover a
  national commission and a single-post district notice.
- **Computed status, manually checked.** Storage rots; computation cannot. But
  computation cannot see postponement either, so a human confirms.
- **No exam level field.** The conducting body already implies it.
- **Prep content removed.** Exam facts only.
- **Cut-off limited to the previous cycle, official only**, with the caveat
  that it is retrospective rather than a threshold.
- **Outcomes typed instead of a "leads to" list**, because one exam can award a
  post, an admission, an eligibility, a fellowship, or a choice between
  exclusive tiers — and because the admitting body is usually not the exam body.
- **Stages carry both a canonical slot and the body's own name**, so filtering
  works without discarding Tamil Nadu's "PCV".
- **Allocation rounds live under outcomes, not stages.**
- **Exam dates are lists**, because most exams are not a single day.
- **Every date carries an explicit status, no nulls.** `confirmed` or
  `provisional`, stored as a `<key>_status` sibling. Dotted date forms are not
  valid TOML and nested `{value, status}` tables break Hugo's `time.AsTime`, so
  a parallel key is the only shape that survives a build — verified by testing
  all four candidates, not assumed.
- **`admit_card_status` is a state, and the date is optional.** Sixteen of
  310 records carry `admit_card_from` and none carry `admit_card_to`, while
  83 mention an admit card in prose — so a date-only model is silent on
  almost every record that has something to say. Five states, of which
  `not_announced` is the *absent* key and is therefore never written, and
  a body that publishes a rule instead of a day gets the rule in
  `admit_card_note` with no date invented from it.
- **Admit-card pill colours are their own family, not the status pills
  reused.** Measured, the status fills are 4.81:1 to 5.36:1 against dark
  `--text`, under the 5.4:1 floor `tokens.css` documents. The admit fills
  are solved to a fixed one-step distance from `--base` in the same hues
  and measured: 1.22:1 light, 1.30:1 dark, with `--text` at 5.78:1 and
  6.20:1 on them. Solving the luminance rather than picking a colour is
  what makes both floors hold at once, since both ratios depend on
  luminance alone.
- **Provisional is shown, not hidden.** A date the body published but has not
  fixed is real information; omitting it left 50 records showing nothing when a
  provisional date was available. It is labelled in words *and* coloured, so
  the distinction survives greyscale, and its countdown is suppressed.
- **One display date format**, `2026, October 04`. A compact `2026.10.04` was
  proposed and dropped as a second format with no consumer.
- **A new `provisional` colour token, not the existing amber.** Amber already
  means "urgent" in this design system, and uncertainty is not urgency. It is
  violet-side to stay clear of the blue used for "info" and the timeline's
  "next" chip. Verified arithmetically against the thresholds `tokens.css`
  documents: 1.26:1 against the page, 5.60:1 against the text, in light mode.
- **Pay is structured, per-post, and handles three vocabularies.** Level
  matrices, rupee ranges and PSU grade-plus-initial all occur, and one exam can
  span levels or set a different scale per post.
- **`source_tier` is five values, one per record.** Where sources disagree the
  value is adjudicated at review rather than stored as a list of candidates.
- **Fee is a matrix, one row per category, always.** A sentence that names
  categories, maps them to amounts and carries the caveats at once is the reason
  candidates misread fees. 666 rows across 151 records; 29 records have a
  `fee_note` and no rate, which is a different fact from a rate of zero.
- **`PwD` is `PwBD`, and `All` is `All candidates` — but `OBC` and `OBC-NCL`
  stay two values.** The first two are abbreviations and a bare word, not
  categories. The third is a real distinction, and merging it was a mistake
  made here and then reverted: an earlier draft argued that because the Central
  OBC List already excludes the creamy layer, "OBC" and "OBC-NCL" said the same
  thing. That holds for a central or university body and fails for a state one.
  49 of the 65 records with a fee row for this class are state bodies or
  district courts, several of which grant OBC benefits including the creamy
  layer. Merging removed the site's ability to say "non-creamy layer only" and
  left those 49 records ambiguous about who is actually covered. A
  jurisdiction-dependent term must not be normalised into one value.
- **`PwBC` and `PwH` were removed, not left empty.** Neither is an Indian
  reservation class, and an unused entry in a controlled list is an invitation.
- **`label` carries a state class that has no national equivalent.** Rajasthan's
  Economically Backward Class, Rajasthan's Backward Classes and Haryana's BC-A/BC-B
  are each distinct from central OBC and, in two cases, charged a different rate.
  Collapsing them into `OBC` put two different amounts under one heading, which
  is worse than showing the notice's own wording. One record had been omitting
  its EBC row entirely and apologising in `fee_note`; with `label` it now has the
  row.
- **A `[[fee]]` row with neither `category` nor `label` fails the build.** A
  blank cell in a fee table is a question the reader cannot answer, and a build
  error is the only thing that reliably surfaces it.
- **Provenance timestamps are RFC 3339 with an offset, not dates and not Unix.**
  The files are human-reviewed and a reviewer is the pipeline's bottleneck, so the
  value has to be readable in a diff; the offset is mandatory because a bare date
  cannot express that two same-day checks are hours apart; and ISO 8601 sorts
  correctly as a string, which the freshness band relies on. Unix was the
  rejected alternative — right for a log, wrong for a reviewed file.
- **Timestamps hold a bare date, and this was corrected after being got wrong.**
  The first migration wrote `T00:00:00+05:30` into all 310 records on the
  argument that midnight is a conventional day-start marker. That was
  backwards: a field whose 310 values are identical and equal to midnight
  carries one bit of information, the timezone, and it is strictly worse than
  the bare date it replaced, because a bare date is honestly day-shaped while a
  midnight timestamp implies an hour nobody measured. The evidence that would
  have justified it was already gone — the same-day schema migrations, fee
  rewrite, admit-card backfill and vocabulary work rewrote all 310 files, so
  every mtime now reads "today" regardless of when the source was fetched. The
  rule now is that the site records the precision it has, a bare date means the
  day is known and the hour is not, and the pipeline must earn an instant by
  actually fetching a source. Both forms parse identically, so nothing
  downstream needed changing.
- **One definition of a milestone, in `_partials/milestones.html`.** The timeline
  and the calendar both read it. It previously ranged over a map of dates and
  looked each label's status up in a second map keyed by the same labels, so
  adding a date meant editing two places with nothing to complain if you forgot.
- **The filter bar hides and shows the cards already in the page.** It does not
  re-render from the JSON index. Hugo computes the order once, in
  `exam-list.html`; a second ordering written in JavaScript would be a second
  thing to keep in agreement with it. It also ships with `hidden` and is revealed
  by script, so a reader without JavaScript gets the plain list and no dead
  controls. Verified: `upsc` returns 16 and `kerala psc` returns 17, matching
  the body counts computed independently from front matter.
- **The calendar is baked in at build time, not fetched.** It is a view of the
  same build that rendered the list it links to, so an edit cannot leave a stale
  event behind. Its opening month is the earliest month holding an event that has
  not happened yet — found by sorting first, because taking the first match in
  site order opened the calendar on December while an event existed for today.
- **Calendar chips carry `--text`, not `--text-muted`.** Measured, the muted token
  on the kind fills runs 4.25:1 to 4.73:1 in light and 3.31:1 to 4.26:1 in dark,
  failing AA for small text in ten of twelve combinations. The muted token is the
  *lower*-contrast choice in both modes, because in light it is a lighter grey on
  a pale fill and in dark a dimmer one on a dark fill. The hierarchy is carried by
  weight instead, which costs no contrast. A past chip also keeps `--text`,
  because `--fill-done` sits a step darker than the page background the
  timeline's muted label was measured against; the neutral fill and muted rule
  already mark it as past.

