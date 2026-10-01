"""Old ExamHub record + its fetched notices -> a record in the new format.

Every value comes from one of two places, and the record says which:

1. A notice fetched by ``scrapy crawl records`` and read by
   ``documents.structure`` (evidence method ``table`` or ``rule``, with the
   notice's URL, page and words).
2. The old ExamHub record, whose structured fields were taken from its own
   official source (evidence method ``manual``, citing that source). These
   are used only where no notice gave the value.

Anything neither gives takes the template's sentinel: ``not_announced`` when
no notification has been found for the cycle, ``unknown`` when one has and it
is silent. Nothing is invented and nothing is tuned per exam.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import tomllib
from pathlib import Path
from typing import Any

from .. import aliases as aliases_mod
from .. import catalogue, records
from .. import links as links_mod
from . import emit
from .schema import document, eligibility, evidence, fee_row, stage, window

log = logging.getLogger(__name__)
RECORDS = Path("work/records")
OUT = Path("site/content/exams")
REPORT = Path("work/convert-report.jsonl")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
HEAD = {'section': 'identity (pipeline)', 'title': 'titles (readers)',
        'purpose': 'who runs it, what it is', 'bodies': 'who runs it',
        'posts': 'posts and vacancies', 'pay': 'pay', 'service': 'terms of service',
        'dates': 'dates and stages', 'eligibility': 'eligibility', 'fee': 'fee',
        'exam_rules': 'exam-wide rules', 'links': 'links', 'provenance': 'provenance (never shown)'}

# How much a document is trusted to describe the cycle, by the kind the
# harvest gave its notice. A notification is the body's full statement.
DOC_RANK = {"notification": 0, "corrigendum": 1, "schedule": 1, "press_release": 2, "source": 3,
            "official": 4, "linked": 3, "calendar": 3, "admit_card": 5, "answer_key": 5,
            "result": 5, "other": 4, "walk_in": 0, "syllabus": 4, "application_status": 5, "counselling": 5}
DOC_TYPE = {"notification": "notification", "corrigendum": "corrigendum", "schedule": "schedule",
            "press_release": "press_release", "admit_card": "admit_card", "answer_key": "answer_key",
            "result": "result", "calendar": "calendar", "syllabus": "syllabus",
            "walk_in": "notification"}  # a walk-in advertisement is the cycle's notification

STAGE_FORMAT = [
    (r"physical|pet|pst|pmt", "physical", "in_person"),
    (r"skill|trade|typing|steno", "skill", "in_person"),
    (r"interview|personality|viva", "interview", "in_person"),
    (r"document", "documents", "in_person"),
    (r"medical", "medical", "in_person"),
    (r"group discussion", "interview", "in_person"),
]


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------

def load_docs(slug: str) -> list[dict]:
    """The converted documents of one record, most trusted first."""
    d = RECORDS / slug
    rows = {}
    if (d / "manifest.jsonl").exists():
        for line in (d / "manifest.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("status") == "ok":
                rows[r["file"].rsplit(".", 1)[0]] = r
    docs = []
    for f in sorted(d.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        role = data.get("role", "")
        head = role.split(":", 1)[0]
        kind = role.split(":")[1] if head == "notice" else head
        data["doc_type"] = kind if head == "notice" else ("other" if head != "source" else "source")
        data["rank"] = DOC_RANK.get(kind, 4)
        data["title"] = role.split(":", 3)[3] if head == "notice" and role.count(":") >= 3 else ""
        docs.append(data)
    docs.sort(key=lambda x: x["rank"])
    return docs


_MATCHER = None


def catalogue_exam(record: dict) -> dict | None:
    global _MATCHER
    if _MATCHER is None:
        cat = catalogue.load()
        _MATCHER = (cat, catalogue.Matcher(cat))
    cat, matcher = _MATCHER
    hay = " ".join([record.get("title", ""), *record.get("known_as", [])])
    for body in records.body_ids(record):
        ids = matcher.match(body, hay)
        if len(ids) == 1:
            return cat.exams[ids[0]]
    return None


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def iso(s: Any) -> dt.date | None:
    if isinstance(s, dt.datetime):
        return s.date()
    if isinstance(s, dt.date):
        return s
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


class Evidence:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, field: str, url: str, page: Any, words: str, method: str) -> None:
        self.rows.append(evidence(field, url, page if isinstance(page, int) else 0,
                                  re.sub(r"\s+", " ", str(words or ""))[:300], method))


def first(docs: list[dict], getter) -> tuple[Any, dict] | tuple[None, None]:
    for d in docs:
        s = d.get("structure")
        if not s:
            continue
        try:
            v = getter(s)
        except (KeyError, IndexError, TypeError):
            v = None
        if v:
            return v, d
    return None, None


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------

def build(old: dict) -> tuple[dict, dict]:
    slug = old["slug"]
    docs = load_docs(slug)
    ev = Evidence()
    src = old["provenance"]["source_url"]
    notices = [d for d in docs if d.get("structure")]
    has_notification = any(d["doc_type"] in ("notification", "corrigendum") for d in notices)
    silent = "unknown" if has_notification else "not_announced"
    stats: dict[str, Any] = {"slug": slug, "docs": len(docs), "pdfs": len(notices),
                             "notification": has_notification, "filled": {}}

    def filled(name: str, how: str) -> None:
        stats["filled"][name] = how

    stats["check"] = {}

    def check(name: str, extracted: Any, examhub: Any) -> None:
        """Where the notice and the old record both give a value, compare."""
        if extracted in (None, "", [], set()) or examhub in (None, "", [], set()):
            return
        stats["check"][name] = {"ok": extracted == examhub, "notice": str(extracted), "examhub": str(examhub)}

    cat_exam = catalogue_exam(old)
    bodies = sorted(records.body_ids(old))

    # ── dates ──────────────────────────────────────────────────────────
    def date_of(key: str):
        return first(notices, lambda s: s["dates"][key])

    app_from = app_to = None
    app_status = silent
    v, d = date_of("registration_open")
    if v:
        app_from = iso(v["date"])
        ev.add("dates.application.from", d["url"], v.get("page"), v.get("evidence"), "table" if v.get("from") == "table" else "rule")
        if v.get("until"):
            app_to = iso(v["until"])
    v2, d2 = date_of("registration_deadline")
    if v2:
        app_to = iso(v2.get("until") or v2["date"])
        ev.add("dates.application.to", d2["url"], v2.get("page"), v2.get("evidence"), "table" if v2.get("from") == "table" else "rule")
    check("application.to", app_to, iso(old.get("registration_deadline")))
    check("application.from", app_from, iso(old.get("registration_open")))
    if app_from or app_to:
        filled("dates.application", "notice")
        prov = (v and v.get("provisional")) or (v2 and v2.get("provisional"))
        app_status = "tentative" if prov else "confirmed"
    else:
        o_from, o_to = iso(old.get("registration_open")), iso(old.get("registration_deadline"))
        if o_from or o_to:
            app_from, app_to = o_from, o_to
            app_status = "tentative" if "provisional" in (old.get("registration_open_status"), old.get("registration_deadline_status")) else "confirmed"
            ev.add("dates.application", src, 0, f"ExamHub record: registration {o_from} to {o_to}", "manual")
            filled("dates.application", "examhub")
    if app_from and not app_to:
        application = window(app_from, app_from, status=app_status)  # only the opening is known
        application["to"] = "unknown"
    elif app_to and not app_from:
        application = window(app_to, app_to, status=app_status)
        application["from"] = "unknown"
    elif app_from:
        application = window(app_from, app_to, status=app_status)
    else:
        application = window(status=silent)

    fee_payment = dict(application)
    v, d = date_of("payment_deadline")
    if v and iso(v["date"]):
        fee_payment = window(application.get("from") if isinstance(application.get("from"), dt.date) else iso(v["date"]),
                             iso(v["date"]), status=app_status)
        ev.add("dates.fee_payment.to", d["url"], v.get("page"), v.get("evidence"), "rule")
    elif old.get("payment_deadline"):
        fee_payment = window(app_from or iso(old["payment_deadline"]), iso(old["payment_deadline"]), status=app_status)
        ev.add("dates.fee_payment.to", src, 0, f"ExamHub record: payment_deadline {old['payment_deadline']}", "manual")

    correction = window(status=silent)
    v, d = date_of("correction_window")
    if v and iso(v["date"]):
        correction = window(iso(v["date"]), iso(v.get("until") or v["date"]), status="confirmed")
        ev.add("dates.correction", d["url"], v.get("page"), v.get("evidence"), "table")
        filled("dates.correction", "notice")

    # stages: from the selection paragraph, else one stage named for the exam
    names, d = first(notices, lambda s: s["selection"])
    names = names or []
    stages = []
    exam_d, exam_doc = date_of("exam_date")
    admit_d, admit_doc = date_of("admit_card_from")
    result_d, result_doc = date_of("result_date")
    mode_v, mode_doc = first(notices, lambda s: s["exam"]["mode"]["value"])
    mode = "unknown"
    mode_text = (mode_v or old.get("mode") or "").lower()
    if re.search(r"computer|cbt|online", mode_text):
        mode = "cbt"
    elif re.search(r"omr|offline|pen|paper", mode_text):
        mode = "omr" if "omr" in mode_text else "pen_paper"
    written_seen = False
    for i, name in enumerate(names or ["Examination"], start=1):
        fmt, smode = "written", mode
        for pat, f, m in STAGE_FORMAT:
            if re.search(pat, name, re.I):
                fmt, smode = f, m
                break
        purpose = "unknown"
        s = stage(name if names else ("Examination" if old.get("section") else name), i, fmt, smode, purpose,
                  minutes="unknown" if has_notification else "not_announced",
                  languages="unknown" if has_notification else "not_announced",
                  centres="unknown")
        for key in ("city_slip", "admit_card", "exam", "answer_key", "result"):
            s[key] = window(status=silent)
        if fmt == "written" and not written_seen:
            written_seen = True
            check("exam", iso(exam_d["date"]) if exam_d else None, iso(old.get("exam_date")))
            if exam_d and iso(exam_d["date"]):
                s["exam"] = window(iso(exam_d["date"]), iso(exam_d.get("until") or exam_d["date"]),
                                   status="tentative" if exam_d.get("provisional") else "confirmed")
                ev.add(f"dates.stages[{i}].exam", exam_doc["url"], exam_d.get("page"), exam_d.get("evidence"), "rule")
                filled("dates.exam", "notice")
            elif iso(old.get("exam_date")):
                s["exam"] = window(iso(old["exam_date"]), status="tentative" if old.get("exam_date_status") == "provisional" else "confirmed")
                ev.add(f"dates.stages[{i}].exam", src, 0, f"ExamHub record: exam_date {old['exam_date']}", "manual")
                filled("dates.exam", "examhub")
            if admit_d and iso(admit_d["date"]):
                s["admit_card"] = window(iso(admit_d["date"]), iso(admit_d.get("until") or admit_d["date"]))
                ev.add(f"dates.stages[{i}].admit_card", admit_doc["url"], admit_d.get("page"), admit_d.get("evidence"), "rule")
            elif iso(old.get("admit_card_from")):
                s["admit_card"] = window(iso(old["admit_card_from"]), status="tentative" if old.get("admit_card_from_status") == "provisional" else "confirmed")
                ev.add(f"dates.stages[{i}].admit_card", src, 0, f"ExamHub record: admit_card_from {old['admit_card_from']}", "manual")
        stages.append(s)
    if stages:
        last = stages[-1]
        if result_d and iso(result_d["date"]):
            last["result"] = window(iso(result_d["date"]))
            ev.add(f"dates.stages[{len(stages)}].result", result_doc["url"], result_d.get("page"), result_d.get("evidence"), "rule")
        elif iso(old.get("result_date")):
            last["result"] = window(iso(old["result_date"]), status="tentative" if old.get("result_date_status") == "provisional" else "confirmed")
            ev.add(f"dates.stages[{len(stages)}].result", src, 0, f"ExamHub record: result_date {old['result_date']}", "manual")
    if names:
        filled("stages", "notice")

    # ── posts ──────────────────────────────────────────────────────────
    vac, vd = first(notices, lambda s: s["vacancies"] if s["vacancies"].get("total") else None)
    post_rows = []
    total: Any = silent
    if vac:
        total = vac["total"]
        ev.add("posts.vacancies_total", vd["url"], vac.get("page"), vac.get("evidence") or "vacancy table", vac.get("from", "table") if vac.get("from") == "table" else "rule")
        filled("posts", "notice")
        for r in vac.get("rows", [])[:60]:
            post_rows.append({'post_name': r["label"][:120] or old["title"], 'post_code': 'none', 'post_unit': 'none',
                              'post_group': 'none', 'post_vacancy_kind': 'regular', 'post_pay_level': 'unknown',
                              'post_vacancies': r.get("total") or 'unknown',
                              'by_category': r["by_category"] or 'unknown'})
    if not post_rows:
        post_rows = [{'post_name': old["title"], 'post_code': 'none', 'post_unit': 'none', 'post_group': 'none',
                      'post_vacancy_kind': 'regular', 'post_pay_level': 'unknown',
                      'post_vacancies': total if vac else silent,
                      'by_category': (vac or {}).get("by_category") or silent}]
    purpose = (cat_exam or {}).get("purpose") or ("admission" if "Academic" in old.get("categories", []) else "recruitment")
    if purpose != "recruitment":
        total, post_rows = "none", [{'post_name': 'none', 'post_code': 'none', 'post_unit': 'none', 'post_group': 'none',
                                     'post_vacancy_kind': 'none', 'post_pay_level': 'none',
                                     'post_vacancies': 'none', 'by_category': 'none'}]
    posts = {'vacancies_total': total, 'vacancies_status': 'tentative' if vac else silent,
             'posts_per_candidate': 'unknown', 'posts_waiting_list_percent': 'unknown',
             'posts_join_in_batches': 'unknown', 'list': post_rows, 'groups': 'none'}

    # ── pay ────────────────────────────────────────────────────────────
    pay_rows = []
    pv, pd = first(notices, lambda s: s["pay"][0])
    op = old.get("pay") or {}
    if pv and (pv.get("low") or pv.get("levels")):
        ev.add("pay[1]", pd["url"], pv.get("page"), pv.get("evidence"), "rule")
        filled("pay", "notice")
        system = "pay_matrix" if pv.get("levels") else "scale"
        low, high = pv.get("low"), pv.get("high")
    elif op:
        ev.add("pay[1]", src, 0, f"ExamHub record: pay {op}", "manual")
        filled("pay", "examhub")
        system = {"pay_matrix": "pay_matrix"}.get(op.get("system"), "scale")
        low, high = op.get("low"), op.get("high")
        pv = {"levels": op.get("level"), "initial": op.get("initial")}
    if pv or op:
        pay_rows.append({'pay_posts': 'all', 'pay_during': 'service', 'pay_label': 'none', 'pay_system': system,
                         'pay_matrix_level': (pv.get("levels") or ['none'])[0] if isinstance(pv.get("levels"), list) else 'none',
                         'pay_grade_pay': 'none',
                         'pay_rupees': [low, high] if low and high else 'unknown',
                         'pay_increments': 'unknown', 'pay_initial': pv.get("initial") or 'unknown', 'pay_per': 'month',
                         'pay_allowances': 'unknown', 'pay_gross': 'unknown', 'pay_gross_where': 'none',
                         'pay_benefits': 'unknown'})
    if purpose != "recruitment":
        pay_rows = [{'pay_posts': 'none', 'pay_during': 'none', 'pay_label': 'none', 'pay_system': 'none',
                     'pay_matrix_level': 'none', 'pay_grade_pay': 'none', 'pay_rupees': 'none', 'pay_increments': 'none',
                     'pay_initial': 'none', 'pay_per': 'none', 'pay_allowances': 'none', 'pay_gross': 'none',
                     'pay_gross_where': 'none', 'pay_benefits': 'none'}]
    elif not pay_rows:
        pay_rows = [{'pay_posts': 'all', 'pay_during': 'service', 'pay_label': 'none', 'pay_system': silent,
                     'pay_matrix_level': silent, 'pay_grade_pay': 'none', 'pay_rupees': silent, 'pay_increments': silent,
                     'pay_initial': silent, 'pay_per': 'month', 'pay_allowances': silent, 'pay_gross': silent,
                     'pay_gross_where': 'none', 'pay_benefits': silent}]

    # ── eligibility ────────────────────────────────────────────────────
    sections: dict[str, dict] = {}
    age, ad = first(notices, lambda s: s["age"] if s["age"].get("limits") else None)
    if age:
        lim = next((l for l in age["limits"] if l.get("max")), age["limits"][0])
        as_of = iso(age.get("as_on"))
        a = {'applies': 'yes', 'age_min': lim.get("min") or 'unknown', 'age_max': lim.get("max") or 'unknown',
             'age_as_of': as_of or 'unknown', 'age_born_from': 'unknown', 'age_born_to': 'unknown'}
        if as_of and lim.get("max"):
            a['age_born_from'] = as_of.replace(year=as_of.year - lim["max"] - 1) + dt.timedelta(days=1)
        if as_of and lim.get("min"):
            a['age_born_to'] = as_of.replace(year=as_of.year - lim["min"])
        rel = [r for r in age.get("relaxations", []) if r.get("years") and r.get("categories")]
        if rel:
            a['relaxations'] = [{'relaxation_category': c, 'relaxation': f"+{r['years']}"}
                                for r in rel for c in r["categories"]][:20]
        sections['age'] = a
        ev.add("eligibility[1].age", ad["url"], lim.get("page"), lim.get("evidence"), "rule")
        filled("eligibility.age", "notice")
    levels, ld = first(notices, lambda s: s["eligibility"]["education_levels"])
    if levels:
        sections['education'] = {'applies': 'yes', 'education_options': [[LEVEL_WORDS.get(l, l)] for l in levels]}
        clause = next(iter(ld["structure"]["eligibility"].get("clauses") or []), {})
        ev.add("eligibility[1].education", ld["url"], clause.get("page"), clause.get("text"), "rule")
        filled("eligibility.education", "notice")
    if purpose != "recruitment":
        sections.setdefault('age', {'applies': 'unknown'})
    elig = [eligibility(**sections)]

    # ── fee ────────────────────────────────────────────────────────────
    rows = []
    fees, fd = first(notices, lambda s: s["fees"])
    if fees and old.get("fee"):
        check("fee.amounts", sorted({f["amount"] for f in fees}), sorted({f["amount"] for f in old["fee"]}))
    if fees:
        for f in fees[:20]:
            for c in f.get("categories") or ["all"]:
                rows.append(fee_row(c, f["amount"], gender=(f.get("gender") or "all").lower()))
        ev.add("fee.rows", fd["url"], fees[0].get("page"), fees[0].get("raw"), "table" if fd["structure"].get("fees") else "rule")
        filled("fee", "notice")
    elif old.get("fee"):
        for f in old["fee"]:
            cats = [c.strip() for c in re.split(r"[/,]| and ", f.get("category", "all")) if c.strip()] or ["all"]
            for c in cats:
                rows.append(fee_row(c, f["amount"], gender=(f.get("gender") or "all").lower()))
        ev.add("fee.rows", src, 0, "ExamHub record: " + "; ".join(f"{f.get('category')} {f.get('amount')}" for f in old["fee"]), "manual")
        filled("fee", "examhub")
    if not rows:
        rows = [fee_row("all", silent)]
    fee = {'fee_refundable': 'unknown', 'fee_bank_charges_extra': 'unknown', 'fee_payment_modes': 'unknown', 'rows': rows}

    # ── links and documents ────────────────────────────────────────────
    docs_out = []
    seen = set()
    for dd in docs:
        if dd["url"] in seen or dd.get("kind") != "pdf" and dd["doc_type"] != "source":
            continue
        seen.add(dd["url"])
        docs_out.append(document(DOC_TYPE.get(dd["doc_type"], "other"), dd["url"]))
    if not docs_out:
        docs_out = [document("other", src)]

    title_year = re.findall(r"20\d\d(?:-\d\d)?", old.get("title", "") + " " + slug)
    # the old record's own check time, so converting again gives the same file
    prov = old.get("provenance") or {}
    stamp = lambda k: (dt.datetime.fromisoformat(prov[k]) if prov.get(k) else dt.datetime.now(IST).replace(microsecond=0))
    rec = {
        'section': 'exams',
        'exam_id': (cat_exam or {}).get("id") or 'unknown',
        'cycle': title_year[-1] if title_year else 'unknown',
        'cycle_status': 'active',
        'title': old["title"],
        'slug': slug,
        'title_official': old["title"],
        'title_series': (cat_exam or {}).get("short_name") or (cat_exam or {}).get("name") or 'unknown',
        'title_aliases': old.get("known_as") or 'none',
        'purpose': purpose,
        'streams': (cat_exam or {}).get("streams") or 'unknown',
        'recruitment_engagement': 'unknown' if purpose == "recruitment" else 'none',
        'recruitment_drive': 'unknown' if purpose == "recruitment" else 'none',
        'recruitment_drive_for': 'all' if purpose == "recruitment" else 'none',
        'bodies': [{'body': b, 'body_role': 'conducts'} for b in (bodies[:1] or old.get("bodies", [])[:1])],
        'posts': posts,
        'pay': pay_rows,
        'service': {k: ('unknown' if purpose == "recruitment" else 'none') for k in (
            'service_bond_months', 'service_bond_amount', 'service_probation_months',
            'service_probation_extendable_months', 'service_probation_exam', 'service_training_cost',
            'service_contract_months', 'service_first_posting_months', 'service_same_field_months',
            'service_same_field_posts', 'service_posting_area')},
        'dates': {'city_slip_separate': 'unknown', 'application': application, 'fee_payment': fee_payment,
                  'late_fee': window(status=silent), 'correction': correction, 'stages': stages},
        'eligibility': elig,
        'fee': fee,
        'exam_rules': {'centre_places': 'unknown', 'centre_choice': 'unknown', 'centre_choices_max': 'unknown',
                       'centre_allotment': 'unknown', 'centre_guaranteed': 'unknown', 'centre_change_allowed': 'unknown',
                       'scribe_allowed': 'unknown', 'scribe_extra_minutes_per_hour': 'unknown',
                       'scores_normalised': 'unknown', 'tie_break_order': 'unknown', 'training_offered_for': 'unknown'},
        'links': {'link_official_page': old.get("official_url") or 'unknown',
                  'link_apply': old.get("apply_url") or 'unknown', 'documents': docs_out},
        'provenance': {'provenance_retrieved': stamp("timestamp_retrieved"),
                       'provenance_last_checked': stamp("timestamp_last_checked"),
                       'evidence': ev.rows or [evidence('none', src, 0, 'nothing extracted', 'rule')]},
    }
    # a file given as the official page goes to the documents; the page is the exam's or body's
    links_mod.fix(rec, catalogue.load())
    # ExamHub's other names sometimes named a different kind of exam (KTET on KSET)
    bad = aliases_mod.wrong(rec, catalogue.load())
    if bad:
        rec["title_aliases"] = [a for a in rec["title_aliases"] if a not in bad] or "none"
    return rec, stats


LEVEL_WORDS = {"Doctorate": "Doctorate (PhD)", "Postgraduate": "Postgraduate degree",
               "Graduate": "Graduate degree", "Diploma / ITI": "Diploma or ITI",
               "Class 12": "Class 12 pass", "Class 10": "Class 10 pass"}


#: when the old records were first converted; every file then carried this stamp
IMPORTED_AT = dt.datetime(2026, 9, 30, 5, 32, 42, tzinfo=IST)


def _newer(path: Path, rec: dict) -> bool:
    """Whether the file on disk was checked after the old record and after the first
    import: the recheck updated it, and converting again would throw that away."""
    try:
        on_disk = tomllib.loads(path.read_text("utf-8").strip().strip("+").strip())["provenance"]["provenance_last_checked"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return False
    return on_disk > max(rec["provenance"]["provenance_last_checked"], IMPORTED_AT)


def run(only: set[str] | None = None, force: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for old in records.load_records():
        if only and old["slug"] not in only:
            continue
        try:
            rec, stats = build(old)
            text = emit.dump(rec, HEAD)
            tomllib.loads(text.strip().strip("+").strip())
        except Exception as exc:
            log.exception("%s failed", old["slug"])
            reports.append({"slug": old["slug"], "error": repr(exc)[:300]})
            continue
        path = OUT / f"{old['slug']}.md"
        if not force and _newer(path, rec):
            log.info("%s: kept, the file was checked after the old record (use --force)", old["slug"])
            continue
        path.write_text(text, encoding="utf-8")
        reports.append(stats)
    with REPORT.open("w", encoding="utf-8") as fh:
        for r in reports:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    ok = [r for r in reports if "error" not in r]
    counts: dict[str, dict[str, int]] = {}
    for r in ok:
        for k, how in r["filled"].items():
            counts.setdefault(k, {}).setdefault(how, 0)
            counts[k][how] += 1
    log.info("%d records written, %d failed", len(ok), len(reports) - len(ok))
    log.info("with a notification: %d; with any PDF: %d",
             sum(r["notification"] for r in ok), sum(1 for r in ok if r["pdfs"]))
    for k, v in sorted(counts.items()):
        log.info("  %-24s %s", k, v)
    agree: dict[str, list[int]] = {}
    for r in ok:
        for k, c in r.get("check", {}).items():
            agree.setdefault(k, [0, 0])[0 if c["ok"] else 1] += 1
    for k, (a, b) in sorted(agree.items()):
        log.info("  check %-18s agree %d, disagree %d", k, a, b)
