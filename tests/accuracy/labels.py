"""Hand-read answers for the notices in notices.json.

Each value was read from the notice by a person. A list holds every acceptable
answer; an empty list means the notice does not give that fact, so any pick is
wrong. Mode is cbt, omr or pen_paper.

Three sets, kept apart so a score says how it was earned:
  TUNED      the finder's rules were written against these
  HELD_OUT_1 labelled blind, then used for tuning (so no longer blind)
  HELD_OUT_2 labelled blind after the rules settled; the honest check
Add new notices to a fresh set, score them before changing any rule.
"""

FIELDS = ["registration_open", "registration_deadline", "payment_deadline", "admit_card_from",
          "admit_card_to", "exam_date", "result_date", "vacancies", "age_as_on", "mode"]


def L(**kw):
    out = {f: [] for f in FIELDS}
    for k, v in kw.items():
        out[k] = v if isinstance(v, list) else [v]
    return out

TUNED = {
    # UPSC Advt 12/2026: 4 posts (1+8+3+1), selection by interview; no exam date
    "0eb820f2": L(registration_open="2026-09-26", registration_deadline="2026-10-16",
                  vacancies="13", age_as_on=["2026-10-16"]),
    # UPSC Advt 11/2026: 7 posts (4+60+2+1+1+140+4); Ladakh post closes 09-10
    "def1f3b5": L(registration_open="2026-09-12", registration_deadline=["2026-10-02", "2026-10-09"],
                  vacancies="212", age_as_on=["2026-10-02"]),
    # SBI Junior Associates 2026: prelims "September 2026" (month only), online test
    "f461364d": L(registration_open="2026-08-11", registration_deadline="2026-08-31",
                  payment_deadline="2026-08-31", vacancies="7680", age_as_on="2026-04-01", mode="cbt"),
    # DSSSB 01/2026: grand total 911, CBT
    "1c6c8827": L(registration_open="2026-02-24", registration_deadline="2026-03-25",
                  payment_deadline=["2026-03-25"], vacancies="911", age_as_on="2026-03-25", mode="cbt"),
    # DSSSB 02/2026: total 216, CBT
    "0af20d27": L(registration_open="2026-02-27", registration_deadline="2026-03-28",
                  payment_deadline=["2026-03-28"], vacancies="216", age_as_on="2026-03-28", mode="cbt"),
    # SLPRB AP constables (communications): dates "notified separately"; 200 + 1 backlog; OMR
    "abd145b4": L(vacancies=["200", "201"], age_as_on="2026-07-01", mode="omr"),
    # SLPRB AP SI 2026: dates notified separately; total 378; OMR
    "edcc3cb6": L(vacancies="378", age_as_on="2026-07-01", mode="omr"),
    # ITBP HC Motor Mechanic 2026: CBT or OMR "at discretion", so mode is not given
    "2e3fa545": L(registration_open="2026-09-28", registration_deadline="2026-10-27",
                  vacancies="21", age_as_on="2026-10-27"),
    # ITBP HC Education & Stress Counsellor 2026
    "06d9abb3": L(registration_open="2026-09-28", registration_deadline="2026-10-27",
                  vacancies="16", age_as_on="2026-10-27"),
    # Union Bank apprentices 2025: 2691 seats; fee date "as notified"; online test
    "74856a28": L(registration_open="2025-02-19", registration_deadline="2025-03-05",
                  vacancies="2691", age_as_on="2025-02-01", mode="cbt"),
    # Union Bank wealth managers 2025: age cut-off = 1st of the month registration opens
    "2b2791b0": L(registration_open="2025-08-05", registration_deadline="2025-08-25",
                  payment_deadline="2025-08-25", vacancies="250", age_as_on="2025-08-01", mode="cbt"),
    # CAT 2026: result "first week of January, 2027" (no day)
    "ab6b2bc7": L(registration_open="2026-08-03", registration_deadline="2026-09-15",
                  admit_card_from="2026-11-04", admit_card_to="2026-11-29", exam_date="2026-11-29", mode="cbt"),
    # JEE Advanced 2026: two registration tracks; the text ends before the results section
    "c0e6ca98": L(registration_open=["2026-04-23", "2026-04-06"], registration_deadline="2026-05-02",
                  payment_deadline="2026-05-04", admit_card_from="2026-05-11", admit_card_to="2026-05-17",
                  exam_date="2026-05-17", mode="cbt"),
    # NEST 2026: merit list "by June 25, 2026"
    "ee5f7920": L(registration_open="2026-01-05", registration_deadline="2026-04-06",
                  payment_deadline="2026-04-12", admit_card_from="2026-05-15", exam_date="2026-06-06",
                  result_date="2026-06-25", mode="cbt"),
    # Maharashtra SET July 2026: late-fee window to 19.06; OMR
    "ce7019b7": L(registration_open="2026-06-02", registration_deadline="2026-06-16",
                  payment_deadline=["2026-06-16", "2026-06-19"], admit_card_from="2026-07-17",
                  exam_date="2026-07-26", mode="omr"),
    # APSSB 05/25 (scan, OCR): opening date garbled ("04-{19-2025"); total 239; exam "tentative"
    "514e275c": L(registration_open="2025-09-04", registration_deadline="2025-09-30",
                  exam_date="2025-12-07", vacancies="239", age_as_on="2025-09-30"),
    # APSSB special drive 2026 (scan, OCR): total 984
    "b6dc1299": L(registration_open="2026-03-23", registration_deadline="2026-04-10",
                  exam_date="2026-05-10", vacancies="984", age_as_on="2026-04-10"),
    # Coal India MT 01/2026: GATE score, no exam of its own
    "594c6c7c": L(registration_open="2026-05-08", registration_deadline="2026-06-07",
                  vacancies="276", age_as_on="2026-04-30"),
    # SBI JA backlog drive 2026: total 1538; prelims "Sep 2026" (month only)
    "5679ecee": L(registration_open="2026-08-07", registration_deadline="2026-08-27",
                  payment_deadline="2026-08-27", vacancies="1538", age_as_on="2026-04-01", mode="cbt"),
    # Meghalaya PSC 16/2025 (Typist): closing date only; age "with reference to 01.01.2025"; 32 posts
    "4626389e": L(registration_deadline="2025-08-16", vacancies="32", age_as_on="2025-01-01"),
    # IIT Kanpur Olympiad admission 2026-27: CBT on 24 June, result 27 June
    "51facc5e": L(registration_open="2026-05-25", registration_deadline="2026-06-15",
                  exam_date="2026-06-24", result_date="2026-06-27", mode="cbt"),
    # BCECE PGMAC 2025 stray round: counselling, no exam; allotment result 26.02.2026
    "3441ed8a": L(registration_open="2026-02-23", registration_deadline="2026-02-25",
                  payment_deadline="2026-02-25", result_date=["2026-02-26"]),
    # AP High Court: a gender-sensitisation handbook, not a notice; every field absent
    "dd80e4f6": L(),
    # NE SLET 2025-26 brochure: no dates in the text; OMR
    "815260b6": L(mode="omr"),
}

HELD_OUT_1 = {
    # Read blind, then used for tuning.
    # CRPF constable: correction-window notice only
    "062e19b6": L(),
    # Manipur PSC Advt 04/2025: text stops before the dates; grand total 4
    "4bc6bd5a": L(vacancies="4"),
    # FACT corrigendum: shortlist for interview, no facts of the exam
    "c8703a69": L(),
    # TN MRB Pharmacist (Homoeopathy) 2018: offline fee till 07.03
    "9dbd6968": L(registration_deadline="2018-03-05", payment_deadline=["2018-03-07", "2018-03-05"],
                  vacancies="23", age_as_on="2018-07-01"),
    # TNFWCCB contractual posts: 11 positions, interview only
    "7aeab7ce": L(registration_deadline="2026-09-19", vacancies="11"),
    # NICL AO 2023-24: 274 posts, online exam, exam dates later
    "5dc69336": L(registration_open="2024-01-02", registration_deadline="2024-01-22",
                  payment_deadline="2024-01-22", vacancies="274", age_as_on="2023-12-01", mode="cbt"),
    # CTET September 2026: OMR answer sheet
    "7992d43c": L(registration_open="2026-05-11", registration_deadline="2026-06-10",
                  payment_deadline="2026-06-10", exam_date="2026-09-06", mode=["omr", "pen_paper"]),
    # IOB specialist officers 2025: 127 vacancies, online exam
    "1fe5246c": L(registration_open="2025-09-12", registration_deadline="2025-10-03",
                  payment_deadline="2025-10-03", vacancies="127", age_as_on="2025-09-01", mode="cbt"),
    # Coal India industrial trainees: age on the 1st of the advert's month
    "cb246f3b": L(registration_open="2025-12-26", registration_deadline="2026-01-15",
                  vacancies="125", age_as_on="2025-12-01"),
    # JKBOPEE M.Sc Nursing 2023: test tentatively 06-08-2023
    "3ec633d8": L(exam_date="2023-08-06"),
    # OJEE 2026: CBT from 4 May; the only age date is B.Sc Nursing's
    "eb510bec": L(registration_open="2026-01-28", registration_deadline="2026-03-22",
                  admit_card_from="2026-04-25", exam_date="2026-05-04", age_as_on="2026-12-31", mode="cbt"),
    # Bundelkhand University JRF: 2 posts, walk-in interview
    "3da747b5": L(registration_deadline="2026-02-17", vacancies="2", age_as_on="2026-02-17"),
}

HELD_OUT_2 = {
    # Read blind after the rules settled; not tuned on.
    # Meghalaya ANM training: screening 18 & 19 July 2024
    "3b416e6f": L(exam_date="2024-07-18"),
    # IOB counsellor: resume on or before 31.05.2024
    "1c4c765c": L(registration_deadline="2024-05-31"),
    # SRCC guest faculty: 3 + 1 vacancies
    "57973b3f": L(registration_deadline="2021-01-29", vacancies="4"),
    # CIL explosives enlistment: two deadlines by product
    "05023429": L(registration_deadline=["2025-01-31", "2025-04-30"]),
    # Meghalaya HC: advertisement recalled
    "2e5d4334": L(),
    # NICL CISO: 1 post, age as on 01-07-2026
    "22186563": L(registration_open="2026-07-15", registration_deadline="2026-07-31",
                  vacancies="1", age_as_on="2026-07-01"),
    # MRB certificate verification schedule
    "057bf781": L(),
    # Tele-MANAS contract posts: five posts of one each; age on the last date
    "6ec54515": L(registration_deadline="2026-09-30", vacancies="5", age_as_on="2026-09-30"),
    # TNPSC Laboratory Assistant 2019: OMR
    "9d81d947": L(registration_deadline="2019-05-20", payment_deadline="2019-05-22",
                  exam_date="2019-06-22", vacancies="1", age_as_on="2019-07-01", mode="omr"),
    # Madras HC final key: exam held 16.10.2022 on OMR sheets
    "0938b426": L(exam_date="2022-10-16", mode="omr"),
    # Meghalaya HC System Analyst: written exam 17.01.2026
    "363c9f19": L(exam_date="2026-01-17"),
}

SETS = {"tuned": TUNED, "held_out_1": HELD_OUT_1, "held_out_2": HELD_OUT_2}
