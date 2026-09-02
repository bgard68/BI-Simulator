"""
One command for a complete live mapping run: generate the unknown source,
have the model propose a mapping, and put that proposal through the gates.

Exists so the same invocation works everywhere -- a Linux CI runner, a
Windows self-hosted runner, or your own terminal during a demo -- with no
shell-specific syntax in between.

Run:  python mapper/live_run.py                # the canonical fixture
      python mapper/live_run.py --seed 904     # an unseen variant
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def step(title, argv):
    print(f"\n=== {title}\n$ python {' '.join(argv)}", flush=True)
    r = subprocess.run([PY] + argv, cwd=ROOT)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=os.environ.get("SEED", "").strip() or None)
    ap.add_argument("--backend", default="claude-cli")
    ap.add_argument("--contract", default="warranty")
    args = ap.parse_args()

    if step("world", ["generate_sources.py"]):
        return 1

    if args.seed:
        src = f"incoming/variant_{args.seed}.txt"
        proposal = f"mapper/runs/variant_{args.seed}.json"
        report = f"mapper/runs/variant_{args.seed}_report.md"
        out = f"mapper/runs/variant_{args.seed}_conformed.csv"
        gen = ["generate_unknown_source.py", "--seed", str(args.seed)]
    else:
        src = "incoming/warranty_registrations.txt"
        proposal = "mapper/recorded/proposal.json"
        report = "mapper/recorded/validation_report.md"
        out = "warehouse/warranty_conformed.csv"
        gen = ["generate_unknown_source.py"]

    if step("unknown source", gen):
        return 1

    rc = step("propose (the model gets a voice)",
              ["mapper/propose_mapping.py", "--backend", args.backend,
               "--contract", args.contract, "--source", src, "--out", proposal])
    if rc:
        print("\nno proposal survived the gates - nothing lands. "
              "That is a correct outcome for a file that cannot satisfy "
              "the contract.")
        return rc

    return step("gates (the vote)",
                ["mapper/validate_mapping.py", "--contract", args.contract,
                 "--proposal", proposal, "--source", src,
                 "--report", report, "--out", out])


if __name__ == "__main__":
    sys.exit(main())
