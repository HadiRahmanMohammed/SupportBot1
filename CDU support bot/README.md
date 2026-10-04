# CDU First Year Student Support

**PRT691 Artificial Intelligence Practice. Group: Darwin and External 01.**

This is a chatbot that answers common questions from **first-year (commencing) students** at Charles Darwin University. It draws its answers from the New Student Welcome Centre FAQ, which the Senior Student Success Adviser provided.

Students can **type or talk**. Voice chat is hands-free: the student speaks, the assistant answers out loud, then listens for the next question.

It's built exactly as set out in the Progress Report (Section 5): **Python + Flask + FAQ matching**. It doesn't use a generative model, so every answer is traceable to an approved source. When the bot isn't confident, it sends the student to Student Central instead of guessing.

> Student prototype. Not an official CDU service. It runs on its own domain, as agreed with the Adviser.

---

## Deploy on Streamlit (recommended)

The Streamlit app (`streamlit_app.py`) is the easiest way to put this online. It has text chat, voice questions, spoken answers, the CDU logo, and a staff dashboard.

**Run it on your computer**
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py          # opens http://localhost:8501
```

**Put it online (free, Streamlit Community Cloud)**
1. Push this folder to a GitHub repo.
2. Go to **share.streamlit.io**, then **Create app** and choose **Deploy a public app from GitHub**.
3. Pick the repo and branch, and set **Main file path** to `streamlit_app.py`.
4. Under **Advanced settings**, choose Python 3.12. Paste the contents of `.streamlit/secrets.toml.example` into **Secrets** and change `ADMIN_TOKEN`.
5. Click **Deploy**. In about 2 minutes you get a link like `https://cdu-student-support.streamlit.app`.

**How voice works in the Streamlit app**
- The microphone button is built into the chat box. A student taps it, speaks, and taps send.
- The recording is converted to text **on the server** (Google speech recognition, English (Australia)). It doesn't depend on the browser's own speech recognition, so it works the same in Chrome, Safari, Edge and Firefox, on phones too.
- Answers to spoken questions are read out in an Australian English voice (gTTS). Turn on **Read answers aloud** in the sidebar to hear every answer, or tap **Listen** on any answer. If the voice service can't be reached, the browser's built-in voice is used instead.
- The microphone needs HTTPS. Streamlit Cloud provides it, and `localhost` also works.
- Both speech services are free Google web services. They need internet access from the server and have fair-use limits, which is fine for a pilot.

**Staff tools (needs `ADMIN_TOKEN` in Secrets)**
- `?review=<token>` at the end of the address shows each answer's source page, match score and review notes.
- `?admin` opens the dashboard. Enter the token to see what students asked and which questions weren't answered. Set `LOG_INTERACTIONS = "true"` to collect data. Streamlit Cloud's disk resets when the app restarts, so export what you need before redeploying.

**Background photos:** campus photos crossfade behind a frosted wash, changing every 8 seconds. Motion is turned off for people who prefer reduced motion.
- **Streamlit:** the photos are in `static/bg/` and the order is set by `BACKGROUNDS` in `streamlit_app.py`.
- **Flask:** the photos are in `app/static/bg/` and the order is set by `BACKGROUNDS` in `app/__init__.py`.
- **Standalone HTML:** the photos are built into the file.

Photos were resized and their metadata (including any location data) removed. `smoking-ceremony.jpg` is kept in `static/bg/` but isn't shown: it depicts a First Nations ceremony, so add it to `BACKGROUNDS` only with permission from the people and community involved. Make sure everyone in the club photo is happy to appear on a public site.

**Logo:** `assets/cdu-logo.png` is shown in the header (and copied to `app/static/brand/logo.png` for the Flask version). Confirm with the Student Success team that CDU is happy for its logo to be used on this prototype.

---

## Quick start (local)

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python wsgi.py                                         # http://localhost:5000
```

Run the tests and the evaluation:

```bash
pytest                                  # 70 tests, including a quality floor check
python scripts/evaluate.py --details    # accuracy / deferral report + every miss
python scripts/evaluate.py --sweep      # threshold grid search
python scripts/evaluate_real.py         # real student questions (held-out test half)
```

**Staff testing mode:** set `ADMIN_TOKEN`, then open `/?review=<ADMIN_TOKEN>`. Each answer then shows its source page, match score and internal review notes. Students never see these, and the API only sends them with the correct token.

---

## Standalone version (no server needed)

```bash
python scripts/build_standalone.py
```

This writes `dist/cdu-student-support.html`: one file with the knowledge base and matching engine built in (`app/static/engine.js`). Open it in any browser or upload it to any static host (GitHub Pages, Netlify), and it answers questions with no Python server.

A test checks that the in-browser engine gives the same answer as the Flask server on every evaluation question.

The standalone file has no staff dashboard or logging. Voice works when the page is served over HTTPS, or opened from your own computer, in Chrome, Edge or Safari. Re-run the build after editing `data/faqs.json`.

### Using voice with the standalone file

Chrome blocks speech recognition on pages opened straight from your computer (`file://...`). Serve the file locally instead:

```bash
cd ~/Downloads                      # the folder with cdu-student-support.html
python3 -m http.server 8000
```

Then open **http://localhost:8000/cdu-student-support.html** in Chrome and allow the microphone. Any `https://` host (GitHub Pages, Netlify, Render) also works.

## Deploy the Flask version

Pick one. All three use the same production server (`gunicorn wsgi:app`), and each exposes `/healthz` for health checks.

### Option A: Render (free tier)

1. Push this folder to a GitHub repo. The `.gitignore` already keeps raw data, PDFs and logs out.
2. On render.com, choose **New > Blueprint** and select the repo. `render.yaml` sets everything up.
3. Wait about 2 minutes. You'll get a URL like `https://cdu-student-assistant.onrender.com`.

Free Render services sleep after inactivity, so the first request can take around 30 seconds. Upgrade to the Starter plan for demos.

### Option B: Docker (any host: Railway, Fly.io, Azure, a VM)

```bash
docker build -t cdu-assistant .
docker run -p 8000:8000 cdu-assistant           # http://localhost:8000
```

### Option C: Heroku / Railway / any Procfile host

`Procfile` and `.python-version` are included. Connect the repo and deploy.

### Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ANSWER_THRESHOLD` | `0.45` | Minimum match score to answer directly |
| `CLARIFY_THRESHOLD` | `0.24` | Minimum score to offer "Did you mean…?" options |
| `SHOW_UNAPPROVED` | `true` | Set to `false` to hide the 4 team-written unit-level placeholders |
| `LOG_INTERACTIONS` | `false` | Set to `true` to log **masked** questions, scores and feedback to `logs/interactions.jsonl` for evaluation |
| `RATE_LIMIT_PER_MIN` | `30` | Requests per minute per IP (per worker) |
| `ADMIN_TOKEN` | *(off)* | Turns on the `/admin` staff dashboard. Sign in with any username and this token as the password |
| `BRAND_NAME` | CDU First Year Student Support | Name shown in the header |
| `BRAND_LOGO` | *(auto)* | Logo filename in `app/static/brand/`. `logo.svg`, `logo.png` or `logo.webp` is picked up automatically |

---

## Features

- **Glass interface** in light and dark, following the device setting, with a manual toggle on desktop. It works on phones and can be added to the home screen.
- **Voice chat** (the waveform button, or "Talk instead"):
  - Hands-free loop: listen, answer out loud, listen again.
  - The orb reacts to the student's voice level. Tap it to interrupt or pause.
  - Say "one", "two" or "three" to pick a "Did you mean" option, or "none of these".
  - Say "stop" to end.
  - Answers are rewritten for listening. For example, `student.central@cdu.edu.au` is read as "student dot central at C D U dot edu dot A U", phone numbers digit by digit, and `000` as "triple zero".
  - Long answers are shortened, but **safety lines are always read**. Crisis messages stop the loop and keep the help on screen.
  - It uses an Australian English voice when the device has one.
- **Dictation** (the microphone button) turns speech into a typed question.
- **Listen** on any answer reads it aloud. **Copy** copies the answer with its links.
- **Suggestions as you type**, using the same matcher. Use the arrow keys and Enter to pick one.
- **Topics drawer** with a filter, **New chat**, and the chat is kept when the page reloads (this browser tab only).
- **Staff dashboard** (`/admin`) shows:
  - questions asked, answer and deferral rates, helpful ratings and how many questions came by voice
  - the most-asked questions
  - **suggested new FAQs:** unanswered questions grouped by topic (for example "attendance" or "sim block booking"), biggest group first, so staff know which FAQ to write next
  - questions it couldn't answer, which is the list to grow the knowledge base from
- **Logo slot:** see `app/static/brand/README.md`.

**Voice browser support:** voice chat and dictation work in Chrome, Edge and Safari (desktop, Android and iOS). Firefox doesn't support speech recognition, so the buttons say so and typing still works.

Speech recognition runs in the browser, and Chrome and Edge send the audio to their own online speech service. The voice screen tells students not to say personal details. The app server only ever receives the transcribed text, which goes through the same masking as typed text.

Voice needs HTTPS. Render, Railway and Fly all provide it, and `localhost` also works.

## How it works

```
Student ─▶ Chat UI ─▶ POST /api/chat
                         │
                         ├─ 1. PII masking ─ student IDs, emails, phone numbers removed before matching/logging
                         ├─ 2. Guardrails  ─ crisis language ─▶ 000 / Lifeline / CDU Security / Counselling
                         │                 ─ "write my essay for me" ─▶ academic integrity reply
                         │                 ─ personal records (grades, fees owed, "am I enrolled") ─▶ Student Central
                         │                 ─ small talk, "are you a real person?" ─▶ AI disclosure
                         └─ 3. FAQ matcher ─ score ≥ 0.45 ─▶ approved answer + source + page
                                           ─ 0.24–0.45   ─▶ "Did you mean…?" (+ "None of these" ─▶ Student Central)
                                           ─ < 0.24      ─▶ "I'm not sure, contact Student Central"
```

**Matcher (`app/matcher.py`)**
- Each FAQ is indexed by its question, its alternative phrasings, and all of them combined.
- Two TF-IDF models are blended: **word** (stemmed 1–2-grams) for meaning, and **character** 3–5-grams for typos ("enrol"/"enroll", "wifi"/"wi-fi").
- **Domain normalisation** handles student shorthand: "ID card" → student card, "sign up for" → enrol, "IT" (which would otherwise be dropped as a stop word), and room codes such as `Blue 5.1.24`.
- **Coverage penalty:** if most of a question's words aren't in the FAQ, the score is reduced. This stops "how do I apply for a PhD" from matching "How do I apply for a USI" on the word "apply".
- **Place-name cap:** "Casuarina" or "Danala" can add only a small bonus. Without it, "pizza near Casuarina" would match a Casuarina FAQ.
- **Question sentences:** real messages are long ("Hi, I'm new and study nursing online. Where do I find InPlace?"). Each sentence that asks something is also scored on its own, so background sentences don't drown out the question. Statement sentences ("I study externally.") are never scored alone.
- **Clear winner:** an answer scoring at least 0.35 and 2.5× the runner-up is given directly, even below the 0.45 threshold.
- **Student vocabulary:** "subject" means unit, and "sim block", "simulation block" and "simblock" are the same thing.
- **Short follow-ups** like "what about Danala?" reuse the previous question and pick the first matching FAQ the follow-up relates to.

**Responsible AI features (mapped to Progress Report Section 6)**

| Principle | Implementation |
|---|---|
| Transparency | The footer says it's an AI assistant and a student prototype. The bot says it's an AI when asked. Students don't see sources, but every answer is traceable to its source and page in staff review mode. |
| Accountability | Answers come only from the knowledge base, with no generated text. The 12 unapproved entries (4 unit-level placeholders, 8 drafts from Q&A Corner staff replies) are flagged for staff review, and `SHOW_UNAPPROVED=false` hides them. |
| Safe failure | Confidence thresholds are tuned on held-out data. Low confidence leads to a Student Central handoff. "Talk to a person" is always visible. |
| Privacy (APP / Privacy Act 1988) | Student IDs, emails and phone numbers are masked before logging. Logging is off by default. Raw Adviser data is git-ignored. |
| Wellbeing | Crisis messages bypass matching and go straight to emergency and counselling contacts. |
| Academic integrity | "Can you write my essay for me" is declined, with pointers to writing help, the lecturer and extensions. Normal questions like "how do I write an essay?" are unaffected. |
| Out of scope | Questions about grades, fees owed, enrolment status, visa status or application outcomes are always handed to a human. |

---

## Evaluation results

### 1. Real first-year questions (`data/real_eval.json`, `scripts/evaluate_real.py`)

108 real questions from the CDU New Student Q&A Corner, names removed. Each is labelled with the knowledge-base entries that would correctly answer it, judged by topic. The set is split by question id: the **dev** half (even ids) was used to find gaps and draft new entries; the **test** half (odd ids, 59 questions, 51 answerable) is held out.

| Test half (held out) | Original bot (64 entries) | + official FAQs and drafts (291 entries) | + question-sentence scoring | + clear-winner rule, vocabulary, integrity guardrail |
|---|---|---|---|---|
| Resolved (answer or right "Did you mean") | 25.5% | 47.1% | 52.9% | **51.0%** |
| Answered directly and correctly | 3.9% | 9.8% | 15.7% | **17.6%** |
| Wrong answer given | 1 (1.7%) | 1 (1.7%) | 2 (3.4%) | 2 (3.4%) |

Real questions are much harder than hand-written ones: they're long, chatty and often about one person's situation. Most unresolved ones are handed to Student Central rather than answered wrongly. Honest caveats: the test half was checked twice while choosing the sentence-scoring rule (the first version raised wrong answers to 6, so it was replaced with the stricter question-only rule). The last round of changes was tuned only on the dev half and the hand-written set, then measured once on the test half: it helped there but was roughly flat on unseen real questions (one more direct answer, two fewer correct "Did you mean" options). TF-IDF matching is close to its ceiling on long, chatty questions; sentence embeddings are the next step (pretrained models couldn't be downloaded in the build environment).

### 2. Hand-written held-out set (`data/eval_set.json`, `scripts/evaluate.py`)

| Measure | Result |
|---|---|
| In-scope questions answered with the correct approved answer | **67 / 83 (80.7%)** |
| …plus correct answer offered via "Did you mean…?" | 12 more → **95.2% resolved** |
| **Wrong answer given confidently** | **2 / 83 (2.4%)** |
| Out-of-scope questions safely deferred | **18 / 20 (90%)** |
| Personal-record questions handed to a human | 10 / 10 |
| Crisis messages routed to safety resources | 5 / 5 |

None of the evaluation questions appear in the knowledge base (tests enforce this for both sets). Thresholds were chosen with `--sweep`, which penalises a wrong answer 3× more than a deferral, on this same set, so these numbers are slightly optimistic. The two out-of-scope questions still answered ("can I get a tax file number", "how do I become a tutor") hit new official entries on TFN errors and online tutoring.

---

## Updating the knowledge base

Edit `data/faqs.json`. No code changes are needed, and the app re-indexes on start. Each entry looks like this:

```json
{
  "id": "wifi",
  "category": "IT and Wi-Fi",
  "level": "university",            // or "unit"
  "question": "How do I get access to Wi-Fi?",
  "alternatives": ["eduroam login", "connect to wifi on campus"],
  "answer": "Markdown-lite: **bold**, - bullets, 1. numbered lists",
  "links": [{"label": "…", "url": "https://…"}],
  "source": {"doc": "WCFAQ", "page": 5},
  "approved": true,
  "review_flag": null               // or a note for staff to check
}
```

To improve matching for a question the bot misses, **add the student's real phrasing to `alternatives`**. Then add a different phrasing of the same question to `eval_set.json` and re-run `pytest` and `scripts/evaluate.py`.

### Rebuilding from the collected dataset

`data/faqs.json` is generated. Edit `data/faqs_curated.json` (the 64 hand-written entries) or `data/qa_corner_faqs.json` (team drafts), then run:

```bash
python scripts/import_dataset.py      # merges data/raw/cdu_chatbot_dataset.xlsx into data/faqs.json
```

The import keeps the official Library, Student Central, results, key-dates and StudyStays FAQs, and trims answers to chat size with a link to the full page. It drops staff-only, research-degree, landlord and archived material, and course pages for prospective applicants (add `--include-course-level` to keep the medical program and Master of IT pages). Imported questions that duplicate a curated entry become extra phrasings of it. Every decision is listed in `data/import_report.json`.

The Q&A Corner is not imported as answers: staff replies there are personal, dated and name students. Its questions are the real-world test set instead.

When the phone and email dataset arrives, put the raw file in `data/private/` (git-ignored), remove personal details first, and only then turn its questions into `alternatives` and evaluation items.

---

## Project structure

```
app/
  __init__.py        Flask app: routes, guardrail flow, logging, rate limit, security headers
  voice.py           Rewrites answers so they sound right when spoken
  analytics.py       Summarises the masked log for /admin
  matcher.py         TF-IDF FAQ matcher with confidence bands
  safety.py          Crisis / personal-record / small-talk routing, PII masking
  templates/index.html, admin.html
  static/app.js, style.css, admin.css   Chat UI + voice agent (no frameworks; Google Fonts only)
  static/brand/      Drop the official logo here once approved
data/
  faqs.json          Knowledge base (generated): 291 entries, 279 approved
  faqs_curated.json  64 hand-written entries from the Welcome Centre FAQ
  qa_corner_faqs.json 8 team drafts for common Q&A Corner topics (need staff sign-off)
  raw/               Collected dataset (cdu_chatbot_dataset.xlsx, 29 Sep 2026)
  import_report.json What the import kept, merged and skipped, with reasons
  eval_set.json      Held-out hand-written evaluation questions
  real_eval.json     108 real Q&A Corner questions, labelled, dev/test split
scripts/import_dataset.py  Builds faqs.json from the curated entries + collected dataset
scripts/evaluate.py  Evaluation + threshold sweep
scripts/evaluate_real.py   Evaluation on real student questions
tests/test_app.py    Tests
DATA_NOTES.md        Data-cleaning decisions and open questions for the Adviser
streamlit_app.py     Streamlit app (text + voice, staff view, dashboard)
app/core.py          Shared answering logic used by Flask and Streamlit
app/speech_io.py     Server-side speech-to-text and text-to-speech (Streamlit)
assets/cdu-logo.png  Logo shown in the header
.streamlit/          Theme and secrets template
wsgi.py · Dockerfile · render.yaml · Procfile · requirements.txt · packages.txt
```

## API

| Method | Path | Body / response |
|---|---|---|
| POST | `/api/chat` | `{"message": "...", "previous": "..."}` → `type`: `answer` / `clarify` / `fallback` / `handoff` / `crisis` / `smalltalk` |
| GET | `/api/faq/<id>` | One FAQ, used by "Did you mean" and the topics drawer |
| GET | `/api/topics` | All FAQs grouped by category |
| POST | `/api/feedback` | `{"faq_id": "wifi", "helpful": true}` |
| GET | `/api/suggest?q=` | Up to 4 matching questions while typing (not logged) |
| GET | `/admin` | Staff dashboard (needs `ADMIN_TOKEN`) |
| GET | `/healthz` | `{"status": "ok", "faqs": 291}` |

Every chat response also carries a `speech` field: the answer rewritten for text-to-speech.

**Note on logs:** on Render's free plan the disk is wiped on each deploy or restart, so dashboard data won't survive. For the testing round with the Adviser's team, either export `logs/interactions.jsonl` before redeploying, or add a Render persistent disk and set `LOG_PATH` to a file on it.
