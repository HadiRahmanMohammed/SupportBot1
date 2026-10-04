"""Framework-free chatbot logic shared by the Flask app and the Streamlit app.

`Assistant.respond()` returns exactly the payload the Flask /api/chat route sends,
so both front ends behave identically.
"""
from __future__ import annotations

from pathlib import Path

from . import safety
from .matcher import FAQMatcher, Result
from .voice import to_speech

RELATED_MIN = 0.45   # minimum score to suggest a related question
FOLLOWUP_MIN = 0.12  # follow-up must overlap the context FAQ on its own
SUGGEST_MIN = 0.22   # minimum score for an as-you-type suggestion
MAX_LEN = 500
PII_NOTE = ("For your privacy, there's no need to share student numbers, emails or phone numbers here. "
            "I've ignored them.")


class Assistant:
    def __init__(self, kb_path: str | Path, answer_threshold: float = 0.45,
                 clarify_threshold: float = 0.24, include_unapproved: bool = True):
        self.matcher = FAQMatcher(kb_path, answer_threshold, clarify_threshold,
                                  include_unapproved=include_unapproved)

    # ----------------------------------------------------------- payloads
    def source_label(self, faq: dict) -> dict:
        src = self.matcher.sources.get(faq["source"]["doc"], {})
        return {"title": src.get("title", faq["source"]["doc"]), "version": src.get("version"),
                "page": faq["source"].get("page"), "approved": bool(faq.get("approved"))}

    def faq_payload(self, faq: dict, score: float | None = None, staff: bool = False) -> dict:
        payload = {"id": faq["id"], "question": faq["question"], "answer": faq["answer"],
                   "links": faq.get("links", []), "category": faq["category"],
                   "speech": to_speech(faq["answer"])}
        # Sources, review notes and match scores are for staff only, never shown to students.
        if staff:
            payload["staff"] = {"source": self.source_label(faq), "review_flag": faq.get("review_flag"),
                                "score": round(score, 3) if score is not None else None}
        return payload

    def faq(self, faq_id: str, staff: bool = False) -> dict | None:
        f = self.matcher.by_id.get(faq_id)
        return {"type": "answer", "faq": self.faq_payload(f, staff=staff)} if f else None

    def topics(self) -> list[dict]:
        cats: dict[str, list] = {}
        for f in self.matcher.faqs:
            cats.setdefault(f["category"], []).append({"id": f["id"], "question": f["question"]})
        return [{"category": c, "questions": q} for c, q in cats.items()]

    # ----------------------------------------------------------- chat
    def respond(self, text: str, previous: str = "", staff: bool = False) -> tuple[dict, dict | None]:
        """Return (response payload, log event or None). Text must be non-empty."""
        text = text.strip()[:MAX_LEN]
        previous = previous.strip()[:MAX_LEN]
        masked, had_pii = safety.mask_pii(text)
        pii_note = PII_NOTE if had_pii else None

        route = safety.classify(text)
        if route == "crisis":
            return ({"type": "crisis", "message": safety.CRISIS_REPLY,
                     "speech": to_speech(safety.CRISIS_REPLY, 200), "pii_note": pii_note},
                    {"q": masked, "route": "crisis"})
        if route == "personal":
            return ({"type": "handoff", "message": safety.PERSONAL_REPLY,
                     "speech": to_speech(safety.PERSONAL_REPLY, 200), "pii_note": pii_note},
                    {"q": masked, "route": "personal"})
        if route in safety.SMALL_TALK:
            msg = safety.SMALL_TALK[route]
            return {"type": "smalltalk", "message": msg, "speech": to_speech(msg, 200), "pii_note": pii_note}, None

        m = self.matcher
        query = safety.strip_pii(text)
        result = m.match(query)
        # Short follow-ups ("what about Danala?") borrow context from the previous question,
        # but only if the follow-up itself relates to the FAQ that context points to.
        # The first context candidate the follow-up relates to wins, so "what about Danala?" after
        # a general food question moves to the Danala food answer.
        if result.band != "answer" and previous and len(query.split()) <= 5:
            ctx = m.match(f"{safety.strip_pii(previous)} {query}")
            own = m.final_scores(query)
            for c in ctx.candidates:
                if c.score >= m.answer_threshold and own[m.faqs.index(c.faq)] >= FOLLOWUP_MIN:
                    result = Result("answer", c, [c, *(x for x in ctx.candidates if x is not c)])
                    break

        event = {"q": masked, "route": result.band,
                 "faq": result.top.faq["id"] if result.top else None,
                 "score": round(result.top.score, 3) if result.top else None}

        if result.band == "answer":
            related = [{"id": c.faq["id"], "question": c.faq["question"]}
                       for c in result.candidates[1:] if c.score >= RELATED_MIN]
            return ({"type": "answer", "faq": self.faq_payload(result.top.faq, result.top.score, staff),
                     "related": related[:2], "pii_note": pii_note}, event)
        if result.band == "clarify":
            options = [{"id": c.faq["id"], "question": c.faq["question"]} for c in result.candidates]
            spoken = "I'm not completely sure what you mean. Did you mean: " + "; ".join(
                f"{n}, {o['question'].rstrip('?')}" for n, o in zip(("one", "two", "three"), options)
            ) + ". Say the number, or say none of these."
            return ({"type": "clarify", "message": "I'm not completely sure what you mean. Did you mean one of these?",
                     "options": options, "speech": spoken,
                     "fallback": safety.FALLBACK_REPLY, "fallback_speech": to_speech(safety.FALLBACK_REPLY, 200),
                     "pii_note": pii_note}, event)
        return ({"type": "fallback", "message": safety.FALLBACK_REPLY,
                 "speech": to_speech(safety.FALLBACK_REPLY, 200), "pii_note": pii_note}, event)

    def suggest(self, q: str) -> list[dict]:
        q = q.strip()[:MAX_LEN]
        if len(q) < 3 or safety.classify(q) in ("crisis", "personal"):
            return []
        result = self.matcher.match(safety.strip_pii(q), k=5)
        if not result.candidates:
            return []
        # only show options close to the best one, so weak matches don't crowd the list
        floor = max(SUGGEST_MIN, result.candidates[0].score * 0.6)
        return [{"id": c.faq["id"], "question": c.faq["question"]}
                for c in result.candidates if c.score >= floor][:4]
