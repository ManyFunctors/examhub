"""Builders that return template blocks with every key present (decision 14).

Callers pass only what the notice says; everything else takes the sentinel
the template gives for "the notice does not say".
"""

import copy


def window(frm=None, to=None, status=None, change='none', changed_from='none'):
    d = {}
    if frm is not None:
        d['from'] = frm
        d['to'] = to if to is not None else frm
    d['status'] = status or ('confirmed' if frm is not None else 'not_announced')
    d['change'] = change
    d['changed_from'] = changed_from
    return d


def marking(qtype='mcq', correct=1, unanswered=0, wrong=0, unit='marks', partial='no'):
    return {
        'marking_question_type': qtype,
        'marking_unit': unit,
        'marking_correct': correct,
        'marking_unanswered': unanswered,
        'marking_wrong': wrong,
        'marking_partial': partial,
    }


def part(name, marks, minutes='none', questions='unknown', languages='unknown',
         taken='compulsory', subjects='none', qualifying='no', min_marks='none',
         posts='all', marks_rules=None):
    return {
        'part_name': name,
        'part_posts': posts,
        'part_taken': taken,
        'part_subjects': subjects,
        'part_questions': questions,
        'part_marks': marks,
        'part_minutes': minutes,
        'part_languages': languages,
        'part_qualifying': qualifying,
        'part_min_marks': min_marks,
        'part_marking': marks_rules or [marking()],
    }


def stage(name, number, fmt, mode, purpose, posts='all', conditions='none',
          minutes='not_announced', languages='not_announced', parts_choose='none',
          centres='as_exam', shortlist_times='none', merit_weight='none',
          min_marks='none', city_slip=None, admit_card=None, exam=None,
          answer_key=None, result=None, parts=None):
    d = {
        'stage_name': name,
        'stage_number': number,
        'stage_format': fmt,
        'stage_mode': mode,
        'stage_purpose': purpose,
        'stage_posts': posts,
        'stage_conditions': conditions,
        'stage_minutes': minutes,
        'stage_languages': languages,
        'stage_centres': centres,
        'stage_shortlist_times': shortlist_times,
        'stage_merit_weight': merit_weight,
        'stage_min_marks': min_marks,
        'stage_parts_choose': parts_choose,
    }
    if not parts:
        d['stage_parts'] = 'none'
    d['city_slip'] = city_slip or window()
    d['admit_card'] = admit_card or window()
    d['exam'] = exam or window()
    d['answer_key'] = answer_key or window()
    d['result'] = result or window()
    if parts:
        d['stage_parts'] = parts
    return d


ELIGIBILITY = {
    'eligibility_posts': 'all',
    'eligibility_parts': 'all',
    'nationality': {'applies': 'unknown', 'nationality_allowed': 'unknown'},
    'domicile': {'applies': 'no', 'domicile_area': 'none', 'domicile_places': 'none',
                 'domicile_other_states': 'eligible'},
    'gender': {'applies': 'no', 'gender_allowed': 'all'},
    'marital': {'applies': 'no', 'marital_rules': 'none'},
    'children': {'applies': 'no', 'children_max': 'none', 'children_counted_from': 'none'},
    'age': {'applies': 'unknown', 'age_as_of': 'unknown', 'age_min': 'unknown',
            'age_max': 'unknown', 'age_born_from': 'unknown', 'age_born_to': 'unknown',
            'age_relaxation_cumulative': 'unknown', 'age_relaxation_max_age': 'none',
            'relaxations': 'none', 'age_by_category': 'none'},
    'education': {'applies': 'unknown', 'education_options': 'unknown',
                  'education_held_by': 'unknown', 'education_final_year': 'unknown',
                  'education_passed_from': 'none', 'education_passed_to': 'none',
                  'education_equivalent': 'unknown', 'education_desirable': 'none',
                  'education_marks': 'none'},
    'prior_exam': {'applies': 'no', 'prior_exam_options': 'none'},
    'certificates': {'applies': 'no', 'certificates_required': 'none'},
    'registration': {'applies': 'no', 'registrations_required': 'none'},
    'experience': {'applies': 'no', 'experience_required': 'none'},
    'language': {'applies': 'no', 'languages_required': 'none'},
    'physical': {'applies': 'no', 'physical_standards': 'none'},
    'medical': {'applies': 'no', 'vision_better_eye': 'none', 'vision_worse_eye': 'none',
                'vision_glasses_allowed': 'unknown', 'colour_blind_allowed': 'unknown',
                'defects_barred': 'none', 'tattoos_allowed': 'unknown',
                'medical_category': 'none', 'medical_guidelines': 'none'},
    'disability': {'applies': 'unknown', 'disability_suitable': 'unknown',
                   'disability_functional': 'none'},
    'employment': {'applies': 'no', 'employment_noc_needed': 'none',
                   'employment_via_employer': 'no', 'employment_resign_if_selected': 'no',
                   'employment_serving_only': 'no', 'employment_service_years': 'none',
                   'employment_service_in': 'none'},
    'character': {'applies': 'unknown', 'character_checks': 'unknown'},
    'attempts': {'applies': 'no', 'attempts_counted': 'none',
                 'attempts_by_category': [{'attempts_category': 'all', 'attempts_max': 'unlimited'}]},
    'category_proof': {'applies': 'no', 'category_certificates': 'none'},
    'other': {'applies': 'no', 'other_rules': 'none'},
}


def eligibility(**sections):
    """sections: section name -> dict of keys to override (merged into defaults)."""
    e = copy.deepcopy(ELIGIBILITY)
    for k, v in sections.items():
        if isinstance(e.get(k), dict):
            e[k].update(v)
        else:
            e[k] = v
    # list-valued sub-blocks go after scalars; emit.py already orders them
    return e


def fee_row(category, rupees, gender='all', posts='all', stage='all', per='application',
            includes='none'):
    return {'fee_category': category, 'fee_gender': gender, 'fee_posts': posts,
            'fee_stage': stage, 'fee_rupees': rupees, 'fee_per': per, 'fee_includes': includes}


def document(dtype, url, published='unknown', stage='all', archive='not_archived'):
    return {'document_type': dtype, 'document_stage': stage, 'document_published': published,
            'document_url': url, 'document_archive': archive}


def evidence(field, document, page, words, method='manual'):
    return {'evidence_field': field, 'evidence_document': document, 'evidence_page': page,
            'evidence_words': words, 'evidence_method': method}
