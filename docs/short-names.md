# Short names

Filled automatically: `examhub-pipeline names --apply` runs in the nightly recheck (`.github/workflows/recheck.yml`)
and sets `title` from, in order, the catalogue short name, the first alias, or the notice name with filler cut.
It only touches records whose `title` still equals `title_official`, so a title set by hand is never changed.

Regenerate this list with `examhub-pipeline names` (dry run).

## Left as is: no short name fits in 48 characters

Name these by hand (set `title`).

| File | Official name |
|---|---|
| d4-ts-tslprb-police-constable-civil-equivalent-2026 | Police Recruitment 2026: Stipendiary Cadet Trainee Police Constable (Civil) or Equivalent and other Posts, Telangana |
| d4-ts-tslprb-sct-police-constable-mechanic-driver-2026 | Police Recruitment 2026: Stipendiary Cadet Trainee Police Constable (Mechanic) and Police Constable (Driver), Telangana |
| d6-kea-social-welfare-residential-school-teacher-2026 | Karnataka Social Welfare Department Residential School Teacher Recruitment, 2026 |
| d7-mh-bmc-mpl-category-d-2026 | Brihanmumbai Municipal Corporation Recruitment 2026 for 10 Multi-Purpose Labour (Category D) Posts on Purely Contract Basis at Dr. V. N. Shirodkar Maternity Home, Vile Parle (East) |
| d7-mh-bmc-shikshan-sevak-pavitra-2026 | Brihanmumbai Municipal Corporation Education Department Recruitment 2026 for Shikshan Sevak (Municipal Corporation School Teachers) through the Pavitra Portal |
| d7-mh-bmc-treatment-organiser-tb-2026 | Brihanmumbai Municipal Corporation Recruitment 2026 for 25 Treatment Organiser Posts in the Assistant Health Officer (TB Control Unit) on Contract Basis |
| d7-up-etawah-icds-anganwadi-worker-2026 | Integrated Child Development Services Etawah District Anganwadi Karyakartri (Anganwadi Worker) Recruitment 2026 |
| mgt-clat-2027 | Common Law Admission Test, 2027 |
| ne-tripura-tpsc-departmental-audit-accounts-officers-grade-v-2026 | Tripura Departmental Examination for in-service Assistant Audit and Accounts Officers, Grade V, 2026 |
| sou-kerala-cofed-junior-assistant-2026 | Junior Assistant (Society Category), Kerala Co-operative Milk Marketing Federation Limited, 2026 |
| sou-kerala-film-dev-corporation-electrician-2026 | Electrician, Kerala State Film Development Corporation Limited, 2026 |
| sou-kerala-land-development-assistant-project-engineer-2026 | Assistant Project Engineer, Kerala Land Development Corporation Limited, 2026 |
| st3-ap-appsc-brief-notifications-2026-27 | Andhra Pradesh Public Service Commission Brief Notifications, 15 September 2026 (Direct Recruitment Batch 2026-27) |

## Left as is: the short name would be the same for several files

The catalogue needs a body short name or an alias per exam that tells them apart.

- **Principal District and Sessions Court 2026**: d7-ka-kodagu-dc-peon-attender-2026, d7-ka-kodagu-dc-process-server-2026, d7-ka-kodagu-dc-typist-2026, d7-ka-mysuru-dc-peon-steno-2026

## Probably one exam in two files

Same exam, harvested under two groups. Merging deletes a file, so it waits for a decision.

- d5-ailet-2027, mgt-ailet-2027
- d5-cat-2026, mgt-cat-2026
- d5-slat-2027, mgt-slat-2027
- d5-xat-2027, mgt-xat-2027
- d6-cbse-ctet-december-2026, tch-ctet-2026-22nd-edition
- d6-hpbose-hp-tet-november-2026, nw-hp-tet-november-2026
- d6-kea-kset-2026, tch-kset-2026
- d6-nta-joint-csir-ugc-net-december-2026, tch-csir-ugc-net-dec-2026
- d6-nta-ugc-net-december-2026, tch-ugc-net-dec-2026
- eng-cuet-pg-2027, mgt-cuet-pg-2027
- nw-hssc-haryana-cet-group-d-2026, st3-hr-hssc-cet-group-d-2026
- nw-hssc-haryana-police-constable-2026, pol-haryana-police-constable-2026
- nw-rpsc-assistant-prosecution-officer-2026, st-rajasthan-assistant-prosecution-officer-2026
- nw-rpsc-protection-officer-2025, st-rajasthan-protection-officer-2025
