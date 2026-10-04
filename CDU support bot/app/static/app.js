(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const log = $("#log"), form = $("#form"), input = $("#input"), send = $("#send");
  const drawer = $("#drawer"), scrim = $("#scrim"), browseBtn = $("#browse-btn");
  const suggestBox = $("#suggest");
  // Staff testing mode: open the page with ?review=<ADMIN_TOKEN> to see sources, scores and review notes.
  const REVIEW = new URLSearchParams(location.search).get("review") || "";
  const staffHeaders = REVIEW ? { "X-Review-Token": REVIEW } : {};
  const STORE_KEY = "cdu-assistant-chat-v2";

  let lastQuestion = "";
  let busy = false;
  let history = []; // [{role:"user"|"bot", data}] persisted for this browser tab only

  // ------------------------------------------------------------ storage (best effort)
  const store = {
    get(k, area = sessionStorage) { try { return JSON.parse(area.getItem(k)); } catch { return null; } },
    set(k, v, area = sessionStorage) { try { area.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
    del(k, area = sessionStorage) { try { area.removeItem(k); } catch { /* ignore */ } },
  };

  // ------------------------------------------------------------ theme
  const root = document.documentElement;
  const savedTheme = store.get("cdu-theme", localStorage);
  if (savedTheme) root.dataset.theme = savedTheme;
  $("#theme-btn").addEventListener("click", () => {
    const t = root.dataset.theme;
    const dark = t === "dark" || (t !== "light" && !matchMedia("(prefers-color-scheme: light)").matches);
    root.dataset.theme = dark ? "light" : "dark";
    store.set("cdu-theme", root.dataset.theme, localStorage);
  });

  // ------------------------------------------------------------ safe mini-markdown
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, "$1<em>$2</em>");
  function md(text) {
    const out = [];
    for (const block of String(text).split(/\n{2,}/)) {
      let list = null, para = [];
      const flushPara = () => { if (para.length) { out.push(`<p>${para.join("<br>")}</p>`); para = []; } };
      const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.join("")}</${list.tag}>`); list = null; } };
      for (const line of block.split("\n")) {
        const ul = line.match(/^\s*-\s+(.*)/), ol = line.match(/^\s*\d+\.\s+(.*)/);
        if (ul || ol) {
          flushPara();
          const tag = ul ? "ul" : "ol";
          if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
          list.items.push(`<li>${inline((ul || ol)[1])}</li>`);
        } else { flushList(); para.push(inline(line)); }
      }
      flushPara(); flushList();
    }
    return out.join("");
  }
  const plain = (text) => String(text).replace(/\*\*|\*/g, "").replace(/^\s*-\s+/gm, "• ");

  function el(tag, attrs = {}, html) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (html !== undefined) n.innerHTML = html;
    return n;
  }
  const ICON = {
    out: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
    speak: '<svg viewBox="0 0 24 24"><path d="M4 9v6h4l5 4V5L8 9zM16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/></svg>',
    stop: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
    copy: '<svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>',
    up: '<svg viewBox="0 0 24 24"><path d="M7 11v9H4v-9zM7 11l4-8a2 2 0 0 1 2 2v4h5.5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.3 20H7"/></svg>',
    down: '<svg viewBox="0 0 24 24"><path d="M17 13V4h3v9zM17 13l-4 8a2 2 0 0 1-2-2v-4H5.5a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6.7 4H17"/></svg>',
  };

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 3200);
  }
  const scrollDown = () => window.scrollTo({ top: document.body.scrollHeight, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });

  // ------------------------------------------------------------ rendering
  function hideWelcome() { const w = $("#welcome"); if (w) w.hidden = true; }

  function addMsg(role, data, { fresh = true, save = true } = {}) {
    hideWelcome();
    const m = el("div", { class: `msg ${role}${fresh ? " fresh" : ""}` });
    if (role === "user") m.append(el("div", { class: "bubble" }, esc(data.text)));
    else if (data.type === "answer") buildAnswer(m, data, fresh);
    else buildMessage(m, data, fresh);
    log.append(m);
    if (save) { history.push({ role, data }); store.set(STORE_KEY, history.slice(-60)); }
    if (fresh) scrollDown();
    return m;
  }

  function optionButtons(container, options) {
    for (const o of options) {
      const b = el("button", { class: "opt", type: "button" }, esc(o.question));
      b.addEventListener("click", () => openFaq(o.id, o.question));
      container.append(b);
    }
  }

  function speakButton(getText) {
    const b = el("button", { class: "tool", type: "button", "aria-pressed": "false", title: "Read aloud" }, ICON.speak + "<span>Listen</span>");
    if (!tts.supported) b.hidden = true;
    b.addEventListener("click", () => {
      if (b.getAttribute("aria-pressed") === "true") { tts.cancel(); return; }
      document.querySelectorAll('.tool[aria-pressed="true"][title="Read aloud"]').forEach(resetSpeakBtn);
      b.setAttribute("aria-pressed", "true"); b.innerHTML = ICON.stop + "<span>Stop</span>";
      tts.speak(getText(), () => resetSpeakBtn(b));
    });
    return b;
  }
  function resetSpeakBtn(b) { b.setAttribute("aria-pressed", "false"); b.innerHTML = ICON.speak + "<span>Listen</span>"; }

  function buildAnswer(m, data) {
    const f = data.faq;
    const b = el("div", { class: "bubble glass" });
    b.append(el("h3", { class: "qtitle" }, esc(f.question)));
    b.insertAdjacentHTML("beforeend", md(f.answer));
    if (f.links?.length) {
      const l = el("div", { class: "links" });
      for (const k of f.links) {
        if (!/^https:\/\//.test(k.url)) continue;
        l.append(el("a", { href: k.url, target: "_blank", rel: "noopener noreferrer" }, esc(k.label) + ICON.out));
      }
      b.append(l);
    }
    if (f.staff?.review_flag) b.append(el("div", { class: "note" }, "Staff review: " + esc(f.staff.review_flag)));
    if (data.pii_note) b.append(el("div", { class: "note" }, esc(data.pii_note)));
    m.append(b);

    const meta = el("div", { class: "meta" });
    if (f.staff) {
      const s = f.staff.source;
      meta.append(el("span", { class: "badge" + (s.approved ? "" : " draft") },
        `${esc(s.title)}${s.page ? `, p.${s.page}` : ""}${s.approved ? "" : " (not approved)"}${f.staff.score != null ? `, match ${f.staff.score}` : ""}`));
    }

    const tools = el("span", { class: "tools" });
    tools.append(speakButton(() => f.speech || plain(f.answer)));
    const copy = el("button", { class: "tool", type: "button", title: "Copy answer" }, ICON.copy + "<span>Copy</span>");
    copy.addEventListener("click", async () => {
      const text = `${f.question}\n\n${plain(f.answer)}${f.links?.length ? "\n\n" + f.links.map((k) => `${k.label}: ${k.url}`).join("\n") : ""}`;
      try { await navigator.clipboard.writeText(text); toast("Answer copied"); } catch { toast("Couldn't copy. Select the text instead."); }
    });
    tools.append(copy);
    for (const [label, val, icon] of [["Helpful", true, ICON.up], ["Not helpful", false, ICON.down]]) {
      const btn = el("button", { class: "tool", type: "button", "aria-pressed": "false", title: label, "aria-label": label }, icon);
      btn.addEventListener("click", () => {
        tools.querySelectorAll('[title="Helpful"],[title="Not helpful"]').forEach((x) => (x.disabled = true));
        btn.setAttribute("aria-pressed", "true");
        fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ faq_id: f.id, helpful: val }) }).catch(() => {});
        if (val) toast("Thanks for the feedback");
        else addMsg("bot", { type: "smalltalk", message: "Sorry that didn't help. Try asking another way, or contact **Student Central** on **1800 061 963** or student.central@cdu.edu.au." });
      });
      tools.append(btn);
    }
    meta.append(tools);
    m.append(meta);

    if (data.related?.length) {
      const r = el("div", { class: "related" }, "<span>Related:</span>");
      optionButtons(r, data.related);
      m.append(r);
    }
  }

  function buildMessage(m, data) {
    const b = el("div", { class: "bubble glass" + (data.type === "crisis" ? " crisis" : "") }, md(data.message));
    if (data.type === "clarify") {
      const o = el("div", { class: "opts" });
      optionButtons(o, data.options);
      const none = el("button", { class: "opt", type: "button" }, "None of these");
      none.addEventListener("click", () => addMsg("bot", { type: "fallback", message: data.fallback, speech: data.fallback_speech }));
      o.append(none);
      b.append(o);
    }
    if (data.pii_note) b.append(el("div", { class: "note" }, esc(data.pii_note)));
    m.append(b);
    if (data.speech && data.type !== "clarify") {
      const meta = el("div", { class: "meta" });
      const tools = el("span", { class: "tools" });
      tools.append(speakButton(() => data.speech));
      meta.append(tools);
      m.append(meta);
    }
  }

  function typing() {
    hideWelcome();
    const m = el("div", { class: "msg bot fresh" });
    m.append(el("div", { class: "bubble glass typing", role: "status", "aria-label": "Assistant is typing" }, "<span></span><span></span><span></span>"));
    log.append(m); scrollDown();
    return m;
  }

  // ------------------------------------------------------------ API
  async function request(url, opts) {
    const t = typing();
    busy = true; send.disabled = true;
    try {
      const res = await fetch(url, { ...opts, headers: { ...(opts?.headers || {}), ...staffHeaders } });
      const data = await res.json().catch(() => ({}));
      t.remove();
      if (!res.ok && data.type !== "error") throw new Error(String(res.status));
      const shown = data.type === "error" ? { type: "error", message: data.message, speech: data.message } : data;
      addMsg("bot", shown);
      return shown;
    } catch {
      t.remove();
      const err = { type: "error", message: "I couldn't connect just now. Try again, or call **Student Central** on **1800 061 963**.", speech: "I couldn't connect just now. Please try again." };
      addMsg("bot", err);
      return err;
    } finally {
      busy = false; send.disabled = false;
    }
  }

  function ask(text, mode = "text") {
    text = text.trim();
    if (!text || busy) return Promise.resolve(null);
    addMsg("user", { text });
    const previous = lastQuestion;
    lastQuestion = text;
    return request("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, previous, mode }) });
  }

  function openFaq(id, question) {
    if (busy) return Promise.resolve(null);
    addMsg("user", { text: question });
    lastQuestion = question;
    return request(`/api/faq/${encodeURIComponent(id)}`);
  }

  // ------------------------------------------------------------ text-to-speech
  const tts = (() => {
    const synth = window.speechSynthesis;
    const supported = !!synth && "SpeechSynthesisUtterance" in window;
    let voice = null, token = 0;
    function pickVoice() {
      if (!supported) return;
      const vs = synth.getVoices();
      const pref = (fn) => vs.find(fn);
      voice = pref((v) => v.lang === "en-AU" && /natural|online|neural/i.test(v.name))
        || pref((v) => v.lang === "en-AU")
        || pref((v) => /^en-(GB|NZ)/.test(v.lang) && /natural|online|neural|google/i.test(v.name))
        || pref((v) => /^en-(GB|NZ|US)/.test(v.lang))
        || pref((v) => v.lang?.startsWith("en")) || null;
    }
    if (supported) { pickVoice(); synth.addEventListener?.("voiceschanged", pickVoice); }
    let current = null, watchdog = 0; // keep a reference: Chrome can garbage-collect an utterance and never fire onend
    function speak(text, onEnd, onBoundary) {
      if (!supported || !text) { onEnd?.(); return; }
      const my = ++token;
      clearTimeout(watchdog);
      // Chrome can silently drop an utterance queued straight after cancel(), so only cancel when needed
      // and wait a tick before speaking.
      const busy = synth.speaking || synth.pending;
      if (busy) synth.cancel();
      // Chrome stops long utterances after about 15 seconds, so speak sentence by sentence.
      const parts = String(text).match(/[^.!?]+[.!?]*\s*/g) || [String(text)];
      let i = 0, finished = false;
      const done = () => { if (finished || my !== token) return; finished = true; clearTimeout(watchdog); onEnd?.(); };
      const next = () => {
        if (my !== token) return;
        clearTimeout(watchdog);
        if (i >= parts.length) { done(); return; }
        const chunk = parts[i++].trim();
        if (!chunk) { next(); return; }
        const u = new SpeechSynthesisUtterance(chunk);
        current = u;
        if (voice) { u.voice = voice; u.lang = voice.lang; } else u.lang = "en-AU";
        u.rate = 1.02; u.pitch = 1;
        u.onend = next;
        u.onerror = (e) => { if (e.error === "interrupted" || e.error === "canceled") return; next(); };
        if (onBoundary) u.onboundary = onBoundary;
        // Watchdog: if the browser never reports the end, move on anyway.
        watchdog = setTimeout(next, 2000 + chunk.length * 80);
        synth.speak(u);
        if (synth.paused) synth.resume();
      };
      setTimeout(next, busy ? 120 : 0);
    }
    function cancel() { token++; clearTimeout(watchdog); if (supported && (synth.speaking || synth.pending)) synth.cancel(); document.querySelectorAll('.tool[aria-pressed="true"][title="Read aloud"]').forEach(resetSpeakBtn); }
    return { supported, speak, cancel };
  })();

  // ------------------------------------------------------------ speech-to-text
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const sttSupported = !!SR;
  const inFrame = (() => { try { return window.self !== window.top; } catch { return true; } })();
  const isMac = /Mac/i.test(navigator.platform || navigator.userAgent);
  function newRecognizer() {
    const r = new SR();
    r.lang = "en-AU"; r.interimResults = true; r.maxAlternatives = 1; r.continuous = false;
    return r;
  }
  // Read results with an index loop: the result list isn't iterable in every browser.
  function transcript(e) {
    let fin = "", interim = "";
    for (let i = 0; i < e.results.length; i++) {
      const res = e.results[i];
      if (!res || !res[0]) continue;
      if (res.isFinal) fin += res[0].transcript; else interim += res[0].transcript;
    }
    return { fin: fin.trim(), interim: interim.trim() };
  }
  function micErrorText(code) {
    const macHint = isMac ? " On a Mac, also check System Settings > Privacy & Security > Microphone allows your browser." : "";
    if ((code === "not-allowed" || code === "service-not-allowed") && inFrame)
      return "The microphone is blocked inside this preview. Open the page in its own Chrome, Edge or Safari tab to talk, or type your question.";
    if (location.protocol === "file:" && ["not-allowed", "service-not-allowed", "stuck", "network", "audio-capture"].includes(code))
      return "Chrome doesn't allow voice input on a file opened from your computer. Open it through localhost or a website instead (see the README). You can type below and I'll read the answers out.";
    if (code === "stuck") return "Speech recognition isn't responding in this window." + (inFrame ? " Open the page in its own Chrome tab to talk." : " Try Chrome or Edge.") + " You can type below and I'll read the answers out.";
    return ({
      "not-allowed": "Microphone access is blocked. Click the lock icon in the address bar, allow the microphone, then try again." + macHint,
      "service-not-allowed": "Speech recognition is turned off for this browser. In Safari it needs Dictation on (System Settings > Keyboard > Dictation). Chrome is the most reliable.",
      "audio-capture": "No microphone was found or it's in use by another app." + macHint,
      "network": "Speech recognition couldn't reach its online service. Check your internet connection. Brave and some privacy browsers block it, so try Chrome or Edge.",
      "language-not-supported": "This browser can't recognise English (Australia). Try Chrome or Edge.",
    })[code] || "I couldn't hear that. Tap to try again.";
  }

  // One-shot dictation into the text box.
  const micBtn = $("#mic-btn");
  let dictation = null;
  micBtn.addEventListener("click", () => {
    if (!sttSupported) { toast("Voice input works in Chrome, Edge and Safari. Firefox doesn't support it yet."); return; }
    if (dictation) { try { dictation.stop(); } catch { /* ignore */ } return; }
    tts.cancel();
    const r = newRecognizer(); dictation = r;
    const before = input.value ? input.value.trim() + " " : "";
    let heardText = "", failed = false;
    micBtn.classList.add("live"); micBtn.setAttribute("aria-label", "Stop dictation");
    input.placeholder = "Listening… speak now";
    r.onresult = (e) => {
      const t = transcript(e);
      heardText = t.fin || t.interim || heardText;
      input.value = before + heardText; grow();
    };
    r.onerror = (e) => {
      if (e.error === "aborted") return;
      if (e.error === "no-speech") { toast("I didn't hear anything. Tap the microphone and speak."); return; }
      failed = true; toast(micErrorText(e.error));
    };
    r.onend = () => {
      dictation = null; micBtn.classList.remove("live"); micBtn.setAttribute("aria-label", "Dictate your question");
      input.placeholder = matchMedia("(max-width: 640px)").matches ? "Ask a question…" : "Ask about enrolment, Wi-Fi, buses…";
      // Some browsers never mark speech as final, so send whatever was heard.
      if (!failed && heardText.trim()) { const v = input.value; input.value = ""; grow(); ask(v); }
    };
    try { r.start(); } catch (err) {
      dictation = null; micBtn.classList.remove("live");
      toast(micErrorText(err?.name === "NotAllowedError" ? "not-allowed" : ""));
    }
  });

  // ------------------------------------------------------------ voice agent
  const voice = (() => {
    const panel = $("#voice"), orb = $("#orb"), status = $("#voice-status"), heard = $("#voice-heard"), reply = $("#voice-reply");
    const orbLabel = $("#orb-label"), muteBtn = $("#voice-mute");
    let state = "idle", rec = null, active = false, misses = 0, muted = false, pendingClarify = null;
    let lastFocus = null, everHeard = false, micBroken = false, startTimer = 0;
    const isSafari = /Safari\//.test(navigator.userAgent) && !/Chrome\/|Edg\//.test(navigator.userAgent);

    const EXIT = /^(stop|stop listening|end|exit|quit|goodbye|bye|that'?s all|thanks,? that'?s all|no thanks|i'?m done)[.!]?$/i;
    const NUMBERS = [/\b(one|1|first|1st)\b/i, /\b(two|2|second|2nd)\b/i, /\b(three|3|third|3rd)\b/i];

    // ---- diagnostics: shown under the voice controls so problems can be reported precisely
    const diagEl = $("#voice-diag");
    const diag = { perm: "unknown", event: "none" };
    const browserName = (() => {
      const ua = navigator.userAgent;
      if (/Edg\//.test(ua)) return "Edge"; if (/OPR\//.test(ua)) return "Opera";
      if (/Chrome\//.test(ua)) return navigator.brave ? "Brave" : "Chrome";
      if (/Safari\//.test(ua)) return "Safari"; if (/Firefox\//.test(ua)) return "Firefox"; return "Other";
    })();
    function renderDiag() {
      diagEl.textContent = `Voice check: ${browserName} · speech recognition ${sttSupported ? "available" : "not available"} · ` +
        `mic permission ${diag.perm} · ${inFrame ? "embedded preview" : "own tab"} · last event: ${diag.event}`;
    }
    function note(ev) { diag.event = ev; renderDiag(); }
    async function readPermission() {
      try {
        const st = await navigator.permissions.query({ name: "microphone" });
        diag.perm = st.state; st.onchange = () => { diag.perm = st.state; renderDiag(); };
      } catch { diag.perm = "unknown"; }
      renderDiag();
    }

    // "Test microphone": shows a live level for a few seconds, separately from speech recognition.
    async function testMic() {
      clearTimeout(startTimer);
      const old = rec; rec = null; try { old?.abort(); } catch { /* ignore */ }
      tts.cancel();
      const meter = $("#voice-meter"), bar = $("#voice-meter-bar");
      if (!navigator.mediaDevices?.getUserMedia) { setState("error", "This browser view can't access a microphone." + (inFrame ? " Open the page in its own tab." : "")); return; }
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (err) {
        note("mic test: " + (err?.name || "error"));
        setState("error", err?.name === "NotFoundError" ? micErrorText("audio-capture") : micErrorText("not-allowed"));
        return;
      }
      setState("paused", "Say something. Watch the bar move.");
      meter.hidden = false;
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const an = ctx.createAnalyser(); an.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.fftSize);
      let peak = 0; const t0 = performance.now();
      await new Promise((done) => {
        const tick = () => {
          an.getByteTimeDomainData(buf);
          let sum = 0; for (let i = 0; i < buf.length; i++) { const d = (buf[i] - 128) / 128; sum += d * d; }
          const lvl = Math.min(1, Math.sqrt(sum / buf.length) * 6);
          peak = Math.max(peak, lvl); bar.style.width = (lvl * 100).toFixed(0) + "%";
          if (performance.now() - t0 < 4000) requestAnimationFrame(tick); else done();
        };
        tick();
      });
      stream.getTracks().forEach((t) => t.stop()); ctx.close().catch(() => {});
      meter.hidden = true; bar.style.width = "0";
      const label = stream.getAudioTracks()[0]?.label || "microphone";
      note(`mic test peak ${(peak * 100).toFixed(0)}% on "${label}"`);
      if (peak < 0.04) setState("error", `No sound reached the page from "${label}". Check it's the right input and not muted` + (isMac ? ", and that System Settings > Privacy & Security > Microphone allows your browser." : "."));
      else setState("paused", "Your microphone works. Tap the orb and ask your question.");
    }

    function setState(s, text) {
      state = s; orb.dataset.state = s;
      if (s !== "listening") delete orb.dataset.hearing;
      if (text !== undefined) status.textContent = text;
      orbLabel.textContent = s === "listening" ? "Stop listening" : s === "speaking" ? "Interrupt and talk" : "Tap to talk";
    }

    function open() {
      if (!sttSupported) { toast("Voice chat works in Chrome, Edge and Safari. Firefox doesn't support it yet, but you can type your question."); return; }
      lastFocus = document.activeElement;
      tts.cancel(); closeDrawer(true);
      panel.hidden = false; active = true; misses = 0; pendingClarify = null;
      heard.textContent = ""; reply.innerHTML = ""; reply.className = "voice-reply";
      orb.focus();
      diag.event = "none"; readPermission(); micBroken = false;
      if (isSafari) {
        // Safari only starts the microphone from a tap, so listen straight away.
        listen("Hi! What do you need help with?");
      } else {
        setState("speaking", "Hi! What do you need help with?");
        say("Hi. What do you need help with?", () => listen("Listening… ask your question"), "Hi! What do you need help with?");
      }
    }

    function close() {
      active = false; clearTimeout(startTimer);
      const r = rec; rec = null;
      try { r?.abort(); } catch { /* ignore */ }
      tts.cancel();
      panel.hidden = true; setState("idle", "");
      lastFocus?.focus?.();
    }

    function say(text, then, label = "Speaking…") {
      setState("speaking", label);
      if (muted || !tts.supported) { setTimeout(() => active && then?.(), 400); return; }
      tts.speak(text, () => { if (active) then?.(); });
    }

    function listen(label = "Listening…") {
      if (!active) return;
      const old = rec; rec = null;
      try { old?.abort(); } catch { /* ignore */ }
      tts.cancel();
      const r = newRecognizer(); rec = r;
      let heardText = "", errored = false;
      setState("listening", label);
      clearTimeout(startTimer);
      // Some views (desktop apps, embedded previews) give a recognizer that never responds.
      startTimer = setTimeout(() => { if (rec === r && active) { note("no response from speech recognition"); micFailed("stuck"); } }, 5000);
      r.onaudiostart = () => { clearTimeout(startTimer); note("listening started"); };
      r.onsoundstart = () => note("sound detected");
      r.onspeechstart = () => { if (rec === r) orb.dataset.hearing = "1"; note("speech detected"); };
      r.onresult = (e) => {
        if (rec !== r) return;
        const t = transcript(e);
        heardText = t.fin || t.interim || heardText;
        heard.textContent = heardText;
        note("heard words");
      };
      r.onerror = (e) => {
        if (rec !== r || e.error === "aborted") return;
        note("error: " + e.error);
        if (e.error === "no-speech") return; // handled in onend
        errored = true; clearTimeout(startTimer);
        if (!everHeard && e.error !== "not-allowed" && e.error !== "service-not-allowed") { micFailed(e.error); return; }
        if (!everHeard) { micFailed(e.error); return; }
        // After a first successful turn, a refusal is usually the browser wanting a fresh tap.
        if (everHeard && (e.error === "not-allowed" || e.error === "service-not-allowed")) setState("paused", "Tap the orb to ask another question");
        else setState("error", micErrorText(e.error));
      };
      r.onend = () => {
        if (rec !== r || !active) return;
        rec = null; clearTimeout(startTimer);
        if (errored) return;
        // Use whatever was heard, even if the browser never marked it final.
        if (heardText.trim()) { misses = 0; everHeard = true; handle(heardText.trim()); return; }
        if (++misses < 3) { listen("Still listening… go ahead"); return; }
        setState("paused", "I didn't hear anything. Tap Test microphone to check your mic, or tap the orb to try again.");
      };
      try { r.start(); }
      catch (err) {
        rec = null; clearTimeout(startTimer);
        if (err?.name === "NotAllowedError") micFailed("not-allowed");
        else setState("paused", "Tap the orb to talk");
      }
    }

    // When the microphone can't be used here, say so out loud and switch to typed questions with spoken answers.
    function micFailed(code) {
      const r = rec; rec = null; try { r?.abort(); } catch { /* ignore */ }
      micBroken = true;
      const msg = micErrorText(code);
      setState("error", msg);
      tts.speak("I can't hear you from here. Type your question below and I'll read the answer out.", () => {});
      const vi = $("#voice-input"); vi.focus();
    }

    function showReply(data) {
      reply.className = "voice-reply" + (data.type === "crisis" ? " crisis" : "");
      if (data.type === "answer") reply.innerHTML = `<p><strong>${esc(data.faq.question)}</strong></p>` + md(data.faq.answer);
      else if (data.type === "clarify") reply.innerHTML = md(data.message) + "<ol>" + data.options.map((o) => `<li>${esc(o.question)}</li>`).join("") + "</ol>";
      else reply.innerHTML = md(data.message || "");
    }

    async function respond(promise) {
      setState("thinking", "Thinking…");
      const data = await promise;
      if (!active || !data) return;
      showReply(data);
      pendingClarify = data.type === "clarify" ? data : null;
      let speech = data.type === "answer" ? data.faq.speech : data.speech;
      if (data.type === "answer" && data.faq.links?.length) speech += " I've put the links in the chat.";
      if (data.type === "crisis") {
        // Don't keep the loop going after a crisis message; keep the help on screen.
        say(speech, () => setState("paused", "Please reach out to one of these services"));
        return;
      }
      say(speech || "Okay.", () => {
        heard.textContent = "";
        if (micBroken) setState("paused", "Type another question, or tap the orb to try the microphone again");
        else listen("Listening… ask another question");
      });
    }

    function handle(text) {
      if (EXIT.test(text)) { say("Okay. Good luck with your studies!", close); return; }
      if (pendingClarify) {
        const c = pendingClarify;
        if (/\b(none|neither|no|nope|something else)\b/i.test(text)) {
          pendingClarify = null;
          const fb = { type: "fallback", message: c.fallback, speech: c.fallback_speech };
          addMsg("bot", fb);
          respond(Promise.resolve(fb));
          return;
        }
        const short = text.split(/\s+/).length <= 4; // "number two", "the first one"
        const idx = short ? NUMBERS.findIndex((re) => re.test(text)) : -1;
        if (idx > -1 && c.options[idx]) { pendingClarify = null; respond(openFaq(c.options[idx].id, c.options[idx].question)); return; }
        pendingClarify = null; // treat it as a new question
      }
      respond(ask(text, "voice"));
    }

    orb.addEventListener("click", () => {
      if (state === "listening") { try { rec?.stop(); } catch { /* ignore */ } return; }
      tts.cancel(); misses = 0; micBroken = false; listen();
    });
    muteBtn.addEventListener("click", () => {
      muted = !muted; muteBtn.setAttribute("aria-pressed", String(muted));
      muteBtn.textContent = muted ? "Unmute replies" : "Mute replies";
      if (muted && state === "speaking") { tts.cancel(); listen(); }
    });
    $("#voice-end").addEventListener("click", close);
    $("#voice-test").addEventListener("click", testMic);
    $("#voice-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const vi = $("#voice-input"), text = vi.value.trim();
      if (!text) return;
      vi.value = "";
      const old = rec; rec = null; try { old?.abort(); } catch { /* ignore */ }
      clearTimeout(startTimer);
      heard.textContent = text;
      handle(text);
    });
    panel.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
      if (e.key === "Tab") { // keep focus inside the dialog
        const f = [...panel.querySelectorAll("button")].filter((b) => !b.hidden);
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    return { open, close };
  })();
  $("#voice-btn").addEventListener("click", voice.open);
  $("#voice-cta").addEventListener("click", voice.open);
  if (!sttSupported) { $("#voice-cta small").textContent = "Available in Chrome, Edge and Safari"; }

  // ------------------------------------------------------------ suggestions as you type
  let sugItems = [], sugIndex = -1, sugTimer = 0, sugSeq = 0;
  function hideSuggest() { suggestBox.hidden = true; sugItems = []; sugIndex = -1; input.setAttribute("aria-expanded", "false"); }
  function renderSuggest() {
    suggestBox.innerHTML = "";
    if (!sugItems.length) { hideSuggest(); return; }
    suggestBox.append(el("li", { class: "hint", role: "presentation" }, "Matching questions"));
    sugItems.forEach((s, i) => {
      const li = el("li", { role: "option", id: `sug-${i}`, "aria-selected": String(i === sugIndex) }, esc(s.question));
      li.addEventListener("mousedown", (e) => { e.preventDefault(); pickSuggest(i); });
      suggestBox.append(li);
    });
    suggestBox.hidden = false; input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-activedescendant", sugIndex > -1 ? `sug-${sugIndex}` : "");
  }
  function pickSuggest(i) { const s = sugItems[i]; hideSuggest(); input.value = ""; grow(); openFaq(s.id, s.question); }
  input.addEventListener("input", () => {
    grow();
    clearTimeout(sugTimer);
    const q = input.value.trim();
    if (q.length < 3) { hideSuggest(); return; }
    sugTimer = setTimeout(async () => {
      const my = ++sugSeq;
      try {
        const { suggestions } = await (await fetch(`/api/suggest?q=${encodeURIComponent(q)}`)).json();
        if (my !== sugSeq || input.value.trim() !== q) return;
        sugItems = suggestions || []; sugIndex = -1; renderSuggest();
      } catch { hideSuggest(); }
    }, 180);
  });
  input.addEventListener("blur", () => setTimeout(hideSuggest, 120));

  // ------------------------------------------------------------ composer
  if (matchMedia("(max-width: 640px)").matches) input.placeholder = "Ask a question…";
  function grow() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 150) + "px"; }
  input.addEventListener("keydown", (e) => {
    if (!suggestBox.hidden && sugItems.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); sugIndex = (sugIndex + 1) % sugItems.length; renderSuggest(); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); sugIndex = (sugIndex - 1 + sugItems.length) % sugItems.length; renderSuggest(); return; }
      if (e.key === "Escape") { hideSuggest(); return; }
      if (e.key === "Enter" && sugIndex > -1) { e.preventDefault(); pickSuggest(sugIndex); return; }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); hideSuggest(); const v = input.value; input.value = ""; grow(); tts.cancel(); ask(v); input.focus(); });
  document.querySelectorAll("#starter-chips button").forEach((b) => b.addEventListener("click", () => ask(b.dataset.q)));
  $("#human-btn").addEventListener("click", () => openFaq("student-central", "How do I talk to a real person?"));

  $("#new-btn").addEventListener("click", () => {
    tts.cancel(); history = []; lastQuestion = ""; store.del(STORE_KEY);
    log.innerHTML = ""; const w = $("#welcome"); if (w) w.hidden = false;
    window.scrollTo({ top: 0 }); input.focus();
  });

  // ------------------------------------------------------------ topics drawer
  let topicsLoaded = false;
  async function openDrawer() {
    drawer.hidden = false; scrim.hidden = false; browseBtn.setAttribute("aria-expanded", "true");
    $("#topic-filter").focus();
    if (topicsLoaded) return;
    try {
      const { topics } = await (await fetch("/api/topics")).json();
      const wrap = $("#topics");
      for (const t of topics) {
        const sec = el("section", { "data-cat": "" });
        sec.append(el("h3", {}, esc(t.category)));
        const ul = el("ul");
        for (const q of t.questions) {
          const li = el("li"), b = el("button", { type: "button" }, esc(q.question));
          b.addEventListener("click", () => { closeDrawer(); openFaq(q.id, q.question); });
          li.append(b); ul.append(li);
        }
        sec.append(ul); wrap.append(sec);
      }
      topicsLoaded = true;
    } catch { $("#topics").textContent = "Topics didn't load. Check your connection and try again."; }
  }
  function closeDrawer(silent) {
    if (drawer.hidden) return;
    drawer.hidden = true; scrim.hidden = true; browseBtn.setAttribute("aria-expanded", "false");
    if (!silent) browseBtn.focus();
  }
  $("#topic-filter").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase().trim();
    document.querySelectorAll("#topics section").forEach((sec) => {
      let any = false;
      sec.querySelectorAll("li").forEach((li) => { const hit = !q || li.textContent.toLowerCase().includes(q); li.hidden = !hit; any ||= hit; });
      sec.hidden = !any;
    });
  });
  browseBtn.addEventListener("click", openDrawer);
  $("#drawer-close").addEventListener("click", () => closeDrawer());
  scrim.addEventListener("click", () => closeDrawer());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !drawer.hidden) closeDrawer(); });

  // ------------------------------------------------------------ background photo slideshow
  (() => {
    const layers = [...document.querySelectorAll("#photos i")];
    if (!layers.length) return;
    layers.forEach((l) => { l.style.backgroundImage = `url("${l.dataset.src}")`; });
    let cur = 0;
    layers[0].classList.add("on");
    if (layers.length < 2 || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    setInterval(() => {
      if (document.hidden) return;
      layers[cur].classList.remove("on");
      cur = (cur + 1) % layers.length;
      layers[cur].classList.add("on");
    }, 8000);
  })();

  // ------------------------------------------------------------ restore this tab's chat
  const saved = store.get(STORE_KEY);
  if (Array.isArray(saved) && saved.length) {
    history = saved;
    for (const h of saved) addMsg(h.role, h.data, { fresh: false, save: false });
    const lastUser = [...saved].reverse().find((h) => h.role === "user");
    if (lastUser) lastQuestion = lastUser.data.text;
    requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight }));
  }
})();
