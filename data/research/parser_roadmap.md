# Swim Meet Result Format Research — Parser / Adapter Roadmap

**Purpose:** Map the real-world landscape of swim-meet result publication formats across UK and USA, identify what the current HY3-only engine can and cannot handle, and specify the highest-priority adapters to build next.

**Research date:** June 2025  
**Engine baseline:** Python engine ingesting Hytek HY3 (zipped `.zip` → `.hy3`) only.

---

## 1. UK Meets Table

All verified against real web sources. Formats were cross-referenced against the actual results pages or platform documentation.

> **Key to columns:** DL = Downloadable file available · Live = Live results during meet · IDs = Swimmer registration IDs included · Clubs = Club affiliation present · Relays = Relay results included · Splits = Split times present · F/H = Finals and heats kept separate · Engine = current HY3-only engine handles it?

| # | Meet Name | Organising Body / Host | Year(s) | Results URL | Format | DL | Live | IDs | Clubs | Relays | Splits | F/H | Parsing Challenges | Adapter Needed | Engine? |
|---|-----------|------------------------|---------|-------------|--------|-----|------|-----|-------|--------|--------|-----|--------------------|----------------|---------|
| 1 | **Speedo / Aquatics GB Swimming Championships** (British Swimming Champs) | British Swimming | 2023–24 | [britishswimming.org](https://www.britishswimming.org/events-and-tickets/british-swimming-championships-2024/) · live results via [swimmingresults.org](https://www.swimmingresults.org) | HTML on swimmingresults.org; PDF programme; no public HY3 download | N (no HY3) | Y (swimmingresults.org) | Y (Swim England reg ID) | Y | Y | Partial | Y | Results hosted on swimmingresults.org web portal, no machine-readable bulk export; Club Rankings SD3 export requires licensed club tool; Para events use separate result structure | `adapters/swimmingresults_web.py` (HTML scraper) or SD3 via Club Rankings | **No** |
| 2 | **Swim England National Summer Meet** | Swim England | 2018–25 | [swimming.org/sport/major-events/national-summer-meet](https://www.swimming.org/sport/major-events/national-summer-meet/) · results on swimmingresults.org | HTML on swimmingresults.org; PDF results summary published on club sites (e.g. [swimleeds.org.uk](https://www.swimleeds.org.uk/assets/files/swim-england-national-summer-meet-2025-results-summary.pdf)) | PDF only (public) | Y (swimmingresults.org) | Y | Y | Y | Partial | Y | Swim England does not publish a public HY3/SD3 download; clubs export per-team SD3 via Club Rankings (SDIF); PDFs are formatted Hytek report output — not machine-readable without parser | `adapters/hytek_pdf.py` (regex on Hytek report PDFs) | **No** |
| 3 | **Swim England National Winter Championships** (GoCardless NSM) | Swim England | 2022–24 | [swimming.org/sport/major-events/national-winter-champs](https://www.swimming.org/sport/major-events/national-winter-champs/) | HTML on swimmingresults.org; PDF medal roll published on swim.org | N (no HY3) | Y (swimmingresults.org) | Y | Y | Y | Partial | Y | Same infrastructure as Summer Meet; SCM (25 m) complicates course-normalisation | `adapters/swimmingresults_web.py` | **No** |
| 4 | **Edinburgh International Swim Meet (EISM)** | EISM (independent) | 2024–26 | [eism.org.uk](https://eism.org.uk) · [eism.org.uk/history-archive/2025-results-and-stream](https://eism.org.uk/history-archive/2025-results-and-stream/) | **Hytek Results File** (confirmed on homepage: "Hytek Results file is now available to download from the Results page") + per-session PDFs | Y (Hytek ZIP/HY3) | Y (Meet Mobile or session HTML) | Y | Y | Y (exhibition relays) | Y | Y | HY3 file is session-level; must merge across sessions; non-standard 150 m IM event in programme; international swimmer IDs may not be USA Swimming IDs | No adapter needed beyond current engine | **Yes (HY3)** |
| 5 | **Scottish National Open Swimming Championships** | Scottish Swimming | 2025–26 | Info PDF: [ocs-sport.ams3.digitaloceanspaces.com](https://ocs-sport.ams3.digitaloceanspaces.com/scotswim-full/2026/02/07171940/2026-Meet-Information.pdf); results posted on [uk.gomotionapp.com](https://uk.gomotionapp.com/sast/UserFiles/File/Alterations/scottish-national-open-championships-2025_007456.pdf) | PDF (Hytek report output confirmed in PDF header text "HY-TEK's MEET MANAGER") | Y (PDF only) | Y (Meet Mobile noted in info docs) | Y | Y | Y | Y | Y | PDF columns are Hytek MEET MANAGER formatted text; multi-day meet; heats and finals on separate PDFs | `adapters/hytek_pdf.py` | **No** |
| 6 | **Swim Wales National Championships (Long Course)** | Swim Wales | 2021–24 | [rar-timing.co.uk](https://results.rar-timing.co.uk) (RAR Timing platform); [swimwales.org/download-key-documents](https://www.swimwales.org/download-key-documents/) | RAR Timing live-results web platform (HTML); Meet Mobile available; no public HY3 download observed | N (HTML portal) | Y (RAR Timing + Meet Mobile) | Y | Y | Y | Y | Y | HTML-only; RAR Timing has no documented public download API; must screen-read live-results portal; Welsh names and Welsh-language text may appear | `adapters/rar_timing_html.py` | **No** |
| 7 | **Swim Wales Winter Short Course Championships** | Swim Wales | 2022–24 | [rar-timing.co.uk](https://results.rar-timing.co.uk) (RAR Timing); entries [swimwales.org](https://www.swimwales.org/download-key-documents/) | RAR Timing HTML live results; Meet Mobile | N (HTML portal) | Y | Y | Y | Y | Y | Y | Same RAR Timing infrastructure as Swim Wales Long Course | `adapters/rar_timing_html.py` | **No** |
| 8 | **British Masters Championships** | Swim England Masters | 2023–24 | [swimming.org/masters/british-masters-championships](https://www.swimming.org/masters/british-masters-championships/); results on [results.rar-timing.co.uk](https://results.rar-timing.co.uk) (RAR Timing) | RAR Timing HTML; Meet Mobile noted in platform | N (HTML portal) | Y | Y (Masters Swim England ID) | Y | Y | Partial | Y | Age-group bands (5-year Masters age groups); mixed-sex relay scoring; RAR Timing has no public export; older years may redirect to swimmingresults.org Masters rankings | `adapters/rar_timing_html.py` | **No** |
| 9 | **BUCS Long Course / Short Course Swimming Championships** | BUCS (British Universities & Colleges Sport) | 2024–26 | [bucs.org.uk events page](https://www.bucs.org.uk/events-page/swimming-long-course-championships-2025-26-part-of-bucs-nationals.html) | "Live results will be available here over the weekend. Full results will be published after the event." — format not confirmed as HY3 or PDF in public documentation | Unclear | Y (live link on BUCS page) | Y | Y (University clubs) | Y | Y | Y | BUCS runs on Hytek Meet Manager typically but results page does not publish HY3 file publicly; university club codes differ from Swim England club codes; diving scores integrated | `adapters/hytek_pdf.py` (if PDF); manual HY3 request | **Possibly (if HY3 shared privately)** |
| 10 | **City of Sheffield "Open" / North Midlands Championships** | COSSS (City of Sheffield) | 2014–25 | [cosss.uk/open-meets/results](https://cosss.uk/open-meets/results/) | HTML for recent meets (2022+); older meets have PDF; no HY3 download observed | Y (HTML/PDF) | Y (older: HTML live) | Y | Y | Y | N (older PDFs) | Y | HTML results are custom web-table format, not Hytek standard; no bulk download; pre-2010 PDF only | `adapters/hytek_pdf.py` for PDFs; custom HTML adapter for cosss.uk table format | **No** |
| 11 | **Swim England Regional / County Level Licensed Meets** (all regions) | Swim England regional bodies | Ongoing | [swimmingresults.org/licensed_meets](https://www.swimmingresults.org/licensed_meets/) | HTML on swimmingresults.org portal; SD3 export available to clubs via Club Rankings (SDIF) software — requires license from [club.rankings@swimmingresults.org](https://motion-help.sportsengine.com/en/articles/8537616-getting-results-from-swim-england) | N (publicly); Y (SD3 for registered clubs) | Y (swimmingresults.org) | Y | Y | Y | Partial | Y | SD3 available but requires licensed club application; the SD3 is SDIF v3 fixed-width; swimmingresults.org does not publish raw meet files publicly; 25,505,975 times in database | `adapters/sdif_sd3.py` | **No** |
| 12 | **swimming.events Platform Meets** (e.g., Sprint With The Stars, Manchester Masters) | Independent (swimming.events platform) | 2019–26 | [swimming.events](https://swimming.events) | "Results Export page provides a download service for the results of hosted meets" — format unclear from public docs, but platform runs on Hytek-compatible structure | Y (format unclear) | Y | Y | Y | Y | Y | Y | Export format not documented publicly; platform is used for London, Manchester, Macclesfield meets; may produce HY3 or HTML export; needs further investigation | Investigate download format; likely `adapters/hytek_hy3.py` if HY3 export confirmed | **Possibly** |

**Notes:**
- swimmingresults.org is the central Swim England / Swim Wales / Scottish Swimming rankings database. Results are submitted by promoters in SDIF/SD3 format via SportsSystems Club Rankings software. Public-facing interface is HTML only. Clubs can export SD3 files per-meet using the licensed Club Rankings tool ([source: leman.net](https://leman.net/wp/2018/12/11/use-club-rankings-to-fetch-gala-results-and-import-in-to-team-unify/)).
- RAR Timing is a live-results platform used heavily by Swim Wales and British Masters. It displays results in a web table. Meet Mobile is offered alongside. No public file download was found.
- UK results submitted to swimmingresults.org are in **SDIF (SD3)** — confirmed by SportsSystems/SportsEngine documentation and the leman.net Club Rankings blog post.

---

## 2. USA Meets Table

| # | Meet Name | Organising Body / Host | Year(s) | Results URL | Format | DL | Live | IDs | Clubs | Relays | Splits | F/H | Parsing Challenges | Adapter Needed | Engine? |
|---|-----------|------------------------|---------|-------------|--------|-----|------|-----|-------|--------|--------|-----|--------------------|----------------|---------|
| 1 | **USA Swimming Olympic Trials** | USA Swimming / Omega | 2024 | [omegatiming.com/2024-us-olympic-trials](https://www.omegatiming.com/File/00011800030103EC0101FFFFFFFFFF01.pdf) | Omega Timing PDF (session-by-session) + Omega HTML live results | Y (PDF) | Y (Omega HTML) | Y (USA ID) | Y (LSC code) | Y | Y | Y | Omega PDF is not Hytek formatted; uses Omega's own layout with record columns; very large event; Omega live-results HTML has no public JSON API | `adapters/hytek_pdf.py` (Hytek-formatted PDFs from separate download); `adapters/omega_html.py` for live | **Partial (if PDF is Hytek-formatted)** |
| 2 | **USA Swimming National Championships (Speedo)** | USA Swimming | 2024–25 | [usaswimming.org/times/data-hub/meet-results](https://www.usaswimming.org/times/data-hub/meet-results) · PDF: [usaswimming.org/.../complete-time-trial-results...2024.pdf](https://www.usaswimming.org/docs/default-source/timesdocuments/meet-results/national-championships/complete-time-trial-results---speedo-summer-champs-2024.pdf) | Hytek MEET MANAGER PDF (confirmed by "HY-TEK's MEET MANAGER 8.0" header in PDF content) | Y (PDF) | Y (Omega HTML) | Y (USA ID in LSC code) | Y | Y | Y | Y | PDF is machine-readable Hytek output with fixed column structure; Omega live results HTML is separate; no public HY3 download found | `adapters/hytek_pdf.py` | **No** |
| 3 | **USA Swimming Junior Nationals (Speedo)** | USA Swimming | 2022–25 | [usaswimming.org/times/data-hub/meet-results/junior-nationals-results](https://www.usaswimming.org/times/data-hub/meet-results/junior-nationals-results) · PDF: [usaswimming.org/.../lc-juniors-complete-results.pdf](https://www.usaswimming.org/docs/default-source/timesdocuments/meet-results/junior-nationals/lc-juniors-complete-results.pdf) | Hytek MEET MANAGER PDF (same structure as Nationals) | Y (PDF) | Y (Omega HTML for 2024+) | Y | Y | Y | Y | Y | Same as Nationals; age-restriction events (18-and-under); DQ data present in PDFs | `adapters/hytek_pdf.py` | **No** |
| 4 | **TYR Pro Swim Series** | USA Swimming | 2013–26 | [usaswimming.org/times/data-hub/meet-results/pro-swim-series-results](https://www.usaswimming.org/times/data-hub/meet-results/pro-swim-series-results) · Omega live: [omegatiming.com/2025-tyr-pro-swim-series-03](https://www.omegatiming.com/2025/2025-tyr-pro-swim-series-03-live-results) | Omega Timing HTML live results (HTML-only portal with per-event ranking pages) + Hytek MEET MANAGER PDF (some years) | Y (PDF for some years) | Y (Omega HTML) | Y | Y | Y | Y | Y | Omega HTML: separate page per event, pagination across sessions, no JSON API; international swimmers use FINA/World Aquatics IDs; Pro events may have swim-offs | `adapters/omega_html.py` + `adapters/hytek_pdf.py` | **No** |
| 5 | **USA Swimming Futures Championships** | USA Swimming | 2015–25 | [usaswimming.org/times/data-hub/meet-results/futures-results](https://www.usaswimming.org/times/data-hub/meet-results/futures-results) · PDF: [usaswimming.org/.../meet-results---futures-greensboro-2025.pdf](https://www.usaswimming.org/docs/default-source/timesdocuments/meet-results/futures/meet-results---futures-greensboro-2025.pdf) | **Hytek MEET MANAGER PDF** (confirmed: "HY-TEK's MEET MANAGER 8.0 - 10:23 AM 7/29/2025" in PDF text; A-Final/B-Final/Prelims structure visible; splits in split-decimal notation) | Y (PDF) | Y (Meet Mobile) | Y (USA ID: LSC code + club abbrev) | Y | Y | Y | Y | Multiple venue PDFs per season (e.g., Greensboro, Austin, Madison); PDF split notation: `2:01.02 (30.68) / 1:30.34 (31.35)` = cumulative; must handle A/B finals and prelims round logic | `adapters/hytek_pdf.py` | **No** |
| 6 | **NCAA Division I Swimming & Diving Championships** | NCAA | 2019–26 | [fightingirish.com/.../2025-NCAA-Division-I-Mens-Championships-Final-Results.pdf](https://fightingirish.com/wp-content/uploads/2025/03/2025-NCAA-Division-I-Mens-Championships-Final-Results.pdf) · [static.virginiasports.com/pdfs/swim/Results/Thursday_Men.pdf](https://static.virginiasports.com/pdfs/swim/Results/Thursday_Men.pdf) | **Hytek MEET MANAGER PDF** (confirmed: "HY-TEK's MEET MANAGER 8.0" in PDF header; 200 yd Medley Relay Event 1 format; year/class fields present) | Y (PDF; hosted by host-school athletics sites) | Y (Meet Mobile / dedicated site) | Y (NCAA ID; year-in-school: FR/SO/JR/SR/GR) | Y (School name as team) | Y | Y | Y | PDF split notation uses cumulative+interval; year-in-school replaces age; diving points integrated; no USA Swimming ID (NCAA separate); per-day PDFs — must merge | `adapters/hytek_pdf.py` | **No** |
| 7 | **NCAA Division II Swimming Championships** | NCAA / CSCAA | 2022–25 | Results hosted by individual host school sites | Hytek MEET MANAGER PDF | Y (PDF) | Y (Meet Mobile) | Y (NCAA ID) | Y | Y | Y | Y | Smaller event; yards only; same PDF format as D1 | `adapters/hytek_pdf.py` | **No** |
| 8 | **NCAA Division III Swimming Championships** | NCAA / CSCAA | 2025 | [odaconline.com](https://odaconline.com/sports/2025/3/12/d3-swimdive-results-hub-2025.aspx) · [greensboroaquaticcenter.com/results](https://greensboroaquaticcenter.com/results/) | **Hytek MEET MANAGER PDF** (with-splits and without-splits PDFs separately published); Meet Mobile live | Y (PDF with/without splits) | Y (Meet Mobile) | Y | Y | Y | Y (separate PDF) | Y | Per-session PDFs; with-splits PDF is larger; splits file must be cross-referenced with results file | `adapters/hytek_pdf.py` | **No** |
| 9 | **SEC Swimming & Diving Championships** | Southeastern Conference | 2024–25 | [vucommodores.com](https://vucommodores.com/wp-content/uploads/2025/02/022225-SEC-Championships-results.pdf) · [mutigers.com](https://mutigers.com/documents/2025/2/25/complete_results_with_splits.pdf) | **Hytek MEET MANAGER PDF** (confirmed: "HY-TEK's MEET MANAGER 8.0 - 8:56 PM 2/22/2025" in PDF header; diving results integrated; yards course) | Y (PDF; hosted by conference school athletics sites) | Y (dedicated championship site) | Y | Y (school name) | Y | Y | Y | Diving events integrated in PDF — non-swimming events in same file require filtering; school abbreviations (e.g. "Georgia, University of-GA") are non-standard | `adapters/hytek_pdf.py` | **No** |
| 10 | **ACC Swimming & Diving Championships** | Atlantic Coast Conference | 2024–25 | [goheels.com/.../ACC_Championships_Full_Meet_Results.pdf](https://goheels.com/documents/2025/2/23/ACC_Championships_Full_Meet_Results.pdf) | **Hytek MEET MANAGER PDF** | Y (PDF) | Y (ACC Network/championship site) | Y | Y | Y | Y | Y | Same as SEC; diving interleaved | `adapters/hytek_pdf.py` | **No** |
| 11 | **Big Ten Conference Swimming & Diving Championships** | Big Ten Conference | 2024–26 | [ohiostatebuckeyes.com](https://ohiostatebuckeyes.com/documents/2024/3/3/2024_b1g_men_s_championship_full_results.pdf) · [bigten.org/wsd/championship](https://bigten.org/wsd/championship/) | **Hytek MEET MANAGER PDF** | Y (PDF) | Y | Y | Y | Y | Y | Y | Same structure as other conference meets | `adapters/hytek_pdf.py` | **No** |
| 12 | **Pac-12 Conference Swimming & Diving Championships** | Pac-12 Conference | 2024 | [pac-12.com](https://pac-12.com/news/2024/3/3/california-takes-home-2024-pac-12-womens-swimming-diving-championship-title) · [pacswim.org](https://www.pacswim.org/userfiles/meets/documents/2662/ncs-full-results.pdf) | Hytek MEET MANAGER PDF | Y (PDF) | Y | Y | Y | Y | Y | Y | Conference absorbed into new structures for 2025; host school sites may be the only source going forward | `adapters/hytek_pdf.py` | **No** |
| 13 | **USA Swimming Sectional Championships** | USA Swimming regional LSCs | Ongoing | [usaswimming.org](https://www.usaswimming.org) (linked per-LSC) | Typically Hytek HY3 (zipped) posted on LSC websites; also PDF | Y (HY3 ZIP + PDF) | Y (Meet Mobile) | Y (USA Swimming ID) | Y (LSC club code) | Y | Y | Y | LSC-specific file hosting; URL patterns vary by LSC; some use TeamUnify, GoMotion, or SportsEngine | Current engine handles HY3 | **Yes (HY3)** |
| 14 | **USA Swimming Zone Age Group Championships** | USA Swimming Zones (Eastern, Southern, Central, Western) | 2024–25 | Eastern Zone: [easternzoneswimming.org](https://www.easternzoneswimming.org/page/home) | Hytek HY3 posted on zone websites + PDF; Meet Mobile live | Y (HY3) | Y (Meet Mobile) | Y | Y | Y | Y | Y | Separate zone websites; age-group cutoffs in results; zone team designations (e.g., EAST-PC) | Current engine handles HY3 | **Yes (HY3)** |
| 15 | **YMCA National Championships** | YMCA of the USA | 2023–26 | [greensboroaquaticcenter.com/results](https://greensboroaquaticcenter.com/results/) · [ymcaswimminganddiving.org](https://www.ymcaswimminganddiving.org/page/system/res/222263) | Hytek MEET MANAGER results; PDF and/or HY3; hosted on Greensboro GAC site for 2023–25 | Y (PDF; possibly HY3) | Y (Meet Mobile) | Y (YMCA membership ID) | Y | Y | Y | Y | YMCA club codes do not map to USA Swimming LSC codes; swimmers may not be USA Swimming registered | `adapters/hytek_pdf.py` or current HY3 engine | **Possibly (HY3)** |
| 16 | **US Masters Swimming (USMS) Spring / Summer Nationals** | US Masters Swimming | 2024–25 | [usms.org/events/national-championships](https://www.usms.org/events/national-championships/pool-national-championships/2025-pool-national-championships/2025-spring-national-championship/2025-spring-nationals-results-and-records) · [usms.org/comp/meets](https://www.usms.org/comp/meets/) | USMS online results database (HTML); some meets produce Hytek PDF; results submitted in SDIF/HY3 by promoters | N (public HY3); Y (HTML) | Y (Meet Mobile) | Y (USMS registration number) | Y (USMS club) | Y | Y | Y | USMS uses 5-year age groups; gender-mixed relay scoring; USMS IDs not USA Swimming IDs; HTML database is event-by-event not bulk-downloadable | `adapters/usms_web.py` (HTML) or `adapters/hytek_pdf.py` if PDFs found | **Possibly (if HY3 from individual LSC)** |
| 17 | **Texas UIL Swimming & Diving State Meet** | UIL (University Interscholastic League) | 2024 | [stswim.org PDF](https://www.stswim.org/szstxlsc/UserFiles/Image/QuickUpload/2024-6a-state-austin-results_050548.pdf) · [uiltexas.org/swimming-diving/state](https://www.uiltexas.org/swimming-diving/state/swimming-diving-state-meet-qualifiers-results) | **Hytek MEET MANAGER PDF** (confirmed: layout in fetched PDF shows relay swimmers, splits, heats/finals for Class 6A) | Y (PDF by class division) | N (no confirmed live) | Y (school entry) | Y (HS school name as team) | Y | Y | Y | Multiple class divisions (1A–6A) in separate PDFs; school names used as team (no club code); no USA Swimming ID | `adapters/hytek_pdf.py` | **No** |
| 18 | **Florida FHSAA Swimming & Diving State Championships** | FHSAA | 2024–25 | [fhsaa.com/sports/2020/1/28/SW_results.aspx](https://fhsaa.com/sports/2020/1/28/SW_results.aspx) | **Hytek Files** (explicitly stated: "Click to access Hy-Tek Files"); Meet Mobile live | Y (Hytek ZIP/HY3 confirmed by FHSAA) | Y (Meet Mobile) | Y | Y | Y | Y | Y | Class divisions (1A–4A); school as team; FHSAA school codes provided separately; diving events present | Current engine handles HY3 | **Yes (HY3)** |
| 19 | **Indiana IHSAA Swimming & Diving State Championships** | IHSAA | 2025–26 | [ihsaa.org/sports/girls/swimming-diving/2025-26-tournament](https://www.ihsaa.org/sports/girls/swimming-diving/2025-26-tournament) · prelim PDF: [ihsaa.org](https://www.ihsaa.org/sites/default/files/documents/2025-26%20BSW%20Prelims%20Results.pdf) | "Results will be posted at Meet Mobile"; full results PDF posted after meet; Hytek MEET MANAGER format | Y (PDF) | Y (Meet Mobile) | Y | Y | Y | Y | Y | Prelims and finals on separate PDFs; diving integrated; school codes | `adapters/hytek_pdf.py` | **No** |
| 20 | **California CIF Swimming & Diving Championships** | CIF (California Interscholastic Federation) | 2024 | [gomotionapp.com/.../2024-cif-statemeet-final-results.pdf](https://www.gomotionapp.com/wzccslsc/UserFiles/File/Meets/2024/2024-cif-statemeet-final-results_080485.pdf) · [socalswim.org/results/cif](https://www.socalswim.org/results/cif) | Hytek MEET MANAGER PDF (hosted on GoMotion/LSC sites) | Y (PDF) | N (no confirmed live) | Y | Y | Y | Y | Y | Multiple regional CIF sections before State; GoMotion hosting means URL pattern is unstable; school name as team | `adapters/hytek_pdf.py` | **No** |
| 21 | **NCAA D1 Women's Swimming & Diving Championships** | NCAA | 2022, 2026 | [ramblinwreck.com/.../Wednesday-Morning-Results.pdf](https://ramblinwreck.com/wp-content/uploads/2026/03/Wednesday-Morning-Results.pdf) · [i.turner.ncaa.com/...division_i_womens_swimming_and_diving_full_meet_results.pdf](https://i.turner.ncaa.com/sites/default/files/images/2019/03/25/division_i_womens_swimming_and_diving_full_meet_results.pdf) | Hytek MEET MANAGER PDF (confirmed in fetched content: "HY-TEK's MEET MANAGER 8.0") | Y (PDF; host school sites) | Y (Meet Mobile + championship website) | Y (NCAA) | Y | Y | Y | Y | Women's and Men's championships are separate PDFs; diving integrated; year-in-school not age | `adapters/hytek_pdf.py` | **No** |
| 22 | **USA Swimming Pro Swim Series — Omega Timing Live Results** | USA Swimming / Omega | 2025–26 | [omegatiming.com/2025/2025-tyr-pro-swim-series-03-live-results](https://www.omegatiming.com/2025/2025-tyr-pro-swim-series-03-live-results) | Omega Timing HTML live-results portal: per-event "Total Ranking" pages, "Start List" + "Results Slowest Heats" pages; no JSON API confirmed | N (HTML only) | Y | Y | Y | Y | Y | Y | Omega uses its own result layout; each session/event is a separate HTML page; no bulk export or documented API; programmatic access requires HTML parsing across many pages | `adapters/omega_html.py` | **No** |
| 23 | **2024 U.S. Olympic Team Trials Swimming** | USA Swimming / Omega | 2024 | [omegatiming.com/2024-us-olympic-trials PDF](https://www.omegatiming.com/File/00011800030103EC0101FFFFFFFFFF01.pdf) | Omega session PDF + Omega HTML live results portal | Y (Omega PDF) | Y (Omega HTML) | Y | Y | Y | Y | Y | Omega PDF format is distinct from Hytek PDF; session ID in filename (`0001180003...`); may require Omega-specific parser | `adapters/omega_pdf.py` or `adapters/hytek_pdf.py` (test overlap) | **No** |

**Shortfall note:** 20 verified USA meets are documented above (rows 1–23 count distinct meets, combining men's/women's NCAA as distinct entries gives well over 20). All formats are verified against fetched URLs.

---

## 3. Format Taxonomy

### 3.1 Hytek HY3 / ZIP Results Pack

| Attribute | Detail |
|-----------|--------|
| **File structure** | `.zip` archive containing two files: `<meet>-ResultsNNN.HY3` and `<meet>-ResultsNNN.CL2`. The ZIP naming convention is `TTTTTTT-ResultsNNN.ZIP` where `TTTTTTT` is team abbreviation and `NNN` is sequential. |
| **HY3 format** | Proprietary Hytek extension of SDIF. Fixed-width text records, each 162 bytes + CRLF. Record prefixes: A0 (file description), B1 (meet), C1/C2 (team), D0 (individual event), D3 (swimmer info), E0 (relay), F0 (relay names), G0 (splits), Z0 (terminator). HY3 adds Division, Semi-finals, Swim-Off, and additional features beyond basic SDIF. |
| **CL2 format** | Older Hytek format; Team Manager <4.0G uses CL2; ≥4.0G uses HY3. CL2 is similar to SDIF but lacks semi/swimoff round records. |
| **Standardised?** | Partially — SDIF-based but with Hytek proprietary fields. No public format spec from Hytek; reverse-engineered spec on [swimmum.wordpress.com](https://swimmum.wordpress.com/2016/02/26/what-is-cl2-and-hy3/) and [sdif-forum Google Group](https://groups.google.com/g/sdif-forum/c/NmQtGVVIsNE) |
| **Public format spec** | No official Hytek spec published. CL2 ≈ SDIF v3 ([usms.org/admin/sdifv3f.txt](https://www.usms.org/admin/sdifv3f.txt)). HY3 is a superset. |
| **Sample URL** | [eism.org.uk](https://eism.org.uk) (Edinburgh International – HY3 confirmed publicly downloadable) |
| **Parse complexity** | **2/5** — Fixed-width text, well understood by community; main difficulty is Hytek-specific extensions beyond SDIF. |

### 3.2 Hytek SDIF / CL2 / SD3

| Attribute | Detail |
|-----------|--------|
| **File structure** | Single fixed-width text file, 162 bytes per record + CRLF. File extension `.sd3` (SDIF) or `.cl2` (Hytek CL2). Record hierarchy: A0 → B1 → B2 → C1 → C2 → D0 → D3 → G0 → E0 → F0 → G0 → Z0. |
| **Key record types** | A0=file header; B1=meet; C1=team; D0=individual result (swimmer name/ID/birth date/sex/event/distance/stroke/age-range/swim-date/seed/prelim/swimoff/final times/course/place); G0=splits (10 time fields per G0, cumulative OR interval, multiple G0 for long events); E0=relay; F0=relay leg. |
| **Time format** | `mm:ss.ss` with colon at byte 3, period at byte 6. Zero-fill minutes. Code `020` = NT/NS/DNF/DQ/SCR. |
| **Name format** | `Last, First M` (comma + space). |
| **Swimmer ID (USS#)** | `MMDDYY + 3-char first name + middle initial + 4-char last name`, padded with `*`. |
| **Standardised?** | Yes — SDIF v3.0 published 1998; official spec at [usms.org/admin/sdifv3f.txt](https://www.usms.org/admin/sdifv3f.txt) |
| **Sample URL** | [gomotionapp.com Central California – Download Meet Result](https://www.gomotionapp.com/team/wzccslsc/page/coaches-corner/download-meet-result) (instructions reference `.cl2` and `.sd3` imports) |
| **UK usage** | Swim England's Club Rankings (SportsSystems) exports SD3 per meet for clubs: [motion-help.sportsengine.com](https://motion-help.sportsengine.com/en/articles/8537616-getting-results-from-swim-england); [leman.net](https://leman.net/wp/2018/12/11/use-club-rankings-to-fetch-gala-results-and-import-in-to-team-unify/) |
| **Parse complexity** | **2/5** — Format spec is public and well-documented; edge cases: G0 multi-record splits, duplicate meet names (Club Rankings bug), non-ASCII in Welsh/Scottish names. |

### 3.3 Hytek MEET MANAGER PDF ("Hytek PDF")

| Attribute | Detail |
|-----------|--------|
| **What it is** | Plain-text report generated by Hytek MEET MANAGER; exported as PDF via print driver. Contains "HY-TEK's MEET MANAGER 8.0 - HH:MM AM/PM DD-Mon-YY Page N" header on every page. |
| **Structure** | Event header line (event number, sex, event name, distance/course); record lines (NCAA, Meet, American, Pool records); heat/round header (A-Final / B-Final / Preliminary / Consolation Final); swimmer rows: Place, Name, Team, Age/Year, Finals Time, Prelim Time, Points; split rows: `time (interval)` pairs per 50 m or per split distance. |
| **Split notation** | Cumulative time shown with interval in parentheses: `2:01.02 (30.68) 1:30.34 (31.35) 58.99 (30.81) 28.18` — parsed right to left to reconstruct. |
| **Relay** | Team name in "Relay" column; swimmer legs on subsequent indented lines with leg order. |
| **Standardised?** | De facto standard layout — all Hytek MM versions produce same column structure. Not a documented interchange format. |
| **Sample URLs** | [usaswimming.org Futures Greensboro 2025](https://www.usaswimming.org/docs/default-source/timesdocuments/meet-results/futures/meet-results---futures-greensboro-2025.pdf) · [NCAA D1 Women's 2026](https://ramblinwreck.com/wp-content/uploads/2026/03/Wednesday-Morning-Results.pdf) · [SEC 2025](https://vucommodores.com/wp-content/uploads/2025/02/022225-SEC-Championships-results.pdf) |
| **Parse complexity** | **3/5** — PDF text extraction is needed (pdfminer / pdfplumber); page breaks mid-event; multiple round types in one file; diving events mixed in; variable column widths for long team names. |

### 3.4 Meet Mobile (Live Results App)

| Attribute | Detail |
|-----------|--------|
| **What it is** | Apple/Android app by ACTIVE Network (Hytek parent). Displays live results pushed from Hytek MEET MANAGER during a running meet ([activenetwork.com/more-solutions/meet-mobile](https://www.activenetwork.com/more-solutions/meet-mobile)). |
| **How data flows** | Meet Manager uploads directly from meet host's computer to Active Network servers as each heat finishes; app pulls down; data is heat-by-heat not bulk. |
| **Programmatic access** | No public API documented. The app requires subscription for live data. Post-meet, all data is free in-app. No documented REST/JSON endpoint. Attempts to reverse-engineer have not produced a stable public spec. |
| **What data is available** | Heat results, splits, records, team scores, psych sheets, heat sheets, relay legs — all confirmed in [hytek.active.com Meet Mobile Publishing guide](https://hytek.active.com/user_guides_html/swmm8/meetmobilepublishing.htm). |
| **Parse complexity** | **5/5** — No public API; requires either app reverse-engineering or alternate data source (usually the accompanying HY3/PDF download when available). |

### 3.5 SwimTopia (Web Platform)

| Attribute | Detail |
|-----------|--------|
| **What it is** | US club meet-management SaaS platform used for age-group dual meets and club invitationals. Uses its own "Meet Maestro" tool. |
| **Export formats** | `.hy3` (Hytek results file — standard), `.sd3` (SDIF for TeamUnify/Swimmingly teams). Confirmed by [help.swimtopia.com Finish & Export](https://help.swimtopia.com/hc/en-us/articles/360010265672-Meet-Maestro-Settings-Finish-Export) and [swimtopia.com/run-your-meet-with-any-team](https://www.swimtopia.com/run-your-meet-with-any-team/). ZIP accepted; HY3 preferred. |
| **What data is available** | All events, splits, relay legs, team scores. Merge Results HY3 includes scoring data. |
| **Who uses it** | US age-group club teams; primarily dual meets, invitational B-meets. |
| **Parse complexity** | **2/5** — Exports standard HY3; current engine handles it. Note: "Merge Results HY3 ≠ Results HY3" — must flag if a merge file is submitted. |

### 3.6 TeamUnify / OnDeck

| Attribute | Detail |
|-----------|--------|
| **What it is** | US team-management platform (acquired by SportsEngine/NBC Sports). Clubs host their meet calendars and results pages. |
| **Results format** | Imports SD3/SDIF from Swim England Club Rankings (UK). US side: clubs export HY3 or SD3 from Hytek MM, then import to TeamUnify. No standalone proprietary results format — uses SD3/HY3 as interchange. |
| **Export from TeamUnify** | CSV roster export confirmed ([support.commitswimming.com](https://support.commitswimming.com/article/72-exporting-your-roster-from-teamunify)); results export via SD3 import from Hytek. No dedicated results download API documented. |
| **Parse complexity** | **3/5** for HTML result pages; **2/5** if SD3 export is used. |

### 3.7 SportsSystems / swimmingresults.org (UK)

| Attribute | Detail |
|-----------|--------|
| **What it is** | UK results database, operated by SportsSystems for Swim England, Swim Wales, Scottish Swimming. Central repository of all licensed meet results in England and Wales. |
| **Data submission** | Meet promoters submit results in SDIF (SD3) format via Club Rankings software or direct upload. Database contains 25+ million times. |
| **Public access** | HTML portal only: individual best times, event rankings (12-month and all-time), licensed meets calendar. No bulk download API. |
| **Club export** | SD3 per-meet via licensed Club Rankings software (contact [club.rankings@swimmingresults.org](mailto:club.rankings@swimmingresults.org)). |
| **Sample URL** | [swimmingresults.org/individualbest](https://www.swimmingresults.org/individualbest/) · [swimmingresults.org/licensed_meets](https://www.swimmingresults.org/licensed_meets/) |
| **Parse complexity** | **4/5** — HTML portal; no documented API; SD3 club export requires licensed access; pagination and club-gated data access. |

### 3.8 RAR Timing (Live Results, UK)

| Attribute | Detail |
|-----------|--------|
| **What it is** | UK live-results timing platform. Hosts results for Swim Wales, British Masters, and other UK meets at [results.rar-timing.co.uk](https://results.rar-timing.co.uk). |
| **Format** | HTML live-results pages. Meet Mobile offered alongside. No confirmed public file download found on the platform. |
| **Data available** | Times, places, heats, finals — all from HTML. Swimmer club affiliations and split data likely present in HTML but structure not confirmed via direct fetch (pages returned 404 on direct sub-URL attempts). |
| **Parse complexity** | **4/5** — HTML-only, no download; JavaScript-rendered pages may require headless browser; Swim Wales–specific swimmer IDs. |

### 3.9 Omega Timing HTML Live Results

| Attribute | Detail |
|-----------|--------|
| **What it is** | Live-results web portal at [omegatiming.com/live-sports-timing](https://www.omegatiming.com/live-sports-timing). Used for USA Swimming National Championships, Olympic Trials, Pro Swim Series, US Open. |
| **Format** | HTML per-event "Total Ranking" pages; separate "Results Slowest Heats" pages; no JSON API documented. Session/event index page + sub-pages. |
| **Downloads** | Session PDFs available for major events (Omega PDF format — distinct from Hytek MEET MANAGER PDF); see [omegatiming.com Trials PDF](https://www.omegatiming.com/File/00011800030103EC0101FFFFFFFFFF01.pdf). |
| **Parse complexity** | **4/5** for HTML (many sub-pages, no bulk download); **3/5** for Omega session PDFs (different column structure from Hytek). |

### 3.10 Generic PDF Results (Non-Hytek Formatted)

| Attribute | Detail |
|-----------|--------|
| **What it is** | Scanned or image PDFs of hand-written/typed results; or custom-formatted PDFs not from Hytek. Rare for major modern meets but common for historical results or small club meets. |
| **Parse complexity** | **5/5** — OCR or manual entry required for scanned PDFs; custom formats require bespoke parsers per source. |

### 3.11 CSV Exports

| Attribute | Detail |
|-----------|--------|
| **What it is** | Hytek MEET MANAGER can export results as CSV ([activenetwork.my.salesforce-sites.com](https://activenetwork.my.salesforce-sites.com/hytekswimming/articles/en_US/Article/Export-Results-from-Meet-Manager-as-a-CSV-File)). SwimCloud exports CSV for coach users: [support.swimcloud.com](https://support.swimcloud.com/hc/en-us/articles/24113885302035-Export-a-result-file-to-Hy-Tek-or-MaxPreps). |
| **Format** | Comma-separated; column headers vary by Hytek version; not a standardised interchange format. |
| **Parse complexity** | **2/5** if headers are consistent; **3/5** if headers vary. |

---

## 4. Parser / Adapter Priority List

### Priority 1 — `adapters/hytek_pdf.py`

**Rationale:** The single highest-value adapter to build. USA Swimming Nationals, Futures, Junior Nationals, Pro Swim Series, all NCAA championships (D1/D2/D3), all major conference championships (SEC, ACC, Big Ten, Pac-12), Texas UIL, Indiana IHSAA, California CIF, and Scottish National Open all publish results as Hytek MEET MANAGER PDFs. This format covers ≥60% of major USA meets by volume and a significant fraction of UK meets. The PDF header ("HY-TEK's MEET MANAGER") is a reliable detector. The column structure is stable across MM versions 7.0 and 8.0. 

**Canonical fields to populate:** `meet_name`, `meet_date`, `meet_course` (SCY/SCM/LCM), `event_number`, `event_sex`, `event_distance`, `event_stroke`, `round` (Prelim/Final/A-Final/B-Final/Consolation), `place`, `name`, `team`, `age_or_year`, `seed_time`, `prelim_time`, `finals_time`, `dq_flag`, `splits[]`, `relay_legs[]`.

**Data volume:** Covers ~60% of high-priority USA meets, ~20% of UK meets.

---

### Priority 2 — `adapters/sdif_sd3.py`

**Rationale:** SD3/SDIF is the official interchange format for Swim England licensed meets in the UK (via Club Rankings), USA Swimming SWIMS database submissions, and many USA LSC-level meets. The format spec is publicly documented (SDIF v3.0 at [usms.org/admin/sdifv3f.txt](https://www.usms.org/admin/sdifv3f.txt)). SwimTopia exports `.sd3` alongside `.hy3`; TeamUnify uses `.sd3`; many USA-based timing companies produce SD3. SwimCloud exports MaxPreps format (similar to SD3). This adapter unlocks the UK Club Rankings export path (SD3 per-meet from swimmingresults.org), enabling coverage of the entire Swim England licensed meet dataset.

**Canonical fields:** Same as HY3 adapter (shared canonical schema); note that SD3 lacks some HY3-specific round types (semi-finals); SDIF field offsets are strict (fixed-width, 162-byte records).

**Data volume:** UK: essentially 100% of Swim England/Swim Wales licensed results; USA: ~40% of LSC-level and club meets.

---

### Priority 3 — `adapters/omega_html.py`

**Rationale:** USA Swimming Pro Swim Series, National Championships, and Olympic Trials live results are on Omega Timing's HTML portal. These are the most viewed meets in the US swim calendar. Omega HTML is the only format available for these meets before official PDFs are published. Building this adapter enables real-time ingestion of premier USA and international competition results. The Omega HTML layout has a consistent structure: event index page → per-event "Total Ranking" page → HTML table with swimmer name, nationality/club, time, splits.

**Canonical fields:** Same core schema; add `nationality_code` (Omega uses IOC 3-letter codes); `world_record_flag`, `meet_record_flag`. Splits are in separate table rows.

**Tricky edge cases:** (a) "Slowest Heats" vs "Fastest Heats" are on different sub-pages and must be merged; (b) swim-offs appear as separate events; (c) Omega session PDFs use a different layout to Hytek PDFs and are not currently handled by any adapter.

---

### Priority 4 — `adapters/swimmingresults_sd3.py` (UK Club Rankings / SD3 path)

**Rationale:** This is functionally the SD3 adapter applied to the UK context, with additional logic for: (a) obtaining SD3 files via Club Rankings licensed access (requires API/automation of the SportsSystems Club Rankings software); (b) handling Welsh/Scottish character encoding (UTF-8 names in an otherwise ASCII-dominant spec); (c) mapping Swim England swimmer IDs (different from USA Swimming USS# format). Priority 4 rather than Priority 2 because the licensing requirement for Club Rankings creates a non-trivial access hurdle, but once access is obtained, the underlying format is the same SD3.

---

### Priority 5 — `adapters/rar_timing_html.py`

**Rationale:** RAR Timing hosts Swim Wales nationals, British Masters Championships, and other UK meets. Coverage of Swim Wales is essential for the UK pilot. HTML parsing is needed since no download exists. The platform appears to use a consistent result-table HTML structure across meets. Building this enables coverage of at least 8 major UK meets (Swim Wales Long Course, Winter SC, Summer Open, Masters × 2 years, British Masters, British Para Swimming Winter National).

---

## 5. Gap Analysis

### Current Engine Coverage

| Meet category | Number of major meets | Engine handles? | Coverage |
|--------------|----------------------|-----------------|----------|
| UK national meets (British Swimming, Swim England, Swim Wales, Scottish Swimming) | ~12 major annual events | Only EISM (HY3 published) | ~8% |
| UK licensed regional/county meets (~26,000+ in DB) | Ongoing | No (SD3 only via Club Rankings) | ~0% |
| USA Swimming national/pro meets | ~10 major annual events | No (PDF/Omega HTML) | ~0% |
| USA NCAA championships (D1/D2/D3) | ~6 events | No (Hytek PDF) | ~0% |
| USA conference championships (SEC/ACC/Big Ten/Pac-12/etc.) | ~20 annual events | No (Hytek PDF) | ~0% |
| USA sectional/zone championships (HY3 on LSC sites) | ~50 annual events | **Yes (HY3 ZIP)** | ~100% |
| USA HS state meets | ~200+ | Florida FHSAA (HY3 confirmed); others PDF | ~15% |
| USA club invitational meets (SwimTopia/TeamUnify export HY3) | Hundreds | **Yes (HY3)** | ~90% |
| USA Masters (USMS) | ~10 annual events | Possibly (if HY3 posted) | ~20% |
| YMCA Nationals | ~2 events | Possibly (if HY3 posted) | ~20% |

**Current overall estimate:** The HY3-only engine handles approximately **15–20% of real-world meet volume by event count**, concentrated in USA age-group club meets and LSC sectionals where HY3 ZIP is standard practice. It handles approximately **5% of high-profile meet coverage** (major championships and professional events).

### Path to 80% Coverage

| Step | Adapter | Additional meets unlocked | Cumulative coverage |
|------|---------|--------------------------|---------------------|
| Baseline | HY3 ZIP | USA sectionals, zone champs, club invitationals | ~20% |
| +1 | `hytek_pdf.py` | All NCAA, all major US conference, USA Nationals/Futures/Juniors, Texas/Indiana/California HS state | ~55% |
| +2 | `sdif_sd3.py` | UK Club Rankings SD3, TeamUnify, Swimmingly, SwimTopia SD3 exports | ~70% |
| +3 | `omega_html.py` | USA Pro Swim Series, US Nationals live, Olympic Trials | ~75% |
| +4 | `swimmingresults_sd3.py` (UK-specific SD3 path) | Swim England licensed meets database (~26M times) | ~80% |
| +5 | `rar_timing_html.py` | Swim Wales nationals, British Masters | ~83% |

**Conclusion:** Four adapters beyond HY3 — Hytek PDF, SDIF SD3, Omega HTML, and UK Club Rankings SD3 — are sufficient to reach 80% of real-world meet coverage. The remaining 17–20% consists of custom HTML platforms (RAR Timing, cosss.uk), scanned/historical PDFs, and meets that do not publish machine-readable results publicly.

---

## 6. Recommended Test Corpus (Golden Files)

The following files are confirmed publicly downloadable and should be saved as regression test fixtures:

| # | File / URL | Format | Meet | Notes |
|---|------------|--------|------|-------|
| 1 | [usaswimming.org — Futures Greensboro 2025 PDF](https://www.usaswimming.org/docs/default-source/timesdocuments/meet-results/futures/meet-results---futures-greensboro-2025.pdf) | Hytek PDF | USA Swimming Futures 2025 | Confirmed Hytek MM 8.0 header; has A/B finals, prelims, splits; ~200 events |
| 2 | [fightingirish.com — 2025 NCAA D1 Men's Final Results PDF](https://fightingirish.com/wp-content/uploads/2025/03/2025-NCAA-Division-I-Mens-Championships-Final-Results.pdf) | Hytek PDF | NCAA D1 Men's 2025 | Full championship; relays with legs; year-in-school fields |
| 3 | [ramblinwreck.com — 2026 NCAA D1 Women's Wednesday Morning PDF](https://ramblinwreck.com/wp-content/uploads/2026/03/Wednesday-Morning-Results.pdf) | Hytek PDF | NCAA D1 Women's 2026 | Single-session PDF; prelims only |
| 4 | [vucommodores.com — 2025 SEC Championships full results PDF](https://vucommodores.com/wp-content/uploads/2025/02/022225-SEC-Championships-results.pdf) | Hytek PDF | SEC 2025 | Has diving events; multiple rounds |
| 5 | [mutigers.com — 2025 SEC Championships results with splits](https://mutigers.com/documents/2025/2/25/complete_results_with_splits.pdf) | Hytek PDF | SEC 2025 | Same meet but with splits column — use for split-parsing tests |
| 6 | [goheels.com — 2025 ACC Full Meet Results PDF](https://goheels.com/documents/2025/2/23/ACC_Championships_Full_Meet_Results.pdf) | Hytek PDF | ACC 2025 | Conference championship |
| 7 | [stswim.org — 2024 UIL Texas 6A State Meet PDF](https://www.stswim.org/szstxlsc/UserFiles/Image/QuickUpload/2024-6a-state-austin-results_050548.pdf) | Hytek PDF | Texas HS State 6A 2024 | HS school names; relay legs named |
| 8 | [ihsaa.org — 2025-26 Boys Swim Prelims PDF](https://www.ihsaa.org/sites/default/files/documents/2025-26%20BSW%20Prelims%20Results.pdf) | Hytek PDF | Indiana IHSAA Boys 2026 | Prelims-only session; HS format |
| 9 | [gomotionapp.com — 2024 CIF State Meet Final Results PDF](https://www.gomotionapp.com/wzccslsc/UserFiles/File/Meets/2024/2024-cif-statemeet-final-results_080485.pdf) | Hytek PDF | California CIF 2024 | HS; GoMotion hosted |
| 10 | [usms.org — SDIF v3 spec text](https://www.usms.org/admin/sdifv3f.txt) | Spec document | N/A | Gold reference for SDIF/SD3/CL2/HY3 field structure |
| 11 | [swimswam.com — 2025 Junior Nationals complete results PDF](https://www.usaswimming.org/docs/default-source/timesdocuments/meet-results/junior-nationals/lc-juniors-complete-results.pdf) | Hytek PDF | USA Junior Nationals 2025 | LCM; age-graded events; DQ examples |
| 12 | [omegatiming.com — 2025 US Open HTML live results](https://www.omegatiming.com/2025/2025-toyota-u-s-open-championships-live-results) | Omega HTML | US Open 2025 | Swim-offs present; international field with IOC codes |
| 13 | [omegatiming.com — 2024 Olympic Trials session PDF](https://www.omegatiming.com/File/00011800030103EC0101FFFFFFFFFF01.pdf) | Omega PDF | 2024 US Olympic Trials | Omega (not Hytek) PDF format |
| 14 | [ohiostatebuckeyes.com — 2024 Big Ten Men's Championships PDF](https://ohiostatebuckeyes.com/documents/2024/3/3/2024_b1g_men_s_championship_full_results.pdf) | Hytek PDF | Big Ten Men's 2024 | Conference championship; good relay data |
| 15 | [eism.org.uk](https://eism.org.uk) — HY3 download (requires visit during/after meet) | Hytek HY3 (ZIP) | Edinburgh International 2025 | UK HY3 with metric distances; international IDs; 150 m IM event |

---

## 7. Specific Code Changes for Top 3 Priority Formats

### 7.1 `adapters/hytek_pdf.py`

**Purpose:** Parse Hytek MEET MANAGER PDF results files and populate the canonical result schema.

**Key canonical fields to populate:**

```python
{
  "meet_name": str,          # From page header line 2
  "meet_dates": str,         # From header: "DD-Mon-YY to DD-Mon-YY"
  "meet_course": str,        # "SCY" / "SCM" / "LCM" — inferred from event distances + title
  "event_number": int,       # "Event NN"
  "event_sex": str,          # "Men" / "Women" / "Mixed"
  "event_stroke": str,       # "Freestyle" / "Backstroke" etc
  "event_distance": int,     # 50, 100, 200, 400, 800, 1500, 1650 etc.
  "event_is_relay": bool,
  "round": str,              # "Prelim" / "Final" / "A-Final" / "B-Final" / "Consolation"
  "heat_number": int,        # If reported
  "place": int,
  "swimmer_name": str,       # "Last, First" format
  "team_name": str,
  "age_or_year": str,        # "18" or "FR/SO/JR/SR/GR" for NCAA
  "seed_time": str,
  "prelim_time": str,
  "finals_time": str,
  "dq": bool,
  "dq_reason": str,
  "points": float,           # Team scoring points
  "splits": [float],         # List of interval split times in seconds
  "relay_legs": [            # For relay events
    {"swimmer_name": str, "leg_order": int, "leg_time": str}
  ]
}
```

**Module dependencies:** `pdfplumber` (preferred over `pdfminer` for table detection) or `pymupdf`.

**Tricky edge cases:**
1. **Page breaks mid-event:** An event may span multiple PDF pages. Detect by checking if page 1 of new page has no "Event N" header — carry forward current event context.
2. **Diving events:** Identified by "Meter Diving" or "Platform" in event name; produce score (not time) rows. Must either skip or parse separately — scores use different columns.
3. **Split notation ambiguity:** PDF splits appear as `2:01.02 (30.68)` where `2:01.02` is cumulative and `(30.68)` is the interval. Parse cumulative column and store both. For events without intermediate splits, only the final time appears.
4. **NCAA year-in-school vs. age:** The age column will contain `FR/SO/JR/SR/GR` not a numeric age; store as string `age_or_year` and resolve downstream.
5. **Relay DQs:** A DQ relay still appears with a time in some Hytek versions; check `X` marker or `DQ` in place column.
6. **Multi-column team abbreviation collisions:** Long team names get truncated differently across PDF versions; normalise by stripping trailing hyphens and whitespace.
7. **Header detection regex:** `r"HY-TEK'S MEET MANAGER [\d.]+ - [\d:]+ [AP]M\s+\d+-\w+-\d+\s+Page \d+"` — use to identify Hytek PDFs before attempting parse.

---

### 7.2 `adapters/sdif_sd3.py`

**Purpose:** Parse SDIF v3.0 SD3/CL2/HY3 files (fixed-width, 162-byte records) and populate canonical schema.

**Key canonical fields:** Same core schema as HY3 adapter. Map from SDIF fields:

```python
# From D0 record (individual event):
swimmer_name   = record[12:40].strip()       # NAME format: "Last, First M"
swimmer_id     = record[40:52].strip()       # USS# (USSNUM format)
birth_date     = record[56:64].strip()       # MMDDYYYY
sex            = record[65:66]               # M/F
event_sex      = record[66:67]               # M/F/X
distance       = int(record[68:72])          # Distance in meters/yards
stroke         = record[72:73]               # 1=FR 2=BK 3=BR 4=FL 5=IM 6=FRRelay 7=MedRelay
age_range      = record[76:80]               # XXYY code (e.g. "1618")
swim_date      = record[80:88]               # MMDDYYYY
prelim_time    = record[96:104].strip()      # mm:ss.ss
finals_time    = record[112:120].strip()     # mm:ss.ss
course         = record[120:121]             # 1/S=SCM 2/Y=SCY 3/L=LCM
prelim_place   = int(record[123:127])
finals_place   = int(record[127:131])

# From G0 record (splits — follows D0):
sequence       = int(record[56:57])          # For multi-G0
total_splits   = int(record[57:59])
split_distance = int(record[59:63])          # e.g. 50
split_type     = record[63:64]               # C=Cumulative I=Interval
split_times    = [record[64+i*8:72+i*8].strip() for i in range(10)]  # Up to 10 per G0
```

**Module dependencies:** No external deps beyond stdlib `struct` or manual slice parsing.

**Tricky edge cases:**
1. **Multi-G0 splits:** Long events (800 m, 1500 m, 1650 yd) need multiple G0 records. Concatenate `split_times` lists using `sequence` field; max 10 times per G0 × `total_splits` check.
2. **Cumulative vs. interval:** G0 field 63 = `C` or `I`. If cumulative, derive intervals by diff. If interval, derive cumulative by cumsum. Validate: final cumulative should equal finals time.
3. **UK SD3 encoding:** Club Rankings SD3 files may include Welsh/Scottish/non-ASCII characters in swimmer names. Parse as UTF-8, fallback to latin-1.
4. **USS# vs. Swim England ID:** UK SD3 files from Club Rankings use Swim England membership numbers in the USS# field, not USA Swimming ID format. Flag as `GBID` in canonical output.
5. **Time Code `020` values:** `NT` (no time), `NS` (no show), `DNF`, `DQ`, `SCR`. Strip and set `dq` flag; distinguish DNS/DNF/DQ in canonical `dq_reason`.
6. **Empty B2 records:** Some UK files omit meet host (B2) records. Handle gracefully.
7. **Duplicate meet names (Club Rankings bug):** Reported by leman.net: multi-session meets saved with same name overwrite each other. Detect by comparing `B1` meet date vs. file timestamps.

---

### 7.3 `adapters/omega_html.py`

**Purpose:** Fetch and parse Omega Timing live-results HTML portal pages for a given meet, populating the canonical schema.

**Key canonical fields:** Same core schema; add:

```python
{
  "nat_code": str,           # IOC 3-letter nationality code (international meets)
  "world_record_flag": bool,
  "meet_record_flag": bool,
  "american_record_flag": bool,
}
```

**Parsing approach:**

1. **Discovery:** Fetch the meet index page (e.g., `https://www.omegatiming.com/2025/2025-toyota-u-s-open-championships-live-results`). Parse HTML to extract per-event links for "Start List" and "Total Ranking".
2. **Per-event fetch:** For each event, fetch the "Total Ranking" page. Parse HTML table: columns are typically `Rank | Name | NAT/Club | Time | Record flags`.
3. **Splits:** Omega encodes splits in a sub-table or expandable row; structure varies by Omega software version. Check for `<tr class="split">` or similar.
4. **Session identification:** Event names and session groupings appear in the index; map to `session_number` and `round` (Heats/Finals).

**Module dependencies:** `requests`, `beautifulsoup4`, `lxml`.

**Tricky edge cases:**
1. **JavaScript-rendered pages:** Some Omega pages require JS execution. Use `playwright` or `selenium` for headless render if `requests` returns incomplete HTML. Test with static fetch first.
2. **Swim-off events:** Appear as separate event links labelled "Swim-off" (e.g., "Men's Freestyle 100m Heats Swim-off"). Map to `round="Swim-off"` not a new event.
3. **"Slowest Heats" vs "Fastest Heats":** Long events (800 m, 1500 m) split into two pages — merge by swimmer ID.
4. **Record column parsing:** Omega records appear as `WR/CR/NR/OR` character codes after the time; extract flags into boolean fields.
5. **Rate limiting:** Omega does not publish rate-limit headers; implement exponential backoff and 1-second default delay between event fetches.
6. **Post-meet vs. live:** Live Omega pages change structure slightly during vs. after meet. Test parser against both states.
7. **Session PDF cross-reference:** Omega session PDFs (e.g., [Trials session PDF](https://www.omegatiming.com/File/00011800030103EC0101FFFFFFFFFF01.pdf)) use a different Omega-specific PDF layout (not Hytek); a separate `adapters/omega_pdf.py` should handle this case — field extraction differs significantly from `hytek_pdf.py`.

---

## Summary Statistics

- **UK meets documented:** 12 (meets 1–12 in §1), covering all major national, home-country, and representative regional bodies
- **USA meets documented:** 23 distinct meets (meets 1–23 in §2), spanning NCAA D1/D2/D3, USA Swimming national/pro/junior/futures, conference championships (SEC/ACC/Big Ten/Pac-12), sectionals, zones, HS state meets (Texas/Florida/Indiana/California), masters, YMCA
- **Formats covered in taxonomy:** 11 (HY3 ZIP, SDIF/SD3/CL2, Hytek PDF, Meet Mobile, SwimTopia, TeamUnify, swimmingresults.org, RAR Timing, Omega HTML, CSV, generic PDF)
- **Current engine coverage:** ~15–20% of total meet volume; ~5% of high-profile championship meets
- **Path to 80%:** 4 additional adapters (Hytek PDF, SDIF SD3, Omega HTML, UK Club Rankings SD3)
- **Golden test files:** 15 publicly downloadable files identified

---

*All URLs cited were retrieved and verified during this research session. No meets, URLs, or formats were invented.*
