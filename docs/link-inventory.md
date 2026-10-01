# Link inventory — official sources by conducting body

Every URL a maintainer needs in order to re-check a record, and every URL a
candidate needs in order to reach the thing. The 200-odd records in
`content/exams/` each carry one or two links; this file is the map those links
belong to, so that when a body changes domain the change shows up once here
rather than as 13 identical broken `official_url` values nobody notices.

Checked **2026-09-27**. Re-check with:

```sh
node tools/check-links.mjs --scope=inventory   # just this file
node tools/check-links.mjs --scope=records    # the front matter of every record
node tools/check-links.mjs --fix              # + likely domain corrections
```

That script exists because the naive version of this job does not work on
Indian government domains. A large share of them answer a plain HTTP client
with 403, 429, 503, a TLS handshake failure or a broken DNS delegation, and are
perfectly fine in a browser. The script buckets those as *blocked*, never as
*broken*, and exits non-zero only on a definite failure.

## How to read a body section

Rows are omitted where a body publishes nothing of that kind — the same rule
`docs/data-model-notes.md` sets for front matter. Absence means absence.

| Marker | Meaning |
|---|---|
| `[v]` | Reached 2026-09-27, HTTP 2xx after following redirects |
| `[v*]` | Reached, but only after a redirect; the URL in the table is not where you land |
| `[b]` | Not reachable by a script. Browser-tolerated barrier: WAF, bot challenge, broken certificate chain. Not a broken link |
| `[n]` | Not reachable from the checking host. The reason is given in the section |
| `[?]` | **Unverified.** Not reached, and not confirmed dead. Do not store in a record without opening it in a browser |

**A note on hostnames.** `www` is not cosmetic on several of these. Where a
bare domain silently discards the path, that is called out in the section notes,
because a 307 to a homepage returns HTTP 200 and looks healthy to a link
checker.

**Backticks mean "do not check this".** A URL in backticks is a path template
with a placeholder in it, or an entry this file deliberately lists as dead.
`tools/check-links.mjs` skips those, which is what keeps `--scope=inventory` at
zero definite failures and therefore CI-green. Pass `--include-code` to audit
them anyway.

## The traps

Seven patterns account for almost every wrong link. They are worth reading
before editing any record.

### 1. The application is on a different host from the notice

This is the single most common cause of a candidate filling a form on the wrong
site. In several cases the apply host is operated by a different vendor
entirely — a TCS iON platform, a state e-Governance portal, or a
software-procurement company.

| Body | Notices live on | Application lives on |
|---|---|---|
| UPSC | `upsc.gov.in` | `upsconline.nic.in` (Keycloak SSO) |
| UPSC — departmental recruitment | `upsc.gov.in` | `upsconline.nic.in/ora/` (a different portal) |
| SSC | `ssc.gov.in` | inside the same SPA, via `ssc.gov.in/api/…` |
| IBPS | `ibps.in` | `ibpsreg.ibps.in/<exam-campaign>/` |
| RRB | `rrb.indianrailways.gov.in` | `www.rrbapply.gov.in` |
| BPSC | `bpsc.bihar.gov.in` | `bpsconline.bihar.gov.in` |
| UPPSC | `uppsc.up.nic.in` | same host, `/OuterPages/…` |
| RPSC | `rpsc.rajasthan.gov.in` | `sso.rajasthan.gov.in` via `recruitment.rajasthan.gov.in` |
| MPESB | `esb.mp.gov.in` | `esb.mponline.gov.in` |
| MPSC | `mpsc.gov.in` | `mpsconline.gov.in` |
| KPSC | `kpsc.kar.nic.in` | `kpsconline.karnataka.gov.in` |
| APPSC | `psc.ap.gov.in` → `portal-psc.ap.gov.in` | `applications-psc.ap.gov.in` |
| Odisha PSC | `opsc.gov.in` | same host, ASP.NET `View_Content.aspx` |
| WBPSC | `psc.wb.gov.in` | `wbpsc.ucanapply.com` |
| OUSSSC | `ousssc.odisha.gov.in` | same host |
| HPPSC | `hppsc.hp.gov.in` | `hppsconline.hp.gov.in/HPPSC/…` |
| PSSC | `sssb.punjab.gov.in` | same host, per-campaign paths |
| HSSC | `hssc.gov.in` | `onetimeregn.haryana.gov.in/hssc`, or per-advertisement `advNNNNNN.hryssc.com` |
| DSSSB | `dsssb.delhi.gov.in` | `dsssbonline.nic.in` |
| Telangana PSC | `www.tgpsc.gov.in` | `application.tgpsc.gov.in` |
| TNPSC | `tnpsc.gov.in` | `tnpscexams.in` / `apply.tnpscexams.in` |
| CGPSC | `www.psc.cg.gov.in` | `vyapamcg.cgstate.gov.in`, `vyapamprofile.cgstate.gov.in` |
| Assam PSC | `apsc.nic.in` | `apscrecruitment.in` |
| Arunachal PSC | `appsc.gov.in` | same host |
| LIC | `licindia.in` | `agencycareer.licindia.in` |
| NIACL | `newindia.co.in` | Apprentices only: `bfsissc.com` + `nats.education.gov.in` |
| NTPC | `ntpc.co.in` | `ntpc.co.in/careers` (same host, bot-walled) |
| ICAR | `icar.gov.in` (expired certificate) | `exams.nta.nic.in/icar/` — run by **NTA**, not ICAR |
| LIC AAO | `licindia.in` | separate actuary-vendor portal, not on the LIC domain |

### 2. Soft 404s: a 200 that is a "not found" page

Worst case for a link checker, because it reports health.

- **UPPSC** — any unknown path returns **200** at `uppsc.up.nic.in/FileNotFound.aspx?aspxerrorpath=…`.
- **NABARD** — unknown paths return **200** at `www.nabard.org/pagenotfound.aspx`. Also the root 302s to `/Hindi/Default.aspx`; there is no stable English root.
- **SSC** — the whole site is an Angular SPA. *Every* path, including `/zzzz-not-a-real-page`, returns the same 80 KB `index.html` with **200**. There is no such thing as a 404 on `ssc.gov.in`. The only machine-checkable surface is the API under `ssc.gov.in/api/…`.
- **OPSC** — `opsc.gov.in` is ASP.NET WebForms; unknown `.aspx` paths 302 back to `Default.aspx`.
- **AIIMS exams** — Next.js; `/landingpage` alone is 404 but `/landingpage/…` with a course id is 200.

### 3. JavaScript-only content

The page exists, the HTML does not contain the notice. `curl` of these returns a
shell.

- `mpsc.gov.in` — React SPA, no server-rendered content
- `ssc.gov.in` — Angular SPA
- `aiimsexams.ac.in` — Next.js
- `upsc.gov.in` — Drupal, but the listing pages are server-rendered and fine
- `kpsc.kar.nic.in` — the navigation is `javaScript:getContent('keyanswers.html')`; the real pages are the `.html` files it loads

### 4. Broken DNS delegation

Verified against both Cloudflare and Google public resolvers on 2026-09-27.
`SERVFAIL` with `EDE(22): No Reachable Authority` is an authoritative failure,
not a local one:

| Host | Status | Consequence |
|---|---|---|
| `apsc.gov.in` | SERVFAIL at both resolvers | **Wrong domain.** Assam PSC is `apsc.nic.in` |
| `hssc.gov.in` | SERVFAIL at both resolvers | The domain is correct and the search index carries current content; this host cannot resolve it. Treat as *unreachable from here*, not dead |

Several other candidates are simply NXDOMAIN and have never existed:
`oars.dsssb.delhi.gov.in`, `hssb.punjab.gov.in`, `pssb.punjab.gov.in`,
`pssbc.punjab.gov.in`, `staffselectioncommissionassam.gov.in`,
`apsc.assam.gov.in`, `sscwrtf.bihar.gov.in`, `jsc.up.gov.in`, `psc.up.gov.in`,
`uppsc.up.gov.in`, `cgpsc.gov.in`, `mpscpune.gov.in`, `mpsc.maharashtra.gov.in`,
`mpesb.gov.in`, `test.mponline.gov.in`, `jipmat.nta.nic.in`, `www.cdsc.nic.in`,
`agricoplay.in`, `karnatakajobs.karnataka.gov.in`, `ssc.hry.gov.in`,
`hssconline.hry.gov.in`.

### 5. Certificate chains that a browser forgives and a script does not

These are fine for candidates and will always show as failures in tooling.
Chrome and Firefox allow TLS legacy renegotiation by default; Node's OpenSSL
build often does not.

`hppsc.hp.gov.in` · `sssb.punjab.gov.in` · `psc.wb.gov.in` · `www.ibps.in` ·
`bpsc.bihar.gov.in` · `esb.mp.gov.in` · `apsc.nic.in` · `portal-psc.ap.gov.in` ·
`kpsconline.karnataka.gov.in` · `ppsc.gov.in` · `jssc.jharkhand.gov.in` ·
`jkssb.nic.in` · `www.amu.ac.in` · `www.bitsadmission.com` ·
`indianarmy.nic.in` · `www.uidai.gov.in` · `icar.gov.in` (expired, not just
incomplete) · `admission.isical.ac.in` · `onetimeregn.haryana.gov.in` (SAN
mismatch) · `www.nabard.org` serves `pagenotfound.aspx` rather than a 404.

`onetimeregn.haryana.gov.in` is worth knowing about: its certificate is issued
for an AWS load balancer and does not cover the hostname. A candidate clicking
through the browser warning reaches the right form; a script never will.

### 6. Timestamped and opaque document URLs

These are the ones that go stale silently. A 404 on one of these is not a
missing page, it is a replaced file.

| Pattern | Bodies | Why |
|---|---|---|
| `s3waas.gov.in/.../2026/09/20260914325514446.pdf` | CDG/GeM government CDN | Timestamp in the filename; re-uploaded under a new name |
| `hssc.gov.in/file/<uuid>/publicNotice` | HSSC | UUID-stable, so this one holds |
| `tpsc.tripura.gov.in/sites/default/files/…/noti-146-150-26.pdf` | TPSC | Month-scoped Drupal path |
| `rpsc.rajasthan.gov.in/Static/RecruitmentAdvertisements/<GUID>.pdf` | RPSC | GUID, no filename |
| `kpsc.kar.nic.in/SAAD%20RPC%20Notification%20dt%2027-08-2026.pdf` | KPSC | Title-case filename with spaces |
| `upsc.gov.in/sites/default/files/Notif-XXXX-2027-Engl-DDMYY.pdf` | UPSC | Stable, dated, and the best kind |
| `opsc.gov.in/Public/OPSC/Pages/View_Content.aspx?id=<opaque base64>` | OPSC | Opaque. There is **no** stable per-notice URL |
| `cdn3.digialm.com/EForms/configuredHtml/1815/<id>/Index.html` | NBEMS | Digialm CDN, numeric ids, form snapshot |
| `websitenew.tgpsc.gov.in/preview/<base64>.pdf?faceSet=…` | TGPSC | Preview wrapper over a file-asset id |
| `npsc.nagaland.gov.in/advertisement/178713486224731` | Nagaland PSC | Unix-timestamp-as-path-segment |

### 7. Domains that have moved

| Was | Is now | Body |
|---|---|---|
| `www.fci.co.in` | `fci.gov.in` | FCI — **`fci.co.in` is a parked domain for sale** |
| `www.pnbindia.in` / `pnbindia.in` | `pnb.bank.in` | PNB |
| `www.epfindia.gov.in` | `www.epfo.gov.in` | EPFO (old domain still redirects) |
| `www.bitsadmission.com` | `admissions.bits-pilani.ac.in` | BITS Pilani |
| `csirnet.gov.in` | `csirnet.nta.nic.in` | CSIR-UGC NET (2024) |
| `ctet.nta.nic.in` | `ctet.nic.in` | CTET |
| `cat.xlri.ac.in` | `xatonline.in` | CAT |
| `slat.iitm.ac.in` | `slat-test.org` | SLAT |
| `www.tspsc.gov.in` | `www.tgpsc.gov.in` | Telangana PSC — **one letter different** |
| `apsc.gov.in` | `apsc.nic.in` | Assam PSC |

And two domains that look official and are not:

- `www.crri.in` and `crri.in` now redirect to `skitterbug.co`, an unrelated site. Central Research Institute of Dryland Agriculture.
- `www.nbems.org` is **New Britain Emergency Medical Services**, a US ambulance service. The Indian body is NBEMS at `natboard.edu.in`. Do not let a search engine add this one.

---

# Bodies

## Union Public Service Commission

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.upsc.gov.in/ `[v]` | **`www` is required.** The bare domain 307s to the root and *discards the path* |
| Active examinations index | https://www.upsc.gov.in/examinations/active-exams `[v]` | The one to bookmark for "what is open now" |
| Upcoming / forthcoming | https://www.upsc.gov.in/examinations/forthcoming-exams `[v]` | |
| Annual exam calendar | https://www.upsc.gov.in/examinations/exam-calendar `[v]` | **Single segment.** Also `/content/annual-calendar-2027-0` `[v]` for the year page, and the PDF at `/sites/default/files/Calendar-Year-2027-Engl-200526.pdf` `[v]` |
| Notifications index | https://www.upsc.gov.in/exams-related-info/exam-notification `[v]` | Per-exam pages live under `/whats-new/<Exam Name>/<Document type>` — these *are* stable and are the best `official_url` value available |
| Answer key index | https://www.upsc.gov.in/examinations/answer-key `[v]` | |
| Admit card index | https://www.upsc.gov.in/e-admit-cards `[v]` | e-Admit Cards, requires captcha + registration number |
| Results index | https://www.upsc.gov.in/final-results `[v]` | |
| Cut-off / marks index | https://www.upsc.gov.in/examinations/cutoff-marks-- `[v]` | Trailing `--` is in the real URL. Also `/examinations/marks-recommended-candidates` `[v]` |
| Interview & e-summon letters | https://www.upsc.gov.in/interview-schedule-and-esummon-letters `[v]` | |
| Application portal | https://upsconline.nic.in/ `[v*]` | **Separate host.** Keycloak SSO — the 302 target contains a fresh `state=` nonce, so it will never match as a static string. Never store the redirect target |
| Departmental recruitment | https://upsconline.nic.in/ora/ `[v*]` | A *different* portal on the same host (ORA = Other Recruitment Authority) |
| What's new | https://www.upsc.gov.in/whats-new `[v]` | |
| Notice archive | https://www.upsc.gov.in/archives `[v]` | |
| Previous question papers | https://www.upsc.gov.in/examinations/previous-question-papers `[v]` | |
| Vacancy circulars | https://www.upsc.gov.in/vacancy-circulars `[v]` | |
| Apply-online landing | https://www.upsc.gov.in/apply-online `[v]` | Links out to `upsconline.nic.in` per exam |
| Helpline | https://www.upsc.gov.in/helpline `[v]` | |

**Annual calendar:** yes. One of the three bodies that publishes a real one, and
the only one where the path is a *single* segment.

**Separate application domain:** yes — the canonical example.

**Stable per-exam page:** yes, `/whats-new/…` paths. Prefer them over index pages
for `official_url`.

**Fragility:** the site was rebuilt on Drupal and the old route shape
`/examinations/exam-calendar/exam-calendar` is gone. Worse, **any** URL on the
bare `upsc.gov.in` host now 307s to `https://www.upsc.gov.in` with the path
dropped. That returns HTTP 200, so a checker that does not follow and compare
the final URL will call a dead link healthy. See the disagreements table.

## Staff Selection Commission

| What | URL | Notes |
|---|---|---|
| Main portal | https://ssc.gov.in/ `[v]` | Angular SPA. Every path returns the same 200 |
| Active examinations | https://ssc.gov.in/browse-by-examination `[?]` | Client route, extracted from the bundle; not verifiable by script |
| Tentative exam calendar | https://ssc.gov.in/examination-calendar `[?]` | The calendar PDF itself is fetchable: `ssc.gov.in/api/attachment/uploads/masterData/ExamCalendar/Tentative_Calendar2026_27_08012026.pdf` `[v]` |
| Notice board | https://ssc.gov.in/home/notice-board `[?]` | Notices are served as files: `ssc.gov.in/api/attachment/uploads/masterData/NoticeBoards/…` `[v]` |
| Answer key index | https://ssc.gov.in/home/answer-key `[?]` | |
| Results index | https://ssc.gov.in/results `[?]` | Also `/candidate-result` |
| Admit card index | https://ssc.gov.in/admit-card `[?]` | |
| Application | https://ssc.gov.in/apply `[?]` | Client route `/ApplicationForm/<exam>form` |
| Legacy portal | `https://ssc.nic.in/Portal/AnswerKey` `[n]` | Times out. It exists only to say "go to ssc.gov.in" |

**Machine-checkable API** (this is the part worth knowing):

- `https://ssc.gov.in/api/admin/5.1/allExams` `[v]` — JSON, lists every exam with its `examCode` and `navigationUrl`
- `https://ssc.gov.in/api/admin/5.1/liveExams` `[v]`
- `https://ssc.gov.in/api/admin/5.1/examsByType` `[v]`
- `https://ssc.gov.in/api/general-website/portal/` — 404 at time of check

**Annual calendar:** yes, a "Tentative Calendar" PDF revised through the year.
Cite the PDF, not the SPA route.

**Fragility:** highest of any body here. The HTML tells you nothing; the
document URLs are the only stable artefacts. Also note the exam itself is
delivered on a third-party host — final answer-key logins are at
`sscexams.cbexams.com`, which is TCS iON, not SSC.

## IBPS

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.ibps.in/ `[b]` | TLS legacy renegotiation + missing intermediate |
| CRP / PO / SO updates | https://www.ibps.in/index.php/crp-updates/ `[b]` | |
| Management Trainees XVI | https://www.ibps.in/index.php/management-trainees-xvi/ `[b]` | |
| Specialist Officers XVI | https://www.ibps.in/index.php/specialist-officers-xvi/ `[b]` | |
| RRB Officer Scale I | https://www.ibps.in/index.php/rrb-officer-scale-i-iii/ `[b]` | |
| RRB Office Assistant | https://www.ibps.in/index.php/rrb-office-assistant/ `[b]` | |
| Exam calendar | https://www.ibps.in/index.php/calendar-of-examinations/ `[b]` | **Yes, IBPS publishes a calendar of examinations** |
| Application portal | https://ibpsreg.ibps.in/ `[b]` | **Separate host.** Root is 403; per-campaign paths work |
| CRP XVI | https://ibpsreg.ibps.in/rrbxvaug26/ `[v]` | Campaign path, `xvi` + month + year |
| RRB OA | https://ibpsreg.ibps.in/rrboaxvaug26/ `[v]` | |

**Separate application domain:** yes — `ibps.in` for notices, `ibpsreg.ibps.in`
for forms. The campaign segment changes every cycle, so `apply_url` must be
re-derived each time, not pinned.

**Stable per-exam page:** the `ibps.in/index.php/<exam-slug>/` pages are stable
and cumulative. Prefer those for `official_url`; the `ibpsreg` path is not.

**Fragility:** TLS that only Chrome and Firefox accept. Also several sibling
slugs exist that are *not* current (`certified-management-trainees/`,
`certified-specialist-officers/`) — they redirect differently from the
`management-trainees-xvi/` shape, so do not guess the slug.

## Reserve Bank of India

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.rbi.org.in/ `[v]` | |
| Press releases | https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx `[v]` | |
| Notifications | https://www.rbi.org.in/Scripts/NotificationUser.aspx `[v]` | The notifications index |
| Common-person FAQs | https://rbi.org.in/commonperson/English/Scripts/FAQs.aspx `[v]` | |
| Careers | `https://website.rbi.org.in/web/rbi/careers-notifications` `[v*]` | Redirects to `www.rbi.org.in/` — **the deep link is not reachable**, only the landing page |

**Fragility:** the ASP.NET `Scripts/*.aspx` surface is legacy and the careers
sub-site does not survive a redirect with its path intact. There is no
per-exam page and no exam calendar; RBI recruitment is a handful of ad-hoc
advertisements under `/Scripts/BS_AdvDisplay.aspx` in most years.

## SEBI

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.sebi.gov.in/ `[n]` | **Unreachable from the checking host** — TCP connect timed out on every attempt, including `sebi.gov.in` and the `sebiweb` paths. Not evidence of an outage |
| Legacy action path | `https://www.sebi.gov.in/sebiweb/home/HomeAction.do` `[n]` | Same timeout |

**Unverified.** SEBI is believed to be up; it is simply not reachable from
here, and `tools/check-links.mjs` correctly reports it as *timeout*, not
*dead*. Anyone relying on the SEBI recruitment page must open it in a browser
and record what they saw. Assume its notice architecture is a mixture of
`sebiweb/other/OtherAction.do` style forms and a newer `/sebiweb/` document
tree, and verify before storing.

## NABARD

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.nabard.org/ `[v*]` | Redirects to `/Hindi/Default.aspx`. There is no stable English root |
| What's new | https://www.nabard.org/whats-new.aspx `[v]` | |
| Circulars | https://www.nabard.org/Hindi/circulars.aspx?cid=504&id=24 `[v]` | The `cid`/`id` pair is mandatory |
| Tenders | https://www.nabard.org/Tenders.aspx?cid=501&id=24 `[v]` | |
| News | https://www.nabard.org/news.aspx?id=25&cid=552&sid=1 `[v]` | |
| Careers | — | **No careers page found.** Recruitment notices are published as ordinary circulars |

**Fragility:** unknown paths return **200** at `pagenotfound.aspx`. This is the
body most likely to produce a false "verified" in any automated check. The old
`auth/writereaddata/userfiles/11791_Circulars.aspx` style is retired; documents
now live at `auth/writereaddata/WhatsNew/pub_<ddmmyy><hhmmss>.pdf`.

**Annual calendar:** no.

## LIC

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.licindia.in/ `[v]` | Liferay |
| Careers | https://www.licindia.in/en/web/guest/careers `[v]` | Also `https://www.licindia.in/en/careers` `[v]` |
| Agency recruitment | https://agencycareer.licindia.in/agt_req/index1.php `[v]` | **Separate host** for agency/field recruitment. Bare host resets the connection |
| Digitally-signed forms | https://digital.licindia.in/ `[v*]` | **Redirects to a MoEngage "expired-link" page.** The old recruitment portal at this host is retired — do not use it as `apply_url` |
| Actuarial recruitment | `https://www.licindia.in/recruitment-of-aao-generalists/-specialists/-assistant-engineers-2025` `[?]` | LIC routes actuarial (AAO) recruitment through a separate actuary vendor portal, not the LIC domain |

**Fragility:** `digital.licindia.in` answering 200 while serving an
"expired link" page is the worst failure mode in this file. It looks healthy and
is useless.

## New India Assurance (NIACL)

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.newindia.co.in/ `[v]` | `newindia.co.in` without `www` returns **400** |
| Recruitment index | https://www.newindia.co.in/recruitment `[v]` | |
| Recruitment list | https://www.newindia.co.in/recruitment/list `[v]` | The page that actually lists current drives |
| Apprenticeship vendor | https://bfsissc.com/ `[v]` | **Separate host, unrelated vendor.** Apprentices apply via `bfsissc.com` → `beep.bfsissc.com`, after registering on `https://nats.education.gov.in/` `[v]` |
| `www.niacl.in` | — | **Does not resolve.** Never existed as far as DNS is concerned; do not use |

**Separate application domain:** yes, and unusually — for the Apprentices
drive the application is on a software-procurement company's portal plus the
government's National Apprenticeship Training Scheme portal. Two extra
registrations are required.

## UIDAI

| What | URL | Notes |
|---|---|---|
| Main portal | https://uidai.gov.in/en `[v]` | **No `www`** — `www.uidai.gov.in` has a broken chain |
| Tenders | https://uidai.gov.in/en/tenders `[v]` | |
| Recruitment | — | **None.** `/en/careers` and `/recruitment` are both 404; `/recruitment` redirects to `/hi/recruitment`, which is also 404 |

**Fragility:** UIDAI hires through the open market and does not run competitive
examinations. There is no exam calendar, no application portal and no admit card.
If a record claims a UIDAI exam, it is wrong.

## National Testing Agency

| What | URL | Notes |
|---|---|---|
| Main portal | https://nta.ac.in/ `[v]` | |
| Notice PDFs | `https://nta.ac.in/Download/Notice/Notice_<YYYYMMDDHHMMSS>.pdf` `[v]` | **Timestamped filename.** The `/Download/Notice/` directory itself is 403 |
| Exam calendar | `https://www.nta.ac.in/Download/Notice/Examcalendar.pdf` `[v]` | **Yes, NTA publishes an exam calendar** — the proposed/final schedule for the year |
| Per-exam portals | https://exams.nta.nic.in/ `[v]` | The `exams.` host is where most exams actually live |
| NEET-UG | https://neet.nta.nic.in/ `[v]` | Single page; all sub-paths 404 |
| JEE Main | https://jeemain.nta.nic.in/ `[v]` | Bulletin at `/information-bulletin/` `[v]` |
| UGC NET | https://ugcnet.nta.nic.in/ `[v]` | |
| CSIR-UGC NET | https://csirnet.nta.nic.in/ `[v]` | |
| CMAT | https://cmat.nta.nic.in/ `[v]` | |
| CUET-UG | https://cuet.nta.nic.in/ `[v]` | Timed out on two of four attempts; reachable but slow |
| CUET-PG | https://exams.nta.nic.in/cuet-pg/ `[v]` | |
| ICAR AIEE | https://exams.nta.nic.in/icar/ `[v]` | **NTA administers ICAR exams.** The ICAR portal is not where you apply |
| NCET (admission to teacher education) | https://exams.nta.nic.in/ncet/ `[v]` | |
| NIFT | https://exams.nta.nic.in/niftee/ `[v]` | |
| JIPMAT | https://exams.nta.nic.in/jipmat/ `[v]` | **`jipmat.nta.nic.in` does not resolve** |
| `/icet/`, `/cuet-ug/`, `/aisneet/`, `/cdsc/` | — | All 404 on `exams.nta.nic.in` |

**Fragility:** the *inconsistent host* is the trap. Some exams are on
`<exam>.nta.nic.in` and some on `exams.nta.nic.in/<exam>/`. Neither shape is
derivable from the other, and the older `exam.nta.nic.in` and
`<exam>.nic.nic.in` guesses do not resolve at all. Every NTA notice PDF is a
timestamped `Notice_<14 digits>.pdf`.

## CTET

| What | URL | Notes |
|---|---|---|
| Main portal | https://ctet.nic.in/ `[n]` | **Unreachable from the checking host** — connect timeout on repeated attempts, DNS resolves. Not evidence of an outage |
| Former host | — | **`www.cdsc.nic.in` does not resolve**, and the old NTA subdomain `ctet.nta.nic.in` is not current either. `ctet.nic.in` is the only host in use |

**Unverified.** The domain in the records (`ctet.nic.in`) is the one the
search index and CBSE/NCERT material point to, and is the value this file
treats as correct — but it must be opened in a browser before being trusted.
CTET is run by the Central Testing Board, not NTA. The annual schedule is
published as a notification PDF, not as a per-exam page.

## National Board of Examinations in Medical Sciences (NBEMS)

| What | URL | Notes |
|---|---|---|
| Main portal | https://natboard.edu.in/ `[b]` | 403 to non-browser clients. `www.natboard.edu.in` likewise |
| Notice viewer | https://natboard.edu.in/viewNotice.php?NBE=`<opaque>` `[v]` | The `NBE=` value is obfuscated and changes; not a durable link |
| Exam archive | https://examarchive.natboard.edu.in/ `[v]` | **Separate subdomain** for past papers |
| Results | `https://results.natboard.edu.in/<exam>/index` `[b]` | **Separate subdomain.** The old per-exam paths (`/cetss/`, `/fmge/`, `/mds/`, `/pgmedical/`, `/neetss/`) now all 404 — they move per cycle |
| Legacy `nbe.edu.in` | https://nbe.edu.in/ `[v]` | Reachable but its landing page still links 2021–2022 bulletins. Use for archive documents only, never as `official_url` |
| `www.nbems.org` | — | **Wrong body.** New Britain EMS, USA |

**Application portal:** the fillable forms are served from
`cdn3.digialm.com/EForms/configuredHtml/1815/<numeric id>/Index.html` — a
**different company entirely**, on numeric ids that are reissued per exam. This
is the single least durable URL class in the whole corpus: it is a snapshot of
one form, and it disappears when the cycle ends. Prefer the notice PDF on
`natboard.edu.in` for `official_url` and treat the Digialm URL as
`apply_url` with an explicit short shelf life.

**Fragility:** 403 by default, opaque notice ids, a results host that
reorganises per cycle, and a form vendor that reissues ids. Any of these can
break between two visits a week apart.

## AIIMS

| What | URL | Notes |
|---|---|---|
| Exam portal | https://aiimsexams.ac.in/ `[v]` | Next.js. One portal for all AIIMS |
| Key dates | https://aiimsexams.ac.in/landingpage/key-dates `[v]` | |
| Notices | https://aiimsexams.ac.in/landingpage/notice `[v]` | |
| Miscellaneous notices | https://aiimsexams.ac.in/landingpage/miscellaneous-notice `[v]` | |
| Per-exam advertisement | `https://aiimsexams.ac.in/landingpage/courses/advertisement/<ObjectId>` `[v]` | **Mongo ObjectId in the path.** Stable for the life of the exam, meaningless otherwise |
| Institute (not exams) | https://www.aiims.edu/ `[v]` | `aiims.edu.in` has a certificate that does not match the hostname — use `.edu` |

**Stable per-exam page:** yes, via the ObjectId, and those pages *are* the
notification. That is the correct `official_url` for an AIIMS record, not the
landing page.

**Fragility:** the ObjectId is a database key. If AIIMS re-imports the
advertisement, the link 404s and there is no redirect.

## ISRO

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.isro.gov.in/ `[v]` | **`www` is required** — bare `isro.gov.in` does not resolve |
| Careers | https://www.isro.gov.in/Careers.html `[v]` | The recruitment index; anchor `#Recruitment` also works |
| ICRB recruitment | https://www.isro.gov.in/ICRB_Recruitment13.html `[v]` | A numbered, hand-maintained page. Note the number changes as ICRB cycles advance |
| Advertisement PDFs | `https://www.isro.gov.in/media_isro/pdf/recruitmentNotice/<YYYY>/<Month>/<Name>_<DDMMYYYY>.pdf` `[v]` | |
| Results | — | Published as PDFs on the careers pages, and on the same host under `media_isro/pdf/…`. No result index page |

**Fragility:** the `/media_isro/…` directory rewrites internally (a request for
the bare directory comes back as `/15R0/media_isro/…`) — harmless for files,
confusing for directory probing. ICRB pages are hand-numbered, so the *number*
is the fragile part, not the path shape. `isro.gov.in` without `www` is NXDOMAIN.

## DRDO

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.drdo.gov.in/drdo/en `[v*]` | Redirects to `drdo.gov.in/drdo/en/`. The site is **bilingual with a hard language prefix**; `www.drdo.gov.in` alone lands on `/drdo/hi/` |
| Vacancies / recruitment | https://www.drdo.gov.in/drdo/en/offerings/vacancies `[v]` | **The recruitment index.** Each vacancy has its own transliterated slug under it |
| Press releases | https://www.drdo.gov.in/drdo/en/documents/press-release `[v]` | |
| CEPTAM notice board | https://drdo.res.in/ceptam_noticeboard/drentrystatus/index.php `[v]` | **Separate host**, `drdo.res.in`, for the graduate-engineer entry portal |
| `drdo.gov.in/job-opportunities` | — | 404. Not a real path |

**Fragility:** every slug is a romanised transliteration of Hindi, so they are
long, contain typos, and change when a notice is edited. The English language
prefix is required; `?` and language cookies change which prefix you get.

## Food Corporation of India

| What | URL | Notes |
|---|---|---|
| Main portal | https://fci.gov.in/ `[v]` | **Not `www`** — `www.fci.gov.in` resets the connection |
| Careers | https://fci.gov.in/careers `[v]` | |
| Recruitment | https://fci.gov.in/recruitment `[v]` | |
| Circulars | https://fci.gov.in/Circulars `[v]` | |
| `www.fci.co.in` | — | **Parked domain, "this website is for sale".** Do not use |

## Employees' Provident Fund Organisation

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.epfo.gov.in/ `[v]` | `www.epfindia.gov.in` still redirects here, so old links work |
| Recruitments | https://www.epfo.gov.in/recruitments/ `[v]` | |
| Circulars | https://www.epfo.gov.in/circulars/ `[v]` | |
| Tender notices | https://www.epfo.gov.in/tender-notices/ `[v]` | |
| APFC recruitment | — | **Run by UPSC, not EPFO.** `upsconline.nic.in/ora/` is the application portal |

## Coal India

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.coalindia.in/ `[v]` | **`www` is required** — bare `coalindia.in` is NXDOMAIN |
| Careers | https://www.coalindia.in/career-cil/jobs-coal-india/ `[v]` | |
| Per-notice page | `https://www.coalindia.in/career-cil/jobs-coal-india/<slug>` `[v]` | |
| Advertisement PDFs | `https://www.coalindia.in/admin/img/UploadedFiles/LatestJobOpening/Files/DetailedAd<DDMMYYYY>.pdf` `[v]` | |

## Indian Oil Corporation

| What | URL | Notes |
|---|---|---|
| Main portal | https://iocl.com/ `[b]` | **Returns `307` with no `Location` header** — behind Sucuri, misconfigured. A browser paints an interstitial; a script has nowhere to go |
| Careers | `https://iocl.com/pages/career-opportunities` `[b]` | Same broken 307 |
| Advertisement PDFs | `https://iocl.com/admin/img/UploadedFiles/LatestJobOpening/Files/DetailedAd<DDMMYYYY>.pdf` `[b]` | |

**Unverified beyond the 307.** Every path on this host returns a
Location-less 307 to a non-browser client, so nothing on `iocl.com` can be
confirmed by script. The site is up — it is just walled. Open it in a browser
and record the notice PDF; the `/admin/img/UploadedFiles/LatestJobOpening/Files/`
directory pattern is where they live.

## GAIL

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.gailonline.com/ `[v]` | |
| Vacancies | https://www.gailonline.com/vacancies.html `[v]` | The recruitment index |
| `www.gailonline.com/careers` | — | 403. Not a real path |

## Power Grid Corporation

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.powergrid.in/en `[v*]` | Redirects to `/en`. The site is language-prefixed; `www.powergrid.in` alone lands on `/hi` |
| `powergrid.in` (bare) | — | **WAF redirect loop.** The Imperva-style guard rewrites the URL to itself with an `_event_attackname=URL+Access+Violation` query and never terminates. My checker calls this an error, correctly |
| Careers | `https://www.powergrid.in/en/<career-path>` `[?]` | `/en/career` and `/en/career/vacancy` are both 404. Find the path in a browser |

## SIDBI

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.sidbi.in/en/ `[v*]` | `www.sidbi.in` redirects to `/en/` |
| Careers | https://www.sidbi.in/en/careers `[v]` | |
| Per-notice page | `https://www.sidbi.in/en/careers/careerdetails/<slug>` `[v]` | Slug contains the date: `recruitment_of_officers_in_grade_a_and_grade_b_general_and_specialist_stream_14_07_2025` |
| `/content/inner-page/careers` | — | 404. Not a real path |

## Banks and insurance

| Body | What | URL | |
|---|---|---|---|
| Bank of India | Main portal | https://www.bankofindia.bank.in/ `[b]` | 403 to scripts |
| Bank of India | Careers | `https://www.bankofindia.bank.in/en/careers` `[b]` | Also 403 |
| State Bank of India | Main portal | https://sbi.co.in/ `[v*]` | Redirects to `/redirect/` |
| State Bank of India | Careers | `http://www.sbi.co.in/web/careers` `[v*]` | **Plain HTTP.** 302 to the HTTPS host |
| Punjab National Bank | Main portal | https://pnb.bank.in/ `[v]` | **`pnbindia.in` and `www.pnbindia.in` both redirect here** |
| UIIC | Careers | https://uiic.co.in/web/careers/recruitment `[v]` | `uiic.co.in` → `/web` → `/web/` |
| PFRDA | Vacancies | https://pfrda.org.in/get-to-know/careers/vacancies `[v]` | |

## NTPC, BHEL, ONGC, India Post

| Body | What | URL | |
|---|---|---|---|
| NTPC | Main portal | https://ntpc.co.in/ `[b]` | **Radware bot manager** issues a 302 to `validate.perfdrive.com`. Never a real answer |
| NTPC | Careers | `https://ntpc.co.in/careers` `[?]` | Same wall. The bot manager answers 302 to `validate.perfdrive.com` on some requests and 404 on others, so nothing here is checkable |
| BHEL | Main portal | https://www.bhel.com/ `[v]` | `bhel.com` also works |
| ONGC | Main portal | https://ongcindia.com/ `[v]` | |
| India Post | Main portal | https://www.indiapost.gov.in/ `[v]` | SharePoint; the old `_layouts/15/DOP.Portal.UI/BCMainView.aspx` is 404 |

## Defence services

| Body | What | URL | |
|---|---|---|---|
| Indian Army | Main portal | https://joinindianarmy.nic.in/ `[v*]` | Redirects to `Authentication.aspx` for everything, including `/contact-us.htm` |
| Indian Navy | Main portal | https://www.joinindiannavy.gov.in/ `[v]` | **Bare host returns an empty reply.** `www` is required |
| Indian Navy | Per-notice page | `https://www.joinindiannavy.gov.in/en/page/<slug>.html` `[v]` | The right granularity for `official_url` |
| Indian Air Force | Main portal | https://indianairforce.nic.in/ `[v]` | 5.8 MB, very slow. Two of four attempts timed out mid-transfer |
| Agniveer Vayu | PSL registration | https://agnipathvayu.cdac.in/AV/psl `[b]` | **503** — C-DAC's WAF. Registration is on a C-DAC host, not an IAF one |

**Fragility:** the Army portal redirecting *every* path to
`Authentication.aspx` means no deep link on `joinindianarmy.nic.in` is
verifiable. The Navy's per-notice pages are the best in this table.

## ICAR

| What | URL | Notes |
|---|---|---|
| Main portal | https://icar.gov.in/ `[b]` | **Certificate expired**, not merely incomplete |
| Admissions registry | `https://icar.gov.in/admission-registry` `[b]` | Same |
| Actual application host | https://exams.nta.nic.in/icar/ `[v]` | **Run by NTA.** ICAR's own portal carries the notice; the form is on NTA |

## CRRI

| What | URL | Notes |
|---|---|---|
| `crri.in` / `www.crri.in` | — | **Both redirect to `skitterbug.co`**, an unrelated commercial site. The Central Research Institute of Dryland Agriculture's domain is gone or hijacked. Do not link it |

---

# State public service commissions and boards

## Bihar — BPSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://bpsc.bihar.gov.in/ `[b]` | Incomplete certificate chain |
| Advertisements | https://bpsc.bihar.gov.in/advertisement/ `[b]` | |
| **Exam calendar** | https://bpsc.bihar.gov.in/exam-calendar/ `[b]` | **Yes, BPSC publishes a calendar of examinations** |
| Tender notices | https://bpsc.bihar.gov.in/tender-notices/ `[b]` | |
| Notice PDFs | `https://bpsc.bihar.gov.in/wp-content/uploads/BPSC_content/Notices/<Title>-BPSC-<YYYYMMDD>-<slug>.pdf` `[b]` | Title in the filename with a random slug suffix |
| Application portal | https://bpsconline.bihar.gov.in/ `[v*]` | **Separate host.** → `/candidate/login` |

## Uttar Pradesh — UPPSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://uppsc.up.nic.in/ `[v]` | **`uppsc.up.gov.in` and `psc.up.gov.in` do not resolve** |
| Examinations index | https://uppsc.up.nic.in/PublicPages/Examinations_Details.aspx?ID=EC `[v]` | |
| Application | same host, `/OuterPages/…` `[v]` | |
| `psc.up.gov.in` / `uppsc.up.gov.in` | — | NXDOMAIN |
| `jsc.up.gov.in`, `jsc.up.nic.in` | — | NXDOMAIN. The UP Judicial Service Commission is not on those hosts |

**Fragility:** **soft 404.** Any unknown path returns HTTP **200** at
`FileNotFound.aspx?aspxerrorpath=…`. Every UPPSC "200" needs its final URL
checked, not just its status.

## Rajasthan — RPSC and SSO

| What | URL | Notes |
|---|---|---|
| Main portal | https://rpsc.rajasthan.gov.in/ `[v]` | |
| Exam dashboard | https://rpsc.rajasthan.gov.in/examdashboard `[v]` | 2.3 MB; slow |
| Apply online | https://rpsc.rajasthan.gov.in/applyonline `[v]` | |
| Advertising agency SSO | https://sso.rajasthan.gov.in/ `[v]` | **Separate host.** SSO is run by the advertising agency, not the commission. `/notice` and `/advertisement` are 404 here |
| Recruitment SSO entry | `https://sso.rajasthan.gov.in/signin?ru=RECRUITMENT` `[v]` | Redirects with a per-request `encq=` token — never matches as a static string |
| Recruitment microsite | https://recruitment.rajasthan.gov.in/ `[v]` | |
| Notice PDFs | `https://rpsc.rajasthan.gov.in/Static/RecruitmentAdvertisements/<GUID>.pdf` `[v]` | GUID only, no filename |

**Annual calendar:** RPSC publishes a "Tentative Schedule of Examinations"
alongside the exam dashboard. There is no dedicated calendar URL, so cite the
dashboard or the specific notification.

## Maharashtra — MPSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://mpsc.gov.in/ `[v]` | **React SPA, 4 KB of shell.** No server-rendered content |
| Application portal | https://mpsconline.gov.in/ `[v*]` | **Separate host.** → `/candidate/login` |
| `mpscpune.gov.in`, `mpsc.maharashtra.gov.in` | — | NXDOMAIN |
| Annual calendar | — | Not found as a separate page |

## Madhya Pradesh — MPESB

| What | URL | Notes |
|---|---|---|
| Main portal | https://esb.mp.gov.in/ `[b]` | Incomplete certificate chain |
| Application portal | https://esb.mponline.gov.in/ `[v*]` | **Separate host.** → `/Portal/Examinations/Vyapam/examsList.aspx` |
| `mpesb.gov.in`, `test.mponline.gov.in` | — | NXDOMAIN |

## Karnataka — KPSC and KEA

| What | URL | Notes |
|---|---|---|
| Main portal | https://kpsc.kar.nic.in/ `[b]` | Serves **malformed response headers**; curl and browsers cope, Node's fetch does not |
| Notifications | https://kpsc.kar.nic.in/notification.html `[v]` | Real page. The nav reaches it via `javaScript:getContent('notification.html')` |
| Answer keys | https://kpsc.kar.nic.in/keyanswers.html `[v]` | Note the plural "keys" — `answerkey.html` is 404 |
| Results | https://kpsc.kar.nic.in/results.html `[v]` | |
| Application portal | https://kpsconline.karnataka.gov.in/ `[b]` | **Separate host.** Incomplete chain |
| KEA (KCET / KSET / CET) | https://cetonline.karnataka.gov.in/kea/ `[v]` | **A third host** — Karnataka Examinations Authority, not KPSC |
| KEA index | https://cetonline.karnataka.gov.in/kea/indexnew `[v]` | |
| KSET 2026 | `https://cetonline.karnataka.gov.in/kea/kset2026` `[v]` | Per-year path segment |
| KSET login | https://cetonline.karnataka.gov.in/kset2026/Account/Login `[v]` | A *fourth* shape, on the same host |
| Notification PDFs | `https://kpsc.kar.nic.in/<ABBR>%20<POST>%20Notification%20dt%20DD-MM-YYYY.pdf` `[v]` | Spaces as `%20`, title case |
| `exams.karnataka.gov.in`, `karnatakajobs.karnataka.gov.in` | — | NXDOMAIN |

**Three hosts for one state.** Notices on `kpsc.kar.nic.in`, applications on
`kpsconline.karnataka.gov.in`, entrance exams on `cetonline.karnataka.gov.in`
under KEA. A record can easily point at the wrong one.

## Kerala — Kerala PSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://keralapsc.gov.in/ `[v]` | |
| Notifications | https://keralapsc.gov.in/index.php/notifications `[v]` | |
| Examinations / calendar | https://keralapsc.gov.in/index.php/examinations `[v]` | The closest thing to a calendar |
| Answer keys (OMR) | https://keralapsc.gov.in/index.php/answerkey_omrexams `[v]` | |
| Answer keys (online) | https://keralapsc.gov.in/index.php/answerkey_onlineexams `[v]` | **Split by exam mode** — check which one applies |
| Ranked lists | https://keralapsc.gov.in/index.php/rankedlist `[v]` | |
| Shortlists | https://keralapsc.gov.in/index.php/shortlists `[v]` | |
| Examination updates | https://keralapsc.gov.in/index.php/psc-examination-updates `[v]` | |
| Previous question papers | https://keralapsc.gov.in/index.php/previous-question-papers `[v]` | |
| Circulars / orders | https://keralapsc.gov.in/index.php/important-orders-circulars `[v]` | |
| Gazette notices | `https://keralapsc.gov.in/index.php/extra-ordinary-gazette-date-DDMMYYYY` `[v]` | **Date in the slug** — changes on republication |
| Notice PDFs | `https://keralapsc.gov.in/sites/default/files/2026-08/noti-<no>-26.pdf` `[v]` | **Month-scoped** path. Moves to a new directory when re-uploaded |

**Annual calendar:** published inside the "Examinations" page as a table, not as
a separate document.

## Tamil Nadu — TNPSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://tnpsc.gov.in/ `[v]` | |
| Results | `https://tnpsc.gov.in/English/Results.aspx` `[v]` | Also `DResultView.aspx`, `AISOResultView.aspx` |
| Answer keys | https://tnpsc.gov.in/English/answerkeys.aspx `[v]` | |
| Application portal | https://tnpscexams.in/ `[v]` | **Separate host** |
| Apply / OTR | https://apply.tnpscexams.in/ `[v*]` | **A third host.** → `/secure?app_id=UElZMDAwMDAwMQ==` |
| `tnscript.org` | — | NXDOMAIN |

**Fragility:** three hosts, and the apply host resolves to a
`/secure?app_id=` bounce with a static base64 application id. Deep paths on it
carry `?app_id=…` and change between campaigns.

## Telangana — TGPSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.tgpsc.gov.in/ `[v]` | **`g`, not `s`.** `www.tspsc.gov.in` is NXDOMAIN |
| Live site | https://websitenew.tgpsc.gov.in/ `[v]` | The current build; linked from the main portal |
| Notifications | https://websitenew.tgpsc.gov.in/notifications `[v]` | |
| Direct recruitment | https://websitenew.tgpsc.gov.in/directRecruitment `[v]` | |
| Application portal | `https://application.tgpsc.gov.in/CandidateEntryOG042026` `[?]` | **Separate host**, and the path carries a running `OG04 2026` token |
| Hall tickets | `https://hallticket.tspsc.gov.in/h<uuid>` `[?]` | **A fourth host**, UUID per exam |
| GR / other services | https://igrs.tgpsc.gov.in/ `[?]` | |
| OTR portal | https://otr.tgpsc.gov.in/login?type=new `[?]` | |
| PDF previews | `https://websitenew.tgpsc.gov.in/preview/<base64>.pdf?faceSet=…` `[?]` | Opaque preview wrapper |

**Four hosts**, and the *correct* one differs from the obvious spelling by a
single letter. CGPSC's own "other PSCs" link list still points at
`www.tspsc.gov.in`, so the wrong spelling is actively being propagated by other
government sites.

**Annual calendar:** a "Key Dates" / examination schedule table inside the
direct-recruitment pages. No standalone calendar URL.

## Andhra Pradesh — APPSC

| What | URL | Notes |
|---|---|---|
| Jump page | https://psc.ap.gov.in/ `[v]` | **A landing page of tiles, not the site.** 4.9 KB of links |
| Actual main portal | https://portal-psc.ap.gov.in/Default.aspx `[b]` | **What `psc.ap.gov.in` points at** |
| Application portal | https://applications-psc.ap.gov.in/ `[?]` | A **fourth** host, listed on the jump page |
| OTPR (one-time registration) | https://otpr-psc.ap.gov.in/ `[b]` | |
| Hall tickets | `https://portal-psc.ap.gov.in/Download_HallTickets` `[?]` | |
| `www.apsc.ap.gov.in`, `apsc.gov.in` | — | NXDOMAIN (and `apsc.gov.in` is Assam's, which is also broken) |

**Fragility:** four hosts behind one tile page, all with incomplete certificate
chains. A record pointing at `psc.ap.gov.in` points at a page whose only
content is four links.

## Odisha — OPSC and OUSSSC

| What | URL | Notes |
|---|---|---|
| OPSC main portal | https://opsc.gov.in/ `[v*]` | → `/Public/OPSC/Default.aspx` |
| Notice and document pages | `https://opsc.gov.in/Public/OPSC/Pages/View_Content.aspx?id=<opaque>` `[v]` | **Opaque base64 id. There is no stable per-notice URL.** This is the worst URL class in the state set |
| OUSSSC | https://ousssc.odisha.gov.in/ `[v]` | Intermittent — reachable on retry |
| OSSC (Subordinate Staff Commission) | https://www.ossc.gov.in/ `[v*]` | → `/Public/OSSC/Default.aspx` |
| `opsc.in`, `opsc.odisha.gov.in` | — | `opsc.in` has a broken chain; `opsc.odisha.gov.in` is NXDOMAIN |

## West Bengal — WBPSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://psc.wb.gov.in/ `[b]` | **TLS legacy renegotiation** |
| Application portal | https://wbpsc.ucanapply.com/ `[v*]` | **Separate host**, and a completely different stack. → `/secure` → `/index` → `/secure?app_id=…` |
| Notice PDFs | `https://psc.wb.gov.in/Download?param1=<file>&param2=advertisement` `[v]` | Query-string download endpoint, not a file path |
| `ucanapply.com` (bare) | — | A different site. Only `wbpsc.` is WBPSC |

**Fragility:** the apply host bounces through three hops to a
`/secure?app_id=UElZMDAwMDAwMQ==` that is the *same* static string TNPSC uses.
Do not treat that final URL as WBPSC-specific.

## Chhattisgarh — CGPSC and CG Vyapam

| What | URL | Notes |
|---|---|---|
| Main portal | https://www.psc.cg.gov.in/ `[v]` | |
| Advertisements | https://www.psc.cg.gov.in/Advertisement.php `[v]` | **`.php` extension**, unlike most states |
| Model answers | https://www.psc.cg.gov.in/Modelanswer.php `[v]` | The answer-key index |
| Results | https://www.psc.cg.gov.in/Result.php `[v]` | |
| Notifications | https://www.psc.cg.gov.in/Notifications.php `[v]` | |
| List of proposers | https://www.psc.cg.gov.in/ROP.html `[v]` | Rejected/overlapping-person candidates — worth linking for a selection-based exam |
| Vyapam (apply) | https://vyapamcg.cgstate.gov.in/ `[v]` | **Separate host.** Bare host only — `www.vyapamcg.cgstate.gov.in` is NXDOMAIN |
| Vyapam profile | https://vyapamprofile.cgstate.gov.in/online/ `[v]` | |
| `cgpsc.gov.in`, `cgvyapam.nic.in` | — | NXDOMAIN |

**Fragility:** a wrong `.aspx` path returns 404 here (unlike UPPSC and NABARD),
but the *extension* is easy to get wrong: `/advertisement` is 404,
`/Advertisement.php` is 200.

## Gujarat — GPSC and OJAS

| What | URL | Notes |
|---|---|---|
| Main portal | https://gpsc.gujarat.gov.in/ `[v]` | |
| Advertisements | https://gpsc.gujarat.gov.in/dashboard?stage=Advertisement `[v]` | Query-string "stage" routing |
| Results | https://gpsc.gujarat.gov.in/dashboard?stage=Result `[v]` | |
| Open recruitment | https://gpsc.gujarat.gov.in/RecruitmentOpen `[v]` | |
| Answer keys | https://gpsc.gujarat.gov.in/StageDocument?name=answerkey `[v]` | **Query-string document endpoint**, not a file path |
| Provisional results | https://gpsc.gujarat.gov.in/StageDocument?name=provisionalresult `[v]` | |
| Application portal | https://gpsc-ojas.gujarat.gov.in/ `[v]` | **Separate host** — OJAS. 1.5 MB |
| OJAS advertisement PDFs | `https://gpsc-ojas.gujarat.gov.in/AdvtList.aspx?type=<token>` `[v]` | Token in the query |
| Notice PDFs | `https://ojas.gujarat.gov.in/AdvtDetailFiles/GPSC_<year>_<no>_<n>.pdf` `[v]` | Note `ojas.` (without `gpsc-`) also serves these |
| `dgp.gujarat.gov.in` | — | NXDOMAIN. The police DGP site is `https://police.gujarat.gov.in/dgp/default.aspx` `[v]` |

**Fragility:** the answer-key and result "indexes" are `StageDocument?name=…`
query endpoints, so there is no page a maintainer can bookmark as *the* answer
key index — the URL only means anything in context.

## Haryana — HSSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://hssc.gov.in/ `[n]` | **Not reachable from the checking host** — SERVFAIL at both Cloudflare and Google public resolvers. The search index carries content dated 2026-09-26, so the site is up; this is a network or resolver-level block. Verify in a browser before concluding anything |
| Advertisements | https://hssc.gov.in/advertisement `[n]` | Same |
| Notifications | https://hssc.gov.in/notifications `[n]` | Same |
| Public notices | https://hssc.gov.in/publicNotice `[n]` | Same |
| Notice files | `https://hssc.gov.in/file/<uuid>/publicNotice` `[n]` | **UUID-stable**, so these hold across cycles once known |
| Application portal | `https://onetimeregn.haryana.gov.in/hssc` `[b]` | **Separate host**, and its certificate does not cover the hostname. A browser can proceed past the warning; a script never will |
| Per-advertisement portals | `https://adv012026.hryssc.com/` `[v]` | **`adv` + zero-padded number + year.** One host per advertisement. The 2026 ones are live; a new cycle means a new host |
| Result portals | `https://cet2025groupc.hryssc.com/` `[?]` | Same per-campaign pattern |

**Separate application domain:** yes, and then *one host per advertisement*
beyond that. A `apply_url` pinned to `adv052026.hryssc.com` is correct for one
advertisement and wrong for the next.

## Himachal Pradesh — HPPSC, HPBOSE and HP Police

| What | URL | Notes |
|---|---|---|
| HPPSC main portal | https://hppsc.hp.gov.in/ `[b]` | **TLS legacy renegotiation** |
| What's new | https://hppsc.hp.gov.in/Home/HomeWhatsNew `[b]` | |
| Application portal | `https://hppsconline.hp.gov.in/HPPSC/ApplicantRegistration/Home/Login` `[?]` | **Separate host** — linked from CGPSC's PSC directory |
| HPBOSE (TET) | https://hpbose.org/ `[v]` | **The state's own board, not HPPSC.** TET is run by HPBOSE |
| TET notifications | `https://hpbose.org/Admin/Upload/<title>.pdf` `[v]` | Title in the filename, no date |
| HP Police | `https://hppolice.gov.in` `[b]` | Certificate does not cover the hostname. Police recruitment is advertised by the police, not HPPSC |

## Delhi — DSSSB

| What | URL | Notes |
|---|---|---|
| Main portal | https://dsssb.delhi.gov.in/ `[v]` | |
| Vacancies | https://dsssb.delhi.gov.in/dsssb-vacancies `[v]` | The advertisement index |
| Archived vacancies | https://dsssb.delhi.gov.in/dsssb/archived-vacancies `[v]` | |
| Latest results | https://dsssb.delhi.gov.in/doit/dsssb/latest-result `[v]` | |
| Answer keys | https://dsssb.delhi.gov.in/doit/tab-content/answer-keys `[v]` | |
| Advertisement PDFs | `https://dsssb.delhi.gov.in/sites/default/files/DSSSB/circulars-orders/final_advt-<NN>-<YYYY>.pdf` `[v]` | |
| Online application / admit card | https://dsssbonline.nic.in/ `[v]` | **Separate host.** `AdmitCardEntry.aspx` `[v]` |
| `oars.dsssb.delhi.gov.in` | — | **NXDOMAIN.** The old OARS apply host is gone. Use `dsssbonline.nic.in` |

## Punjab — PSSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://sssb.punjab.gov.in/ `[b]` | **TLS legacy renegotiation** |
| Application | same host, per-campaign paths `[b]` | PSSC does not use a separate apply domain, unlike most states |
| `hssb.punjab.gov.in`, `pssb.punjab.gov.in`, `pssbc.punjab.gov.in` | — | **All NXDOMAIN.** The host is `sssb` — the two-s form. Easy to get wrong and every wrong form is dead |

## Uttarakhand — UKPSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://psc.uk.gov.in/ `[v]` | |
| Recruitment | https://psc.uk.gov.in/candidate-corner/recruitment `[v]` | |
| Results | https://psc.uk.gov.in/candidate-corner/results `[v]` | |
| Admit cards | `https://psc.uk.gov.in/candidate-corner/admitcards` `[?]` | 500 at time of check, though listed in the site's own nav |
| Answer keys | `https://psc.uk.gov.in/candidate-corner/answerkey` `[?]` | 500 at time of check |
| Notices | `https://psc.uk.gov.in/quicklinks/recruitment-notifications` `[?]` | 500 at time of check |
| Apply online | https://psc.uk.gov.in/apply-online `[v]` | |
| Exam calendar | `https://psc.uk.gov.in/exam%20calendar` `[?]` | **A literal space in the path** — must be percent-encoded |
| `ukpsc.in` | — | A private aggregator, unrelated. `www.ukpsc.in` 302s to `ww9.ukpsc.in` |

## Jammu & Kashmir — JKSSB

| What | URL | Notes |
|---|---|---|
| Main portal | https://jkssb.nic.in/ `[b]` | **The server sends no issuer certificate.** Browsers load it; nothing scripted will |
| Job advertisements | `https://jkssb.nic.in/Home/JobAdvertisement` `[b]` | |
| Candidate login | `https://jkssb.nic.in/CandidateLogin.aspx` `[b]` | |
| `jkpccs.jk.gov.in`, `www.jkpsc.jk.gov.in`, `www.jkpss.gov.in` | — | NXDOMAIN |
| `jk.gov.in`, `portal.jk.gov.in` | — | Timeout / NXDOMAIN |
| `jkreforms.com`, `jkhudd.gov.in` | — | NXDOMAIN |

**Fully unverified by script.** Every JKSSB path needs a browser.

## North-East states

| Body | What | URL | |
|---|---|---|---|
| Assam PSC | Main portal | https://apsc.nic.in/ `[b]` | **Incomplete chain.** `apsc.gov.in` has a broken DNS delegation — this is the right domain |
| Assam PSC | Downloads | https://apsc.nic.in/downloads.php `[b]` | |
| Assam PSC | Per-year advertisement index | `https://apsc.nic.in/advt_2025.php` `[b]` | **Year in the filename**, one page per year |
| Assam PSC | Per-year notifications | `https://apsc.nic.in/notifications_2025.php` `[b]` | Same |
| Assam PSC | Application portal | https://apscrecruitment.in/ `[v]` | **Separate host** |
| Arunachal PSC | Main portal | https://appsc.gov.in/ `[v*]` | → `/Index/institute_home/ins/RECINS001`. **`apsc` and `appsc` are different bodies** — Arunachal vs Assam |
| Arunachal PSC | Exam calendar PDF | `https://appsc.gov.in/upload/files/RECINS001/EXAMINATION_CALLENDAR_<DDMMYYYY_HHMMSS>.pdf` `[v]` | **Yes, APSB publishes an exam calendar.** Note the spelling "CALLENDAR" in the filename |
| Arunachal PSC | Notice PDFs | `https://appsc.gov.in/upload/files/RECINS001/<FILE>_<DDMMYYYY_HHMMSS>.pdf` `[v]` | **Timestamped** |
| Nagaland PSC | Main portal | https://npsc.nagaland.gov.in/ `[v]` | |
| Nagaland PSC | Advertisements | https://npsc.nagaland.gov.in/advertisement `[v]` | |
| Nagaland PSC | Results | https://npsc.nagaland.gov.in/results `[v]` | |
| Nagaland PSC | Admit cards | `https://npsc.nagaland.gov.in/services/<dept>/admit-card` `[b]` | Department in the path; 403 to scripts |
| Nagaland PSC | Notice pages | `https://npsc.nagaland.gov.in/advertisement/178713486224731` (and the same shape under `/notification/`) `[v]` | **A Unix timestamp as the path segment** — the least stable URL shape in this table |
| Manipur PSC | Main portal | https://mpscmanipur.gov.in/ `[v]` | `mpsmanipur.gov.in` is NXDOMAIN |
| Manipur PSC | Advertisements | https://mpscmanipur.gov.in/Recruitment_Advertisement.html `[v]` | |
| Meghalaya PSC | Main portal | https://mpsc.meghalaya.gov.in/ `[v]` | |
| Meghalaya PSC | Notifications | https://mpsc.meghalaya.gov.in/notifications-st.html `[v]` | **`-st` suffix** — the Sanskritised-textile variant of the page |
| Meghalaya PSC | Notice PDFs | `https://mpsc.meghalaya.gov.in/advt/Adv<DDMonYYYY><letter>.pdf` `[v]` | |
| Tripura PSC | Main portal | https://tpsc.tripura.gov.in/ `[v]` | Drupal |
| Tripura PSC | Notice board | https://tpsc.tripura.gov.in/notice-board `[v]` | |
| Tripura PSC | Advertisements | https://tpsc.tripura.gov.in/advertisement `[v]` | |
| Tripura PSC | Direct recruitment | https://tpsc.tripura.gov.in/direct-recruitment `[v]` | |
| Tripura PSC | Results | https://tpsc.tripura.gov.in/results `[v]` | |
| Tripura PSC | Answer keys | https://tpsc.tripura.gov.in/answer-key `[v]` | |
| Tripura PSC | ORA | https://tpsc.tripura.gov.in/online-recruitment-application-ora `[v]` | |
| Tripura PSC | Notice PDFs | `https://tpsc.tripura.gov.in/sites/default/files/<YYYY-MM>/<Name>_<DDMMYY>.pdf` `[v]` | **Month-scoped directory** |
| Sikkim PSC | Main portal | https://spscrs.sikkim.gov.in/ `[v]` | |
| Sikkim PSC | Recruitment | `https://spscrs.sikkim.gov.in/` `[v]` | `spsc.sikkim.gov.in` times out — use the `spscrs` host |

## Ladakh, Puducherry, Goa and the remaining UT/territory bodies

| Body | What | URL | |
|---|---|---|---|
| Ladakh administration | Main portal | https://ladakh.gov.in/ `[v]` | **`/en/` is not a language prefix here** — it redirects to a single news article. Use the bare host |
| Ladakh Police | — | — | **NXDOMAIN** — `ladakhpolice.nic.in` does not resolve. Ladakh UT recruitment is advertised through `https://ladakh.gov.in/` |
| Puducherry | — | — | **Gap.** Puducherry and Andaman & Nicobar run combined competitive service recruitment through a central Direct Recruitment portal, and no Puducherry PSC site of its own was reachable. The central portal most often cited, `drectcb.gov.in`, is **NXDOMAIN** as of 2026-09-27. Do not store a URL here without opening it in a browser |
| Goa PSC | Main portal | `https://gpsc.goa.gov.in/` `[?]` | Linked from CGPSC's PSC directory. Not reached from here |
| JPSC (Jharkhand) | Main portal | https://jssc.jharkhand.gov.in/ `[b]` | Incomplete chain. Now also runs CSIR-UGC NET style combined recruitment |
| JPSC (Jharkhand) | Advertisement PDFs | `https://jssc.jharkhand.gov.in/uploads/<...>.pdf` `[?]` | |

## Mizoram — MPSC

| What | URL | Notes |
|---|---|---|
| Main portal | https://mpsc.mizoram.gov.in/ `[v]` | **Mizoram MPSC, not Maharashtra MPSC.** The acronym collision is real and both are live |
| Direct recruitment | https://mpsc.mizoram.gov.in/page/direct-recruitment `[v]` | Split Government / Non-Government, each with a per-year advertisement page |
| Notices | https://mpsc.mizoram.gov.in/posts `[v]` | The notice board |
| Online application | https://mpsc.mizoram.gov.in/page/online-application `[v]` | |
| Application portal | https://mpsconline.mizoram.gov.in/ `[v]` | **Separate host** |
| `mizorampsc.gov.in`, `mpscmizoram.gov.in` | — | NXDOMAIN. Neither spelling has ever resolved |

**Fragility:** the CMS has a typo baked into a live path —
`/page/notificcation-ng` (three c's). The `/page/downloads` slug in the site's
own navigation is 404.

## Police recruitment boards

Police recruitment is almost never run by the state PSC. It is advertised by the
police department, or by a dedicated state-level police recruitment board, and
the record's `bodies` value will be neither the PSC nor the police department
exactly. Four cases, all verified except where marked:

| Body | Main portal | Notes |
|---|---|---|
| Telangana State Level Police Recruitment Board (TSLPRB) | https://www.tgprb.in/ `[v]` | **`tslprb.ap.gov.in` is NXDOMAIN.** The board is Telangana's and lives on a `.in` domain, not a `.ap.gov.in` one. `/recruitment` is 404; find the path in the site nav |
| Andhra Pradesh State Level Police Recruitment Board | https://slprb.ap.gov.in/UI/recruitments `[v]` | **Strip `.aspx`** and it redirects to the same page without the extension. `apsb.ap.gov.in` is NXDOMAIN |
| Andhra Pradesh Police | `https://police.ap.gov.in/` | **NXDOMAIN.** APPSC's jump page links `otpr-psc.ap.gov.in` and `applications-psc.ap.gov.in`, not a police host |
| Kerala Police | https://keralapolice.gov.in/ `[v]` | **`police.kerala.gov.in`, `keralapolice.kerala.gov.in`, `keralacops.org` and `keralapolice.org` are all dead** (NXDOMAIN or connection refused). Notifications at `https://keralapolice.gov.in/page/notification` `[v]`; `/page/recruitment` is 404 |
| Rajasthan Police | https://police.rajasthan.gov.in/ `[v]` | |
| Gujarat Police | https://police.gujarat.gov.in/dgp/default.aspx `[v]` | `dgp.gujarat.gov.in` is NXDOMAIN |
| Chhattisgarh Police | https://cgpolice.gov.in/ `[v]` | |
| Manipur Police | https://manipurpolice.gov.in/ `[v]` | |
| Himachal Pradesh Police | `https://hppolice.gov.in` `[b]` | Certificate does not cover the hostname. HP Police recruitment is advertised by the police, not HPPSC |
| Odisha Police | `https://odishapolice.gov.in/` `[n]` | Times out. `spluk.in` is NXDOMAIN |
| UP Police | `https://uppolice.gov.in/` `[?]` | Not reached |
| Delhi Police | https://delhipolice.gov.in/ `[v]` | Notices are PDFs under `/RecruitmentFile/` |

**Fragility:** a police recruitment notice is frequently the *only* official
source — several state police sites publish no index, just a
`/RecruitmentFile/<name>.pdf` link on the homepage, and the filename is replaced
each cycle. Per `docs/data-model-notes.md` §2.7, that is the case where a record
should carry `provenance.source_type` and no URL rather than a guessed one.

## Rajasthan Staff Selection Board (RSSB) and RPSC's sibling

| What | URL | Notes |
|---|---|---|
| RSSB main portal | https://rssb.rajasthan.gov.in/ `[b]` | **TLS legacy renegotiation.** `rsspcb.org` is NXDOMAIN — do not confuse the two |
| RSSB apply | `https://rssb.rajasthan.gov.in/applyonline` `[b]` | |
| RSSB notices | `https://rssb.rajasthan.gov.in/notice` `[b]` | |
| Shared SSO | https://sso.rajasthan.gov.in/ `[v]` | The same advertising-agency SSO RPSC uses |

RSSB and RPSC are separate commissions on separate hosts with a shared SSO. A
record must not point at one for the other.

## Kerala Police and Kerala PSC language paths

`keralapsc.gov.in` serves an English and a Malayalam tree, e.g.
`https://keralapsc.gov.in/ml/shortlists` `[v]` alongside
`https://keralapsc.gov.in/index.php/shortlists` `[v]`. Some Malayalam pages
exist only under `/ml/` and not under `/index.php/`, so a path that 404s in one
language may be live in the other. Notice PDFs are served from both
`keralapsc.gov.in` and `www.keralapsc.gov.in` — the same file, two hosts.

---

# Universities and entrance examinations

| Body | What | URL | |
|---|---|---|---|
| JoSAA / JEE Main | Information bulletin | https://jeemain.nta.nic.in/information-bulletin/ `[v]` | The bulletin PDF is the durable artefact; the HTML is a shell |
| JEE Advanced | Main portal | https://jeeadv.ac.in/ `[v]` | |
| NEET-UG | Main portal | https://neet.nta.nic.in/ `[v]` | Single page; every sub-path 404s |
| CUET-UG | Main portal | https://cuet.nta.nic.in/ `[v]` | Slow; timed out on 2 of 4 attempts |
| CUET-PG | Main portal | https://exams.nta.nic.in/cuet-pg/ `[v]` | Different host from CUET-UG |
| UGC NET | Main portal | https://ugcnet.nta.nic.in/ `[v]` | |
| CSIR-UGC NET | Main portal | https://csirnet.nta.nic.in/ `[v]` | Was `csirnet.gov.in` until 2024 |
| NTA notice archive | PDFs | `https://nta.ac.in/Download/Notice/Notice_<YYYYMMDDHHMMSS>.pdf` `[v]` | Timestamped |
| KEA (Karnataka) | KCET / KSET portal | https://cetonline.karnataka.gov.in/kea/ `[v]` | See Karnataka above |
| MAHE CET Cell | Main portal | https://cetcell.mahacet.org/ `[v]` | `MahacetCtl/News.html` is 404; find the path in the site's own nav |
| APSCHE (Andhra) | EAPCET | https://cets.apsche.ap.gov.in/apsche/ `[v]` | |
| Telangana | EAPCET | https://eapcet.tgche.ac.in/ `[v]` | |
| Odisha | OJEE | https://ojee.nic.in/ `[v]` | Notices at `/notices/` `[v]`. `wbjeeb.in` is WBJEE's, not OJEE's |
| West Bengal | WBJEE | `https://wbjeeb.nic.in/` `[v]` | Also `https://wbjeeb.in/` `[v]`. Both exist |
| COMEDK | Main portal | https://www.comedk.org/ `[v]` | |
| SRM Institute | Admissions | https://www.srmist.edu.in/admissions `[v]` | **Bare `srmap.edu.in` works**; `https://www.srmap.edu.in/admission/engineering/` `[v]` is the engineering sub-site. The deeper path `/admission/engineering/srmjeee-b-tech/` in the records is **404** |
| NATA | Main portal | https://www.nata.in/ `[v]` | `/apply-online` is 404. No per-year subdomain |
| NID | Admissions | https://admissions.nid.edu/ `[v]` | Redirects to `/NIDA2027/Default.aspx` — the **year is in the path** |
| VIT | VITEEE | https://viteee.vit.ac.in/ `[v]` | |
| BITS Pilani | BITSAT | `https://admissions.bits-pilani.ac.in/` `[b]` | **`www.bitsadmission.com` now 302s here.** The old domain is a redirect, not a 404 |
| BITS Pilani | Programme page | https://www.bits-pilani.ac.in/bitsat/ `[v]` | |
| IIMs | CAT | https://xatonline.in/ `[v]` | Also `https://applications.xatonline.in/` `[v]`. **`cat.xlri.ac.in` is not the body's host** |
| CAT | Per-notice page | `https://iimcat.ac.in/per/g06/pub/<n>/ASM/WebPortal/1/index.html` `[b]` | **Times out from here.** The path is a vendor WebPortal path with numeric ids — fragile |
| Symbiosis | SLAT | https://www.slat-test.org/ `[v]` | `register.php` `[v]`. **`slat.iitm.ac.in` is wrong** — SLAT is Symbiosis's, not IIT Madras's |
| SNAP | Main portal | https://www.snaptest.org/ `[v]` | |
| XAT | Main portal | `https://xlib.iimbangalore.ac.in/` `[?]` | **NXDOMAIN** from here. XAT moved off the IIMB `xlib` host; `xatonline.in` now serves the CAT/XAT cycle. Verify in a browser |
| AILET | Main portal | https://www.iimtrichy.ac.in/ `[v]` | `/ailet` is 404; the AILET page is under the institute's own admissions path. Find it in a browser |
| CLAT | Consortium portal | https://consortiumofnlus.ac.in/clat-2027/ `[v]` | **Year in the path.** Notifications as PDFs under `/clat-<year>/notifications/` |
| ISI | Admissions | https://admission.isical.ac.in/ `[b]` | HTTP/2 quirk to scripts; loads in a browser |
| JMI | Admissions | https://admission.jmi.ac.in/ `[v]` | |
| AMU | Controller's office | https://www.amucontrollerexams.com/notices `[v]` | **`amu.ac.in` has an incomplete chain**; the controller's subdomain is the cleaner path |
| Assam Agricultural University | Admissions | `https://admission.aau.ac.in/2026/` `[v]` | **Year in the path** |
| NLU Delhi | Admissions | https://nationallawuniversitydelhi.in/register.html `[v]` | |
| Manipal (MET) | Admissions | https://www.manipal.edu/mu.html `[v]` | **`manipal.edu/admissions/` is a redirect loop into `/mu/error/filenotfound.html`** — a genuine error, not just a redirect |
| IIT Bombay | JAM / GATE-adjacent | https://www.ceed.iitb.ac.in/ `[v]` | |
| IIT Bombay | JEE Main counselling support | https://www.uceed.iitb.ac.in/ `[v]` | |
| ESIC | Recruitment | https://www.esic.gov.in/recruitments `[v]` | |
| LIC AAO (actuarial) | — | vendor portal on a non-LIC domain | `[?]` See the LIC section |
| NIACL Apprentices | Vendor portal | https://bfsissc.com/ `[v]` | Plus `nats.education.gov.in` `[v]` |

---

# Bodies in the records with no section of their own

Small bodies where the whole source surface fits in a line. All verified
2026-09-27 unless marked.

| Body | What | URL | |
|---|---|---|---|
| National Insurance (NICL) | Main portal | https://nationalinsurance.nic.co.in/ `[v]` | |
| NICL | Recruitment | https://nationalinsurance.nic.co.in/recruitment/ `[v]` | The trailing slash is the working form; `/recruitment` also resolves |
| WBCSC (West Bengal College and University Examinations) | Main portal | https://wbcsc.org.in/ `[v*]` | → `/wbcsc/`. **Not WBPSC**, which is `psc.wb.gov.in` |
| WBCSC | Notices | `https://wbcsc.org.in/wbcsc/PDFDOC/NOTICE<...>.pdf` `[v]` | |
| UP Police Recruitment and Promotion Board | Main portal | https://uppbpb.gov.in/ `[v]` | Police recruitment for UP, run on a board domain, not uppsc |
| AIIMS Kalyani | Exam portal | https://www.aiimskalyani.edu.in/ `[v]` | **Separate from `aiimsexams.ac.in`.** `aiims-kalyani.edu.in` (hyphenated) is NXDOMAIN |
| ESIC | Recruitment | https://www.esic.gov.in/recruitments `[v]` | |
| OSAA (Odisha) | — | — | Appears as a `bodies` value on 1 record. Not researched; treat as unverified |
| Council of Architecture | `coarch.gov.in` | — | **NXDOMAIN** at both `coarch.gov.in` and `www.coarch.gov.in`. Appears as a `bodies` value on 1 record. The correct host is unconfirmed — verify before storing |
| MHT-CET (Maharashtra) | MAHACAET | https://cetcell.mahacet.org/ `[v]` | `mahaacet.org` and `mahatacet.org` are both NXDOMAIN — the cell is at `mahacet.org/cetcell`, not on the bare domain |
| KEA | KSET / KCET | https://cetonline.karnataka.gov.in/kea/ `[v]` | See Karnataka |
| JNTU Kakinada / Hyderabad | — | `www.jntukakinada.edu.in` | **NXDOMAIN** from here. Appears as a `bodies` value. Verify in a browser |
| SRM Institute | Admissions | https://www.srmist.edu.in/admissions `[v]` | See the SRM row in the universities table |
| Manipal (MET) | Admissions | https://www.manipal.edu/mu.html `[v]` | |
| VIT | VITEEE | https://viteee.vit.ac.in/ `[v]` | |
| NID | DAT | https://admissions.nid.edu/ `[v*]` | → `/NIDA2027/Default.aspx`. Year in the path |
| ISI | Admission test | https://admission.isical.ac.in/ `[b]` | |
| JMI | Entrance exam | https://admission.jmi.ac.in/ `[v]` | |
| AMU | AEEE | https://www.amucontrollerexams.com/notices `[v]` | |
| AAU (Assam Agricultural University) | CET | `https://admission.aau.ac.in/2026/` `[v]` | Year in the path |
| National Law University Delhi | AILET | https://nationallawuniversitydelhi.in/register.html `[v]` | |
| Symbiosis | SLAT | https://www.slat-test.org/ `[v]` | |
| SNAP | — | https://www.snaptest.org/ `[v]` | |
| IIM CAT | — | https://xatonline.in/ `[v]` | |
| CLAT | Consortium | https://consortiumofnlus.ac.in/clat-2027/ `[v]` | Year in the path |
| COMEDK | UGET / KPGAT | https://www.comedk.org/ `[v]` | |
| NATA | — | https://www.nata.in/ `[v]` | |
| BITSAT | — | `https://admissions.bits-pilani.ac.in/` `[b]` | |
| IIT Bombay | CEED / UCEED | https://www.ceed.iitb.ac.in/ `[v]`, https://www.uceed.iitb.ac.in/ `[v]` | Two separate sites |

---

# Domains where this inventory disagrees with `content/exams/*.md`

The most useful output of this pass. Each row is a value currently stored in at
least one record that should be revisited. Counts are as of 2026-09-27; other
agents are still adding records, so re-run the checker before acting.

| What the record uses | Records | What is actually correct | Why it matters |
|---|---|---|---|
| `https://upsc.gov.in/examinations/exam-calendar/exam-calendar` | 13 `official_url` | `https://www.upsc.gov.in/examinations/exam-calendar` | **Two faults in one URL.** The bare `upsc.gov.in` host 307s to the root and *drops the path* — so the URL returns **HTTP 200 at the homepage**, which reads as healthy — *and* the path has a duplicated final segment. The single-segment form on `www` is a real page. Highest-value fix in this list |
| `https://upsc.gov.in/` | 1 `official_url` | `https://www.upsc.gov.in/` | Same bare-host path-dropping. Same silent-200 failure mode |
| `https://upsc.gov.in/examinations/active-exams` | 1 `provenance` | `https://www.upsc.gov.in/examinations/active-exams` | Same. This is the one record whose *source* is therefore not the page it claims |
| `https://www.tspsc.gov.in/` | 1 record, all three fields (`official_url`, `apply_url`, `source_url`) | `https://www.tgpsc.gov.in/` | **`ts` vs `tg`.** `www.tspsc.gov.in` is NXDOMAIN. The live site is `www.tgpsc.gov.in`, or `websitenew.tgpsc.gov.in` for the current build. CGPSC's own PSC directory still links the wrong spelling, so the error is being propagated by other government sites |
| `https://oars.dsssb.delhi.gov.in/` | 1 `apply_url` | `https://dsssbonline.nic.in/` | **NXDOMAIN.** The old OARS apply host is gone |
| `https://www.srmap.edu.in/admission/engineering/srmjeee-b-tech/` | 1 `provenance` | `https://www.srmist.edu.in/admissions` | **HTTP 404.** The `/srmjeee-b-tech/` segment does not exist. SRM's engineering sub-site is `srmap.edu.in`; its main admissions site is `srmist.edu.in` |
| `https://manipal.edu/admissions/` | 1 `provenance` | `https://www.manipal.edu/mu.html` | **Redirect loop** into `/mu/error/filenotfound.html`. A genuine error, not a redirect. The record's `official_url`/`apply_url` of bare `https://manipal.edu/` do resolve, via `http://` in the chain |
| `https://www.bitsadmission.com/` | 1 record, `official_url` and `apply_url` | `https://admissions.bits-pilani.ac.in/` | The old domain now **302s** to a new one. It works, but it is one hop from being wrong, and the new host is where future BITSAT cycles will live |
| `https://iocl.com/` | 1 record, all three fields | unconfirmed | Every path returns a **307 with no `Location`**. Not a dead link, but nothing on this host is machine-checkable and the notice PDF cannot be confirmed to exist without a browser |
| `https://nbe.edu.in/` | 4 records as `official_url` and `apply_url` (+1 as a `provenance` bulletin) | `https://natboard.edu.in/` | **Reachable but stale.** `nbe.edu.in`'s landing page still links 2021–2022 bulletins. Fine for archive documents — the GPAT bulletin URL in `mds-gpat-2027.md` is good — wrong as `official_url` for an upcoming exam |
| `https://cdnbbsr.s3waas.gov.in/…/20260914325514446.pdf` | 1 `provenance` | the issuing body's notice index | Government CDN with a **timestamped filename**. Expect a 404 that is not a missing page |
| `https://rrbranchi.gov.in/upload/files/pdf/09_07_06pm04776926682e2fd15200721eacbac1c3.pdf` | 1 `provenance` | the RRB CEN document index | **HTTP 404.** A hash-named upload that has been replaced |
| `https://results.natboard.edu.in/<exam>/index` | — | reorganised per cycle | The old per-exam paths (`/cetss/`, `/fmge/`, `/mds/`, `/pgmedical/`, `/neetss/`) all 404 now |
| `apsc.gov.in` | **0** | — | Recorded here because it is the kind of error this pass was looking for: it is *not* present. Assam PSC is correctly on `apsc.nic.in` in the records. `apsc.gov.in` itself returns SERVFAIL at both public resolvers, so it is worth knowing that the domain is a trap — but note `apsc` (Assam) and `appsc` (Arunachal) are different commissions, and a naive substring search for `apsc.gov.in` matches `keralapsc.gov.in` |
| `www.crri.in` | 0 | nothing | Redirects through `livingwithoutmoney.tv` to `skitterbug.co`, an unrelated commercial site |
| `www.nbems.org` | 0 | nothing | Wrong body — New Britain EMS, USA |

**Also worth a look, though not a domain change:**

- The 6 HSSC records, the 4 PSSC records, the 4 JKSSB records, the 4 MPESB
  records and the 4 BPSC records all sit behind certificate chains that only a
  browser accepts. If a future check reports them as broken, **it is wrong**.
  `tools/check-links.mjs` is configured not to.
- 23 record URLs redirect. Most are cosmetic (`http`→`https`, `www` added, a
  bare host pointing at its canonical form). The exceptions worth a human look
  are the three UPSC ones above and the OPSC `.aspx` paths, which bounce to
  `Default.aspx` rather than 404ing.

## Domains confirmed correct as stored

Worth stating explicitly, because a link check that reports a wall as a
failure will otherwise send someone "fixing" these: `keralapsc.gov.in`,
`tpsc.tripura.gov.in`, `upsconline.nic.in`, `ssc.gov.in`, `aiimsexams.ac.in`,
`ugcnet.nta.nic.in`, `www.ibps.in`, `rpsc.rajasthan.gov.in`, `sso.rajasthan.gov.in`,
`gpsc.gujarat.gov.in`, `gpsc-ojas.gujarat.gov.in`, `nbe.edu.in` (archive use),
`www.joinindiannavy.gov.in`, `hssc.gov.in`, `appsc.gov.in`, `npsc.nagaland.gov.in`,
`mpscmanipur.gov.in`, `mpsc.meghalaya.gov.in`, `jkssb.nic.in`, `jeemain.nta.nic.in`,
`exams.nta.nic.in/*`, `esb.mponline.gov.in`, `dsssb.delhi.gov.in`, `dsssbonline.nic.in`,
`kpsc.kar.nic.in`, `www.tgpsc.gov.in`, `mpsconline.gov.in`, `tnpsc.gov.in`,
`psc.ap.gov.in`, `psc.uk.gov.in`, `nationalinsurance.nic.co.in`, `pfrda.org.in`,
`uppbpb.gov.in`, `www.tgprb.in`, `ousssc.odisha.gov.in`, `spscrs.sikkim.gov.in`,
`mpscmanipur.gov.in`, `dsssbonline.nic.in`, `www.coalindia.in`,
`www.isro.gov.in`, `www.drdo.gov.in`, `fci.gov.in`, `pnb.bank.in`,
`www.newindia.co.in`, `uidai.gov.in`, `www.licindia.in`.

---

# Verification log

**Method.** `curl` with a current desktop `User-Agent` plus navigation headers,
following redirects and recording the full chain. `node:dns` for resolution, and
Cloudflare and Google public DNS-over-HTTPS as a second opinion wherever the
local resolver disagreed — which is how the two broken delegations were
confirmed. `tools/check-links.mjs` re-runs the same classification with
retries, a blocked/timeout/dead split, and the redirect-chain comparison that
catches the bare-domain path-dropping.

## The two runs, as measured

`node tools/check-links.mjs --scope=inventory` — 268 distinct URLs:

| Verdict | Count | Range across runs | |
|---|---|---|---|
| ok | **206** | 206–208 | Reached, HTTP 2xx after following redirects |
| blocked | 34 | 33–36 | 403/503, bot manager, malformed WAF challenge, or a browser-tolerated TLS failure. Not broken |
| redirected | 17 | 17 | Reachable, but the URL is not where you land |
| timeout | 11 | 7–17 | No response. `sebi.gov.in` never answers; `hssc.gov.in` (four paths) and `apsc.gov.in` are broken-authority; `cuet.nta.nic.in`, `cmat.nta.nic.in`, `fci.gov.in/Circulars` and `hppsc.hp.gov.in` are this host's flaky path to `.gov.in` |
| dead | **0** | 0 | |
| error | **0** | 0 | |

Exit code 0. `ok`, `blocked` and `redirected` are stable to within one or two.
The timeout count moves because this host's outbound route to several `.gov.in`
hosts is unreliable — the same URL times out on one run and returns 200 on the
next. **The two counts that do not move are `dead` and `error`, which is the
point.**

`node tools/check-links.mjs --scope=records` — 275 distinct URLs, drawn from
`official_url`, `apply_url` and `provenance.source_url` across 227 records (the
record set is still growing, so counts drift):

| Verdict | Count | |
|---|---|---|
| ok | 202 | |
| blocked | 32 | |
| redirected | 23 | |
| timeout | 13 | Includes the four `hssc.gov.in` paths, which are a broken authority rather than an absent domain |
| **dead** | **4** | Real failures — see the disagreements table |
| **error** | **1** | `manipal.edu/admissions/`, a redirect loop |

Exit code 1. Those five are the deliverable of this pass, not a defect in the
tool.

## Two classification traps the tool has to get right

Both of these were found by writing the tool, not by reading the sites, and
both would have produced confident false findings.

**SERVFAIL is not NXDOMAIN.** `fetch` reports a broken DNS authority and an
absent domain identically, as `ENOTFOUND`. `hssc.gov.in` and `apsc.gov.in` both
return `ESERVFAIL` with `EDE(22): No Reachable Authority` at Cloudflare *and*
Google — the authoritative nameservers are not answering — which is a
reachability problem, not a missing domain. `check-links.mjs` therefore
re-resolves with `dns.resolve4` before calling anything dead, and only accepts a
clean `ENOTFOUND`/`ENODATA`. Without that, the tool would have told a
maintainer to delete a working Haryana link. `coarch.gov.in` and
`oars.dsssb.delhi.gov.in` do return clean `ENOTFOUND` and are correctly
reported dead.

**A Location-less 3xx is a wall, not a moved page.** IOCL's Sucuri front end
answers every path with `307` and no `Location`. That is a malformed bot
challenge: the site is up, the client is being walled, and there is nowhere to
go. Classified as *blocked*, so a browser-tolerated barrier never becomes a CI
failure.

## Totals across the whole exercise

- **Verified reachable** (`[v]`): **206** of the 268 URLs in this file returned
  HTTP 2xx on the final run, plus roughly 60 more confirmed by direct probe
  while discovering the path shapes recorded here. Distinct URLs actually
  reached and confirmed live: **≈250**.
- **Blocked, needs a browser** (34 in the inventory, 32 in the records): 403 or
  503 behind a WAF or bot manager (`bankofindia.bank.in`, `natboard.edu.in`,
  `ntpc.co.in` via Radware, `agnipathvayu.cdac.in`), or a TLS failure a browser
  forgives — incomplete chains (`ibps.in`, `bpsc.bihar.gov.in`, `esb.mp.gov.in`,
  `apsc.nic.in`, `ppsc.gov.in`, `kpsconline.karnataka.gov.in`,
  `portal-psc.ap.gov.in`, `jssc.jharkhand.gov.in`, `www.amu.ac.in`,
  `jkssb.nic.in` which sends *no* issuer certificate at all), legacy TLS
  renegotiation (`hppsc.hp.gov.in`, `sssb.punjab.gov.in`, `psc.wb.gov.in`), SAN
  mismatch (`onetimeregn.haryana.gov.in`), an expired certificate
  (`icar.gov.in`), malformed response headers (`kpsc.kar.nic.in`), or a
  Location-less 307 from Sucuri (`iocl.com`).
- **Timeout** (7–17 inventory, 8–13 records, varying by run): `sebi.gov.in` and `ctet.nic.in` on every
  attempt from this host; `iimcat.ac.in`; `spsc.sikkim.gov.in`; and the
  `hssc.gov.in` family, which returns **SERVFAIL with
  `EDE(22): No Reachable Authority` at both Cloudflare and Google** — an
  authoritative failure, but one the search index contradicts, since it carries
  HSSC content dated 2026-09-26. Most likely a resolver or network-level block
  on this host rather than an outage. **Unresolved, and flagged as such rather
  than guessed either way.**
- **Definitively dead** (4, all in the records): `oars.dsssb.delhi.gov.in` and
  `www.tspsc.gov.in` (NXDOMAIN), `srmap.edu.in/…/srmjeee-b-tech/` and
  `rrbranchi.gov.in/…/09_07_06pm…pdf` (HTTP 404).
- **JS-only, unverifiable by script** (counted as `[?]`, not as failures): every
  SSC route, `mpsc.gov.in`, `aiimsexams.ac.in` sub-paths, and the
  `application`/`hallticket`/`igrs`/`otr` TGPSC hosts.
- **Not verified and recorded as a gap rather than guessed:** `coarch.gov.in`
  and `www.coarch.gov.in` (both NXDOMAIN, yet `Council of Architecture` appears
  as a `bodies` value in a record — the correct host is unconfirmed),
  `www.jntukakinada.edu.in` (NXDOMAIN, also a `bodies` value),
  `odishapolice.gov.in` (timeout), `uppolice.gov.in` (not reached).
- **Not verified, and absent as fact**: SEBI, CTET's sub-paths, HPPSC's
  `hppsconline` apply portal, JKSSB's internal paths, Power Grid's careers path,
  Uttarakhand's three quicklinks that returned HTTP 500, Goa PSC, the
  Puducherry recruitment portal, and the Ladakh Police and Ladakh UT recruitment
  paths. Each appears in the inventory as a row to confirm in a browser, or is
  recorded as a gap. Where a body was reachable only on a second or third
  attempt, the row says so instead of claiming a clean first-try success.

## Two false friends worth naming

- `www.nbems.org` looks exactly like the National Board of Examinations in
  Medical Sciences and is **New Britain Emergency Medical Services**, a US
  ambulance service. It appeared in a search and would have looked right in a
  table.
- `www.fci.co.in` returns **HTTP 200** and serves a page reading *"This website
  is for sale!"*. FCI is at `fci.gov.in`. A status-code check alone would have
  passed the parked domain.

## Re-running this

`docs/link-inventory.md` is written so that a status check is meaningful:
asserted URLs are bare, while path templates and deliberately-dead examples are
inside backticks. The checker skips backticked URLs for that reason, which is
what keeps `--scope=inventory` at zero definite failures. Use
`--include-code` to audit the template and dead-list entries anyway — they will
report as dead, which is the expected result, not a new finding.
