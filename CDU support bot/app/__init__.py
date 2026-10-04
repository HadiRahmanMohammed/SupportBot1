"""CDU First Year Student Support: Flask application factory.

Flask is imported inside create_app() so the shared logic (app.core) can be used
by the Streamlit app without Flask installed.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from .analytics import summarise
from .core import FOLLOWUP_MIN, MAX_LEN, RELATED_MIN, SUGGEST_MIN, Assistant  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = Path(__file__).resolve().parent / "static" / "brand"
LOGO_NAMES = ("logo.svg", "logo.png", "logo.webp")
BG_DIR = Path(__file__).resolve().parent / "static" / "bg"
# Background slideshow order. smoking-ceremony.jpg is deliberately not listed: it shows a
# First Nations ceremony, so add it only with permission from the people and community shown.
BACKGROUNDS = ["campus-courtyard.jpg", "students-lawn.jpg", "wcic-club.jpg",
               "yellow-pavilion.jpg", "graduation.jpg", "city-campus.jpg"]


class RateLimiter:
    """Small in-memory sliding-window limiter (per worker) to stop abuse."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def create_app(config: dict | None = None):
    from flask import Flask, Response, jsonify, render_template, request

    app = Flask(__name__)
    app.config.update(
        KB_PATH=os.environ.get("KB_PATH", str(ROOT / "data" / "faqs.json")),
        ANSWER_THRESHOLD=float(os.environ.get("ANSWER_THRESHOLD", 0.45)),
        CLARIFY_THRESHOLD=float(os.environ.get("CLARIFY_THRESHOLD", 0.24)),
        LOG_INTERACTIONS=os.environ.get("LOG_INTERACTIONS", "false").lower() == "true",
        LOG_PATH=os.environ.get("LOG_PATH", str(ROOT / "logs" / "interactions.jsonl")),
        RATE_LIMIT_PER_MIN=int(os.environ.get("RATE_LIMIT_PER_MIN", 30)),
        SHOW_UNAPPROVED=os.environ.get("SHOW_UNAPPROVED", "true").lower() == "true",
        ADMIN_TOKEN=os.environ.get("ADMIN_TOKEN", ""),
        BRAND_LOGO=os.environ.get("BRAND_LOGO", ""),
        BRAND_NAME=os.environ.get("BRAND_NAME", "CDU First Year Student Support"),
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(config)

    assistant = Assistant(app.config["KB_PATH"], app.config["ANSWER_THRESHOLD"],
                          app.config["CLARIFY_THRESHOLD"], include_unapproved=app.config["SHOW_UNAPPROVED"])
    matcher = assistant.matcher
    limiter = RateLimiter(app.config["RATE_LIMIT_PER_MIN"])
    log_lock = threading.Lock()
    app.extensions["matcher"] = matcher
    app.extensions["assistant"] = assistant
    logging.basicConfig(level=logging.INFO)

    # ------------------------------------------------------------- helpers
    def is_staff() -> bool:
        """Staff testing mode: the page sends the admin token as X-Review-Token."""
        token = app.config["ADMIN_TOKEN"]
        sent = request.headers.get("X-Review-Token", "")
        return bool(token) and hmac.compare_digest(sent, token)

    def brand_logo() -> str | None:
        """Official logo file dropped into app/static/brand/ (see README there)."""
        name = app.config["BRAND_LOGO"]
        candidates = [name] if name else list(LOGO_NAMES)
        for n in candidates:
            if n and (BRAND_DIR / n).is_file():
                return f"brand/{n}"
        return None

    def admin_ok() -> bool:
        token = app.config["ADMIN_TOKEN"]
        auth = request.authorization
        return bool(token) and auth is not None and hmac.compare_digest(auth.password or "", token)

    def log_event(event: dict) -> None:
        if not app.config["LOG_INTERACTIONS"]:
            return
        event["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path = Path(app.config["LOG_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with log_lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def client_key() -> str:
        fwd = request.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or request.remote_addr or "anon"

    # -------------------------------------------------------------- routes
    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'",
        )
        return resp

    @app.get("/")
    def index():
        backgrounds = [f for f in BACKGROUNDS if (BG_DIR / f).is_file()]
        return render_template("index.html", brand_logo=brand_logo(), brand_name=app.config["BRAND_NAME"],
                               backgrounds=backgrounds)

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", faqs=len(matcher.faqs), kb_version=matcher.meta.get("kb_version"))

    @app.get("/api/topics")
    def topics():
        return jsonify(topics=assistant.topics())

    @app.get("/api/faq/<faq_id>")
    def get_faq(faq_id):
        data = assistant.faq(faq_id, staff=is_staff())
        return jsonify(data) if data else (jsonify(error="not found"), 404)

    @app.post("/api/chat")
    def chat():
        if not limiter.allow(client_key()):
            return jsonify(type="error", message="You're sending messages quickly. Please wait a moment."), 429
        data = request.get_json(silent=True) or {}
        text = str(data.get("message", "")).strip()[:MAX_LEN]
        previous = str(data.get("previous", "")).strip()[:MAX_LEN]
        channel = "voice" if data.get("mode") == "voice" else "text"
        if not text:
            return jsonify(type="error", message="Please type a question."), 400

        payload, event = assistant.respond(text, previous, staff=is_staff())
        if event:
            log_event({**event, "channel": channel})
        return jsonify(payload)

    @app.get("/api/suggest")
    def suggest():
        """As-you-type question suggestions. Not logged."""
        return jsonify(suggestions=assistant.suggest(request.args.get("q", "")))

    @app.get("/manifest.webmanifest")
    def manifest():
        body = json.dumps({
            "name": app.config["BRAND_NAME"], "short_name": "CDU First Year",
            "start_url": "/", "display": "standalone",
            "background_color": "#0c2233", "theme_color": "#0c2233",
            "icons": [{"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
        })
        return Response(body, mimetype="application/manifest+json")

    @app.get("/admin")
    def admin():
        if not app.config["ADMIN_TOKEN"]:
            return jsonify(error="Admin dashboard is off. Set ADMIN_TOKEN to turn it on."), 404
        if not admin_ok():
            return Response("Sign in with any username and the admin token as the password.", 401,
                            {"WWW-Authenticate": 'Basic realm="Staff dashboard"'})
        titles = {f["id"]: f["question"] for f in matcher.faqs}
        stats = summarise(app.config["LOG_PATH"], titles)
        return render_template("admin.html", s=stats, logging_on=app.config["LOG_INTERACTIONS"],
                               brand_name=app.config["BRAND_NAME"])

    @app.post("/api/feedback")
    def feedback():
        data = request.get_json(silent=True) or {}
        faq_id = str(data.get("faq_id", ""))[:80]
        helpful = data.get("helpful")
        if faq_id not in matcher.by_id or not isinstance(helpful, bool):
            return jsonify(ok=False), 400
        log_event({"route": "feedback", "faq": faq_id, "helpful": helpful})
        return jsonify(ok=True)

    return app
