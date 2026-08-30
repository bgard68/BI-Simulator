"""
Records a REAL agentic mapping session -- commands, live output, and true
timings -- into mapper/recorded/session.json, which the evidence page replays
as an embedded terminal. Nothing here is scripted or re-typed: every line the
player shows was printed by an actual process on an actual run.

Two scenes by design:
  1. an unseen file the model maps successfully  (accepted)
  2. an unseen file that CANNOT satisfy the contract (refused)

Run:  python record_run.py [--accept-seed 601] [--refuse-seed 602]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "mapper", "recorded", "session.json")
MAX_LINES = 46


def run_step(argv, label, cap=MAX_LINES):
    """Run one command, capturing each stdout line with its real offset.

    Commands are launched from the repo root with relative paths, so what the
    player displays is exactly what ran -- no absolute paths, no re-typing.
    """
    parts = argv[1:] if argv[0] == sys.executable else argv
    cmd = ("python " if argv[0] == sys.executable else "") + " ".join(
        (f'"{p}"' if p.startswith("print(") else p) for p in parts)
    print(f"  recording: {cmd}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    t0 = time.monotonic()
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace",
                         bufsize=1, env=env, cwd=ROOT)
    lines, dropped = [], 0
    for raw in p.stdout:
        text = raw.rstrip("\n").rstrip()
        if not text:
            continue
        if len(lines) < cap:
            lines.append({"t": round(time.monotonic() - t0, 2), "text": text[:150]})
        else:
            dropped += 1
    p.wait()
    dur = round(time.monotonic() - t0, 2)
    if dropped:
        lines.append({"t": dur, "text": f"... ({dropped} more lines)"})
    print(f"    -> {len(lines)} line(s), {dur}s, exit {p.returncode}")
    return {"cmd": cmd, "label": label, "lines": lines,
            "duration": dur, "exit_code": p.returncode}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accept-seed", type=int, default=601)   # standard class
    ap.add_argument("--refuse-seed", type=int, default=602)   # unmappable class
    args = ap.parse_args()

    steps = []
    for seed, scene in ((args.accept_seed, "accepted"), (args.refuse_seed, "refused")):
        src = f"incoming/variant_{seed}.txt"
        pjson = f"mapper/runs/variant_{seed}.json"
        steps.append(run_step(
            [sys.executable, "generate_unknown_source.py", "--seed", str(seed)],
            f"{scene}: a file nobody has seen"))
        steps.append(run_step(
            [sys.executable, "-c",
             f"print(*open('{src}',encoding='utf-8').readlines()[:4],sep='')"],
            f"{scene}: what it looks like"))
        steps.append(run_step(
            [sys.executable, "mapper/propose_mapping.py",
             "--source", src, "--out", pjson],
            f"{scene}: the model proposes (gates decide)"))
        if scene == "accepted":
            steps.append(run_step(
                [sys.executable, "mapper/validate_mapping.py",
                 "--proposal", pjson, "--source", src,
                 "--report", f"mapper/runs/variant_{seed}_report.md",
                 "--out", f"mapper/runs/variant_{seed}_conformed.csv"],
                f"{scene}: the eleven gates"))

    session = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "accept_seed": args.accept_seed, "refuse_seed": args.refuse_seed,
        "total_seconds": round(sum(s["duration"] for s in steps), 1),
        "steps": steps,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=1)
    print(f"\nwrote {OUT}  ({session['total_seconds']}s of real session)")


if __name__ == "__main__":
    sys.exit(main())
