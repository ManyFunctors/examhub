# Eligibility rules: which ones, from the data

Research for the ExamHub exam template's `[[eligibility]]` block, 29 September
2026.

## Method

* **Notices:** 230 notification PDFs sampled from the harvest (2024 onwards,
  up to 3 per body, 90 bodies) plus the 33 cached ones. 152 downloaded; 73 had
  a text layer and an eligibility section (the rest are scans; OCR not run).
* **ExamHub:** the `eligibility` prose of all 310 exam pages.
* A keyword pattern per rule, counted per document. The counts are rough (a
  word such as "medical" or "experience" also appears outside eligibility),
  so they show which rules exist and roughly how common each is, not exact
  rates.
* Online checks for rules the sample is too small to show.

## Counts

| Rule | Notices (n=73) | ExamHub (n=310) | Note |
|---|---|---|---|
| education | 83% | 67% | degree, diploma, 10+2 |
| medical | 79% | 24% | noisy; fitness, eyesight, colour blindness |
| age | 58% | 47% | |
| final-year / result awaited | 58% | 15% | noisy |
| experience | 58% | 10% | noisy |
| registration (council, bar) | 38% | 7% | |
| nationality | 34% | 6% | |
| minimum marks / CGPA | 34% | 6% | |
| character, criminal record | 32% | 0% | |
| physical standards | 31% | 11% | police, defence, forest |
| govt employee (NOC, in-service) | 30% | 2% | |
| age relaxation | 28% | 5% | |
| domicile | 24% | 9% | |
| marital status | 17% | 2% | Agniveer, NDA, some state posts |
| computer certificate, typing | 15% | 1% | CCC (UP), CPCT (MP), O level |
| desirable qualification | 12% | 0% | |
| bond / service agreement | 10% | 1% | a condition of service, not eligibility |
| required score (GATE, NET, CTET) | 9% | 4% | |
| NCC / sports | 8% | 1% | |
| employment exchange | 4% | 0% | |
| attempts | 2% | 0% | UPSC CSE, CDS etc. |
| tattoo | 2% | 0% | defence |
| two-child norm | 0% | 0% | law in Rajasthan and Assam (see below) |
| women-only / men-only | 0% | 1% | ANM, Mahila constable |

## Found online

* **Two-child norm.** Rajasthan bars candidates with more than two children
  (born on or after 1 June 2002) from government jobs; upheld by the Supreme
  Court in 2024. Assam applies it from 1 January 2021.
  ([ThePrint](https://theprint.in/india/sc-upholds-rajasthans-2-child-norm-for-govt-jobs/1983408/),
  [Business Standard](https://www.business-standard.com/india-news/two-child-norm-for-govt-jobs-in-rajasthan-gets-supreme-court-approval-124022900564_1.html),
  [Tribune](https://www.tribuneindia.com/news/archive/assam-s-2-child-norm-for-jobs-from-2021-850906))
* **Computer certificates.** UPSSSC requires CCC for Lekhpal, VDO and others;
  MP requires a CPCT score for clerical and data-entry posts.
  ([UPSeva](https://upseva.in/news/upsssc-ganna-paryavekshak-sugarcane-supervisor-recruitment-2026/),
  [RojgarDekho](https://rojgardekho.in/article/upsssc-lekhpal-eligibility-2026),
  [Testbook, MP CPCT](https://testbook.com/mp-cpct))
* **Marital status and tattoos.** Agniveer Vayu takes only unmarried
  candidates, who undertake not to marry during the four years; permanent
  tattoos are barred except in set places and for tribal custom.
  ([IAF Agniveer Vayu 02/2025](https://agnipathvayu.cdac.in/AV/img/upcoming/AGNIVEER_VAYU_02-2025.pdf))

## Proposed list

In the order a candidate checks themselves: who you are, where you are from,
your age, what you studied, what else you hold, your body, your record, your
limits.

| Key | Holds | Why it is its own rule |
|---|---|---|
| `eligibility_posts` | the posts this block covers | decided |
| `eligibility_nationality` | Indian; others allowed (Nepal, Bhutan, Tibetan refugee, PIO) | 34% |
| `eligibility_domicile` | state residence, and what other-state candidates may do | 24% |
| `eligibility_gender` | women-only or men-only posts | rare but decisive |
| `eligibility_marital` | unmarried only; not more than one spouse | 17%; decisive for defence |
| `eligibility_children` | two-child norm | state law (Rajasthan, Assam) |
| `eligibility_age` | min, max, as-on date, resolved per class (relaxations included) | 58% |
| `eligibility_education` | alternatives, minimum marks, final-year allowed, desirable | 83% |
| `eligibility_score` | a valid score in another exam (GATE, NET, CTET, CPCT) | 9%; decisive |
| `eligibility_certificates` | CCC, O level, typing, NCC, sports certificates | 15% |
| `eligibility_registration` | council or bar registration | 38% |
| `eligibility_experience` | years, in what | common in specialist posts |
| `eligibility_language` | knowledge of the state language | TN, KA, WB, MH etc.; undercounted (their PDFs are often scans) |
| `eligibility_physical` | height, chest, weight, run; per gender and class | 31% |
| `eligibility_medical` | fitness, eyesight, colour vision, tattoos | common |
| `eligibility_service` | serving govt employees: NOC, departmental only, in-service | 30% |
| `eligibility_character` | no criminal conviction; character certificate | 32% |
| `eligibility_attempts` | maximum attempts, per class | rare but decisive (UPSC) |
| `eligibility_other` | anything else, verbatim (employment exchange registration, ...) | catch-all |

Left out: **bond / service agreement** (a condition after selection, not who
can apply; belongs with pay and service terms).

## Second pass: more candidates

| Rule | Notices (n=73) | Where it goes |
|---|---|---|
| category certificate rules (format, issued after a date, creamy layer) | 45% | **new: `eligibility_class_proof`** |
| debarred, dismissed from service | 35% | `eligibility_character` |
| driving licence | 17% | `eligibility_certificates` (certificates and licences) |
| posts suitable for which disabilities (OA, OL, VH, HH ...) | 13% | **new: `eligibility_disability`** |
| subjects studied (PCM, PCB, a main subject) | 8% | `eligibility_education` |
| year of passing | 2% | `eligibility_education` |
| swimming | 0% | not needed |

* `eligibility_class_proof`: what a candidate must hold to claim a reserved
  category: the certificate format, the date it must be issued after (OBC-NCL,
  EWS), the creamy-layer rule. Candidates are rejected at document
  verification for exactly this.
* `eligibility_disability`: which disabilities each post is identified as
  suitable for, and the functional requirements. A PwBD candidate cannot
  apply for a post not identified for their disability.

## Third pass: admission and professional exams

The notice sample was mostly recruitment, so three admission and professional
exams were checked online:

* **NEET UG:** NRIs, OCIs, PIOs and foreign nationals may apply
  (`eligibility_nationality` must allow more than "Indian"); minimum marks
  differ by class (50% general, 40% SC/ST/OBC, 45% PwBD), so
  `eligibility_education` needs marks per class; no attempt limit.
  ([Careers360](https://medicine.careers360.com/article/24103),
  [Allen](https://allen.in/neet/eligibility-criteria))
* **JEE Main:** Class 12 passed in the last two years or appearing
  (year of passing, in `eligibility_education`); three consecutive years
  (`eligibility_attempts` counted in years, not only attempts). The 75% rule is
  for admission to NITs, not for sitting the exam: some notices state rules that
  apply later (admission, appointment); these are recorded with a note saying
  when they apply, not as separate rules.
  ([PW](https://www.pw.live/news/jee-main-2026-eligibility-criteria-age-limit-attempt-rules-75-marks-rule),
  [Shiksha](https://www.shiksha.com/engineering/articles/jee-main-eligibility-blogId-19629))
* **CA Final:** both groups of CA Intermediate passed (another exam passed,
  so `eligibility_score` generalises to `eligibility_prior_exam`); articleship
  completed or in its last six months (training counts as
  `eligibility_experience`); AICITSS course done (`eligibility_certificates`).
  ([PW](https://www.pw.live/ca/exams/ca-final-eligibility),
  [Careers360](https://news.careers360.com/icai-announcement-ca-final-eligibility-criteria-out-september-2025-january-2026-exams-spom-articleship-aicitss-exemptions))

## Final list (21 keys)

Grouped in the order a candidate checks themselves. Names follow the
general-first rule.

| # | Key | Holds |
|---|---|---|
| | *who the block is for* | |
| 1 | `eligibility_posts` | the posts this block covers, or `'all'` |
| | *who you are* | |
| 2 | `eligibility_nationality` | Indian; also Nepal, Bhutan, Tibetan refugee, PIO, OCI, NRI, foreign nationals |
| 3 | `eligibility_domicile` | state or district residence; what other-state candidates may do |
| 4 | `eligibility_gender` | women-only or men-only posts |
| 5 | `eligibility_marital` | unmarried only; not more than one living spouse |
| 6 | `eligibility_children` | two-child norm |
| 7 | `eligibility_age` | min, max, as-on date, resolved per class |
| | *what you have done* | |
| 8 | `eligibility_education` | alternatives; subjects; minimum marks per class; year of passing; final-year allowed; desirable |
| 9 | `eligibility_prior_exam` | another exam passed or a valid score: GATE, NET, CTET, CPCT, CA Intermediate |
| 10 | `eligibility_certificates` | certificates and licences: CCC, O level, typing, NCC, sports, driving licence, required courses |
| 11 | `eligibility_registration` | council, bar or institute registration |
| 12 | `eligibility_experience` | years and field; training such as articleship |
| 13 | `eligibility_language` | knowledge of the state language |
| | *your body* | |
| 14 | `eligibility_physical` | height, chest, weight, run; per gender and class |
| 15 | `eligibility_medical` | fitness, eyesight, colour vision, tattoos |
| 16 | `eligibility_disability` | disabilities each post is suitable for; functional requirements |
| | *your record* | |
| 17 | `eligibility_employment` | serving staff: NOC, departmental candidates only, in-service |
| 18 | `eligibility_character` | no conviction; not debarred or dismissed; character certificate |
| | *your limits* | |
| 19 | `eligibility_attempts` | maximum attempts, or years, per class |
| | *proof* | |
| 20 | `eligibility_category_proof` | what claiming a category needs: certificate format, issued-after date, creamy layer |
| | *anything else* | |
| 21 | `eligibility_other` | anything no key above claims, verbatim |

Renamed while settling the list: `eligibility_score` → `eligibility_prior_exam`
(covers passing another exam, not only a score); `eligibility_service` →
`eligibility_employment` (clearer); `eligibility_class_proof` →
`eligibility_category_proof` (readers say "category").
