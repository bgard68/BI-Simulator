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
    args = ap.parse_args()

    os.makedirs(RUNS, exist_ok=True)
    results = []
    for i in range(args.count):
        seed = args.start_seed + i
        src = os.path.join(ROOT, "incoming", f"variant_{seed}.txt")
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "generate_unknown_source.py"),
                            "--seed", str(seed)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"seed {seed}: generator failed: {r.stderr[:200]}")
            continue
        conventions = next((ln.strip() for ln in r.stdout.splitlines()
                            if ln.strip().startswith("delimiter")), "")
        print(f"[{i + 1}/{args.count}] seed {seed}  {conventions}")
        out = os.path.join(RUNS, f"variant_{seed}.json")
        accepted, attempts = run_propose(src, out, args.backend,
                                         args.max_attempts, quiet=True)
        n_att = len(attempts)
        print(f"   -> {'ACCEPTED' if accepted else 'REJECTED'} "
              f"after {n_att} attempt(s)")
        results.append({"seed": seed, "conventions": conventions,
                        "accepted": accepted, "attempts": n_att,
                        "detail": attempts})

    n = len(results)
    acc = [r for r in results if r["accepted"]]
    first = [r for r in acc if r["attempts"] == 1]
    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": args.backend,
        "variants": n,
        "accepted": len(acc),
        "accepted_first_attempt": len(first),
        "avg_attempts_when_accepted": (
            round(sum(r["attempts"] for r in acc) / len(acc), 2) if acc else None),
        "results": results,
    }
    path = os.path.join(RUNS, "benchmark.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    print(f"\n=== benchmark: {len(acc)}/{n} accepted "
          f"({len(first)} on the first attempt) -> {path}")
    return 0 if acc and len(acc) == n else (0 if acc else 1)


if __name__ == "__main__":
    sys.exit(main())
