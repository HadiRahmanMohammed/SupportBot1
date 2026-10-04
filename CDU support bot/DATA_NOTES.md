# Data notes: from Welcome Centre FAQ to knowledge base

**Source:** *New Student Welcome Centre: Frequently Asked Questions*, Version 2 (28/02/2023), 17 pages. Provided by the CDU Senior Student Success Adviser.
**Output:** `data/faqs.json` (64 entries).

These notes record what we found when we inspected the dataset. They're intended as input for the Final Report's "Understanding the Data Context" section, which the Progress Report promised to update once the data arrived.

## What the data actually is

- It's a **staff-facing** guide ("This document will help guide you in answering questions from newly arrived students"), not a student-facing FAQ. As the Progress Report predicted, many answers were written for a staff member to relay rather than for a student to read.
- It's **university-level heavy**. Almost every entry covers admin, campus, IT, accommodation, transport, jobs or international matters. There are **no unit-level questions** (joining online classes, recordings, assessment dates, folders). This confirms the Progress Report's expectation and the "Dataset under-represents unit-level questions" risk.
- It's **international-student heavy**: visa, CoE, GMS scholarship, CDU Global, homestay and banking. This fits the Welcome Centre's audience. Domestic first-years and online students are less represented, which is a fairness point for Section 6.
- It contains **no personal information**. There are no student names, IDs or contact details. The real phone and email question log is still separate and pending.
- It **includes reviewer comments** (Word comments by staff), some of which change the meaning of the main text.

## Cleaning decisions

| Issue found | Decision |
|---|---|
| Staff voice ("double check if they have gone to…", "Walk student over to…") | Rewritten in second person for students, without changing meaning |
| Internal-only escalation notes ("Teams me and I will assist", "Liaise with Centre Coordinator", "escalate to ISS Officer") | **Removed.** These are staff procedures, not student answers |
| Reviewer comment: timetable team asked staff **not** to direct students to "mystic" (being decommissioned) | Followed. The answer points only to the New Student Portal |
| Reviewer comment suggesting a `stapps.cdu.edu.au` timetable link | **Not used.** It was a suggestion in a comment, not approved body text |
| Reviewer comment: Semester Address is not compulsory | Incorporated into the international student record answer |
| Reviewer comment: Buddy Program "not running this semester" | Kept, with a "doesn't run every semester" caveat and a `review_flag` |
| Reviewer comment: free RSA course for international students | **Not used.** It was a comment only and is unverified |
| "Free for some time" (buses) | **Removed** as likely stale; flagged for review |
| GMS FAQs based on **2024–2025** terms and conditions | Kept, but all 5 are flagged to check against the current T&Cs |
| GMS exempted-course lists for 2024/2025 | **Not used.** They're year-specific and would mislead in 2026 |
| Typos: "student centra", "CLV" vs "CVL" | Fixed "Student Central". CLV/CVL is flagged so staff can confirm the provider's name |
| URLs broken across lines by PDF layout (e.g. `newinternational-students`) | Re-joined to the most likely form (`new-international-students`). **Click-test all links before go-live** |
| Some links appear only as page titles (Language and Learning Support, LibCal, Bus service, maps) | Kept as text without guessing URLs. Staff can add the exact URLs |
| Event-specific LibCal links (single-event IDs) | Not used, since they expire |
| Mixed content: the "Who's Who" and "Support Services" tables | Split into separate entries (Counselling, Security, Access and Inclusion, Advocacy, First Nations, ISS, Student Central) plus one overview |

## What we added (and how it's marked)

- **Alternative phrasings** for every FAQ (2–7 each), so students can ask in their own words. These are matching aids only and aren't shown to students.
- **4 unit-level placeholder entries** (online class, recordings, assessment due dates, unit materials). They point to Learnline and the unit coordinator. They're marked `"approved": false`, shown with a "General guidance: not yet staff-approved" badge, and can be hidden with `SHOW_UNAPPROVED=false`.
- **Safety contacts in two answers:** 000 and Lifeline 13 11 14 in the counselling answer and the crisis reply. This is standard Australian crisis information.
- **Student Central contact details** in the fallback message, taken from page 17.

## Data currency

- The document is dated **Feb 2023**, and the GMS section covers the 2024–2025 terms and conditions. By October 2026 several details may have changed: workshop schedules, lounge hours, bus fares and scholarship rules.
- **10 approved entries carry a `review_flag`.** Students see a soft "details may have changed" note on these. Staff see the specific note in `?review=1` mode.

## Questions to ask the Adviser

1. Is this FAQ actively maintained? Is there a newer version than v2 (Feb 2023)?
2. Can her team approve or correct the 4 unit-level placeholder answers?
3. What do "CLV" and "CVL" stand for, and is +61 8 7928 5050 still correct?
4. What are the current GMS terms and conditions? Should scholarship questions just go to CDU Global?
5. When will the phone and email question log arrive, and in what format? (It will be cleaned in `data/private/` and never committed.)
6. Is she comfortable with students seeing the source citation ("New Student Welcome Centre FAQ, p.X")?

## Version 2: the collected dataset (29 Sep 2026)

`data/raw/cdu_chatbot_dataset.xlsx` (git-ignored, because Q&A Corner staff replies greet students by first name) holds 523 rows from the CDU Student Portal and public CDU pages. `scripts/import_dataset.py` turns it into knowledge-base entries; `data/import_report.json` lists every decision.

| Source | Rows | What we did |
|---|---|---|
| LibAnswers (Library and Student Central) | 264 | Kept 222 after removing staff-only, research-degree and dated items; 27 that duplicated a curated entry became extra phrasings of it |
| Important dates 2026 | 27 | Kept current semester, intensive, TAFE and 2027 dates as dated lists; dropped archived and HDR dates |
| Grade release, future students | 8 | Kept, except a worked GPA example and a contact block |
| StudyStays accommodation | 17 | Kept the 5 student rows; dropped the 12 for landlords |
| Medical program FAQ, Master of IT page | 98 | Left out: course pages for prospective applicants, not first-year support (`--include-course-level` adds them) |
| New Student Q&A Corner | 109 | Not used as answers (personal, dated, names students). 108 questions became the real-world test set, names removed |

Cleaning applied to every imported answer: raw links pulled out into link buttons, "Step 1:" turned into numbered lists, date tables turned into "Monday 2 March: Teaching starts", answers cut to chat size at a line break with a link to the full page, and page headings ("Census Dates", "Security") rewritten as the question a student would ask.

From the dev half of the Q&A Corner we drafted 8 entries for topics students ask about often but no official FAQ covers: InPlace and placements, attendance and recordings for online students, timetable time zones, timetables that aren't ready yet, units not open in Learnline, full-time vs part-time load, orientation for online students, and student cards for online students. They're `approved: false` until Student Success staff check them.

**Questions for the Adviser (v2):** Are the placements contacts in `placements-inplace` right for every faculty? Should the medical program and course pages be in scope? Can we get an export of Ask CDU, which blocks automated collection?
