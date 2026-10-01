# D7 — Niche, local, district-level government recruitment: where the notices actually live

Retrieved 2026-09-27. Persona: a candidate in a small town or district in India who wants a
nearby government job — district court clerk or peon, municipal sweeper, taluk office
assistant, Anganwadi worker, primary-school teacher, cooperative bank clerk, panchayat
secretary, state transport driver, forest guard. Not chasing UPSC.

## Method, and why it matters

I led with web search in the blunt vocabulary a real candidate would type, then followed
breadcrumbs: from a state-level board down to the district, from a district court to that
court's own site, from a municipality to its own recruitment board. Only then did I fetch the
actual notice. This ordering is the finding. A candidate who searches "district court clerk
recruitment 2026" gets a wall of UPSC-adjacent aggregator pages and, in the case of
`dcourts.gov.in` recruitment, essentially nothing — because the notices are not indexed
together. They live one per district, on a subdomain named after the district, on a platform
that the state high court and the state public service commission never mention.

Sixteen records written. What follows is the honest characterisation of the sourcing, which
is more useful than the records themselves.

## The one pattern that unlocks the whole slice: `*.dcourts.gov.in`

Every district court in India has its own e-Courts site on a subdomain derived from the
district name, and **each one runs its own recruitment board**. There is no central index.

    https://<district>.dcourts.gov.in/notice-category/recruitments/
    https://<district>.dcourts.gov.in/online-recruitment/
    https://<district>.dcourts.gov.in/document-category/recruitments/

Confirmed reachable during this research: `kodagu`, `yadgir`, `hassan`, `mysuru`, `bengaluru`,
`durg`, `jalgaon`, `surguja`, `uttarakannada`, `dhalaitrp` (Tripura, bilingual `dhalaitrp` not
`dhalai`). Note that some use `/notice-category/recruitments/` and others
`/document-category/recruitments/` — both work, which means a scraper that only knows one
pattern silently misses courts.

**The practical instruction for a candidate: for a district court clerk or peon job, go to
your own district court's subdomain and read its recruitment board. Do not wait for a state
board, because the state board will never mention it.** The Karnataka High Court, for
example, runs the *application* system at `judiciary.karnataka.gov.in/recruitment/district/<code>/<post>/home.php`
while the *notice* sits on the district's own site. Two domains, one recruitment.

### Karnataka — the best-sourced district courts in India, with one serious caveat

Karnataka is the strongest state in this slice. The court publishes the notification, the
vacancy split, the application window and the application link on its own board. Yadgir is
the model: an explicit `Start 31/08/2026` / `End 30/09/2026` pair on the board, a gazette
citation (Karnataka Gazette Volume 161, Issue 41, 25 August 2026, Kalburgi edition, Part 6-C),
and a local-cadre restriction stated plainly.

The caveat is that the platform is CMS-driven and the end date is a manually entered field, so
it is wrong as often as not. **Mysuru district court's board lists an End Date of 31/12/2027
against all four of its 24.04.2026 notifications.** That is a placeholder, not a deadline, and
it is more than a year after the real close. A candidate trusting the official board would
think the applications were still open. The same board's "Last Updated" footer reads
Apr 29, 2026 while carrying newer items, so the footer is not a freshness signal either.

Application forms themselves are unusable without a browser: the Karnataka Judiciary
recruitment pages are a JavaScript/PostgreSQL front end that renders nothing to a fetcher. I
could not read a single field off them. Every substantive detail therefore comes from the
notice PDF or an aggregator, never from the application portal.

### The government CDN — timestamped filenames that get replaced

Almost every notice PDF sits on `cdnbbsr.s3waas.gov.in`, the NIC's S3WaaS CDN, under a path
like:

    https://cdnbbsr.s3waas.gov.in/s3ec01be767243ca8f574c740fb4c26cc6/uploads/2026/07/2026090137.pdf
    https://cdnbbsr.s3waas.gov.in/s3ec03ca793d8b79c1b6665cf109d6077a/uploads/2026/03/2026090590.pdf

Three things a candidate must know:

1. **The upload directory has no relationship to the document date.** The Yadgir notice sits
   in `uploads/2026/03/` and is stamped 5 September 2026. The Kodagu notices sit in
   `uploads/2026/07/` and are stamped 1 September 2026. You cannot infer anything from the
   path.
2. **The filename is a bare sequence number**, not a slug. `2026090137.pdf` carries no title.
   It is regenerated when the court republishes, so a link saved today can serve a different
   document tomorrow, or 404. Any record that pins a CDN URL is pinning a temporary.
3. The `s3ec...` prefix is a per-site hash. It differs per district court, so there is no
   way to construct a sibling URL.

### Notice quality: scans, and what that means in practice

The Kodagu peon notification (`2026090137.pdf`) is a **scan**, not a born-digital document.
Its PDF metadata is unambiguous:

    /Creator (Simple Scan 46.0)   /Producer (LibreOffice 6.4)   /CreationDate (D:20260829145313+05'30')

So it is: paper notice → scanner → OCR → LibreOffice re-wrap. There is an OCR text layer, but
the embedded fonts are `Lohit-Kannada`, `Lohit-Devanagari` and `BookmanOldStyle`, and the
Kannada body text extracts as garbage. I could not read the eligibility, vacancy or fee lines
off this document. I took them from aggregators and from the court's own index page, and I have
not invented a single line of it.

I have therefore **not transcribed any date from a notice PDF I could not read.** Where the
official page states a start date but not a close date — which is the case for all four Kodagu
notifications — the close date in those records is marked `provisional` and sourced to three
mutually consistent aggregators, not to the court.

The Yadgir board, by contrast, states both dates in its own HTML index, which is why that
record is `confirmed` on both ends. That is the difference between a record I trust and one I
am relaying.

## Municipalities

### Maharashtra — an IBM Maximo portal, which is genuinely good

Brihanmumbai Municipal Corporation runs its entire citizen and recruitment site on a SAP
Maximo iView portal:

    https://portal.mcgm.gov.in/irj/portal/anonymous?NavigationTarget=navurl%3A%2F%2F<opaque-hash>&guest_user=english

This is the best-behaved municipal source in the study. It **does** render to a plain fetch,
it carries a live table of every recruitment notice with an advertisement number, the issuing
department, a description, and a Start Date and End Date, and it held at least a dozen live
notices on the day of research. The same vendor pattern is shared by other Indian municipal
corporations, so the `irj/portal/anonymous` path is worth trying on any city.

Two defects worth recording:

- The recruitment hash in the `NavigationTarget` parameter is opaque and changes between
  sessions. It is not reconstructible.
- Notice PDFs live at `/irj/go/km/docs/documents/MCGM%20Department%20List/...` and the
  **filenames are percent-encoded Devanagari transliterations of the Marathi notice title**
  (`GAD_376_ME%20Dt.03.09.2026%20%e0%a4%ae%e0%a5%81...`). They cannot be guessed, typed, or
  reconstructed from the title. You have to copy them out of the rendered board.

For the persona, BMC is not a small town, but the *pattern* is what transfers, and the
Category D **MPL (Multi-Purpose Labour)** advertisements are exactly the municipal sweeper
role. There were at least a dozen live on one day, each with its own reference
(`GAD/388/ME`, `GAD/376/ME`, `HO/820/M&CH`, `HO/1867/KMJP`, `HO/272/CHMH` and others) and each
with a 7–10 day window. A sweeper job is a permanent rolling vacancy stream, not an exam.

BMC's own board also carries errors: the Treatment Organiser row reads "for the period
05.10.2026 to 31.03.2026" — an end date *before* the start date, plainly a typo for
31.03.2027. I recorded no contract-end date as a result.

### Other municipal corporations — JavaScript-only, and this one is a hard stop

- **Surat Municipal Corporation.** `suratmunicipal.gov.in/Information/RecruitmentDashboard`
  returns a page whose entire content area is the literal string *"This page uses Javascript.
  Your browser either doesn't support Javascript or you have it turned off."* Every tile —
  Current Recruitment, News/Notice, Answer Keys, Exam Results, Selection & Waiting List — is a
  JS-rendered link with no payload. There is a separate online recruitment portal at
  `suratmunicipal.gov.in/recruitment/` which I did not resolve, and a contact address
  `recruitment@suratmunicipal.org`. **For Surat, the honest answer is that recruitment is only
  findable by a human with a browser, or by telephone.** No record is written.
- **Amdavad (Ahmedabad) Municipal Corporation.** `amcmodules.ahmedabadcity.gov.in/AMCWEBREC/HRMS/FrmVacancyDetail.aspx`
  is a legacy ASP.NET HRMS page. The search index shows a fragment of a vacancy table
  ("30, 21/2025-26, SAHAYAK FOOD SAFETY OFFICER") and nothing else; the page did not render
  its contents to a fetcher. No record written.
- **Pune Municipal Corporation** has a `/en/b/recruitment` page that surfaced only
  document-verification items in search. No live vacancy advertisement found.

## Zilla Parishad — every district has its own CMS, and the end dates are decorative

Maharashtra ZPs each run their own site on the same NIC S3WaaS stack, with a board at
`/en/notice-category/recruitments` or `/en/notice-category/recruitments-en`. Confirmed
reachable: `zpsatara`, `zpbuldhana`, `zpdharashiv`, `zpjalgaon`, plus per-district sites
`zpbeed`, `zpwashim`, `nhm.zpnagpur`.

What these boards actually contain is mostly **selection lists, waiting lists, compassionate
appointment seniority lists and final merit lists** — not advertisements. On 27 September 2026,
ZP Satara's recruitment board held an MPW 50% additional selection list, a Health Worker
selection list, and a Junior Accounts Officer 2023 *final selection list*. ZP Jalgaon held a
compassionate appointment waiting list and an IFC Block Anchor advertisement whose window had
already closed on 02.09.2026. ZP Buldhana's entire board was one item, "Mission and Notice",
14/08/2026 to 31/08/2026, a 9 MB file.

The pattern that emerges: **a Zilla Parishad "recruitment page" is mostly a place where
appointments go to be published, not where vacancies are advertised.** A candidate looking for
a ZP job will spend most of their time reading merit lists of vacancies that closed months ago.

### Zilla Parishad in West Bengal — an entire ecosystem with no official URL

The Bengali Zilla Parishad (জেলা পরিষদ) system is a separate world. Districts including Gazipur,
Magura, Chuadanga, Narayanganj, Bhola, Jinaidah and Cumilla run their own recruitment notices,
and the notices are published on the district's own site *and* in daily newspapers. The only
index I could find that gathers them is an aggregator, `jobsnoticebd.com`, which lists
Magura closing 10 September 2026 and Bhola 15 September 2026 with no linkable official document
behind either. I could not reach a single official Magura or Bhola ZP recruitment notice. **No
record written — a notice I cannot link is not a notice I can cite, and inventing a URL for it
would be worse than useless.**

## Anganwadi — the clearest case of a notice that lives in a newspaper

Uttar Pradesh runs anganwadi recruitment through `upanganwadibharti.in`, a portal operated
from 3rd Floor, Indira Bhawan, Ashok Marg, Lucknow. It aggregates district ICDS notices,
carries an `Uploaded` date and a `Last Date` for each, and marks each one `Active` or `Closed`.

Three findings:

1. **The Active flag is not a liveness signal.** On 27 September 2026 the portal still showed
   Azamgarh, Banda and Chitrakoot as `Active` although all three closing dates — 14.09.2026,
   22.09.2026, 05.09.2026 — had passed. Read the date, not the label.
2. **The portal's own FAQ states the residency rule in the most direct words in this entire
   study**: *"It is required that the candidate to be a resident of the village assembly/ward
   (in case of urban areas) where the Anganwadi centre is located."* Because vacancies are
   **centre-wise, not district-wise**, a woman from the neighbouring block is ineligible for a
   given centre inside her own district. This is the decisive gate for the persona and it is
   invisible in every headline.
3. **The underlying authority is the District Programme Officer, and the durable artefact is a
   district-level newspaper notice.** The state GO that frames all of it — UP GO
   1092245/2025/3313/58-1-2025(1917687) dated 17 September 2025 — is linked from the portal,
   but the per-district advertisement is not stably addressable.

Rajasthan is worse. The Baran advertisement (Vigyapti/M.Ba.Vi./2026-27/958, Vigyapti Sankhya
2/2026, 08.07.2026, 61 posts across seven project areas) **prints no calendar closing date at
all** — it requires applications "within 30 days from the date of publication", in person, at
the CDPO office, by post not accepted. Deriving 07 August from 08 July plus 30 days would be an
estimate. That record therefore carries a `registration_open` of 2026-07-08 and **no
`registration_deadline` key at all.** This is the single most important sourcing lesson in the
slice: the most reachable sources for this persona are frequently the ones that give you no
date, and the aggregator that "helpfully" computes one for you is guessing on your behalf.

Maharashtra's anganwadi route is partly offline: Kolhapur's WCD Anganwadi Helper advertisement
(अ.वि.-2022/प्र.क्र.94/का-6) was applied for by offline form to the district site. Odisha runs
online through `engagement.odisha.gov.in` for even three-post advertisements (Bhadrak, three
Anganwadi Worker posts, 25.08.2026 to 10.09.2026) — which tells you how small these get.

## Panchayat secretary

- **Chhattisgarh** is the best pattern: the District Panchayat Kanker notice
  (55/उ.सं./पंचा.स्था./2026-27, 27 posts) is on `kanker.gov.in/en/notice/` with the window
  26/05/2026–09/06/2026, applications **offline by post**, and selection by weighted merit —
  Higher Secondary marks 50%, higher qualification 10 marks, computer skill test 25%,
  Rozgar Sahayak experience 15 marks. **No written examination exists.** Narayanpur (14 posts,
  1221/ZP/Estb/Sachiv Bharti/2026-27) is the same shape.
- **Madhya Pradesh** has *no notice at all*. The MP Panchayat Sachiv recruitment is being run
  by MPESB for the first time — previously the post was filled locally without an exam — and
  the widely circulated figure of "23,011 posts" is, by the admission of the Hindi source
  carrying it, **baseless**: it is the number of panchayats in the state, not vacancies, and
  the same source puts the real figure at 3,000–4,000. Notification "may" come July–October
  2026 with the exam "proposed" for November–December. The stated eligibility — graduation plus
  CPCT, and *"मध्यप्रदेश का मूल निवासी होना चाहिए"*, a native of Madhya Pradesh — is exactly
  the gate this persona hits. **No record written: there is no notice to record.**
- **Himachal Pradesh** ran Panchayat Secretary through HPRCA (advt 04/2026, 331 vacancies,
  10 March to 4 April 2026 at `hprca.hp.gov.in`) — a state commission recruitment, which is
  the exception that proves the rule.

## Forest guard

- **UPSSSC** (Advertisement 12-Pariksha/2026, also circulating as 12-Exam/2026 — the same
  recruitment under two numbers), 708 posts, applications 30.06.2026 to 20.07.2026. The gate
  is not residency but **PET 2025**: you must already have sat the Preliminary Eligibility
  Test and hold a valid scorecard, and the application form will not open without your PET
  registration number and OTP. Residency has a distinct bite: *a candidate who is not a
  permanent domicile of Uttar Pradesh is treated as Unreserved*, so a non-UP resident is not
  barred but loses every reserved-category benefit.
  UPSSSC's notice URLs are the worst in the study:
  `upsssc.gov.in/ViewPdf.aspx?ss2XKF%2FcntZMY%2FQS8H1aTFqt7TVl91dOlzlMwUgIiWk` and
  `upsssc.gov.in/Open_PDF_DB.aspx?I4PnQ0tBagmJYUMpOqx34bCUP5R7Jn0k` — **encrypted query-string
  tokens with no readable content, no stable value, and no way to reconstruct or verify them
  later.** The live advertisements list at `upsssc.gov.in/AllNotifications.aspx` rotates and
  drops entries.
- **Tripura Forest Department**, 271 Forest Guard and Forester posts, applications
  01.05.2026 to 31.05.2026 (up to 5:30 PM), age 18–40 as on 01.05.2026, Class 10 for Forest
  Guard and +2 for Forester, with a 33% horizontal women's reservation in both. The notice is
  issued on `forest.tripura.gov.in` but the specific advertisement PDF could not be linked to,
  so that record is tier `other`.
- **Delhi Forest Department** (`forest.delhi.gov.in/recruitments`) is a good example of a board
  that is honest about having nothing: its most recent entry is a Forest Ranger vacancy *on
  deputation* from 27.03.2026, and a contractual Data Entry Operator advertisement from
  2023. No direct recruitment is on offer.

## State transport — the loudest false signal in the slice

MSRTC announced a **17,742-post driver and conductor mega-recruitment** in the Maharashtra
legislative assembly, via the Transport Minister, and it is being covered by multiple Marathi
job portals as though it were a notification. **It is a proposal. There is no advertisement, no
application form, no dates, and no notification number.** Every Marathi portal that has built
a page for it has filled the dates in itself. No record written, and a candidate should treat
any "MSRTC 17,742 posts, apply by X" page as fabricated until `msrtc.maharashtra.gov.in`
publishes something. Maharashtra also scrapped contract recruitment at the end of its first
phase, which closed a route many small-town applicants had been relying on.

For a genuinely-sourced transport record, **BEST Undertaking** (Brihanmumbai Electric Supply &
Transport) ran 364 Bus Vahak (conductor) posts, 08.07.2026 to 29.07.2026. The decisive gate
there is neither education nor residency but a **licence**: a valid bus conductor licence and
badge issued and renewed by the Maharashtra RTA is a mandatory condition of eligibility, so a
first-time applicant who has never held an RTA conductor licence cannot apply at all. The
Marathi marks requirement — minimum 100 at higher level or 50 at lower level — is a second
silent filter.

## Cooperative bank clerk

This is the best-sourced niche in the whole study, and the contrast is instructive.

- **APCOB / District Co-operative Central Bank Ltd., Visakhapatnam** — Staff Assistant, 47
  posts, 24.07.2026 to 07.08.2026, PDF hosted on the state co-operative bank's own domain at
  `apcob.bank.in/wp-content/uploads/2026/07/Notification_Visakhapatnamdccb_SA.pdf`, **with a
  proper text layer**, and it states the residency rule verbatim: *"The DCC Bank has its area
  of operations as the District and as such all positions are within the District and suitable
  for Local Candidates only. Accordingly, candidates local to the erstwhile Visakhapatnam
  District (candidates having domicile of the district), only are eligible to apply."* Note
  "erstwhile" — eligibility is tied to old district boundaries after reorganisation. It also
  carries a ₹2,00,000 two-year contract bond. This is what good looks like, and it proves the
  rest of the slice is a sourcing failure rather than an inherent property of small-town
  recruitment.
- **Sangli DCC Bank** — 444 Clerk (Junior Assistant) posts, closed 10 July 2026; degree plus
  MS-CIT, age 18–35 as on 20.06.2026, fee ₹1,180.
- **Jalna DCC Bank** — 70 posts, 07.07.2026 to 18.07.2026, age reckoned as on 01.04.2026.

Every DCCB in Maharashtra has its own bank domain (`jalnadcc.bank.in`) and its own
advertisement, and none of them is aggregated by any state-level body. The exam date on the
Visakhapatnam notice is given only as "August/September 2026 (tentative)" — a month range with
no day — so **no `exam_date` is recorded on that record at all.**

Kerala runs the equivalent through the Kerala State Co-operative Service Examination Board
(133 posts across Secretary, Assistant Secretary, Junior Clerk/Cashier in three bank grades,
System Administrator and Data Entry Operator, applications 30.05.2026 to 30.30.06.2026) — a
state board, well organised, and the opposite of the district-level experience.

## What was not written, and why

- **MSRTC 17,742 posts** — a legislative announcement, no notification.
- **MP Panchayat Sachiv** — no MPESB notification exists; the 23,011 figure is acknowledged as
  baseless by the source carrying it.
- **West Bengal Zilla Parishad** (Magura, Bhola and others) — aggregator is the only reachable
  copy; no official URL exists for these notices.
- **Surat and Ahmedabad municipal corporations** — JavaScript-only / legacy ASP.NET pages that
  render no vacancies to a fetcher.
- **Hassan district court** (Peon, ADMN/1/2026, 19/08/2026–17/09/2026), **Bengaluru district
  court** (Kalyana Karnataka Region 371-J, five posts from 01.07.2026), **Surguja**,
  **Uttarakannada**, **Dhalai/Absassa** — all located and all with real dates on their boards,
  but all closed before 27 September 2026 and all superseded by the newer Kodagu and Yadgir
  drives. The Dhalai board in particular held only a *final merit list* for an advertisement
  dated 06.05.2026, not an open vacancy.
- **Rajasthan Safai Karamchari** appeared in an aggregator sidebar with a 28.09.2026 date,
  which would have been live — but the notice itself was not located on any official source,
  so it is recorded nowhere rather than being written from a sidebar.

## Honest totals

- **Records written:** 16.
- **Scanned-only or OCR-only notices encountered:** 1 confirmed by direct inspection (the
  Kodagu peon notification, `Simple Scan 46.0` + LibreOffice, Kannada body text unextractable).
  At least 6 further notices in this slice are file-only scans by the same NIC upload
  convention — the Kanker (3 MB), Buldhana (9 MB), Dharashiv (6 MB), Nadia district
  (2–4 MB per centre) and Hastinapur Yamuna Nagar Peon (Adhoc) interview notice — but those
  were identified by size and context from index listings rather than opened, so they are not
  counted as inspected.
- **Notices with no linkable URL at all:** 2 written as records (Chhattisgarh Narayanpur gram
  panchayat secretary; Rajasthan Baran anganwadi), both `source_tier = 'other'`, both carrying
  a real advertisement number and real dates instead of an invented link. A further 3+ (West
  Bengal ZP districts, MP panchayat sachiv) had no notice to link.
- **`source_tier = 'other'` records:** 4 of 16 (25%). The other 12 were confirmed against the
  issuing body's own site.
- **Date fields deliberately left out:** 1 record has no `registration_deadline` at all
  (Baran anganwadi, notice prints no calendar date); no record carries an `exam_date`, because
  not one notice in this slice fixes a single exam day — the usual phrasing is "dates for the
  test/interview will be intimated", or a bare month range.
- **Records with a `provisional` deadline:** 4 of 15 that have one — all four Kodagu
  notifications, where the district court's own board states the opening date but prints no
  closing date, and the close comes from three agreeing aggregators.
- **Domains I could not reach or could not read:** `judiciary.karnataka.gov.in` (JS/PostgreSQL
  application portal, no server-rendered content); `suratmunicipal.gov.in` (JavaScript-only
  dashboard); `amcmodules.ahmedabadcity.gov.in` (legacy ASP.NET HRMS); no official West Bengal
  ZP notice index located at all; no official MPESB Panchayat Sachiv notice exists.
- **`*.dcourts.gov.in` board reached without issue** in every case tried, but the underlying
  notices were `cdnbbsr.s3waas.gov.in` scans with sequence-number filenames, and the Karnataka
  application portals behind them were unreadable.
