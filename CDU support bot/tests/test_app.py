import json
import re
from pathlib import Path

import pytest

from app import create_app
from app.safety import classify, mask_pii, strip_pii

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path):
    app = create_app({"RATE_LIMIT_PER_MIN": 1000, "LOG_INTERACTIONS": True,
                      "LOG_PATH": str(tmp_path / "log.jsonl")})
    app.testing = True
    return app.test_client()


def ask(client, msg, previous=""):
    return client.post("/api/chat", json={"message": msg, "previous": previous}).get_json()


# ------------------------------------------------------------ knowledge base
def test_kb_integrity():
    kb = json.loads((ROOT / "data" / "faqs.json").read_text())
    ids = [f["id"] for f in kb["faqs"]]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for f in kb["faqs"]:
        assert f["source"]["doc"] in kb["sources"], f["id"]
        assert f["level"] in {"university", "unit", "course"}
        assert f["answer"].strip() and f["question"].strip()
        for link in f.get("links", []):
            assert link["url"].startswith("https://"), f["id"]
        if not f["approved"]:
            assert f["review_flag"], "unapproved entries must explain why"


def test_imported_answers_are_clean():
    """Imported answers carry no raw URLs, student names or @-mentions, and stay chat-sized."""
    kb = json.loads((ROOT / "data" / "faqs.json").read_text())
    for f in kb["faqs"]:
        if f["source"]["doc"] in {"WCFAQ", "TEAM"}:
            continue
        assert not re.search(r"(^|\s)@\w", f["answer"]), f["id"]  # @-mentions of students
        assert "http://" not in f["answer"] and "https://" not in f["answer"].replace("https://doi.org", ""), f["id"]
        assert len(f["answer"]) < 1000, f["id"]
        assert "Landlords" not in f["category"]


def test_real_eval_questions_not_in_kb():
    """Real Q&A Corner questions are a held-out test: none may be indexed as a phrasing."""
    kb = json.loads((ROOT / "data" / "faqs.json").read_text())
    indexed = {p.lower().strip() for f in kb["faqs"] for p in [f["question"], *f["alternatives"]]}
    real = json.loads((ROOT / "data" / "real_eval.json").read_text())["items"]
    ids = {f["id"] for f in kb["faqs"]}
    for i in real:
        assert i["question"].lower().strip() not in indexed, i["qid"]
        assert set(i["accept"]) <= ids, i["qid"]


def test_eval_questions_not_in_kb():
    """Held-out questions must not leak into the indexed phrasings."""
    kb = json.loads((ROOT / "data" / "faqs.json").read_text())
    ev = json.loads((ROOT / "data" / "eval_set.json").read_text())
    indexed = {p.lower().strip() for f in kb["faqs"] for p in [f["question"], *f["alternatives"]]}
    for q, _ in ev["in_scope"]:
        assert q.lower().strip() not in indexed, q


# ------------------------------------------------------------------ matching
def test_long_question_finds_the_question_sentence(client):
    msg = ("Hi there, I'm a new student and studying nursing online. I enrolled yesterday and set up my account. "
           "Where do I find InPlace to book my sim block?")
    r = ask(client, msg)
    assert r["type"] == "answer" and r["faq"]["id"] == "placements-inplace"


def test_background_sentences_are_not_scored_alone():
    from app.matcher import segments
    assert segments("I study externally from Tasmania. Are lectures recorded for later?") == ["Are lectures recorded for later?"]
    assert segments("Where is the library?") == []  # single sentence: nothing extra to score

@pytest.mark.parametrize("q,expected", [
    ("how do I connect to wifi", "wifi"),
    ("Where do I get my ID card?", "student-card"),
    ("how to enrol", "enrolling-help"),
    ("IT help", "it-help"),
    ("what does Blue 5.1.24 mean", "room-codes"),
    ("I have nowhere to sleep tonight", "emergency-accommodation"),
    ("where are the toilets at Danala", "danala-bathroom"),
])
def test_answers(client, q, expected):
    r = ask(client, q)
    assert r["type"] == "answer"
    assert r["faq"]["id"] == expected
    assert "staff" not in r["faq"], "sources must not reach students"


@pytest.mark.parametrize("q", ["what is the capital of France", "how do I cook rice",
                               "what's the weather tomorrow", "pizza near casuarina"])
def test_out_of_scope_never_answers(client, q):
    assert ask(client, q)["type"] in {"fallback", "clarify"}


def test_fallback_mentions_student_central(client):
    r = ask(client, "what is the capital of France")
    assert "1800 061 963" in r["message"]


def test_followup_uses_context(client):
    r = ask(client, "what about danala?", previous="where can I get food")
    assert r["type"] == "answer" and r["faq"]["id"] == "danala-food"


def test_followup_ignores_unrelated_context(client):
    r = ask(client, "can i bring my dog", previous="where can I get food")
    assert r["type"] != "answer"


def test_unapproved_entries_are_labelled(client):
    r = ask(client, "where can I find recorded lectures")
    assert r["faq"]["id"] == "unit-recordings"
    assert "staff" not in r["faq"]
    app = create_app({"ADMIN_TOKEN": "t"})
    r = app.test_client().post("/api/chat", json={"message": "where can I find recorded lectures"},
                               headers={"X-Review-Token": "t"}).get_json()
    assert r["faq"]["staff"]["source"]["approved"] is False
    r = app.test_client().post("/api/chat", json={"message": "wifi"}, headers={"X-Review-Token": "wrong"}).get_json()
    assert "staff" not in r["faq"]


def test_hide_unapproved(tmp_path):
    app = create_app({"SHOW_UNAPPROVED": False})
    m = app.extensions["matcher"]
    assert all(f["approved"] for f in m.faqs)
    r = app.test_client().post("/api/chat", json={"message": "where can I find recorded lectures"}).get_json()
    assert r.get("faq", {}).get("id") != "unit-recordings"


# ---------------------------------------------------------------- guardrails
@pytest.mark.parametrize("q", ["I want to kill myself", "thinking about suicide",
                               "I keep hurting myself", "I am not safe"])
def test_crisis(client, q):
    r = ask(client, q)
    assert r["type"] == "crisis"
    assert "000" in r["message"] and "13 11 14" in r["message"]


@pytest.mark.parametrize("q", ["what are my grades", "did I pass", "how much do I owe",
                               "am I enrolled in PRT691", "what's my GPA", "withdraw me from a unit"])
def test_personal_handoff(client, q):
    assert ask(client, q)["type"] == "handoff"


@pytest.mark.parametrize("q,route", [("hi", "greeting"), ("thanks!", "thanks"), ("are you a real person?", "who")])
def test_small_talk(q, route):
    assert classify(q) == route


def test_pii_masked_and_not_logged(client, tmp_path):
    r = ask(client, "my student number is s385676 email me at a.b@gmail.com or 0412 345 678 about wifi")
    assert r["pii_note"]
    log = (tmp_path / "log.jsonl").read_text()
    assert "385676" not in log and "gmail" not in log and "0412" not in log


def test_mask_and_strip():
    masked, found = mask_pii("I'm S1234567, call +61 8 8946 6600")
    assert found and "[STUDENT_ID]" in masked and "[PHONE]" in masked
    assert "1234567" not in strip_pii("I'm S1234567")


# ----------------------------------------------------------------------- API
def test_empty_and_long_input(client):
    assert client.post("/api/chat", json={"message": "  "}).status_code == 400
    r = client.post("/api/chat", json={"message": "wifi " * 500})
    assert r.status_code == 200


def test_bad_json(client):
    assert client.post("/api/chat", data="nope", content_type="text/plain").status_code == 400


def test_topics_and_faq(client):
    t = client.get("/api/topics").get_json()["topics"]
    assert any(c["category"] == "IT and Wi-Fi" for c in t)
    assert client.get("/api/faq/wifi").get_json()["faq"]["id"] == "wifi"
    assert client.get("/api/faq/nope").status_code == 404


def test_feedback(client):
    assert client.post("/api/feedback", json={"faq_id": "wifi", "helpful": True}).get_json()["ok"]
    assert client.post("/api/feedback", json={"faq_id": "x", "helpful": True}).status_code == 400


def test_rate_limit():
    c = create_app({"RATE_LIMIT_PER_MIN": 3}).test_client()
    codes = [c.post("/api/chat", json={"message": "wifi"}).status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[-1] == 429


def test_health_and_headers(client):
    r = client.get("/healthz")
    assert r.get_json()["status"] == "ok"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    page = client.get("/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "<title>CDU First Year Student Support</title>" in html and "student prototype" in html
    assert "FAQ" not in html and "Welcome Centre" not in html


def test_evaluation_floor():
    """Guard against regressions: fail if quality drops below agreed floors."""
    from scripts.evaluate import run
    r = run()
    assert r["resolved_rate"] >= 0.90
    assert r["wrong_rate"] <= 0.05
    assert r["oos_safe_rate"] >= 0.85
    assert r["personal_ok"] == r["personal_total"]
    assert r["crisis_ok"] == r["crisis_total"]


# ------------------------------------------------------------- voice / v2
from app.voice import to_speech  # noqa: E402


def test_speech_text_is_speakable():
    s = to_speech("Email **student.central@cdu.edu.au** or call **1800 061 963**.\n- Go to Blue 5.1.24")
    assert "**" not in s and "@" not in s
    assert "student dot central at C D U dot edu dot A U" in s
    assert "1 8 0 0, 0 6 1, 9 6 3" in s
    assert "Blue 5 dot 1 dot 24" in s


def test_speech_keeps_safety_lines_when_trimming():
    long = "\n".join(["- " + "word " * 30] * 4) + "\n\nIf you're in danger, call **000**."
    s = to_speech(long)
    assert "triple zero" in s and "more detail in the chat" in s


def test_every_response_has_speech(client):
    for q in ["wifi", "what are my grades", "I want to kill myself", "hi", "capital of France", "IT help at casuarina"]:
        r = ask(client, q)
        speech = r["faq"]["speech"] if r["type"] == "answer" else r.get("speech")
        assert speech, q


def test_clarify_speech_lists_options(client):
    r = ask(client, "my student number is s385676 and I can't log into wifi")
    if r["type"] == "clarify":
        assert "Say the number" in r["speech"] and r["fallback_speech"]


def test_voice_channel_logged(client, tmp_path):
    client.post("/api/chat", json={"message": "wifi", "mode": "voice"})
    assert '"channel": "voice"' in (tmp_path / "log.jsonl").read_text()


def test_suggest(client):
    s = client.get("/api/suggest?q=eduroam").get_json()["suggestions"]
    assert s and s[0]["id"] == "wifi"
    assert client.get("/api/suggest?q=hi").get_json()["suggestions"] == []
    assert client.get("/api/suggest?q=what are my grades").get_json()["suggestions"] == []


def test_admin_off_without_token(client):
    assert client.get("/admin").status_code == 404


def test_admin_requires_token(tmp_path):
    import base64
    app = create_app({"ADMIN_TOKEN": "s3cret", "LOG_INTERACTIONS": True, "LOG_PATH": str(tmp_path / "l.jsonl")})
    c = app.test_client()
    c.post("/api/chat", json={"message": "what is the capital of France"})
    c.post("/api/chat", json={"message": "wifi"})
    assert c.get("/admin").status_code == 401
    bad = base64.b64encode(b"x:nope").decode()
    assert c.get("/admin", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"staff:s3cret").decode()
    page = c.get("/admin", headers={"Authorization": f"Basic {good}"})
    assert page.status_code == 200 and "capital of France" in page.get_data(as_text=True)


def test_logo_slot(tmp_path, monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, "BRAND_DIR", tmp_path)
    c = create_app().test_client()
    assert "icon.svg" in c.get("/").get_data(as_text=True)
    (tmp_path / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    html = create_app().test_client().get("/").get_data(as_text=True)
    assert "brand/logo.svg" in html


def test_manifest_and_permissions(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.get_json()["display"] == "standalone"
    assert "microphone=(self)" in client.get("/").headers["Permissions-Policy"]


# ------------------------------------------------------- standalone page parity
import shutil  # noqa: E402
import subprocess  # noqa: E402


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_standalone_engine_matches_server(tmp_path):
    """The in-browser engine must give the same result as the Flask server."""
    from scripts.build_standalone import export_kb
    app = create_app({"RATE_LIMIT_PER_MIN": 10**6})
    (tmp_path / "kb.json").write_text(json.dumps(export_kb(app)))
    ev = json.loads((ROOT / "data" / "eval_set.json").read_text())
    qs = [[q, ""] for q, _ in ev["in_scope"]] + [[q, ""] for q in ev["out_of_scope"] + ev["personal"] + ev["crisis"]]
    qs += [["what about danala?", "where can I get food"], ["hi", ""], ["my id is s385676, wifi help", ""]]
    real = json.loads((ROOT / "data" / "real_eval.json").read_text())["items"]
    qs += [[i["question"], ""] for i in real]  # long, multi-sentence questions exercise sentence scoring
    (tmp_path / "qs.json").write_text(json.dumps(qs))
    out = subprocess.check_output(["node", str(ROOT / "tests/js/parity.js"), str(tmp_path / "kb.json"),
                                   str(ROOT / "app/static/engine.js"), str(tmp_path / "qs.json")])
    c = app.test_client()
    for (q, prev), js in zip(qs, json.loads(out)):
        d = c.post("/api/chat", json={"message": q, "previous": prev}).get_json()
        py = [d["type"], d["faq"]["id"] if "faq" in d else ",".join(o["id"] for o in d.get("options", []))]
        assert py == js, q


# ------------------------------------------------------- integrity and staff insights
def test_integrity_requests_are_declined(client):
    for msg in ["can you write my essay for me", "could someone do my assignment", "give me the answers to the quiz"]:
        r = ask(client, msg)
        assert r["type"] == "smalltalk" and "academic integrity" in r["message"], msg


def test_integrity_does_not_block_normal_questions(client):
    for msg in ["how do I write my essay?", "can someone help me with referencing?", "Can anyone tell me if I do my exam online?"]:
        assert ask(client, msg)["type"] != "smalltalk" or "integrity" not in ask(client, msg)["message"], msg


def test_clear_winner_is_answered():
    from app.matcher import FAQMatcher
    m = FAQMatcher(ROOT / "data" / "faqs.json")
    r = m.match("I live overseas, so how do I get my student card?")
    assert r.band == "answer"


def test_suggested_topics_group_similar_questions():
    from app.analytics import suggest_topics
    qs = ["where do I book my sim block in inplace", "how do I book sim block nursing", "sim block booking inplace help",
          "where is the gym", "parking permit cost"]
    groups = suggest_topics(qs)
    assert groups and groups[0]["count"] == 3 and "sim" in groups[0]["topic"]
