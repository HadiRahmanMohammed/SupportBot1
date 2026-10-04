"""FAQ matching engine.

Retrieval-only: the bot can only ever return an answer that exists in the
knowledge base. Each FAQ is indexed by its question plus alternative phrasings.
An incoming question is scored against every phrasing with two TF-IDF models
(word n-grams for meaning, character n-grams for typos and word variants), and
the best score per FAQ decides the match.

Scores fall into three bands:
  * answer   - confident enough to return the approved answer
  * clarify  - plausible, so offer the top candidates as "Did you mean...?"
  * fallback - not confident, so defer to Student Central (never guess)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Words that matter in this domain but sit in sklearn's default stop list.
_KEEP = {"call", "find", "first", "full", "fill", "back", "move", "part", "system", "bill"}
STOP_WORDS = frozenset(ENGLISH_STOP_WORDS - _KEEP) | {
    "cdu", "charles", "darwin", "university", "uni", "please", "hi", "hello",
    "want", "need", "know", "tell", "help", "question", "just", "like", "ok",
    "near", "nearby", "close", "around", "today", "tomorrow", "really", "get", "got",
}

# Normalise common spellings and student shorthand before matching.
SYNONYMS = [
    (r"\bwi[\s-]?fi\b", "wifi"),
    (r"\binternet\b", "wifi"),
    (r"\benrol+(ment|ing|ed|s)?\b", "enrol"),
    (r"\b(sign(ing)? up|register(ing)?|signup) (for|in|to)\b", "enrol in"),
    (r"\bwon't\b", "will not"),
    (r"\bcan't\b", "can not"),
    (r"n't\b", " not"),
    (r"'(s|re|m|ve|ll|d)\b", ""),
    (r"\bmulti[\s-]?factor\b", "mfa"),
    (r"\b(2fa|two[\s-]?factor)\b", "mfa"),
    (r"\bid card\b", "student card"),
    (r"\b(timetables?|schedule)\b", "timetable"),
    (r"\b(licen[cs]e)\b", "licence"),
    (r"\b(cv|resumes?)\b", "resume"),
    (r"\b(toilets?|restrooms?|washrooms?)\b", "bathroom"),
    (r"\b(cafe|café|canteen)\b", "cafe"),
    (r"\b(housing|rent|renting|room to rent)\b", "accommodation"),
    (r"\b(lecturer|teacher)\b", "lecturer"),
    (r"\b(assignment|assessment)s?\b", "assessment"),
    (r"\b(scholarship)s?\b", "scholarship"),
    (r"\bgms\b", "global merit scholarship"),
    (r"\bcoe\b", "confirmation enrolment coe"),
    (r"\bintl\b", "international"),
    (r"\bsem\b", "semester"),
    (r"\bpwd\b", "password"),
    (r"\bsubjects?\b", "unit"),  # students say "subject", CDU says "unit"
    (r"\b(sim(ulation)?[\s-]?blocks?|simblocks?)\b", "simblock"),
    (r"\b(red|orange|blue|green|purple|yellow|pink)\s?\d+\.\d+\.\d+\b", "room code building"),
]
_SYN = [(re.compile(p, re.I), r) for p, r in SYNONYMS]


LOCATION_WORDS = {"casuarina", "danala", "palmerston", "alice", "springs", "campus",
                  "campuses", "nt", "territory", "australia", "darwin", "city"}
LOCATION_BONUS = 0.2
COVERAGE_FLOOR = 0.45  # weight kept when none of the query's content words are in the FAQ

_SUFFIXES = ("ing", "ed", "es", "s", "ly", "e")


def stem(word: str) -> str:
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def _word_tokens(text: str) -> list[str]:
    """Tokenise already-normalised text: drop stop words, light stemming."""
    toks = (w.strip(".'-") for w in re.findall(r"[a-z0-9][a-z0-9'.-]*", text))
    return [stem(w) for w in toks if len(w) > 1 and w not in STOP_WORDS]


def content_stems(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9][a-z0-9'.-]*", normalise(text)):
        w = w.strip(".'-")
        if len(w) > 1 and w not in STOP_WORDS and w not in LOCATION_WORDS:
            out.add(stem(w))
    return out

# A clear winner is answered even below the answer threshold: it must score at least MARGIN_MIN
# and be MARGIN_RATIO times the runner-up (chosen on the dev half and the hand-written set).
MARGIN_MIN = 0.35
MARGIN_RATIO = 2.5
MIN_SEGMENT_STEMS = 3  # a sentence needs this many content words to be scored on its own
_SENTENCE_END = re.compile(r"([.?!])\s+")
# Only sentences that ask something are scored alone; background ("I study nursing online.") is not.
QUESTION_START = (r"^(how|what|what's|where|when|who|which|why|can|could|do|does|is|are|will|should|would|am|any|"
                  r"i can't|i cannot|i'm unable|i am unable|i'm having trouble|i am having trouble)\b")
_QUESTION_START = re.compile(QUESTION_START, re.I)


def segments(text: str) -> list[str]:
    """Question sentences of a multi-sentence message that carry enough content to score alone."""
    parts = [p.strip() for p in _SENTENCE_END.sub(r"\1\n", text).split("\n") if p.strip()]
    if len(parts) < 2:
        return []
    return [p for p in parts if (p.endswith("?") or _QUESTION_START.search(p))
            and len(content_stems(p)) >= MIN_SEGMENT_STEMS]


_IT_UPPER = re.compile(r"\bIT\b")
_IT_LOWER = re.compile(r"\bit (support|help|desk|team|staff|questions?|problems?|issues?|access|set ?up)\b")


def normalise(text: str) -> str:
    text = _IT_UPPER.sub("itms", text)  # "IT" would otherwise vanish as a stop word
    text = text.lower().replace("’", "'")
    text = _IT_LOWER.sub(r"itms \1", text)
    for pat, rep in _SYN:
        text = pat.sub(rep, text)
    text = re.sub(r"[^a-z0-9@.'\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Match:
    faq: dict
    score: float


@dataclass
class Result:
    band: str  # "answer" | "clarify" | "fallback"
    top: Match | None
    candidates: list[Match] = field(default_factory=list)


class FAQMatcher:
    def __init__(self, kb_path: str | Path, answer_threshold: float = 0.45,
                 clarify_threshold: float = 0.24, word_weight: float = 0.6,
                 include_unapproved: bool = True):
        self.kb_path = Path(kb_path)
        self.answer_threshold = answer_threshold
        self.clarify_threshold = clarify_threshold
        self.word_weight = word_weight
        self.include_unapproved = include_unapproved
        self._load()

    # ------------------------------------------------------------------ build
    def _load(self) -> None:
        kb = json.loads(self.kb_path.read_text(encoding="utf-8"))
        self.meta = kb.get("meta", {})
        self.sources = kb.get("sources", {})
        self.faqs: list[dict] = [f for f in kb["faqs"]
                                 if self.include_unapproved or f.get("approved")]
        self.by_id = {f["id"]: f for f in self.faqs}
        if len(self.by_id) != len(self.faqs):
            raise ValueError("Duplicate FAQ ids in knowledge base")

        texts, owners = [], []
        for i, f in enumerate(self.faqs):
            phrases = [f["question"], *f.get("alternatives", [])]
            # each phrasing on its own, plus all phrasings together (helps longer questions)
            for phrase in [*phrases, " ".join(phrases)]:
                texts.append(normalise(phrase))
                owners.append(i)
        self._owners = np.array(owners)
        self._texts = texts  # kept so the index can be exported to the standalone page
        # Vocabulary each FAQ "knows about", used to penalise matches that hinge on
        # one shared word while the rest of the question is about something else.
        self._vocab = []
        for f in self.faqs:
            blob = " ".join([f["question"], *f.get("alternatives", []), f["answer"], f["category"],
                             *(l["label"] for l in f.get("links", []))])
            self._vocab.append(content_stems(blob))

        self._word = TfidfVectorizer(ngram_range=(1, 2), tokenizer=_word_tokens, token_pattern=None,
                                     lowercase=False, sublinear_tf=True)
        self._char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self._word_m = self._word.fit_transform(texts)
        self._char_m = self._char.fit_transform([self._strip_stop(t) for t in texts])

    @staticmethod
    def _strip_stop(text: str) -> str:
        return " ".join(w for w in text.split() if w not in STOP_WORDS) or text

    # ------------------------------------------------------------------ query
    def scores(self, query: str) -> np.ndarray:
        """Best combined similarity per FAQ (array aligned with self.faqs)."""
        q = normalise(query)
        w = cosine_similarity(self._word.transform([q]), self._word_m)[0]
        c = cosine_similarity(self._char.transform([self._strip_stop(q)]), self._char_m)[0]
        if not _word_tokens(q):
            combined = c * 0.7  # no meaningful words: trust char overlap less
        else:
            combined = self.word_weight * w + (1 - self.word_weight) * c
        best = np.zeros(len(self.faqs))
        np.maximum.at(best, self._owners, combined)
        return best

    def final_scores(self, query: str) -> np.ndarray:
        """Scores with place names limited to a small bonus.

        Place names are rare (high-IDF) words, so "pizza near Casuarina" could match
        any Casuarina FAQ. The score is driven by the rest of the question, and the
        place name can add at most LOCATION_BONUS on top.
        """
        s = self.scores(query)
        words = normalise(query).split()
        core = [w for w in words if w.strip("?.!,'") not in LOCATION_WORDS]
        if len(core) == len(words):
            return s
        s_core = self.scores(" ".join(core)) if core else np.zeros_like(s)
        return np.maximum(s_core, np.minimum(s, s_core + LOCATION_BONUS))

    def coverage(self, query: str) -> np.ndarray:
        """Share of the query's content words that each FAQ's text covers (0..1)."""
        q = content_stems(query)
        if not q:
            return np.ones(len(self.faqs))
        return np.array([len(q & v) / len(q) for v in self._vocab])

    def _adjusted(self, text: str) -> np.ndarray:
        return self.final_scores(text) * (COVERAGE_FLOOR + (1 - COVERAGE_FLOOR) * self.coverage(text))

    def match(self, query: str, k: int = 3) -> Result:
        # Long messages ("Hi, I'm new and study nursing online. Are lectures recorded?") dilute the
        # real question, so each sentence is also scored on its own and the best score is kept.
        s = self._adjusted(query)
        for seg in segments(query):
            s = np.maximum(s, self._adjusted(seg))
        order = np.argsort(-s)[:k]
        cands = [Match(self.faqs[i], float(s[i])) for i in order]
        top = cands[0]
        runner_up = cands[1].score if len(cands) > 1 else 0.0
        clear_winner = top.score >= MARGIN_MIN and top.score >= MARGIN_RATIO * runner_up
        if top.score >= self.answer_threshold or clear_winner:
            return Result("answer", top, cands)
        if top.score >= self.clarify_threshold:
            return Result("clarify", top, [c for c in cands if c.score >= self.clarify_threshold])
        return Result("fallback", top, cands)
