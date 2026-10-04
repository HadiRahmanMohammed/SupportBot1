/* In-browser engine for the standalone page.
 *
 * A port of app/matcher.py + app/safety.py + the /api routes in app/__init__.py.
 * The TF-IDF vocabularies and IDF weights are exported from the trained Python
 * index (scripts/build_standalone.py), so answers match the Flask server.
 * When window.CDU_KB is present, requests to /api/* are answered here instead of
 * going over the network.
 */
(() => {
  "use strict";
  const KB = window.CDU_KB;
  if (!KB) return;
  const P = KB.params;
  const STOP = new Set(KB.stop);
  const LOC = new Set(KB.location);
  const SYN = KB.synonyms.map(([p, r]) => [new RegExp(p, "gi"), r]);
  const IT_UPPER = new RegExp(KB.it_upper, "g");
  const IT_LOWER = new RegExp(KB.it_lower, "g");
  const SFX = KB.suffixes;

  // ---------------------------------------------------------------- text prep
  function normalise(text) {
    text = text.replace(IT_UPPER, "itms");
    text = text.toLowerCase().replace(/’/g, "'");
    text = text.replace(IT_LOWER, "itms $1");
    for (const [re, rep] of SYN) { re.lastIndex = 0; text = text.replace(re, rep); }
    text = text.replace(/[^a-z0-9@.'\s-]/g, " ");
    return text.replace(/\s+/g, " ").trim();
  }
  const pyStrip = (w, chars) => { let a = 0, b = w.length; while (a < b && chars.includes(w[a])) a++; while (b > a && chars.includes(w[b - 1])) b--; return w.slice(a, b); };
  function stem(w) {
    for (const s of SFX) if (w.endsWith(s) && w.length - s.length >= 3) return w.slice(0, -s.length);
    return w;
  }
  function wordTokens(text) {
    const out = [];
    for (let w of text.match(/[a-z0-9][a-z0-9'.-]*/g) || []) {
      w = pyStrip(w, ".'-");
      if (w.length > 1 && !STOP.has(w)) out.push(stem(w));
    }
    return out;
  }
  function contentStems(text) {
    const out = new Set();
    for (let w of normalise(text).match(/[a-z0-9][a-z0-9'.-]*/g) || []) {
      w = pyStrip(w, ".'-");
      if (w.length > 1 && !STOP.has(w) && !LOC.has(w)) out.add(stem(w));
    }
    return out;
  }
  const stripStop = (t) => t.split(" ").filter((w) => w && !STOP.has(w)).join(" ") || t;

  // ---------------------------------------------------------------- vectorisers
  function wordFeatures(text) {
    const toks = wordTokens(text), feats = [...toks];
    for (let i = 0; i + 1 < toks.length; i++) feats.push(toks[i] + " " + toks[i + 1]);
    return feats;
  }
  function charFeatures(text) {
    text = text.toLowerCase().replace(/\s\s+/g, " ");
    const feats = [];
    for (const raw of text.split(/\s+/).filter(Boolean)) {
      const w = " " + raw + " ";
      for (let n = 3; n <= 5; n++) {
        let off = 0;
        feats.push(w.slice(off, off + n));
        while (off + n < w.length) { off++; feats.push(w.slice(off, off + n)); }
        if (off === 0) break;
      }
    }
    return feats;
  }
  function vectorise(feats, idf) {
    const tf = new Map();
    for (const f of feats) if (idf[f] !== undefined) tf.set(f, (tf.get(f) || 0) + 1);
    const v = new Map(); let norm = 0;
    for (const [f, c] of tf) { const x = (1 + Math.log(c)) * idf[f]; v.set(f, x); norm += x * x; }
    norm = Math.sqrt(norm);
    if (norm > 0) for (const [f, x] of v) v.set(f, x / norm);
    return v;
  }
  const dot = (a, b) => { let s = 0; const [sm, lg] = a.size < b.size ? [a, b] : [b, a]; for (const [f, x] of sm) { const y = lg.get(f); if (y) s += x * y; } return s; };

  const docsW = KB.texts.map((t) => vectorise(wordFeatures(t), KB.word_idf));
  const docsC = KB.texts.map((t) => vectorise(charFeatures(stripStop(t)), KB.char_idf));
  const vocab = KB.vocab.map((v) => new Set(v));
  const FAQS = KB.faqs;
  const BY_ID = Object.fromEntries(FAQS.map((f) => [f.id, f]));

  // ---------------------------------------------------------------- matcher
  function scores(query) {
    const q = normalise(query);
    const w = vectorise(wordFeatures(q), KB.word_idf);
    const c = vectorise(charFeatures(stripStop(q)), KB.char_idf);
    const noWords = wordTokens(q).length === 0;
    const best = new Array(FAQS.length).fill(0);
    for (let i = 0; i < KB.texts.length; i++) {
      const cs = dot(c, docsC[i]);
      const comb = noWords ? cs * 0.7 : P.word_weight * dot(w, docsW[i]) + (1 - P.word_weight) * cs;
      const o = KB.owners[i];
      if (comb > best[o]) best[o] = comb;
    }
    return best;
  }
  function finalScores(query) {
    const s = scores(query);
    const words = normalise(query).split(" ").filter(Boolean);
    const core = words.filter((w) => !LOC.has(pyStrip(w, "?.!,'")));
    if (core.length === words.length) return s;
    const sc = core.length ? scores(core.join(" ")) : s.map(() => 0);
    return s.map((x, i) => Math.max(sc[i], Math.min(x, sc[i] + P.location_bonus)));
  }
  function coverage(query) {
    const q = contentStems(query);
    if (!q.size) return FAQS.map(() => 1);
    return vocab.map((v) => { let n = 0; for (const t of q) if (v.has(t)) n++; return n / q.size; });
  }
  function adjusted(text) {
    const f = finalScores(text), cov = coverage(text);
    return f.map((x, i) => x * (P.coverage_floor + (1 - P.coverage_floor) * cov[i]));
  }
  // Long messages dilute the real question, so each question sentence is also scored on its own.
  function segments(text) {
    const parts = text.replace(/([.?!])\s+/g, "$1\n").split("\n").map((p) => p.trim()).filter(Boolean);
    if (parts.length < 2) return [];
    const qs = new RegExp(P.question_start, "i");
    return parts.filter((p) => (p.endsWith("?") || qs.test(p)) && contentStems(p).size >= P.min_segment_stems);
  }
  function match(query, k = 3) {
    let s = adjusted(query);
    for (const seg of segments(query)) { const a = adjusted(seg); s = s.map((x, i) => Math.max(x, a[i])); }
    const order = s.map((x, i) => [x, i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]).slice(0, k);
    const cands = order.map(([score, i]) => ({ faq: FAQS[i], score }));
    const top = cands[0];
    const runnerUp = cands.length > 1 ? cands[1].score : 0;
    const clearWinner = top.score >= P.margin_min && top.score >= P.margin_ratio * runnerUp;
    if (top.score >= P.answer_threshold || clearWinner) return { band: "answer", top, cands };
    if (top.score >= P.clarify_threshold) return { band: "clarify", top, cands: cands.filter((c) => c.score >= P.clarify_threshold) };
    return { band: "fallback", top, cands };
  }

  // ---------------------------------------------------------------- guardrails
  const S = KB.safety;
  const rx = (p) => new RegExp(p, "i");
  const INTEGRITY = rx(S.integrity);
  const CRISIS = rx(S.crisis), PERSONAL = rx(S.personal), GREET = rx(S.greeting), THANKS = rx(S.thanks), BYE = rx(S.bye), WHO = rx(S.who);
  const PII = S.pii.map(([p, tok]) => [new RegExp(p, "g"), tok]);
  function classify(t) {
    if (CRISIS.test(t)) return "crisis";
    if (INTEGRITY.test(t)) return "integrity";
    if (PERSONAL.test(t)) return "personal";
    if (GREET.test(t)) return "greeting";
    if (THANKS.test(t)) return "thanks";
    if (BYE.test(t)) return "bye";
    if (WHO.test(t)) return "who";
    return null;
  }
  function maskPii(t) { let found = false; for (const [re, tok] of PII) { re.lastIndex = 0; if (re.test(t)) found = true; re.lastIndex = 0; t = t.replace(re, tok); } return [t, found]; }
  function stripPii(t) { for (const [re] of PII) { re.lastIndex = 0; t = t.replace(re, " "); } return t.replace(/\s+/g, " ").trim(); }

  // ---------------------------------------------------------------- routes
  const payload = (f) => ({ id: f.id, question: f.question, answer: f.answer, links: f.links, category: f.category, speech: f.speech });
  const PII_NOTE = "For your privacy, there's no need to share student numbers, emails or phone numbers here. I've ignored them.";

  function chat(body) {
    const text = String(body.message || "").trim().slice(0, 500);
    const previous = String(body.previous || "").trim().slice(0, 500);
    if (!text) return [400, { type: "error", message: "Please type a question." }];
    const [, hadPii] = maskPii(text);
    const pii_note = hadPii ? PII_NOTE : null;
    const route = classify(text);
    if (route === "crisis") return [200, { type: "crisis", message: S.replies.crisis, speech: S.speech.crisis, pii_note }];
    if (route === "personal") return [200, { type: "handoff", message: S.replies.personal, speech: S.speech.personal, pii_note }];
    if (route) return [200, { type: "smalltalk", message: S.replies[route], speech: S.speech[route], pii_note }];

    const query = stripPii(text);
    let r = match(query);
    if (r.band !== "answer" && previous && query.split(/\s+/).length <= 5) {
      const ctx = match(`${stripPii(previous)} ${query}`);
      const own = finalScores(query);
      const pick = ctx.cands.find((c) => c.score >= P.answer_threshold && own[FAQS.indexOf(c.faq)] >= P.followup_min);
      if (pick) r = { band: "answer", top: pick, cands: [pick, ...ctx.cands.filter((c) => c !== pick)] };
    }
    if (r.band === "answer") {
      const related = r.cands.slice(1).filter((c) => c.score >= P.related_min).slice(0, 2).map((c) => ({ id: c.faq.id, question: c.faq.question }));
      return [200, { type: "answer", faq: payload(r.top.faq), related, pii_note }];
    }
    if (r.band === "clarify") {
      const options = r.cands.map((c) => ({ id: c.faq.id, question: c.faq.question }));
      const words = ["one", "two", "three"];
      const speech = "I'm not completely sure what you mean. Did you mean: " +
        options.map((o, i) => `${words[i]}, ${o.question.replace(/\?+$/, "")}`).join("; ") + ". Say the number, or say none of these.";
      return [200, { type: "clarify", message: "I'm not completely sure what you mean. Did you mean one of these?", options, speech,
        fallback: S.replies.fallback, fallback_speech: S.speech.fallback, pii_note }];
    }
    return [200, { type: "fallback", message: S.replies.fallback, speech: S.speech.fallback, pii_note }];
  }

  function suggest(q) {
    q = q.trim().slice(0, 500);
    if (q.length < 3 || ["crisis", "personal"].includes(classify(q))) return [];
    const r = match(stripPii(q), 5);
    const floor = Math.max(P.suggest_min, r.cands[0].score * 0.6);
    return r.cands.filter((c) => c.score >= floor).slice(0, 4).map((c) => ({ id: c.faq.id, question: c.faq.question }));
  }

  function topics() {
    const cats = new Map();
    for (const f of FAQS) { if (!cats.has(f.category)) cats.set(f.category, []); cats.get(f.category).push({ id: f.id, question: f.question }); }
    return [...cats].map(([category, questions]) => ({ category, questions }));
  }

  function route(url, opts) {
    const u = new URL(url, "http://local");
    const body = opts?.body ? (() => { try { return JSON.parse(opts.body); } catch { return {}; } })() : {};
    if (u.pathname === "/api/chat") return chat(body);
    if (u.pathname === "/api/topics") return [200, { topics: topics() }];
    if (u.pathname === "/api/suggest") return [200, { suggestions: suggest(u.searchParams.get("q") || "") }];
    if (u.pathname === "/api/feedback") return [200, { ok: true }];
    const m = u.pathname.match(/^\/api\/faq\/(.+)$/);
    if (m) { const f = BY_ID[decodeURIComponent(m[1])]; return f ? [200, { type: "answer", faq: payload(f) }] : [404, { error: "not found" }]; }
    return [404, { error: "not found" }];
  }

  const realFetch = window.fetch?.bind(window);
  window.fetch = (url, opts) => {
    if (typeof url === "string" && url.startsWith("/api/")) {
      const [status, data] = route(url, opts);
      return new Promise((res) => setTimeout(() => res(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } })), 160));
    }
    return realFetch(url, opts);
  };
  window.CDU_ENGINE = { match, chat, suggest, normalise };
})();
