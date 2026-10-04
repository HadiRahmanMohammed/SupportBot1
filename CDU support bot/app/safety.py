"""Guardrails that run before FAQ matching.

1. Crisis language       -> immediate safety resources (never routed to an FAQ).
2. Personal-record asks  -> defer to a human; the bot cannot see student records.
3. Academic integrity    -> "write my essay for me" is declined, with pointers to real help.
4. Small talk            -> short friendly reply, no FAQ lookup.
5. PII detection/masking -> personal details are masked before anything is logged.
"""
from __future__ import annotations

import re

STUDENT_CENTRAL = {
    "phone": "1800 061 963",
    "email": "student.central@cdu.edu.au",
    "in_person": "Student Central (Orange 1, Casuarina) or the support staff in the Library Foyer",
}

# --------------------------------------------------------------------- crisis
_CRISIS = re.compile(
    r"\b(suicid\w*|kill(ing)? my ?self|end(ing)? (my|it) (life|all)|want to die|"
    r"don'?t want to (live|be alive|be here)|self[\s-]?harm\w*|hurt(ing)? my ?self|cut(ting)? my ?self|"
    r"no reason to live|being (abused|assaulted|attacked)|someone (is )?(hurting|threatening) me|"
    r"i('m| am) (not safe|in danger))\b",
    re.I,
)

CRISIS_REPLY = (
    "I'm really sorry you're going through this. You deserve support from a real person right now.\n\n"
    "- **If you're in immediate danger, call 000.**\n"
    "- **Lifeline:** 13 11 14 (24/7, free and confidential)\n"
    "- **CDU Security (24/7):** +61 8 8946 6666\n"
    "- **CDU Counselling:** +61 8 8946 6288 or counselling@cdu.edu.au\n\n"
    "I'm an automated assistant and can't provide crisis support, but these people can, and they want to help."
)

# ------------------------------------------------------------ personal records
_PERSONAL = re.compile(
    r"\b(my|mine)\b.{0,25}\b(grades?|marks?|results?|gpa|wam|transcript|score|"
    r"balance|invoice|debt|refund|application( status)?|offer letter|"
    r"enrol(ment)? status|student record|account balance|visa status)\b"
    r"|\b(how much (do )?i owe|did i (pass|fail)|am i (enrolled|enroled)|what did i get|"
    r"change my enrol\w*|withdraw me|unenrol me|enrol me|check my (enrol\w*|fees?|account)|"
    r"why (was|is) my .{0,20}(rejected|declined|cancelled))\b",
    re.I,
)

PERSONAL_REPLY = (
    "That depends on your personal student record, which I can't see or change. "
    "I only give general information.\n\n"
    "**Student Central** can look into it for you:\n"
    f"- Phone: **{STUDENT_CENTRAL['phone']}**\n"
    f"- Email: **{STUDENT_CENTRAL['email']}**\n"
    f"- In person: {STUDENT_CENTRAL['in_person']}"
)

FALLBACK_REPLY = (
    "I'm not sure about that one, and I'd rather not guess. **Student Central** can help:\n"
    f"- Phone: **{STUDENT_CENTRAL['phone']}**\n"
    f"- Email: **{STUDENT_CENTRAL['email']}**\n"
    f"- In person: {STUDENT_CENTRAL['in_person']}\n\n"
    "You could also try rephrasing, or search **AskCDU** (ask.cdu.edu.au)."
)

# --------------------------------------------------------- academic integrity
# Only requests for someone else to do the work; "how do I write my essay?" is a normal question.
_INTEGRITY = re.compile(
    r"\b(can|could|would|will) (you|someone|anyone)( please)? (just )?(write|do|finish|complete)\b.{0,15}"
    r"\b(essay|assignment|assessment|report|homework|exam|quiz|reflection)s?\b"
    r"|\b(write|do|finish|complete)\b.{0,25}\b(essay|assignment|assessment|report|homework)s?\b.{0,12}\bfor me\b"
    r"|\b(give|send|tell) me (the )?(answers?|solutions?) (to|for)\b",
    re.I,
)

INTEGRITY_REPLY = (
    "I can't write or complete assessments for you. Handing in work that isn't your own breaks CDU's "
    "**academic integrity** rules. I can point you to help with doing it yourself:\n"
    "- **Writing and referencing:** ask me how to structure an essay or reference, or about free online tutoring\n"
    "- **Your lecturer** can explain what the task is asking\n"
    "- **Short on time?** Ask me how to get an assignment extension"
)

# ------------------------------------------------------------------ small talk
_GREETING = re.compile(r"^\s*(hi+|hello+|hey+|g'?day|good (morning|afternoon|evening)|yo|kia ora)\b[\s!.,]*$", re.I)
_THANKS = re.compile(r"^\s*(thanks?( you)?|thank u|ty|cheers|ta|awesome|great|perfect|ok(ay)?|cool)\b[\s!.,]*(so much|heaps|mate)?[\s!.,]*$", re.I)
_BYE = re.compile(r"^\s*(bye|goodbye|see ya|see you|cya)\b[\s!.,]*$", re.I)
_WHO = re.compile(r"\b(who|what) are you\b|\bare you (a )?(real|human|person|bot|ai|robot)\b", re.I)

SMALL_TALK = {
    "greeting": "Hi! I'm CDU First Year Student Support. Ask me about getting started, enrolment, IT and Wi-Fi, the Library, getting around campus, accommodation, transport, jobs, or support services.",
    "thanks": "You're welcome! Is there anything else I can help with?",
    "bye": "Good luck with your studies! Come back any time.",
    "integrity": INTEGRITY_REPLY,
    "who": "I'm an **AI assistant, not a person**. I can answer common questions and point you to the right people. I can't see your personal student record.",
}

# ------------------------------------------------------------------------- PII
_PII = [
    (re.compile(r"\b[sS]\d{6,7}\b"), "[STUDENT_ID]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(\+?61|0)[\s-]?\d(?:[\s-]?\d){7,9}(?!\d)"), "[PHONE]"),
    (re.compile(r"\b\d{9,}\b"), "[NUMBER]"),
]


def mask_pii(text: str) -> tuple[str, bool]:
    found = False
    for pat, token in _PII:
        text, n = pat.subn(token, text)
        found = found or n > 0
    return text, found


def strip_pii(text: str) -> str:
    """Remove personal details entirely before matching (mask tokens would add noise)."""
    for pat, _ in _PII:
        text = pat.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify(text: str) -> str | None:
    """Return a guardrail route name, or None to continue to FAQ matching."""
    if _CRISIS.search(text):
        return "crisis"
    if _INTEGRITY.search(text):
        return "integrity"
    if _PERSONAL.search(text):
        return "personal"
    if _GREETING.match(text):
        return "greeting"
    if _THANKS.match(text):
        return "thanks"
    if _BYE.match(text):
        return "bye"
    if _WHO.search(text):
        return "who"
    return None
