"""CDU First Year Student Support: Streamlit app.

Run locally:   streamlit run streamlit_app.py
Deploy:        Streamlit Community Cloud > New app > pick this repo > main file: streamlit_app.py

Students can type or speak. The microphone button in the chat box records audio,
which is transcribed on the server (app/speech_io.py), so voice doesn't depend on
the browser's own speech recognition. Answers can be read aloud in an Australian
English voice.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from app.analytics import summarise
from app.core import Assistant
from app.speech_io import synthesize, transcribe

ROOT = Path(__file__).resolve().parent
LOGO = ROOT / "assets" / "cdu-logo.png"
BRAND = "CDU First Year Student Support"
STUDENT_CENTRAL = ("**Student Central**  \nPhone: **1800 061 963**  \nEmail: **student.central@cdu.edu.au**  \n"
                   "In person: Student Central (Orange 1, Casuarina) or the Library Foyer")
# Background slideshow (files in ./static/bg/, served by Streamlit at /app/static/bg/).
# smoking-ceremony.jpg is also in that folder but left out: add it only with permission from the
# people and community shown, as it depicts a First Nations ceremony.
BACKGROUNDS = ["campus-courtyard.jpg", "students-lawn.jpg", "wcic-club.jpg",
               "yellow-pavilion.jpg", "graduation.jpg", "city-campus.jpg"]
SLIDE_SECONDS = 8
STARTERS = [
    ("Activate my account", "How do I activate my student account?"),
    ("Connect to Wi-Fi", "How do I connect to Wi-Fi on campus?"),
    ("Find my timetable", "Where can I find my timetable?"),
    ("Get my student card", "How do I get a student card?"),
    ("Read a room code", "What does Blue 5.1.24 mean?"),
    ("Find somewhere to live", "I need help finding accommodation"),
    ("Lecture recordings", "Where can I find recorded lectures?"),
    ("Meet people", "How can I meet new friends on campus?"),
]


# ------------------------------------------------------------------ settings
def setting(name: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then environment variables."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file
        pass
    return os.environ.get(name, default)


ADMIN_TOKEN = setting("ADMIN_TOKEN")
LOG_INTERACTIONS = setting("LOG_INTERACTIONS", "false").lower() == "true"
LOG_PATH = Path(setting("LOG_PATH", str(ROOT / "logs" / "interactions.jsonl")))


@st.cache_resource(show_spinner=False)
def get_assistant() -> Assistant:
    return Assistant(setting("KB_PATH", str(ROOT / "data" / "faqs.json")),
                     float(setting("ANSWER_THRESHOLD", "0.45")), float(setting("CLARIFY_THRESHOLD", "0.24")),
                     include_unapproved=setting("SHOW_UNAPPROVED", "true").lower() == "true")


@st.cache_data(show_spinner=False, max_entries=300)
def speech_audio(text: str) -> bytes | None:
    return synthesize(text)


@st.cache_data(show_spinner=False)
def logo_b64() -> str:
    return base64.b64encode(LOGO.read_bytes()).decode() if LOGO.exists() else ""


def log_event(event: dict) -> None:
    if not LOG_INTERACTIONS:
        return
    event["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def is_staff() -> bool:
    sent = st.query_params.get("review", "")
    return bool(ADMIN_TOKEN) and hmac.compare_digest(sent, ADMIN_TOKEN)


# ------------------------------------------------------------------ page + style
st.set_page_config(page_title=BRAND, page_icon=":material/school:", layout="centered",
                   initial_sidebar_state="auto")

st.html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,750&family=Figtree:wght@400;500;600;700&display=swap');
/* Light frosted glass in the CDU brand palette: primary blue PMS 2765C, black type, secondary colours as accents. */
:root {
  --navy: #211645; --ink: #000000; --muted: #4d4866;
  --lagoon: #007A87; --gold: #EFBD47; --sky: #A0CFEB; --orange: #D55C19;
  --glass: rgba(255,255,255,.58); --glass-edge: rgba(255,255,255,.9);
  --shadow: 0 10px 30px rgba(33,22,69,.10);
}
html, body, [data-testid="stApp"], .stMarkdown, button, input, textarea { font-family: "Figtree", ui-sans-serif, system-ui, sans-serif; }
html, body { background: #eeedf5; }
[data-testid="stApp"] { background: transparent; color: var(--ink); }

/* campus photo slideshow behind a frosted wash */
.cdu-bg { position: fixed; inset: 0; z-index: -1; overflow: hidden; pointer-events: none; background: #eeedf5; }
.cdu-bg i {
  position: absolute; inset: -40px; background-size: cover; background-position: center;
  opacity: 0; filter: blur(2px) saturate(1.15); transform: scale(1.04);
  animation-name: cdu-fade; animation-iteration-count: infinite; animation-timing-function: ease-in-out;
}
.cdu-bg i:first-child { opacity: 1; }
.cdu-bg::after {
  content: ""; position: absolute; inset: 0;
  background:
    radial-gradient(70vmax 60vmax at 0% 0%, rgba(160,207,235,.35), transparent 60%),
    radial-gradient(60vmax 60vmax at 100% 20%, rgba(114,206,155,.18), transparent 60%),
    linear-gradient(rgba(238,237,245,.36), rgba(238,237,245,.50));
}
@media (prefers-reduced-motion: reduce) { .cdu-bg i { animation: none !important; } }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"], .block-container { padding-top: 1.2rem; max-width: 780px; }
h1, h2, h3, h4 { font-family: "Bricolage Grotesque", "Figtree", sans-serif !important; color: var(--navy) !important; letter-spacing: -.02em; }

/* header bar */
.cdu-bar {
  display: flex; align-items: center; gap: 16px; padding: 12px 18px; margin-bottom: 8px;
  background: var(--glass); border: 1px solid var(--glass-edge); border-radius: 22px;
  -webkit-backdrop-filter: blur(18px) saturate(150%); backdrop-filter: blur(18px) saturate(150%);
  box-shadow: var(--shadow);
}
.cdu-bar img { height: 62px; width: auto; }
.cdu-bar .sep { width: 1px; align-self: stretch; background: rgba(33,22,69,.18); }
.cdu-bar .title { font: 700 1.25rem/1.1 "Bricolage Grotesque", sans-serif; color: var(--navy); letter-spacing: -.01em; }
.cdu-bar .sub { font-size: .85rem; color: var(--muted); margin-top: 2px; }

.cdu-hero { background: rgba(255,255,255,.62); border: 1px solid var(--glass-edge); border-radius: 22px;
  padding: 6px 22px 16px; margin: 6px 0 14px; -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); box-shadow: var(--shadow); }
.cdu-foot { background: rgba(255,255,255,.6); border-radius: 999px; padding: 4px 12px; width: fit-content; margin-left: auto !important; margin-right: auto !important; }
.cdu-hero h2 { font-size: clamp(1.9rem, 5vw, 2.8rem) !important; line-height: 1.05; margin: 18px 0 8px; }
.cdu-hero p { color: var(--muted); font-size: 1.04rem; max-width: 52ch; margin: 0 0 6px; }

/* chat bubbles */
[data-testid="stChatMessage"] {
  background: rgba(255,255,255,.72); border: 1px solid var(--glass-edge); border-radius: 20px;
  -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px); box-shadow: var(--shadow);
  padding: 14px 16px;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: linear-gradient(135deg, rgba(33,22,69,.92), rgba(0,122,135,.92)); border-color: transparent;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p,
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stCaptionContainer"] { color: #fff !important; }

/* buttons */
.stButton > button, .stLinkButton > a {
  border-radius: 999px !important; border: 1px solid rgba(33,22,69,.14) !important;
  background: rgba(255,255,255,.7) !important; color: var(--navy) !important; font-weight: 600;
}
.stButton > button:hover, .stLinkButton > a:hover { border-color: var(--navy) !important; background: #fff !important; }
.stButton > button[kind="primary"] { background: var(--navy) !important; color: #fff !important; border-color: var(--navy) !important; }

/* chat input */
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background: transparent; }
[data-testid="stChatInput"] {
  background: rgba(255,255,255,.75) !important; border: 1px solid var(--glass-edge) !important;
  border-radius: 22px !important; box-shadow: var(--shadow); -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);
}

/* sidebar */
[data-testid="stSidebar"] { background: rgba(255,255,255,.62); -webkit-backdrop-filter: blur(18px); backdrop-filter: blur(18px); border-right: 1px solid var(--glass-edge); }
.cdu-help { background: rgba(255,255,255,.7); border: 1px solid var(--glass-edge); border-radius: 16px; padding: 12px 14px; font-size: .92rem; }
.cdu-foot { text-align: center; color: var(--muted); font-size: .78rem; margin-top: 10px; }
@media (max-width: 640px) { .cdu-bar { margin-top: 34px; gap: 12px; } .cdu-bar img { height: 46px; } .cdu-bar .sub { display: none; } }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
""")

def background_html() -> str:
    files = [f for f in BACKGROUNDS if (ROOT / "static" / "bg" / f).exists()]
    if not files:
        return ""
    n, total = len(files), len(files) * SLIDE_SECONDS
    show = 100 / n                       # share of the cycle each photo is on screen
    fade = min(4.0, show / 4)
    keyframes = (f"@keyframes cdu-fade {{ 0% {{ opacity: 0 }} {fade:.2f}% {{ opacity: 1 }} "
                 f"{show:.2f}% {{ opacity: 1 }} {show + fade:.2f}% {{ opacity: 0 }} 100% {{ opacity: 0 }} }}")
    layers = "".join(
        f'<i style="background-image:url(app/static/bg/{f});animation-duration:{total}s;'
        f'animation-delay:{i * SLIDE_SECONDS - (fade / 100) * total:.2f}s"></i>'
        for i, f in enumerate(files))
    return f'<style>{keyframes}</style><div class="cdu-bg" aria-hidden="true">{layers}</div>'


st.html(background_html())

# ------------------------------------------------------------------ state
ss = st.session_state
ss.setdefault("messages", [])        # [{"role": "user"|"assistant", ...}]
ss.setdefault("last_q", "")
ss.setdefault("pending", None)       # action queued by a button callback
ss.setdefault("voice_replies", False)

assistant = get_assistant()
STAFF = is_staff()


def queue(action: str, value: str = "", label: str = "") -> None:
    ss.pending = (action, value, label)


def new_chat() -> None:
    ss.messages, ss.last_q, ss.pending = [], "", None


def add_assistant(payload: dict, speak: bool) -> None:
    msg = {"role": "assistant", "data": payload}
    if speak:
        text = payload["faq"]["speech"] if payload.get("type") == "answer" else payload.get("speech", "")
        if payload.get("type") == "answer" and payload["faq"].get("links"):
            text += " I've put the links on screen."
        msg["speak_text"] = text
        msg["autoplay"] = True
    ss.messages.append(msg)


def ask(text: str, mode: str = "text") -> None:
    text = text.strip()
    if not text:
        return
    ss.messages.append({"role": "user", "text": text, "mode": mode})
    payload, event = assistant.respond(text, ss.last_q, staff=STAFF)
    ss.last_q = text
    if event:
        log_event({**event, "channel": mode})
    add_assistant(payload, speak=(mode == "voice" or ss.voice_replies))


def open_faq(faq_id: str, question: str, mode: str = "text") -> None:
    data = assistant.faq(faq_id, staff=STAFF)
    if not data:
        return
    ss.messages.append({"role": "user", "text": question, "mode": mode})
    ss.last_q = question
    add_assistant(data, speak=(mode == "voice" or ss.voice_replies))


def feedback(faq_id: str, key: str) -> None:
    val = ss.get(key)
    if val is not None:
        log_event({"route": "feedback", "faq": faq_id, "helpful": val == 1})


def listen_now(i: int) -> None:
    m = ss.messages[i]
    d = m["data"]
    m["speak_text"] = d["faq"]["speech"] if d.get("type") == "answer" else d.get("speech", "")
    m["autoplay"] = True


# Run any action queued by a button before drawing the page.
if ss.pending:
    action, value, label = ss.pending
    ss.pending = None
    if action == "ask":
        ask(value)
    elif action == "faq":
        open_faq(value, label)
    elif action == "fallback":
        add_assistant(json.loads(value), speak=ss.voice_replies)


# ------------------------------------------------------------------ staff dashboard (?admin)
if "admin" in st.query_params:
    st.markdown("## Staff dashboard")
    if not ADMIN_TOKEN:
        st.info("The dashboard is off. Set ADMIN_TOKEN in the app's secrets to turn it on.")
        st.stop()
    pw = st.text_input("Admin token", type="password")
    if not pw or not hmac.compare_digest(pw, ADMIN_TOKEN):
        st.stop()
    titles = {f["id"]: f["question"] for f in assistant.matcher.faqs}
    s = summarise(LOG_PATH, titles)
    if not LOG_INTERACTIONS:
        st.warning("Logging is off. Set LOG_INTERACTIONS = \"true\" in the app's secrets to collect masked questions.")
    c = st.columns(4)
    c[0].metric("Questions", s["total"]); c[1].metric("Answered", f'{s["answered_pct"]}%')
    c[2].metric("Did you mean", f'{s["clarify_pct"]}%'); c[3].metric("To Student Central", f'{s["fallback_pct"]}%')
    c = st.columns(4)
    c[0].metric("Helpful", "–" if s["helpful_pct"] is None else f'{s["helpful_pct"]}%')
    c[1].metric("By voice", s["voice"]); c[2].metric("Handoffs", s["handoff"]); c[3].metric("Crisis", s["crisis"])
    st.markdown("#### Suggested new FAQs")
    st.caption("Unanswered questions grouped by topic. The biggest groups are where a new FAQ would help most.")
    st.dataframe([{"Topic": t["topic"], "Questions": t["count"], "Examples": " | ".join(t["examples"])}
                  for t in s["suggested_topics"]] or [{"Topic": "Not enough unanswered questions yet"}],
                 use_container_width=True, hide_index=True)
    st.markdown("#### Questions it couldn't answer")
    st.dataframe(s["gaps"] or [{"q": "Nothing yet"}], use_container_width=True, hide_index=True)
    st.markdown("#### Most asked")
    st.dataframe(s["top"] or [{"question": "Nothing yet"}], use_container_width=True, hide_index=True)
    st.stop()


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### Talk to a person")
    st.html(f'<div class="cdu-help">{STUDENT_CENTRAL.replace("  ", "<br>").replace("**", "")}</div>')
    st.toggle("Read answers aloud", key="voice_replies")
    st.button("New chat", on_click=new_chat, icon=":material/add_comment:", use_container_width=True)
    st.markdown("### Topics")
    for t in assistant.topics():
        with st.expander(t["category"]):
            for q in t["questions"]:
                st.button(q["question"], key=f"topic_{q['id']}", on_click=queue, args=("faq", q["id"], q["question"]),
                          use_container_width=True)
    st.caption("AI assistant (student prototype). Please don't share personal details.")


# ------------------------------------------------------------------ header
logo_html = f'<img src="data:image/png;base64,{logo_b64()}" alt="Charles Darwin University">' if logo_b64() else ""
st.html(f"""
<div class="cdu-bar">{logo_html}<div class="sep"></div>
  <div><div class="title">First Year Student Support</div><div class="sub">Quick answers for new students, by text or voice</div></div>
</div>""")


# ------------------------------------------------------------------ messages
def render_assistant(i: int, m: dict) -> None:
    d = m["data"]
    kind = d.get("type")
    if kind == "answer":
        f = d["faq"]
        st.markdown(f"**{f['question']}**")
        st.markdown(f["answer"])
        links = [k for k in f.get("links", []) if str(k.get("url", "")).startswith("https://")]
        if links:
            cols = st.columns(min(3, len(links)))
            for n, k in enumerate(links):
                cols[n % len(cols)].link_button(k["label"], k["url"], icon=":material/open_in_new:", use_container_width=True)
        if f.get("staff"):
            s = f["staff"]; src = s["source"]
            st.caption(f'Staff view: {src["title"]}, p.{src["page"]}{"" if src["approved"] else " (not approved)"}, match {s["score"]}'
                       + (f' — review: {s["review_flag"]}' if s.get("review_flag") else ""))
        if d.get("related"):
            st.caption("Related")
            for r in d["related"]:
                st.button(r["question"], key=f"rel_{i}_{r['id']}", on_click=queue, args=("faq", r["id"], r["question"]))
        st.feedback("thumbs", key=f"fb_{i}", on_change=feedback, args=(f["id"], f"fb_{i}"))
    elif kind == "crisis":
        st.error(d["message"])
    elif kind == "clarify":
        st.markdown(d["message"])
        for o in d["options"]:
            st.button(o["question"], key=f"opt_{i}_{o['id']}", on_click=queue, args=("faq", o["id"], o["question"]))
        fb = json.dumps({"type": "fallback", "message": d["fallback"], "speech": d["fallback_speech"]})
        st.button("None of these", key=f"none_{i}", on_click=queue, args=("fallback", fb))
    else:
        st.markdown(d.get("message", ""))
    if d.get("pii_note"):
        st.caption(d["pii_note"])

    # Spoken reply: server voice (gTTS), with the browser's own voice as a fallback.
    if m.get("speak_text"):
        audio = speech_audio(m["speak_text"])
        autoplay = m.pop("autoplay", False)
        if audio:
            st.audio(audio, format="audio/mp3", autoplay=autoplay)
        elif autoplay:
            components.html(
                "<script>try{const s=window.speechSynthesis;s.cancel();const u=new SpeechSynthesisUtterance("
                + json.dumps(m["speak_text"]) + ");u.lang='en-AU';s.speak(u);}catch(e){}</script>", height=0)
    elif kind != "clarify":
        st.button("Listen", key=f"listen_{i}", icon=":material/volume_up:", on_click=listen_now, args=(i,))


if not ss.messages:
    st.html("""<div class="cdu-hero"><h2>What do you need sorted this week?</h2>
      <p>Type your question, or tap the microphone in the box below and say it. If I can't help, I'll point you to someone who can.</p></div>""")
    cols = st.columns(2)
    for n, (label, q) in enumerate(STARTERS):
        cols[n % 2].button(label, key=f"start_{n}", on_click=queue, args=("ask", q), use_container_width=True)
else:
    for i, m in enumerate(ss.messages):
        if m["role"] == "user":
            with st.chat_message("user", avatar=":material/person:"):
                st.markdown(m["text"])
                if m.get("mode") == "voice":
                    st.caption("Spoken")
        else:
            with st.chat_message("assistant", avatar=":material/support_agent:"):
                render_assistant(i, m)

st.html('<p class="cdu-foot">AI assistant (student prototype). Please don\'t share personal details.</p>')


# ------------------------------------------------------------------ input (text or voice)
value = st.chat_input("Ask about enrolment, Wi-Fi, buses…", accept_audio=True, max_chars=500)
if value is not None:
    text = (value.text if hasattr(value, "text") else str(value)) or ""
    audio = getattr(value, "audio", None)
    if text.strip():
        ask(text)
    elif audio is not None:
        with st.spinner("Listening to your recording…"):
            heard, err = transcribe(audio.getvalue())
        if heard:
            ask(heard, mode="voice")
        else:
            ss.messages.append({"role": "assistant", "data": {"type": "smalltalk", "message": err, "speech": err},
                                "speak_text": err, "autoplay": True})
    st.rerun()
