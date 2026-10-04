"""Evaluate on real first-year questions from the New Student Q&A Corner (data/real_eval.json).

Real questions are long and chatty ("Hi, I'm new and studying nursing online... are lectures
recorded?"), so this is a much harder test than the hand-written eval set.

Outcomes per question:
  correct  - answered with an acceptable entry
  clarify  - "Did you mean" offered, and one of the options is acceptable
  deferred - handed to Student Central (right when nothing in the KB answers it)
  wrong    - answered with an entry that doesn't answer the question (the failure that matters)

Usage:
  python scripts/evaluate_real.py                    # test split (held out)
  python scripts/evaluate_real.py --split all --details
  KB_PATH=data/faqs_curated.json python scripts/evaluate_real.py   # the original 64-entry KB
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import Assistant  # noqa: E402


def run(split: str = "test", details: bool = False, kb: str | None = None,
        answer_t: float = 0.45, clarify_t: float = 0.24) -> dict:
    kb = kb or os.environ.get("KB_PATH", str(ROOT / "data" / "faqs.json"))
    bot = Assistant(kb, answer_t, clarify_t)
    items = json.loads((ROOT / "data" / "real_eval.json").read_text(encoding="utf-8"))["items"]
    items = [i for i in items if split == "all" or i["split"] == split]
    counts = {"correct": 0, "clarify": 0, "deferred_ok": 0, "deferred_missed": 0, "wrong": 0, "clarify_miss": 0}
    misses = []
    for it in items:
        res, _ = bot.respond(it["question"])
        acc = set(it["accept"])
        t = res["type"]
        if t == "answer":
            ok = res["faq"]["id"] in acc
            counts["correct" if ok else "wrong"] += 1
            if not ok:
                misses.append(("WRONG", it, res["faq"]["id"]))
        elif t == "clarify":
            ids = [o["id"] for o in res["options"]]
            if acc & set(ids):
                counts["clarify"] += 1
            elif acc:
                counts["clarify_miss"] += 1
                misses.append(("CLARIFY-MISS", it, ids))
            else:
                counts["deferred_ok"] += 1  # nothing right to offer; the fallback button still leads to Student Central
        else:  # fallback / handoff
            if acc:
                counts["deferred_missed"] += 1
                misses.append(("DEFERRED", it, None))
            else:
                counts["deferred_ok"] += 1
    n = len(items)
    answerable = sum(1 for i in items if i["accept"])
    out = {"split": split, "n": n, "answerable": answerable, **counts,
           "resolved_pct": round(100 * (counts["correct"] + counts["clarify"]) / max(answerable, 1), 1),
           "correct_pct": round(100 * counts["correct"] / max(answerable, 1), 1),
           "wrong_pct": round(100 * counts["wrong"] / n, 1)}
    if details:
        for kind, it, got in misses:
            print(f"  [{kind}] #{it['qid']} {it['question'][:90]!r} accept={it['accept'][:3]} got={got}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["test", "dev", "all"])
    ap.add_argument("--details", action="store_true")
    a = ap.parse_args()
    r = run(a.split, a.details)
    print(f"=== Real student questions ({r['split']}): {r['n']} questions, {r['answerable']} answerable from the KB ===")
    print(f"  Answered correctly ............ {r['correct']:3d}   {r['correct_pct']}% of answerable")
    print(f"  Right option in 'Did you mean'  {r['clarify']:3d}")
    print(f"  Resolved (answer + clarify) ... {r['resolved_pct']}% of answerable")
    print(f"  Deferred, nothing to answer ... {r['deferred_ok']:3d}")
    print(f"  Deferred, answer existed ...... {r['deferred_missed'] + r['clarify_miss']:3d}")
    print(f"  Wrong answer given ............ {r['wrong']:3d}   {r['wrong_pct']}% of all")


if __name__ == "__main__":
    main()
