"""
Field-scale measurement for the agentic mapper: generate N variant unknown
sources (each with randomly drawn conventions), let the model face every one
cold, and report acceptance statistics. This is the answer to "how often
does it fail?" -- measured, not asserted.

Run:  python mapper/benchmark.py --count 10
Cost: one short model call per variant per attempt (subscription or any
      OpenAI-compatible endpoint); everything else is free and deterministic.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from propose_mapping import run_propose

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "mapper", "runs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--start-seed", type=int, default=1)
    ap.add_argument("--backend", choices=["claude-cli", "openai-compatible"],
                    default="claude-cli")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--append", action="store_true",
                    help="resume/extend an existing benchmark.json instead of "
                         "starting fresh (safe to run in chunks)")
    ap.add_argument("--publish", action="store_true",
                    help="also write the committed summary the evidence page "
                         "renders (mapper/recorded/benchmark.json)")
    args = ap.parse_args()

    os.makedirs(RUNS, exist_ok=True)
    path = os.path.join(RUNS, "benchmark.json")
    results = []
    if args.append and os.path.exists(path):        # resume a chunked run
        with open(path, encoding="utf-8") as f:
            results = json.load(f).get("results", [])
        done = {r["seed"] for r in results}
        print(f"resuming: {len(results)} variant(s) already measured")
    else:
        done = set()

    for i in range(args.count):
        seed = args.start_seed + i
        if seed in done:
            continue
        src = os.path.join(ROOT, "incoming", f"variant_{seed}.txt")
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "generate_unknown_source.py"),
                            "--seed", str(seed)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"seed {seed}: generator failed: {r.stderr[:200]}")
            continue
        def field(prefix):
            return next((ln.split(":", 1)[1].strip() for ln in r.stdout.splitlines()
                         if ln.strip().startswith(prefix)), "")
        mode = field("mode").split(" --")[0]
        conventions = field("delimiter")
        should_accept = mode != "unmappable"
        print(f"[{i + 1}/{args.count}] seed {seed} [{mode}]  {conventions}")
        out = os.path.join(RUNS, f"variant_{seed}.json")
        accepted, attempts = run_propose(src, out, args.backend,
                                         args.max_attempts, quiet=True)
        n_att = len(attempts)
        correct = (accepted == should_accept)
        print(f"   -> {'ACCEPTED' if accepted else 'REJECTED'} after {n_att} "
              f"attempt(s) — {'correct' if correct else 'WRONG OUTCOME'}")
        results.append({"seed": seed, "mode": mode, "conventions": conventions,
                        "should_accept": should_accept, "accepted": accepted,
                        "correct": correct, "attempts": n_att, "detail": attempts})
        with open(path, "w", encoding="utf-8") as f:   # checkpoint every variant
            json.dump({"results": results}, f, indent=1)

    n = len(results)
    mappable = [r for r in results if r["should_accept"]]
    unmappable = [r for r in results if not r["should_accept"]]
    acc = [r for r in mappable if r["accepted"]]
    first = [r for r in acc if r["attempts"] == 1]
    correctly_rejected = [r for r in unmappable if not r["accepted"]]
    by_mode = {}
    for r in results:
        m = by_mode.setdefault(r["mode"], {"n": 0, "correct": 0})
        m["n"] += 1
        m["correct"] += 1 if r["correct"] else 0

    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": args.backend,
        "variants": n,
        "mappable": len(mappable),
        "accepted": len(acc),
        "accepted_first_attempt": len(first),
        "avg_attempts_when_accepted": (
            round(sum(r["attempts"] for r in acc) / len(acc), 2) if acc else None),
        "unmappable": len(unmappable),
        "correctly_rejected": len(correctly_rejected),
        "correct_outcomes": sum(1 for r in results if r["correct"]),
        "by_mode": by_mode,
        "results": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    if args.publish:
        # committed, page-readable summary: drop the verbose per-attempt logs
        pub = dict(summary)
        pub["results"] = [{k: v for k, v in r.items() if k != "detail"}
                          for r in summary["results"]]
        pubpath = os.path.join(ROOT, "mapper", "recorded", "benchmark.json")
        os.makedirs(os.path.dirname(pubpath), exist_ok=True)
        with open(pubpath, "w", encoding="utf-8") as f:
            json.dump(pub, f, indent=1)
        print(f"published summary -> {pubpath}")

    print(f"\n=== benchmark over {n} variants")
    print(f"    mappable   : {len(acc)}/{len(mappable)} accepted "
          f"({len(first)} on the first attempt)")
    print(f"    unmappable : {len(correctly_rejected)}/{len(unmappable)} correctly rejected")
    print(f"    by mode    : " + ", ".join(
        f"{m} {v['correct']}/{v['n']}" for m, v in sorted(by_mode.items())))
    print(f"    -> {path}")
    return 0 if summary["correct_outcomes"] == n else 1


if __name__ == "__main__":
    sys.exit(main())
