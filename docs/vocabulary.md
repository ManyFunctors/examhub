# Vocabulary research

Status: **research, September 2026.** This is the evidence and the proposal
that the controlled vocabularies in `data/catalogue/` will be rebuilt from. No
code reads this file.

Three sources, in order of authority:

1. **ExamHub's own data model** (`docs/data-model-notes.md`).
   ExamHub is where the data ends up, so where it already names a thing, the
   pipeline uses that name.
2. **The harvest**: 51,516 notices and 105 structured PDFs, counted below.
   What notices actually say beats what a guide says they say.
3. **Official and secondary sources on the web**, cited per section. A value
   marked † is from a secondary source or from memory and must be confirmed
   against a notice from that body before it goes into the vocabulary.

## 0. Rules for every vocabulary

* **One list per concept, in `data/catalogue/`.** Code reads it; code never
  keeps its own copy. Today the same ideas live in four places (`vocab.toml`,
  `documents.py`, `profiles.py`, `config.py`) under different names.
* **Map spellings, never merge classes.** Each value carries the aliases that
  mean exactly it. "UR", "General" and "Open" are one class written three
  ways; "OBC" and "OBC-NCL" are two classes.
* **Aliases are scoped.** An abbreviation can mean different things in
  different states (see 1.4), so an alias belongs to a jurisdiction unless it
  is national.
* **The raw wording is always kept.** A mapped value sits next to the words
  the notice used. A label that maps to nothing is kept as-is and goes to a
  worklist (`unmapped-<vocab>.jsonl`), exactly as an unmatched notice does.
* **Values are never repurposed.** A wrong value moves to `[deprecated]` with
  its replacement, so old harvests still load.

## 1. Reservation categories

The largest vocabulary, and the one where a wrong merge does real harm.

### 1.1 Four axes

A candidate has **exactly one** value on axis A, and **any number** on B and C.
A fee, vacancy or age row may combine them ("SC Women", "OBC-NCL (PwBD)").

| Axis | What it is | Examples |
|---|---|---|
| A. Social class (vertical) | The caste or economic class | Unreserved, OBC-NCL, SC, Kerala Ezhava, Karnataka 2A |
| B. Horizontal class | Cuts across A | PwBD, Ex-Servicemen, Women, Sportsperson |
| C. Locality and medium | Where you are from or studied | Domicile, Other State, Karnataka Rural, Tamil medium (PSTM) |
| D. Gender qualifier | Qualifies a row; not a group | `Male`, `Female` (ExamHub `fee.gender`) |

Plus one value outside the axes: **`All candidates`**, a single rate for
everyone. It is not Unreserved.

**Naming clash to avoid:** ExamHub already uses `categories` for its site
taxonomy (`Government`, `Private`, `Academic`) and `category` for the fee
row's reservation class. The pipeline's vocabulary should be named
`reservation` (file `reservation.toml`) so the two are never confused.

### 1.2 National values

| Value | Axis | Aliases (inside a category column or list) | Notes |
|---|---|---|---|
| `Unreserved` | A | General, Gen, GEN, UR, UG, Open, OC, GT, GM, OM, Non-reserved, Others | The user's canonical name. ExamHub currently writes `General` (68 fee rows) |
| `OBC` | A | OBC, BC (only where the body has no state split) | The body's own OBC, whatever it means by it |
| `OBC-NCL` | A | OBC-NCL, OBC (NCL), OBC Non-Creamy Layer, NCL | Separate from `OBC` (ExamHub §2.4a). "OBC-NGL" is not a term: no notice or guide uses it |
| `SC` | A | SC, Scheduled Caste | |
| `ST` | A | ST, Scheduled Tribe | |
| `EWS` | A | EWS, Economically Weaker Section | |
| `PwBD` | B | PwBD, PwD, PH, PWD, Divyang, Divyangjan, Physically Handicapped, Differently Abled, DA | Never `PwBC` or `PwH` (ExamHub bans both) |
| `PwBD-A` | B | VH, VI, Blind, Low Vision | RPwD Act 2016 s.34(a) |
| `PwBD-B` | B | HH, HI, Deaf, Hard of Hearing | s.34(b) |
| `PwBD-C` | B | OH, LD, Locomotor, Cerebral Palsy, Leprosy Cured, Dwarfism, Acid Attack Victim, Muscular Dystrophy | s.34(c) |
| `PwBD-D` | B | Autism, Intellectual Disability, SLD, Mental Illness | s.34(d) |
| `PwBD-E` | B | Multiple Disabilities, Deaf-Blind, MD | s.34(e) |
| `Ex-Servicemen` | B | ESM, Ex-SM, Ex-Serviceman | Central alias only. See 1.4 for DESM |
| `Disabled Ex-Servicemen` | B | DESM (central bodies only), Disabled ESM | |
| `Dependent of Ex-Servicemen` | B | Ward of ESM, WESM, ESM (Dependent), DESM (Haryana only) | |
| `Ex-Agniveer` | B | Agniveer, Former Agniveer | CAPF and state police quotas since 2024 |
| `Women` | B | Women, Female candidates (as a group), Mahila | Distinct from the `Female` row qualifier |
| `Transgender` | B | Transgender, Third Gender, TG, Other (gender) | |
| `Sportsperson` | B | Meritorious Sportsperson, MSP, Outstanding Sportsperson, Sports quota | |
| `Freedom Fighter Dependant` | B | DFF, Ward of Freedom Fighter, WFF, Freedom Fighter | |
| `Orphan` | B | Orphan | Maharashtra 1%, Uttarakhand 5% |
| `Widow` | B | Widow | |
| `Destitute Widow` | B | DW, Destitute Widow | Tamil Nadu |
| `Divorcee` | B | Divorcee, Divorced Women | Rajasthan† |
| `Project Affected Person` | B | PAP, Project Displaced, PDP | Maharashtra and others |
| `Earthquake Affected` | B | Earthquake Affected | Maharashtra† |
| `Kashmiri Migrant` | B | Kashmiri Migrant | Mostly age relaxation |
| `1984 Riot Victim` | B | 1984 riots | Central age relaxation |
| `Government Employee` | B | Govt. Servant, In-service, Departmental candidate | Mostly age relaxation |
| `Home Guard` | B | Home Guard | |
| `Contract Employee` | B | Contractual employee, Samvida | Often bonus marks, not reservation |
| `BPL` | B | BPL, Below Poverty Line | Himachal Pradesh |
| `Government School Student` | B | Govt. school students | Puducherry, Tamil Nadu 7.5% (admissions) |
| `Domicile` | C | Domicile, Bonafide resident, Local, Native | The body's own state |
| `Other State` | C | Other State, Non-domicile, Non-local, Outside [State] | Usually treated as Unreserved by the notice itself |

### 1.3 State classes, by jurisdiction

Each is its own value, with an id scoped to the state (`ka:2A`, `tn:MBC/DNC`).
None is folded into a national value.

| Jurisdiction | Axis A values | Axis B/C values specific to the state |
|---|---|---|
| Andhra Pradesh | `BC-A`, `BC-B`, `BC-C`, `BC-D`, `BC-E`, `OC` (= Unreserved alias), `SC Group I`, `SC Group II`, `SC Group III` | `Local`, `Non-local` (zonal); Women 33⅓% |
| Arunachal Pradesh | `APST` | `Non-APST` (80:20 split for posts) |
| Assam | `OBC/MOBC`, `MOBC`, `ST(P)`, `ST(H)` | |
| Bihar | `EBC`, `BC`, `BC Women` | Women 35%, Bihar domicile only since July 2025 |
| Chhattisgarh | Unreserved, OBC, SC, ST, EWS | Domicile |
| Delhi | `OBC (Delhi)` (OBC from outside Delhi is Unreserved) | |
| Goa | Unreserved, OBC, SC, ST, EWS | |
| Gujarat | `SEBC` | |
| Haryana | `BC-A`, `BC-B`, `DSC`, `OSC` (Other Scheduled Castes) | `Dependent of Ex-Servicemen` (Haryana DESM) |
| Himachal Pradesh | Unreserved, OBC, SC, ST, EWS | `BPL`, Ward of ESM, Ward of Freedom Fighter |
| Jammu and Kashmir | `OM` (= Unreserved alias), `RBA`, `ALC/IB`, `OSC` (Other Social Castes), `PSP` (Pahari Speaking People) | |
| Jharkhand | `BC-I`, `BC-II`†, `PVTG`† | |
| Karnataka | `Cat-1`, `2A`, `2B`, `3A`, `3B`, `GM` (= Unreserved alias) | `Rural`, `Kannada Medium`, `Kalyana Karnataka (371J)`, `Project Displaced`†, Women 33% |
| Kerala | `Ezhava/Thiyya/Billava` (ETB), `Muslim`, `LC/AI`, `Hindu Nadar`, `SIUC Nadar`, `SCCC`, `Viswakarma`, `Dheevara`, `OBC`, `EWS` | |
| Madhya Pradesh | Unreserved, OBC, SC, ST, EWS | Women 35% |
| Maharashtra | `VJ-A`, `NT-B`, `NT-C`, `NT-D`, `SBC`, `SEBC`, `Open` (= Unreserved alias) | `Orphan`, `Project Affected Person`, `Earthquake Affected`, `Part-time Graduate Employee`† |
| Manipur | Unreserved, OBC, SC, ST | |
| Meghalaya | `Khasi-Jaintia`, `Garo`, `Other ST/SC` | |
| Mizoram | ST (most posts) | |
| Nagaland | `Indigenous ST of Nagaland`, `Backward Tribe` (Eastern Nagaland and others) | |
| Odisha | `SEBC` | |
| Puducherry | `MBC`, `OBC`, `EBC`, `BCM`, `BT` (Backward Tribe) | `Government School Student`, `Freedom Fighter Dependant` |
| Punjab | `SC (M&B)` Mazhabi & Balmiki, `SC (R&O)` Ramdasia & Others, `BC` | `ESM (Self)`, `ESM (Dependent)`, `LDESM` (Lineal Descendant of ESM), `Freedom Fighter Punjab`, `PH Punjab` |
| Rajasthan | `MBC`, `Saharia`† | `TSP Area` / `Non-TSP Area`, `Widow`†, `Divorcee`† |
| Sikkim | `BL` (Bhutia-Lepcha), `Limboo-Tamang`†, `MBC`†, `OBC (Central List)`, `OBC (State List)` | `Sikkim Subject / COI`† |
| Tamil Nadu | `GT` (= Unreserved alias), `BC` (other than Muslim), `BCM`, `MBC/DNC`, `SC(A)` Arunthathiyar | `PSTM` (Tamil medium, 20%), `Destitute Widow` |
| Telangana | `BC-A`…`BC-E`, `OC` (= Unreserved alias), `SC Group I`, `SC Group II`, `SC Group III` | `Local` / `Non-local` (95% local, zonal), Women 33⅓% |
| Tripura | Unreserved, SC, ST (no state OBC reservation) | |
| Uttar Pradesh | Unreserved, OBC, SC, ST, EWS | Women of UP 20%, DFF 2%, ESM 5% |
| Uttarakhand | Unreserved, OBC, SC, ST, EWS | Uttarakhand Women 30%, `State Movement Activist` 10%, Orphan 5%, DFF 2% |
| West Bengal | `OBC-A`, `OBC-B` | |

Still to research (no entry yet): Ladakh (post-2025 domicile rules),
Andaman and Nicobar, Lakshadweep, Dadra and Nagar Haveli and Daman and Diu,
Chandigarh. They mostly follow the central list; confirm from a notice.

### 1.4 Abbreviations that change meaning by state

This is why aliases must be scoped. Evidence for each is in the sources.

| Written | Means in | Means in |
|---|---|---|
| `OSC` | Haryana: Other **Scheduled** Castes (an SC sub-group) | J&K: Other **Social** Castes (a backward-class group, not SC) |
| `DESM` | Central bodies: **Disabled** Ex-Servicemen | Haryana: **Dependent of** Ex-Servicemen |
| `BC` | Tamil Nadu: BC other than Muslims | Bihar and Punjab: each state's own BC list |
| `OC` | Tamil Nadu: Open Competition | AP and Telangana: Open Category (both Unreserved, but a different word) |
| `EBC` | Bihar: Extremely Backward Classes | Puducherry: Extreme Backward Classes (a different list) |
| `MBC` | Tamil Nadu: Most Backward Classes | Rajasthan: More Backward Classes; Puducherry: its own list |
| `SBC` | Maharashtra: Special Backward Class | Rajasthan: the pre-2019 name of its MBC |
| `UG` | Category column: Unreserved | Anywhere else: undergraduate |

### 1.5 What the harvest already shows

Category tokens in the 51,516 notice titles alone: General 604, SC 328, ST 86,
PwD 42, Open 42, PwBD 41, EWS 34, SBC 31, PH 24, OM 14, APST 12, OBC-NCL 11,
UR 10, OBC-A/B 19, NCL 8, GM 6, ESM 4, MBC 4, EBC 3, Agniveer 2. PDFs will
surface many more; the worklist in §0 is how the list stays exhaustive.

## 2. Dates and events

Today there are three names for the same thing:

| ExamHub key | `vocab.toml` `event_kind` | `documents.py` | Decision |
|---|---|---|---|
| `registration_open` | `registration_open` | `registration_open` | keep |
| `registration_deadline` | `registration_close` | `registration_deadline` | **ExamHub's name**; deprecate `registration_close` |
| `payment_deadline` | `fee_deadline` | `payment_deadline` | ExamHub's name |
| `correction_window` (`{from, to}`) | `correction_window` | `correction_window` | keep; a range |
| `admit_card_from` / `admit_card_to` | `admit_card` | `admit_card_from` | ExamHub's names |
| `exam_date` (→ `exam_dates`) | `exam` | `exam_date` | ExamHub's name |
| `result_date` | `result` | `result_date` | ExamHub's name |
| `age_as_on` | — | `age_as_on` | add |
| — | `answer_key` | `answer_key` | add `answer_key_date`; `answer_key_objection` window† |
| — | `interview` | — | stage date, see §5 |
| — | `document_verification` | — | stage date, see §5 |
| — | `counselling` | — | an outcome date, not a stage (ExamHub §2.5) |

Also from ExamHub: every date has a `_status` of `confirmed` or `provisional`;
`admit_card_status` is `not_announced` · `announced` · `released` · `delayed` ·
`withdrawn`, and `not_announced` is never written. Granularity stays `day`,
`month`, `quarter`; only `day` goes in a date field.

## 3. Document types

**Status (1 Oct 2026):** the types are adopted in `crawl/adapters.py` (`classify_doc_type`)
and `vocab.toml`; each harvest reclassifies notices still typed `other`. The subtypes are not
done yet.

The notice-level `doc_type` (from the title) and the PDF-level `kind` (from
reading it) are two lists today. Proposal: one two-level list. The title sets
the type; reading the PDF may add a subtype, but only a subtype of that type.

| Type | Subtypes | Evidence for adding it |
|---|---|---|
| `notification` | `advertisement`, `brochure`, `prospectus`, `detailed_notice`, `short_notice` | |
| `corrigendum` | `extension`, `addendum`, `postponement`, `cancellation` | |
| `schedule` | `exam_schedule`, `interview_schedule`, `physical_test_schedule`, `dv_schedule` | "interview" is in 2,517 unclassified titles |
| `application_status` | `eligible_list`, `ineligible_list`, `scrutiny`, `rejection_list` | **new**. "eligible applicn scrutiny" 952, "ineligibility list" 835, "eligibility list" 681 |
| `admit_card` | `exam_city` | |
| `answer_key` | `provisional`, `final`, `objection` | |
| `result` | `merit_list`, `selection_list`, `waiting_list`, `cut_off`, `marks`, `shortlist` | |
| `counselling` | `seat_matrix`, `allotment`, `round`, `mop_up`, `stray_vacancy` | **new**. "seat matrix" 643, "round physical counselling" 526, "mop round" 135 |
| `walk_in` | | **new**. "walk interview" 445; ExamHub already has `selection_method = walk_in` |
| `syllabus` | | Already a PDF kind |
| `calendar` | | |
| `press_release` | | |
| `other` | | |

Today 44% of notices (22,853) are `other`. The words above account for most
of them; the rest need the same frequency pass after the change.

## 4. Education and qualification

Keep the level list, fix its gaps, and add a second list for named
credentials, because "B.Ed" or "MBBS" is what a candidate filters by.

**`qualification_level`** (a ladder, one per requirement):
`none` · `class_5` · `class_8` · `class_10` · `class_12` · `iti` · `diploma` ·
`graduate` · `postgraduate` · `doctorate`

* `iti` is separate from `diploma`: different certificates (NCVT/SCVT versus a
  polytechnic diploma), and notices ask for one or the other.
* `doctorate` is added; `documents.py` already emits it.
* `professional` is dropped as a level: MBBS or LLB is a `graduate`-level
  credential. What made it "professional" moves to the credential list.

**`credential`** (named, any number): examples of families, not the full list:
teaching (`B.Ed`, `D.El.Ed`, `B.P.Ed`, `CTET`, `State TET`), medical (`MBBS`,
`BDS`, `BAMS`, `BHMS`, `B.Sc Nursing`, `GNM`, `ANM`, `D.Pharm`, `B.Pharm`),
law (`LLB`, `LLM`), engineering (`B.E/B.Tech`, `M.E/M.Tech`, `GATE score`),
accounts (`CA`, `CS`, `CMA`), research (`NET`, `JRF`, `SET/SLET`), trades
(`ITI <trade>`, `NAC`), languages and skills (typing speed, shorthand speed,
`CCC`/`O Level` computer certificates), physical (`Driving licence`).

Flags on a requirement, not values: `final_year_may_apply`, `min_percent`,
`relaxed_for` (reservation values).

## 5. Selection: stages, methods, mode

ExamHub already has the answer; the pipeline adopts it.

**`stage` slots** (ExamHub): `primary` · `secondary` · `physical` · `skill` ·
`interview` · `medical` · `document_verification`. Each stage also keeps the
body's own `official_name` verbatim.

Sub-kinds worth recognising inside a slot, from SSC, police and state notices:

| Slot | Sub-kinds and aliases |
|---|---|
| `primary` | Tier I, Prelims, Preliminary, Screening test, Paper I, Stage I, CBT-1 |
| `secondary` | Tier II, Mains, Main Written, Paper II, Descriptive, CBT-2 |
| `physical` | PST (Physical Standard Test), PET (Physical Endurance / Efficiency Test), PMT (Physical Measurement Test), PE&MT, Physical Fitness Test |
| `skill` | Typing test, Stenography / shorthand, DEST (Data Entry Speed Test), CPT (Computer Proficiency Test), Trade test, Driving test, Practical |
| `interview` | Personality Test, Viva voce, Oral test, Group Discussion†, Interaction |
| `medical` | DME (Detailed Medical Examination), RME (Review Medical), Medical fitness |
| `document_verification` | DV, Certificate verification, PCV (Tamil Nadu) |

**`selection_method`** (ExamHub): `written` · `written+interview` ·
`merit_marks` · `lottery` · `skill_test` · `walk_in` · `merit+interview`.

**`exam_mode`**: `cbt` · `omr` · `pen_paper` (descriptive) · `online_proctored`
· `hybrid`. ExamHub stores this as text today (`Offline`, `CBT`, `OMR`).

**Negative marking** stays text (ExamHub §2.5): it varies by paper and part.

## 6. Pay

ExamHub names three systems and they are all real. Proposed `pay.system`:

| System | What a notice says | Structured as |
|---|---|---|
| `pay_matrix` | "Level 7", "Pay Level 2 and 3" | `level` list, 1–18 |
| `scale` | "₹69,250 – ₹1,34,200" (states) | `low`, `high` |
| `psu_grade` | "E-1 Grade, ₹40,000–1,40,000, IDA" | `grade` E0–E9, `low`, `high`, `initial` |
| `bank_scale` | "JMGS-I", "Scale I", clerical scale | `grade` JMGS-I, MMGS-II, MMGS-III, SMGS-IV, SMGS-V, TEGS-VI, TEGS-VII |
| `pre_7cpc` | "PB-2 ₹9,300–34,800 + Grade Pay ₹4,200" | `band` PB-1…PB-4, `grade_pay` |
| `consolidated` | "₹25,000 per month consolidated", fixed pay, honorarium | `amount`, `period` |
| `stipend` | fellowships, apprentices, trainees | `amount`, `period` |

7th CPC entry pay per level, for a sanity check (a "Level 7" post whose
stated range starts below ₹44,900 is a misread):

| Level | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Entry ₹ | 18,000 | 19,900 | 21,700 | 25,500 | 29,200 | 35,400 | 44,900 | 47,600 | 53,100 |

| Level | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 |
|---|---|---|---|---|---|---|---|---|---|
| Entry ₹ | 56,100 | 67,700 | 78,800 | 1,23,100 | 1,44,200 | 1,82,200 | 2,05,400 | 2,25,000 | 2,50,000 |

**`post_group`**: `Group A` · `Group B` · `Group C` · `Group D` (pre-2006, still
in state notices), plus `gazetted` / `non_gazetted` as a flag. Some states say
`Class I`…`Class IV` (Gujarat, Maharashtra): aliases, scoped.

**`appointment_type`**: `regular` · `temporary` · `probation`† · `contractual`
· `ad_hoc` · `guest` · `deputation` · `absorption` · `apprentice` ·
`outsourced` · `tenure` · `fellowship`. The harvest shows `adhoc` in 237
unclassified titles and "guest faculty" in 226.

## 7. Fees

From ExamHub §2.4: `fee_basis` is `per_form` · `per_group` · `per_post` ·
`per_paper`. Rows are one per reservation value (§1), with `gender` and
`note`. Proposed additions, as the notices separate them:
`fee_component`: `application` · `examination` · `processing` · `late` ·
`correction` · `re_evaluation`. GST and bank charges are **not** fee rows
(`documents.py` already skips them).

## 8. Admissions (counselling)

These belong to ExamHub's `outcomes`, not to stages. From JoSAA and MCC:

* **`quota`**: `AI` (All India), `HS` (Home State), `OS` (Other State),
  `AIQ` (medical 15%), `State`, `Deemed`, `Central University`, `Institutional`,
  `IP` (ESIC insured persons), `AFMS`, `Management`, `NRI`, `Minority`
  (Muslim, Jain, linguistic), `Open` (open seat quota).
* **`seat_pool`**: `Gender-Neutral`, `Female-only (including supernumerary)`.
* **`round`**: `Round 1`…`Round N`, `Mop-up`, `Stray vacancy`, `Spot`, `Upgradation`†.
* **Seat category** is the reservation list (§1) with a `(PwD)` suffix,
  e.g. `OBC-NCL (PwD)`.

## 9. Catalogue vocabularies: usage check

Counted over the 1,017 exams, 462 bodies and 467 feeds on `main`:

| Vocabulary | Finding | Proposal |
|---|---|---|
| `body_kind` | All used except `other` | No change. Consider `school_organisation` (KVS, NVS)† |
| `exam_purpose` | All 7 used | No change |
| `frequency` | 2 exams have none | Lint should require it |
| `qualification` | 58 exams have none; `professional` used 47 times | See §4: split into level plus credential |
| `stream` | `fisheries` unused | Keep; it is a real stream |
| `feed_adapter` | `html_table` unused (0 of 467) | Keep only if a feed will use it, otherwise deprecate |
| `feed_yields` | `admit_cards` unused | Keep |
| `feed_status` | Every feed is `active`, though feed health shows dead ones | Status is by design never machine-edited; a periodic human pass should set `broken` and `blocked` from `feed-health.jsonl` |
| `doc_type` | 44% `other` | §3 |
| `event_kind` | Names differ from ExamHub | §2 |
| `stage` | Matches ExamHub | Add sub-kinds (§5) |
| `granularity` | `day`, `month`, `quarter` | No change |

## 10. Languages

For exam medium and language papers: the 22 languages of the Eighth
Schedule plus English. Medium is a list on a stage (SSC and NTA exams offer
13 or more).

## 11. Where each vocabulary will live

| File | Holds |
|---|---|
| `data/catalogue/vocab.toml` | Catalogue vocabularies (§9), unchanged in shape |
| `data/catalogue/reservation.toml` | §1: values, axis, jurisdiction, aliases, source URL |
| `data/catalogue/terms.toml` | §2 to §8: dates, document types, qualification, stages, pay, fees, admissions |

Lint checks that every value the code can emit is in one of these files, and
that no alias is claimed twice within one jurisdiction.

## Open questions

1. `Unreserved` versus ExamHub's `General`: does ExamHub migrate its 68
   rows, or does the pipeline map at the boundary until it does?
2. Should a state class record a `family` (Haryana `DSC` → SC) only for site
   filtering? The value itself would never be shown or merged as SC.
3. The † entries need a notice from that body before they are added.

## Sources

* ExamHub, `docs/data-model-notes.md` §2.2–2.8, §5 (local).
* OBC-NCL: [ClearIAS](https://www.clearias.com/obc-reservation-eligibility/).
* Haryana DSC/OSC, BC-A/BC-B: [HSSC Advt. 04/2026](https://hssc.gov.in/file/ac1f23cd-99c4-13a6-819c-32aaa1600063/advertisements), [HSSC](https://x.com/HSSCorg_in/status/1924276442533179426).
* Telangana SC groups: [ANI](https://aninews.in/news/national/general-news/telangana-enforces-sc-sub-categorization-for-future-recruitments-education-related-decisions20250414202413/); women 33⅓%: [Telangana Today](https://telanganatoday.com/telangana-govt-implements-33-percent-horizontal-reservation-for-women-in-recruitment); BC-A…E and OC: [TGPSC](https://websitenew.tgpsc.gov.in/preview/UFJFU1NOT1RFLzE1LUcuTy5Ncy5Oby4wMywwOTA5MjAyMDIwMjIwNTA2MTE0NjA0LnBkZg==r95v17a0y2d8i13v).
* Andhra Pradesh SC groups: [G.O. 7 of 2025](https://www.aputf.org/wp-content/uploads/2025/04/2025SW_MS7_E-Dt.18.04.2025.pdf), [The News Minute](https://www.thenewsminute.com/andhra-pradesh/andhra-govts-ordinance-on-sc-sub-classification-creates-three-sub-groups).
* Kerala: [Kerala PSC rules for reservation](https://www.keralapsc.gov.in/rules-reservation).
* Karnataka: [Campus Karnataka](https://campuskarnataka.com/reservation-categories/), [Deccan Herald](https://www.deccanherald.com/india/karnataka/karnataka-govt-rolls-out-new-quota-roster-general-category-share-down-to-44-3710562).
* Tamil Nadu: [TNPSC FAQ](https://tnpsc.gov.in/static_pdf/document/FAQ_English.pdf).
* Maharashtra: [PW](https://www.pw.live/state-psc/exams/reservation-in-mpsc).
* Bihar: [Drishti](https://www.drishtiias.com/state-pcs-current-affairs/bihar-s-new-domicile-rule-excludes-non-residents-from-women-s-quota).
* Punjab: [PSSSB ADA 2026](https://www.freejobalert.com/articles/psssb-ada-recruitment-2026-apply-online-for-170-assistant-district-attorney-posts-3046627).
* J&K: [Daily Excelsior](https://www.dailyexcelsior.com/reservation-for-oscs-ib-loc-up-rba-down-to-half-sc-sts-static/).
* Assam: [Sewa Setu](https://sewasetu.assam.gov.in/site/service-apply/issuance-of-backward-classes-obcmobc-certificate).
* West Bengal: [Karmasandhan](https://www.karmasandhan.com/wbpsc-obc-sub-category-wbcs-wbjs-miscellaneous/).
* Puducherry: [PGAC reservation](https://www.pgacpdy.in/reservation).
* Arunachal: [Arunachal Times](https://arunachaltimes.in/index.php/2026/07/07/reservation-policy/).
* Meghalaya: [Personnel Dept. roster](https://personnel.meghalaya.gov.in/Rules/R%20Roster.pdf).
* Nagaland: [DPAR ch. 9](https://dpar.nagaland.gov.in/chapter-9-reservation-in-services/).
* Uttarakhand: [India Code, Women's Reservation Act 2022](https://www.indiacode.nic.in/handle/123456789/19384?view_type=browse), [UKSSSC 2026](https://www.adda247.com/exams/uttarakhand/uksssc-inter-level-recruitment-2026/).
* Madhya Pradesh women 35%: [ANI](https://www.aninews.in/news/national/general-news/mp-cabinet-approves-35-pc-reservation-for-women-in-all-recruitments-of-state-govt-services20241105142320/).
* Himachal Pradesh: [HPPSC advertisement](http://www.hppsc.hp.gov.in/hppsc/WriteReadData/LINKS/HPAS%202025%20ADVT%20Maind525471b-62f2-4a75-b707-6f18926200e0.pdf).
* Delhi OBC: [DSSSB FAQ](https://dsssb.delhi.gov.in/faqs?page=1).
* Gujarat and Odisha SEBC: [Free Press Journal](https://www.freepressjournal.in/education/big-reservation-overhaul-odisha-raises-scst-quotas-introduces-1125-sebc-reservation-in-medical-technical-courses-from-202627).
* Sikkim BL: [Wikipedia, Bhutia-Lepcha](https://en.wikipedia.org/wiki/Bhutia-Lepcha).
* Central reservation (DoPT master circular, August 2026): [StaffNews](https://www.staffnews.in/2026/08/reservation-in-posts-and-services-in-the-central-government-dopt-master-circular.html).
* PwBD sub-classes: [RPwD Act 2016](https://www.tezu.ernet.in/PwD/RPWD-ACT-2016.pdf).
* 7th CPC pay matrix: [Salary-Calculator.in](https://salary-calculator.in/pay-matrix).
* PSU grades and IDA: [indianpaycalculator.in](https://www.indianpaycalculator.in/cpse-psu-salary-calculator); bank scales: [bankerkumar.com](https://www.bankerkumar.com/p/12th-bps-salary-officer.html).
* Appointment types: [UPSC, deputation and absorption](https://upsc.gov.in/about-us/divisions/appointment/appointment-deputation-absorption).
* Physical tests: [PW, SSC CPO selection](https://www.pw.live/ssc/exams/ssc-cpo-selection-process).
* JoSAA seat types and quotas: [RankMatrix](https://www.rankmatrix.in/guides/josaa-seat-matrix); MCC quotas: [Shiksha](https://www.shiksha.com/medicine-health-sciences/mcc-neet-counselling).
