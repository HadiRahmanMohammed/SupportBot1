"""Evaluate the assistant on the held-out question set.

Runs every question through the full /api/chat pipeline (guardrails + matcher)
and reports the measures from the Progress Report, Section 7:
  1. how often the bot returns the correct approved answer
  2. how often it correctly defers instead of guessing
  3. how often it gives a wrong answer (the failure that matters most)

Usage:
  python scripts/evaluate.py                 # report at current thresholds
  python scripts/evaluate.py --sweep         # grid-search thresholds
  python scripts/evaluate.py --details       # list every miss
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


def run(answer_t: float | None = None, clarify_t: float | None = None, details: bool = False) -> dict:
    cfg = {"RATE_LIMIT_PER_MIN": 10**6, "LOG_INTERACTIONS": False, "ADMIN_TOKEN": "eval"}
    if answer_t is not None:
        cfg.update(ANSWER_THRESHOLD=answer_t, CLARIFY_THRESHOLD=clarify_t)
    client = create_app(cfg).test_client()
    ev = json.loads((ROOT / "data" / "eval_set.json").read_text())

    def ask(q):
        return client.post("/api/chat", json={"message": q}, headers={"X-Review-Token": "eval"}).get_json()

    r = {"in_total": 0, "correct": 0, "clarify_hit": 0, "clarify_miss": 0, "wrong": 0, "deferred": 0,
         "oos_total": 0, "oos_safe": 0, "oos_wrong": 0,
         "personal_total": 0, "personal_ok": 0, "crisis_total": 0, "crisis_ok": 0, "misses": []}

    for q, exp in ev["in_scope"]:
        r["in_total"] += 1
        a = ask(q)
        if a["type"] == "answer":
            if a["faq"]["id"] == exp:
                r["correct"] += 1
            else:
                r["wrong"] += 1
                r["misses"].append(("WRONG", q, exp, a["faq"]["id"], a["faq"]["staff"]["score"]))
        elif a["type"] == "clarify":
            ids = [o["id"] for o in a["options"]]
            if exp in ids:
                r["clarify_hit"] += 1
            else:
                r["clarify_miss"] += 1
                r["misses"].append(("CLARIFY-MISS", q, exp, ids, None))
        else:
            r["deferred"] += 1
            r["misses"].append(("DEFERRED", q, exp, a["type"], None))

    for q in ev["out_of_scope"]:
        r["oos_total"] += 1
        a = ask(q)
        if a["type"] == "answer":
            r["oos_wrong"] += 1
            r["misses"].append(("OOS-ANSWERED", q, "FALLBACK", a["faq"]["id"], a["faq"]["staff"]["score"]))
        else:
            r["oos_safe"] += 1

    for q in ev["personal"]:
        r["personal_total"] += 1
        a = ask(q)
        ok = a["type"] == "handoff"
        r["personal_ok"] += ok
        if not ok:
            r["misses"].append(("PERSONAL-MISSED", q, "PERSONAL", a["type"], None))

    for q in ev["crisis"]:
        r["crisis_total"] += 1
        a = ask(q)
        ok = a["type"] == "crisis"
        r["crisis_ok"] += ok
        if not ok:
            r["misses"].append(("CRISIS-MISSED", q, "CRISIS", a["type"], None))

    n = r["in_total"]
    r["answer_accuracy"] = r["correct"] / n
    r["resolved_rate"] = (r["correct"] + r["clarify_hit"]) / n
    r["wrong_rate"] = r["wrong"] / n
    r["oos_safe_rate"] = r["oos_safe"] / r["oos_total"]
    # Objective for tuning: reward correct answers, penalise confident wrong answers 3x
    r["objective"] = (r["correct"] + 0.5 * r["clarify_hit"] - 3 * r["wrong"] - 3 * r["oos_wrong"]) / (n + r["oos_total"])
    return r


def report(r: dict, details: bool) -> None:
    pct = lambda x: f"{100 * x:5.1f}%"  # noqa: E731
    print("\n=== CDU First Year Student Support: evaluation ===")
    print(f"In-scope questions ............. {r['in_total']}")
    print(f"  Correct approved answer ...... {r['correct']:3d}  {pct(r['answer_accuracy'])}")
    print(f"  Correct via 'Did you mean' ... {r['clarify_hit']:3d}")
    print(f"  Resolved (answer + clarify) .. {pct(r['resolved_rate'])}")
    print(f"  Wrong answer given ........... {r['wrong']:3d}  {pct(r['wrong_rate'])}")
    print(f"  Deferred to Student Central .. {r['deferred'] + r['clarify_miss']:3d}")
    print(f"Out-of-scope questions ......... {r['oos_total']}")
    print(f"  Safely deferred .............. {r['oos_safe']:3d}  {pct(r['oos_safe_rate'])}")
    print(f"  Wrongly answered ............. {r['oos_wrong']:3d}")
    print(f"Personal-record questions handed off .. {r['personal_ok']}/{r['personal_total']}")
    print(f"Crisis messages routed to safety ...... {r['crisis_ok']}/{r['crisis_total']}")
    if details and r["misses"]:
        print("\nMisses:")
        for kind, q, exp, got, score in r["misses"]:
            print(f"  [{kind}] {q!r}  expected={exp}  got={got}  score={score}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--details", action="store_true")
    args = ap.parse_args()
    if args.sweep:
        rows = []
        for a in [0.35, 0.38, 0.40, 0.42, 0.45, 0.48, 0.50, 0.55]:
            for c in [0.20, 0.24, 0.28, 0.32]:
                if c >= a:
                    continue
                res = run(a, c)
                rows.append((res["objective"], a, c, res))
        rows.sort(key=lambda x: -x[0])
        print("objective  answer_t  clarify_t  correct  clarify_hit  wrong  oos_wrong")
        for obj, a, c, res in rows[:12]:
            print(f"{obj:9.3f}  {a:8.2f}  {c:9.2f}  {res['correct']:7d}  {res['clarify_hit']:11d}  {res['wrong']:5d}  {res['oos_wrong']:9d}")
    else:
        report(run(details=args.details), args.details)
