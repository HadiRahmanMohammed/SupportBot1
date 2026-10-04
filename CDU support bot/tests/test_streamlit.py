"""Headless tests for the Streamlit app (streamlit.testing.v1.AppTest)."""
import io
import wave
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = st_testing.AppTest
ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "streamlit_app.py")


@pytest.fixture(autouse=True)
def no_network_speech(monkeypatch):
    """Keep tests offline: fake text-to-speech, and transcription unless a test overrides it."""
    import app.speech_io as sio
    monkeypatch.setattr(sio, "synthesize", lambda text: b"ID3fake-mp3" if text else None)


def run_app(**params):
    at = AppTest.from_file(APP, default_timeout=60)
    for k, v in params.items():
        at.query_params[k] = v
    return at.run()


def texts(at):
    return " ".join(m.value for m in at.markdown)


def test_loads_with_logo_and_starters():
    at = run_app()
    assert not at.exception
    assert any("What do you need sorted" in h.proto.body for h in at.get("html"))
    assert len([b for b in at.button if b.key and b.key.startswith("start_")]) == 8


def test_typed_question_gets_answer():
    at = run_app()
    at.chat_input[0].set_value("how do I connect to the wifi").run()
    assert not at.exception
    assert "How do I get access to Wi-Fi?" in texts(at)
    assert "Welcome Centre" not in texts(at)          # no sources shown to students


def test_starter_button():
    at = run_app()
    at.button(key="start_0").click().run()
    assert "activation.cdu.edu.au" in texts(at)


def test_personal_and_crisis_routes():
    at = run_app()
    at.chat_input[0].set_value("what are my grades").run()
    assert "personal student record" in texts(at)
    at.chat_input[0].set_value("I want to kill myself").run()
    assert any("000" in e.value and "13 11 14" in e.value for e in at.error)


def test_out_of_scope_defers():
    at = run_app()
    at.chat_input[0].set_value("what is the capital of France").run()
    assert "rather not guess" in texts(at)


def test_read_aloud_toggle_adds_audio():
    at = run_app()
    at.toggle[0].set_value(True).run()
    at.chat_input[0].set_value("where can I park").run()
    assert len(at.get("audio")) == 1


def _wav(seconds=0.5):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def test_transcribe_handles_bad_audio():
    from app.speech_io import transcribe
    text, err = transcribe(b"")
    assert text is None and "empty" in err


def test_staff_view_needs_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t0k")
    at = run_app(review="t0k")
    at.chat_input[0].set_value("wifi").run()
    assert any("Staff view" in c.value for c in at.caption)
    at = run_app(review="wrong")
    at.chat_input[0].set_value("wifi").run()
    assert not any("Staff view" in c.value for c in at.caption)


def test_admin_dashboard_locked(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t0k")
    at = run_app(admin="1")
    assert "Staff dashboard" in texts(at) and not at.get("metric")
    at.text_input[0].set_value("t0k").run()
    assert at.get("metric")


def test_transcribe_reads_wav(monkeypatch):
    import speech_recognition as sr
    from app.speech_io import transcribe
    seen = {}

    def fake_google(self, audio, language=None, **kw):
        seen["rate"], seen["lang"] = audio.sample_rate, language
        return "how do I get a student card"
    monkeypatch.setattr(sr.Recognizer, "recognize_google", fake_google)
    text, err = transcribe(_wav(1.0))
    assert text == "how do I get a student card" and err is None
    assert seen == {"rate": 16000, "lang": "en-AU"}


def test_transcribe_unclear(monkeypatch):
    import speech_recognition as sr
    from app.speech_io import transcribe

    def unclear(self, audio, **kw):
        raise sr.UnknownValueError()
    monkeypatch.setattr(sr.Recognizer, "recognize_google", unclear)
    text, err = transcribe(_wav(1.0))
    assert text is None and "couldn't make out" in err
