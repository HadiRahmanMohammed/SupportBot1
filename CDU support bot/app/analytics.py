"""Summarise the masked interaction log for the staff dashboard (/admin)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .matcher import STOP_WORDS, _word_tokens, normalise, stem

GROUP_SIMILARITY = 0.25  # questions at least this similar are treated as the same topic


def suggest_topics(questions: list[str], min_size: int = 2, limit: int = 8) -> list[dict]:
    """Group unanswered questions by topic so staff can see which new FAQs would help most.

    Questions are linked when their TF-IDF similarity is at least GROUP_SIMILARITY, and each
    connected group becomes one suggested topic, labelled with its most characteristic words.
    """
    qs = [q for q in dict.fromkeys(q.strip() for q in questions) if q]
    if len(qs) < min_size:
        return []
    texts = [normalise(q) for q in qs]
    vec = TfidfVectorizer(tokenizer=_word_tokens, token_pattern=None, lowercase=False)
    try:
        m = vec.fit_transform(texts)
    except ValueError:  # no usable words at all
        return []
    sim = cosine_similarity(m)
    parent = list(range(len(qs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(qs)):
        for j in range(i + 1, len(qs)):
            if sim[i, j] >= GROUP_SIMILARITY:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(qs)):
        groups.setdefault(find(i), []).append(i)
    terms = np.array(vec.get_feature_names_out())
    out = []
    for members in groups.values():
        if len(members) < min_size:
            continue
        weight = np.asarray(m[members].sum(axis=0)).ravel()
        # show real words ("attendance"), not the stems the matcher uses ("attendanc")
        words = Counter(w for i in members for w in texts[i].split() if w not in STOP_WORDS and len(w) > 2)
        def readable(term):
            forms = [(n, w) for w, n in words.items() if " ".join(stem(x) for x in w.split()) == term]
            return max(forms)[1] if forms else term
        label = ", ".join(readable(t) for t in terms[np.argsort(-weight)[:3]] if " " not in t)
        out.append({"topic": label, "count": len(members), "examples": [qs[i] for i in members[:3]]})
    out.sort(key=lambda g: -g["count"])
    return out[:limit]


def summarise(log_path: str | Path, faq_titles: dict[str, str], recent: int = 40) -> dict:
    path = Path(log_path)
    events = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    questions = [e for e in events if e.get("route") != "feedback"]
    feedback = [e for e in events if e.get("route") == "feedback"]
    routes = Counter(e.get("route") for e in questions)
    total = len(questions)

    top = Counter(e["faq"] for e in questions if e.get("route") == "answer" and e.get("faq"))
    unhelpful = Counter(e["faq"] for e in feedback if e.get("helpful") is False)
    helpful_n = sum(1 for e in feedback if e.get("helpful") is True)
    all_gaps = [e for e in questions if e.get("route") in ("fallback", "clarify")]
    gaps = all_gaps[-recent:][::-1]
    channels = Counter(e.get("channel", "text") for e in questions)

    def pct(n):
        return round(100 * n / total, 1) if total else 0.0

    return {
        "total": total,
        "answered_pct": pct(routes.get("answer", 0)),
        "clarify_pct": pct(routes.get("clarify", 0)),
        "fallback_pct": pct(routes.get("fallback", 0)),
        "handoff": routes.get("personal", 0),
        "crisis": routes.get("crisis", 0),
        "voice": channels.get("voice", 0),
        "feedback_total": len(feedback),
        "helpful_pct": round(100 * helpful_n / len(feedback), 1) if feedback else None,
        "top": [{"id": k, "question": faq_titles.get(k, k), "count": v} for k, v in top.most_common(10)],
        "unhelpful": [{"id": k, "question": faq_titles.get(k, k), "count": v} for k, v in unhelpful.most_common(10)],
        "gaps": [{"q": e.get("q", ""), "route": e.get("route"), "best": faq_titles.get(e.get("faq"), ""),
                  "score": e.get("score"), "ts": e.get("ts", "")} for e in gaps],
        "suggested_topics": suggest_topics([e.get("q", "") for e in all_gaps]),
        "first_ts": events[0].get("ts") if events else None,
        "last_ts": events[-1].get("ts") if events else None,
    }
