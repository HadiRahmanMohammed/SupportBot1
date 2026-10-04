"""Build a single-file version of CDU First Year Student Support that works without the server.

The trained Python index (TF-IDF vocabularies and IDF weights, guardrail patterns,
pre-generated speech text) is exported into the page, and app/static/engine.js
answers /api/* requests in the browser with the same logic as the Flask app.

Outputs:
  dist/cdu-student-support.html           complete page: open it in a browser or host it anywhere
  dist/cdu-student-support.artifact.html  same page without the outer <html>/<head> wrapper (for hosts
                                          that supply their own document skeleton)
  dist/kb.json                            the exported index (used by the parity test)

Usage:  python scripts/build_standalone.py
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import RELATED_MIN, FOLLOWUP_MIN, SUGGEST_MIN, create_app  # noqa: E402
from app import matcher as M  # noqa: E402
from app import safety as S  # noqa: E402
from app.voice import to_speech  # noqa: E402

DIST = ROOT / "dist"


def export_kb(app) -> dict:
    m = app.extensions["matcher"]
    word_idf = {t: float(m._word.idf_[i]) for t, i in m._word.vocabulary_.items()}
    char_idf = {t: float(m._char.idf_[i]) for t, i in m._char.vocabulary_.items()}
    replies = {"crisis": S.CRISIS_REPLY, "personal": S.PERSONAL_REPLY, "fallback": S.FALLBACK_REPLY, **S.SMALL_TALK}
    return {
        "params": {
            "answer_threshold": m.answer_threshold, "clarify_threshold": m.clarify_threshold,
            "word_weight": m.word_weight, "coverage_floor": M.COVERAGE_FLOOR, "location_bonus": M.LOCATION_BONUS,
            "min_segment_stems": M.MIN_SEGMENT_STEMS, "margin_min": M.MARGIN_MIN, "margin_ratio": M.MARGIN_RATIO, "question_start": M.QUESTION_START,
            "related_min": RELATED_MIN, "followup_min": FOLLOWUP_MIN, "suggest_min": SUGGEST_MIN,
        },
        "stop": sorted(M.STOP_WORDS),
        "location": sorted(M.LOCATION_WORDS),
        "suffixes": list(M._SUFFIXES),
        "synonyms": [[p.pattern, r] for p, r in M._SYN],
        "it_upper": M._IT_UPPER.pattern,
        "it_lower": M._IT_LOWER.pattern,
        "texts": m._texts,
        "owners": [int(o) for o in m._owners],
        "word_idf": word_idf,
        "char_idf": char_idf,
        "vocab": [sorted(v) for v in m._vocab],
        "faqs": [{"id": f["id"], "question": f["question"], "answer": f["answer"], "links": f.get("links", []),
                  "category": f["category"], "speech": to_speech(f["answer"])} for f in m.faqs],
        "safety": {
            "crisis": S._CRISIS.pattern, "personal": S._PERSONAL.pattern, "integrity": S._INTEGRITY.pattern, "greeting": S._GREETING.pattern,
            "thanks": S._THANKS.pattern, "bye": S._BYE.pattern, "who": S._WHO.pattern,
            "pii": [[p.pattern, tok] for p, tok in S._PII],
            "replies": replies,
            "speech": {k: to_speech(v, 200) for k, v in replies.items()},
        },
    }


def build() -> None:
    app = create_app({"LOG_INTERACTIONS": False})
    kb = export_kb(app)
    DIST.mkdir(exist_ok=True)
    kb_json = json.dumps(kb, separators=(",", ":"), ensure_ascii=False)
    (DIST / "kb.json").write_text(kb_json, encoding="utf-8")

    static = ROOT / "app" / "static"
    html = app.test_client().get("/").get_data(as_text=True)
    css = (static / "style.css").read_text(encoding="utf-8")
    engine = (static / "engine.js").read_text(encoding="utf-8")
    appjs = (static / "app.js").read_text(encoding="utf-8")
    icon = "data:image/svg+xml;base64," + base64.b64encode((static / "icon.svg").read_bytes()).decode()

    safe_kb = kb_json.replace("</", "<\\/")  # never let data close the <script>
    scripts = (f"<script>window.CDU_KB={safe_kb};</script>\n"
               f"<script>\n{engine}\n</script>\n<script>\n{appjs}\n</script>")
    html = re.sub(r'<link rel="stylesheet" href="/static/style\.css[^"]*">', lambda _: f"<style>\n{css}\n</style>", html)
    html = re.sub(r'<script src="/static/app\.js[^"]*"></script>', lambda _: scripts, html)
    html = html.replace("/static/icon.svg", icon)
    for photo in (static / "bg").glob("*.jpg"):
        uri = "data:image/jpeg;base64," + base64.b64encode(photo.read_bytes()).decode()
        html = html.replace(f"/static/bg/{photo.name}", uri)
    for logo in (static / "brand").glob("logo.*"):
        mime = {"svg": "image/svg+xml", "png": "image/png", "webp": "image/webp"}.get(logo.suffix[1:], "image/png")
        uri = f"data:{mime};base64," + base64.b64encode(logo.read_bytes()).decode()
        html = html.replace(f"/static/brand/{logo.name}", uri)
    html = re.sub(r'\s*<link rel="manifest"[^>]*>', "", html)
    html = re.sub(r'\s*<link rel="apple-touch-icon"[^>]*>', "", html)
    (DIST / "cdu-student-support.html").write_text(html, encoding="utf-8")

    # Body-only variant: title, fonts and styles first, then the page content.
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    keep = "\n".join(re.findall(r'<title>.*?</title>|<meta name="description"[^>]*>|<link rel="(?:preconnect|stylesheet)"[^>]*>|<style>.*?</style>', head, re.S))
    (DIST / "cdu-student-support.artifact.html").write_text(keep + "\n" + body.strip() + "\n", encoding="utf-8")

    size = (DIST / "cdu-student-support.html").stat().st_size
    print(f"Built dist/cdu-student-support.html ({size / 1024:.0f} KB, {len(kb['faqs'])} FAQs)")


if __name__ == "__main__":
    build()
