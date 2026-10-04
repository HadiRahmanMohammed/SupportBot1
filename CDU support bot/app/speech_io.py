"""Server-side speech for the Streamlit app.

Speech-to-text runs on the server from a WAV recording (Streamlit's chat input
records audio in the browser and uploads it), so it doesn't depend on the
browser's own speech recognition, which is unreliable across browsers.

  transcribe(wav_bytes) -> (text | None, error | None)
  synthesize(text)      -> mp3 bytes | None   (Australian English voice)

Both use free Google web services (via the SpeechRecognition and gTTS packages)
and need internet access from the server. Streamlit Community Cloud has it.
"""
from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)

STT_ERRORS = {
    "unclear": "I couldn't make out what you said. Try again a little closer to the mic, or type your question.",
    "service": "Voice recognition is unavailable right now. Please type your question.",
    "empty": "That recording was empty. Hold the mic button and speak, then try again.",
    "missing": "Voice recognition isn't installed on this server. Please type your question.",
}


def transcribe(wav_bytes: bytes, language: str = "en-AU") -> tuple[str | None, str | None]:
    if not wav_bytes or len(wav_bytes) < 2000:  # under ~0.05 s of 16 kHz audio
        return None, STT_ERRORS["empty"]
    try:
        import speech_recognition as sr
    except ImportError:
        return None, STT_ERRORS["missing"]
    r = sr.Recognizer()
    try:
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio = r.record(source)
    except Exception as exc:  # unreadable or non-WAV upload
        log.warning("Could not read audio: %s", exc)
        return None, STT_ERRORS["empty"]
    try:
        text = r.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        return None, STT_ERRORS["unclear"]
    except sr.RequestError as exc:
        log.warning("Speech service error: %s", exc)
        return None, STT_ERRORS["service"]
    text = (text or "").strip()
    return (text, None) if text else (None, STT_ERRORS["unclear"])


def synthesize(text: str) -> bytes | None:
    """Australian English text-to-speech. Returns None if the service is unavailable."""
    if not text:
        return None
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(text=text, lang="en", tld="com.au").write_to_fp(buf)
        return buf.getvalue() or None
    except Exception as exc:  # no network, rate limited, package missing
        log.warning("Text-to-speech unavailable: %s", exc)
        return None
