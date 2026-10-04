"""Turn chat answers (markdown-lite) into text that sounds natural when spoken.

The browser's speech synthesiser reads whatever it is given, so
"student.central@cdu.edu.au" and "1800 061 963" need to be rewritten to be
understandable by ear. Long answers are trimmed, and the listener is told the
full detail is in the chat.
"""
from __future__ import annotations

import re

MAX_WORDS = 70

_EMAIL = re.compile(r"\b([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)\b")
_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:au|com|org|net|gov))\b(/[\w/.-]*)?", re.I)
_PHONE = re.compile(r"(\+?\d[\d ]{6,}\d)")
_ROOM = re.compile(r"\b([A-Z][a-z]+) (\d+)\.(\d+)\.(\d+)\b")
_ORDINAL_STEPS = ["First", "Then", "Next", "After that", "Then", "Finally"]


_SAY_AS_WORD = {"edu", "com", "gov", "org", "net", "ask", "my"}


def _spell_token(tok: str) -> str:
    # short acronyms such as "cdu" or "au" are clearer spelled out
    if len(tok) <= 3 and tok.isalpha() and tok.lower() not in _SAY_AS_WORD:
        return " ".join(tok.upper())
    return tok


def _speak_address(addr: str) -> str:
    return " dot ".join(_spell_token(p) for p in addr.split("."))


def _speak_email(m: re.Match) -> str:
    return f"{_speak_address(m.group(1))} at {_speak_address(m.group(2))}"


def _speak_phone(m: re.Match) -> str:
    out = []
    for g in m.group(1).split():
        digits = " ".join(g.lstrip("+"))
        out.append(f"plus {digits}" if g.startswith("+") else digits)
    return ", ".join(out)


def to_speech(md: str, max_words: int = MAX_WORDS) -> str:
    text = md.replace("**", "").replace("*", "")
    text = _EMAIL.sub(_speak_email, text)
    text = _ROOM.sub(lambda m: f"{m.group(1)} {m.group(2)} dot {m.group(3)} dot {m.group(4)}", text)
    text = re.sub(r"\b000\b", "triple zero", text)
    text = text.replace("24/7", "twenty-four seven")
    text = text.replace(" . ", ", then ").replace("[", "").replace("]", "").replace(" + ", " and ")
    text = _DOMAIN.sub(lambda m: _speak_address(m.group(1)), text)
    text = _PHONE.sub(_speak_phone, text)

    sentences: list[str] = []
    step = 0
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        num = re.match(r"^\d+\.\s+(.*)", line)
        bullet = re.match(r"^-\s+(.*)", line)
        if num:
            body = num.group(1)
            body = body[0].lower() + body[1:] if body[:1].isupper() and body[1:2].islower() else body
            line = f"{_ORDINAL_STEPS[min(step, len(_ORDINAL_STEPS) - 1)]}, {body}"
            step += 1
        elif bullet:
            line = bullet.group(1)
        line = re.sub(r":\s*$", ".", line)
        if line[-1] not in ".!?":
            line += "."
        sentences.append(line)

    words, spoken, cut = 0, [], False
    for s in sentences:
        n = len(s.split())
        if cut and not _is_safety(s):
            continue
        if spoken and words + n > max_words and not _is_safety(s):
            cut = True
            continue
        spoken.append(s)  # safety lines are always spoken, even past the limit
        words += n
    if cut:
        spoken.append("There's more detail in the chat.")
    return " ".join(spoken)


def _is_safety(sentence: str) -> bool:
    return any(k in sentence for k in ("triple zero", "Lifeline", "unsafe", "danger"))
