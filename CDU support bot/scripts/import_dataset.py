"""Merge the collected CDU dataset (data/raw/cdu_chatbot_dataset.xlsx) into the knowledge base.

Inputs
  data/faqs_curated.json          the 64 hand-written entries (Welcome Centre FAQ + team placeholders)
  data/raw/cdu_chatbot_dataset.xlsx  official FAQs collected 29 Sep 2026 (LibAnswers, website pages,
                                  StudyStays) and the New Student Q&A Corner

Output
  data/faqs.json                  curated entries + cleaned official entries (what the bot uses)
  data/import_report.json         what was kept, skipped and merged, with reasons

The Q&A Corner is *not* imported as answers: staff replies there are personal ("Hi Sonam, your
placement unit is EPE635"), dated and name students. Its real student questions are used as a
held-out real-world test instead (data/real_eval.json, labelled by hand).

Usage:  python scripts/import_dataset.py [--include-course-level]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.matcher import FAQMatcher  # noqa: E402

RAW = ROOT / "data" / "raw" / "cdu_chatbot_dataset.xlsx"
CURATED = ROOT / "data" / "faqs_curated.json"
OUT = ROOT / "data" / "faqs.json"
REPORT = ROOT / "data" / "import_report.json"
QA_DRAFTS = ROOT / "data" / "qa_corner_faqs.json"  # team drafts for common Q&A Corner topics

MAX_ANSWER = 750      # characters shown in chat; longer answers are cut at a line break
DUP_SCORE = 0.62      # an imported question this close to a curated one is treated as a duplicate
# Reviewed by hand: these score above DUP_SCORE but are a different topic, so they stay separate.
NOT_DUPLICATE = {
    "What is census date, and when is it?", "Where do I find information about my exams?",
    "Who can use which Library spaces?", "How do I apply to graduate when I finish my course?",
    "Can someone at CDU proofread my assignment?", "What is Turnitin or SafeAssign and how to submit an assignment",
    "Help with Learnline", "Who can help me with Overseas Student Health Cover (OSHC)",
    "Am I eligible to study at uni?", "How to apply for Advanced standing - Credit transfer and/or RPL",
    "How to apply to CDU if you are an International Student", "Where can I get food?",
    "How do I photocopy my ID card?", "Why has a book I borrowed been recalled?",
}
# Headings too vague to keep as an extra phrasing (they match unrelated questions).
VAGUE_HEADINGS = {"Completion process", "Exams", "Security", "Databases", "Recalled items", "Copy my ID"}

# LibAnswers section -> chatbot category
CATEGORY = {
    "Technology": "IT and Wi-Fi",
    "Directional": "Campus and wayfinding",
    "CDU services": "Campus and wayfinding",
    "Student Central": "Enrolment and study plans",
    "Borrow": "Library",
    "Library account": "Library",
    "Library services": "Library",
    "Library spaces": "Library",
    "Databases": "Library",
    "Search": "Finding sources",
    "Research": "Finding sources",
    "Referencing": "Referencing and EndNote",
    "Assignment": "Assignments and academic integrity",
    "Academic writing": "Assignments and academic integrity",
    "Copyright": "Assignments and academic integrity",
}
# Directional rows that are really admin questions
ADMIN_WORDS = re.compile(r"census|fees|enrol|results|study plan|timetable|student record", re.I)

# Out of scope for first-year students (staff-only or research-degree material), by question start.
EXCLUDE = {
    "staff": ["How do I get or replace a staff card", "What music can I use for my students",
              "Can I show Netflix in class", "Can I include copyright material in exams",
              "Who owns the copyright of teaching and learning", "Can I reproduce the image from a textbook in my Learnline",
              "Can you invigilate my exam", "Does the library accept donations",
              "How do I request photographs/videos from the Library's collections",
              "Online Library resources for CDU Alumni", "Can past students still access",
              "Public access to CDU Libraries", "Can members of the public borrow",
              "I'm studying at another university, can I use", "Academic Document Request after Graduation"],
    "research degree": ["Which Creative Commons licence", "I am completing a thesis by prior publication",
                        "I want to reproduce a map I found in a book in my thesis",
                        "What is fair dealing, and when does it stop applying to my thesis",
                        "Do I need permission to include my own published articles", "How do I find or deposit a thesis",
                        "How to find out which journals are in the top", "DMP ID", "CDU Press",
                        "How can I get an ISBN", "Does CDU Library provide access to Covidence",
                        "What services are there for me as a researcher", "Is there plagiarism checking software for HDR",
                        "Can I upload copyrighted material to a generative AI tool for my research",
                        "How can I find out the impact factor", "How do I get access to Library resources when I haven't started my research",
                        "What do I need to know about First Nations Knowledge and Intellectual Property",
                        "How do I know who owns the copyright for the material", "What is RightsLink"],
    "no answer": ["Copyright check: Can I use this material"],
    "dated notice": ["Library Closures", "Ebook Central Update"],
}

# Page headings rewritten as the question a student would ask (the heading stays as an alternative).
REWRITE = {
    "Census Dates": "What is census date, and when is it?",
    "Completion process": "How do I apply to graduate when I finish my course?",
    "Device charging": "Where can I charge my phone or laptop?",
    "Adjust file size for email": "How do I make a file small enough to email?",
    "Finding a lecturer's office": "How do I find my lecturer's office?",
    "Where to find books in the Casuarina campus Library": "Where are the books in the Casuarina Library?",
    "Full text article not available": "What do I do if the full text of an article isn't available?",
    "Requesting books from another CDU campus": "How do I request a book from another CDU campus?",
    "All about the Mandatory Academic Integrity Module": "What is the mandatory Academic Integrity Module?",
    "City Campus | Danala Quick Info": "What's at the City campus (Danala) and when is it open?",
    "Changing or updating details on my student record": "How do I update my details or change my name on my student record?",
    "Chrome blocking EndNote download": "Chrome is blocking my EndNote download. What do I do?",
    "EndNote Referencing has a strange font and spacing in Word": "Why are my EndNote references in a strange font or spacing?",
    "Error message when installing EndNote on Mac": "I get an error installing EndNote on my Mac. What do I do?",
    "Reporting broken links in Library Search": "How do I report a broken link in Library Search?",
    "My EndNote toolbar has disappeared from Word": "My EndNote toolbar has disappeared from Word. How do I get it back?",
    "How to apply to CDU if you are an International Student": "How do I apply to CDU as an international student?",
    "When are my final results available": "When are my final results available?",
    "Accessing your Reading List": "How do I access my unit reading list?",
    "Scanning without a CDU account": "Can I scan without a CDU account?",
    "How to prepare print jobs": "What do the print settings mean?",
    "Uploading from and dowloading to OneDrive": "How do I upload to and download from OneDrive?",
    "Recalled items": "Why has a book I borrowed been recalled?",
    "How to access Yolŋu keyboard onscreen and Yolŋu fonts": "How do I type Yolŋu characters on a library computer?",
    "How to use accessibility mode in Ebook Central from Proquest": "How do I use accessibility mode in Ebook Central?",
    "Clear browser cache": "How do I clear my browser cache?",
    "Unique Student Identifier (USI) and Tax File Number (TFN) Issues": "Where do I get my USI, and who do I contact about a USI or TFN error?",
    "Exams": "Where do I find information about my exams?",
    "Taking a break from study": "How do I take a break from my studies?",
    "Apprenticeships": "How do I find out about apprenticeships and traineeships?",
    "My eQuals enquiries": "Who do I contact about my eQuals (digital testamur)?",
    "How can I get access to a building": "How do I get after-hours access to a building?",
    "How to scan": "How do I scan a document on a library printer?",
    "How to apply for Advanced standing - Credit transfer and/or RPL": "How do I apply for credit transfer or RPL (advanced standing)?",
    "Databases": "Where do I find the library databases?",
    "How do I get books? Placing Requests on Library items": "How do I place a request for a library book?",
    "Penalties for withdrawal from a unit": "What are the penalties for withdrawing from a unit?",
    "How do I check and pay my student fees": "How do I check and pay my student fees?",
    "I want to use cash": "Can I pay with cash on campus?",
    "Where is a specific building": "Where is a particular building on campus?",
    "Enable browser cookies": "How do I enable browser cookies?",
    "Security settings in Windows preventing your EndNote download": "Windows security is blocking my EndNote download. What do I do?",
    "Where is my lecture happening": "Where is my lecture happening?",
    "How do I withdraw from a Unit": "How do I withdraw from a unit?",
    "How do I contact my Lecturer": "How do I contact my lecturer?",
    "Security": "How do I contact campus security?",
    "Where to find food": "What food outlets are on campus, and when are they open?",
    "Can I use WiFi at another university": "Can I use WiFi at another university?",
    "Can't log in to a computer": "I can't log in to a library computer. What do I do?",
    "Identifying resources required": "How do I find the resources required for my unit?",
    "Copy my ID": "How do I photocopy my ID card?",
    "No option to do a Draft Submission through Turnitin or SafeAssign": "Why is there no draft submission option in Turnitin or SafeAssign?",
    "Streaming digital content from Kanopy": "How do I stream films on Kanopy?",
    "Where can I get help - online or in person": "Where can I get help, online or in person?",
    "Dealing with eBook error messages": "What do I do about an eBook error message?",
    "Library & Archives NT (LANT) Services and Facilities": "What services does Library & Archives NT (LANT) offer at Danala?",
    "All about Library & Archives NT (LANT)": "What is Library & Archives NT (LANT)?",
    "Resume course after a break": "How do I resume my course after a break?",
    "Help with Higher Education Contribution Scheme (HECS)": "Where can I get help with HECS?",
    "What is the Tertiary Enabling Program (TEP)": "What is the Tertiary Enabling Program (TEP)?",
    "Renewing items": "How do I renew my library books?",
    "I have returned my book but it's still on my account": "I returned my book but it's still on my account. What do I do?",
    "CDU Services and Support": "What services and support does CDU offer students?",
    "Downloading EndNote": "How do I download EndNote?",
    "EndNote and Cloud Storage": "Can I keep my EndNote library in OneDrive or cloud storage?",
    "EndNote and Norton virus software": "Norton antivirus is causing problems with EndNote. What do I do?",
    "Sim Block nomination": "Who do I contact about my nursing Sim Block nomination?",
    "How to apply - SATAC / UAC": "How do I apply through SATAC or UAC?",
    "How do I follow up on my enrolment application": "How do I follow up on my enrolment application?",
    "Who can help me with Overseas Student Health Cover (OSHC)": "Who can help me with Overseas Student Health Cover (OSHC)?",
    "What is Turnitin or SafeAssign and how to submit an assignment": "What is Turnitin or SafeAssign, and how do I submit an assignment?",
    "Help with Learnline": "Who can help me with Learnline?",
    "I can't find the book I want on the shelves even though it's listed as available":
        "I can't find a book on the shelf even though it's listed as available. What do I do?",
    "I am attending an event here at CDU but don't know where to go": "I'm attending an event at CDU. How do I find where to go?",
}

# Important dates: turn page headings into questions students actually ask.
DATES = {
    "Semester 1 (S1) 2026": ("dates-s1-2026", "When does Semester 1 2026 start, and what are the key dates?",
                             ["semester 1 2026 dates", "when does semester 1 start", "census date semester 1",
                              "when is week 1 of semester 1", "S1 2026 grade release"]),
    "Semester 2 (S2) 2026": ("dates-s2-2026", "When does Semester 2 2026 start, and what are the key dates?",
                             ["semester 2 2026 dates", "when does semester 2 start", "census date semester 2",
                              "when does this semester end", "S2 2026 exams and grade release"]),
    "Summer Semester (SS) 2026": ("dates-summer-2026", "What are the Summer Semester 2026 dates?",
                                  ["summer semester dates", "when does summer semester start",
                                   "summer school dates", "census date summer semester"]),
    "Higher Education Intensives 2026": None,  # heading only, details are in the six rows below
    "CDU TAFE dates": ("dates-tafe-2026", "What are the CDU TAFE term dates for 2026?",
                       ["TAFE term dates", "when does TAFE term start", "VET term dates"]),
    "Higher Education Semester dates": ("dates-2027", "What are the semester dates for 2027?",
                                        ["2027 semester dates", "when does semester 1 2027 start",
                                         "next year's semester dates", "when does next semester start"]),
    "Higher Education intensive dates": ("dates-intensives-2027", "What are the intensive teaching dates for 2027?",
                                         ["2027 intensive dates", "intensive units next year"]),
}


# ----------------------------------------------------------------- cleaning
URL = re.compile(r"\(?\s*(https?://[^\s)]+)\s*\)?")


def link_label(url: str) -> str:
    p = urlparse(url)
    host = p.netloc.replace("www.", "")
    seg = [s for s in p.path.split("/") if s and not re.fullmatch(r"\d+|files|\d{4}-\d{2}", s)]
    if host.endswith("cdu.edu.au") and host != "cdu.edu.au":
        name = host.split(".")[0]
        return {"ask": "Ask CDU", "libguides": "Library guide", "portal": "CDU Portal", "learnline": "Learnline",
                "mystudentinfo": "MyStudentInfo", "stapps": "Course Catalogue", "libanswers": "Library answers",
                "library": "CDU Library"}.get(name, name.capitalize())
    if seg:
        last = re.sub(r"\.(pdf|aspx?|html?)$", "", seg[-1], flags=re.I)
        last = re.sub(r"[-_]+", " ", last).strip()
        if last and not re.search(r"\d{3,}|[?=&]", last) and len(last) < 50:
            label = last[0].upper() + last[1:]
            return f"{label} (PDF)" if seg[-1].lower().endswith(".pdf") else label
    return host


def clean_answer(text: str) -> tuple[str, list[dict]]:
    text = str(text).replace("​", "").replace("\xa0", " ").replace("\r", "")
    links, seen = [], set()

    def grab(m):
        url = m.group(1).rstrip(".,;'\"")
        url = re.sub(r"^http://", "https://", url)
        if "doi.org" in url:          # DOIs are content, not links
            return m.group(0)
        p = urlparse(url)
        useful = p.path.strip("/") and "phonedirectory" not in p.netloc and "'" not in url
        if useful and url not in seen and len(links) < 2:
            seen.add(url)
            links.append({"label": link_label(url), "url": url})
        return ""

    text = URL.sub(grab, text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([,.;:])", r"\1", text)
    lines = [l.strip() for l in text.split("\n")]
    lines = [l for l in lines if l and l not in {":", "-", "."}]
    lines = [re.sub(r"^Step (\d+)\s*[:.-]\s*", r"\1. ", l) for l in lines]  # numbered list in chat
    # Date tables: "July" / "Monday 20, Teaching starts" -> "- Monday 20 July: Teaching starts"
    month, dated = None, []
    for l in lines:
        if re.fullmatch(r"(January|February|March|April|May|June|July|August|September|October|November|December)", l):
            month = l; continue
        d = re.match(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) (\d+), (.+)", l)
        dated.append(f"- **{d.group(1)} {d.group(2)} {month}**: {d.group(3)}" if d and month else l)
    lines = dated
    # Bullets: short lines after a lead-in become a list
    out, total, cut = [], 0, False
    for l in lines:
        if total + len(l) > MAX_ANSWER and out:
            cut = True
            break
        out.append(l)
        total += len(l)
    if not out:
        return "", links
    body = "\n".join(out)
    if cut:
        body += "\n\n" + ("There's more detail on the page below." if links
                          else "Ask the Library or Student Central for the full details.")
    return body, links


def slug(text: str, n: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    words = [w for w in words if w not in {"how", "do", "i", "can", "the", "a", "an", "is", "my", "to", "what", "where", "are", "of", "in", "for", "and", "or"}]
    return "-".join(words[:n]) or "item"


def as_question(q: str) -> str:
    q = re.sub(r"\s+", " ", str(q)).strip().rstrip(".")
    return q


# ----------------------------------------------------------------- build
def build(include_course: bool) -> None:
    curated = json.loads(CURATED.read_text(encoding="utf-8"))
    sheets = pd.read_excel(RAW, sheet_name=None)
    report = {"kept": [], "skipped": [], "merged_into_curated": []}
    new: list[dict] = []

    def skip(row, reason):
        report["skipped"].append({"source": row["source"], "question": as_question(row["question"]), "reason": reason})

    def add(row, faq_id, question, alternatives, category, level="university", answer=None):
        ans, links = clean_answer(row["answer"] if answer is None else answer)
        if len(ans) < 25:
            return skip(row, "answer too short or empty")
        page = re.sub(r"^http://", "https://", str(row.get("url") or ""))
        if page.startswith("http") and page not in {l["url"] for l in links}:
            label = "Full answer" if "libanswers" in page else link_label(page)
            links.insert(0, {"label": label, "url": page})  # the source page first: it has the full answer
        new.append({"id": faq_id, "category": category, "level": level, "question": question,
                    "alternatives": alternatives, "answer": ans, "links": links,
                    "source": {"doc": row["_doc"], "page": None, "url": page or None},
                    "approved": True, "review_flag": None})
        report["kept"].append({"id": faq_id, "source": row["source"], "question": question})

    # LibAnswers (Library and Student Central)
    lib = sheets["LibAnswers"].assign(_doc="LIBANSWERS")
    for _, r in lib.iterrows():
        q = as_question(r["question"])
        why = next((k for k, starts in EXCLUDE.items() if any(q.startswith(s) for s in starts)), None)
        sec = str(r["section"]).split(";")[0].strip()
        if r["type"] != "Q&A":
            skip(r, "question only, no answer"); continue
        if why or sec == "Staff Information":
            skip(r, f"out of first-year scope ({why or 'staff'})"); continue
        cat = CATEGORY.get(sec, "Library")
        if sec == "Directional" and ADMIN_WORDS.search(q):
            cat = "Enrolment and study plans"
        kw = [k.strip() for k in str(r.get("keywords") or "").split(";") if k.strip() and k.strip().lower() != "nan"]
        alts = []
        if kw:
            alts.append(" ".join(kw))  # one combined keyword phrase, not one per keyword
        question = REWRITE.get(q, q)
        if question != q and q not in VAGUE_HEADINGS:
            alts.append(q)
        add(r, f"lib-{slug(question)}", question, alts, cat)

    # Website pages
    web = sheets["Website_FAQ"].assign(_doc="WEBSITE")
    for _, r in web.iterrows():
        src, q = r["source"], as_question(r["question"])
        if src.startswith("CDU Menzies Medical Program") or src.startswith("Master of IT"):
            if not include_course:
                skip(r, "course-level page for prospective applicants (use --include-course-level)"); continue
            add(r, f"course-{slug(q)}", q, [], "Course information", level="course"); continue
        if src == "Important dates 2026":
            if str(r["section"]) in ("Archived dates", "Higher Degree by Research (HDR)", "nan", "CDU Menzies Medical Program (CMMP)") \
                    or q in ("Higher Education", "Ask CDU", "Higher Degree by Research (HDR)"):
                skip(r, "archived, research-degree or heading-only dates"); continue
            if q.startswith("HE Intensive"):
                n = q.split()[-1]
                add(r, f"dates-intensive-{n}-2026", f"What are the dates for Higher Education Intensive {n} in 2026?",
                    [f"intensive {n} dates", f"HE intensive {n}", "intensive unit census date"], "Key dates"); continue
            spec = DATES.get(q)
            if not spec:
                skip(r, "heading-only dates"); continue
            add(r, spec[0], spec[1], spec[2], "Key dates"); continue
        if src == "Grade release and results FAQ":
            if q == "Example of GPA calculation":
                skip(r, "worked example, merged into the GPA answer"); continue
            if q.startswith("I have just checked my results"):
                add(r, "results-grade-codes", "What do grades like NA, AC or WW on my results mean?",
                    ["my result says NA", "what does AC grade mean", "grade codes on my transcript",
                     "unit graded NA", q], "Results and grades"); continue
            add(r, f"results-{slug(q)}", q, [], "Results and grades"); continue
        if src == "Top 3 FAQs for future students":
            if r["type"] != "Q&A":
                skip(r, "contact block, already covered"); continue
            add(r, f"future-{slug(q)}", re.sub(r"^\d+\.\s*", "", q), [], "Thinking about studying"); continue
        skip(r, "not student-facing")

    # StudyStays accommodation (student rows only)
    acc = sheets["Accommodation_FAQ"].assign(_doc="STUDYSTAYS")
    for _, r in acc.iterrows():
        if str(r["section"]).strip() != "Students":
            skip(r, "for landlords and providers, not students"); continue
        q = as_question(r["question"])
        add(r, f"housing-{slug(q)}", q, ["off campus accommodation", "studystays"], "Accommodation")

    # ---- de-duplicate: within the import, then against the curated entries
    uniq, seen_q, ids = [], set(), {f["id"] for f in curated["faqs"]}
    for f in new:
        key = re.sub(r"[^a-z0-9]", "", f["question"].lower())
        if key in seen_q:
            report["skipped"].append({"source": f["source"]["doc"], "question": f["question"], "reason": "duplicate question"})
            continue
        seen_q.add(key)
        base, i = f["id"], 2
        while f["id"] in ids:
            f["id"] = f"{base}-{i}"; i += 1
        ids.add(f["id"])
        uniq.append(f)

    m = FAQMatcher(CURATED)
    by_id = {f["id"]: f for f in curated["faqs"]}
    final_new = []
    for f in uniq:
        res = m.match(f["question"])
        keep_apart = f["question"] in NOT_DUPLICATE or any(a in NOT_DUPLICATE for a in f["alternatives"])
        if res.top.score >= DUP_SCORE and not keep_apart:
            target = by_id[res.top.faq["id"]]
            alts = target.setdefault("alternatives", [])
            if f["question"] not in alts:
                alts.append(f["question"])
            report["merged_into_curated"].append({"imported": f["question"], "curated_id": target["id"],
                                                  "curated_question": target["question"], "score": round(res.top.score, 3)})
            continue
        final_new.append(f)

    kb = {"meta": {**curated["meta"], "kb_version": "2.0.0", "prepared": "2026-10-03",
                   "notes": curated["meta"]["notes"] + " v2 adds official Library, Student Central, results, "
                            "key dates and StudyStays FAQs collected 29 Sep 2026, cleaned and trimmed for chat."},
          "sources": {**curated["sources"],
                      "LIBANSWERS": {"title": "CDU LibAnswers (Library and Student Central)", "version": "Collected 29 Sep 2026",
                                     "owner": "CDU Library / Student Central", "type": "Public, official"},
                      "WEBSITE": {"title": "CDU website (important dates, results FAQ, future students)",
                                  "version": "Collected 29 Sep 2026", "owner": "CDU", "type": "Public, official"},
                      "STUDYSTAYS": {"title": "CDU StudyStays accommodation FAQ", "version": "Collected 29 Sep 2026",
                                     "owner": "CDU Accommodation", "type": "Public, official"}},
          "faqs": curated["faqs"] + final_new}
    drafts = json.loads(QA_DRAFTS.read_text(encoding="utf-8"))["faqs"]
    kb["faqs"] += drafts
    kb["sources"]["QACORNER"] = {"title": "Team draft from New Student Q&A Corner staff replies",
                                 "version": "Draft, pending staff approval", "owner": "Project team",
                                 "type": "Placeholder, not yet approved"}
    OUT.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["kept"] = [k for k in report["kept"] if k["id"] in {f["id"] for f in final_new}]
    report["summary"] = {"curated": len(curated["faqs"]), "imported": len(final_new), "qa_corner_drafts": len(drafts),
                         "merged_into_curated": len(report["merged_into_curated"]),
                         "skipped": len(report["skipped"]), "total": len(kb["faqs"])}
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-course-level", action="store_true")
    build(ap.parse_args().include_course_level)
