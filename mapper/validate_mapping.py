"""
The deterministic side of the agentic mapping stage: replays a (recorded)
proposal against the full unknown source and either accepts it -- writing the
conformed table -- or fails with a gate-by-gate report. No model involved;
this is what CI runs on every push.

Run:  python mapper/validate_mapping.py
      python mapper/validate_mapping.py --proposal path.json --source file.txt
Exit: 0 all gates pass, 1 otherwise
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mapping_lib as lib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", default=os.path.join(ROOT, "mapper", "recorded", "proposal.json"))
    ap.add_argument("--source", default=os.path.join(ROOT, "incoming", "warranty_registrations.txt"))
    ap.add_argument("--report", default=os.path.join(ROOT, "mapper", "recorded", "validation_report.md"))
    ap.add_argument("--out", default=os.path.join(ROOT, "warehouse", "warranty_conformed.csv"))
    args = ap.parse_args()

    with open(args.proposal, encoding="utf-8") as f:
        recorded = json.load(f)
    proposal = recorded.get("proposal", recorded)
    meta = recorded.get("meta", {})

    gates = [("S1-S4 structural: shape, coverage, whitelist, canonical maps",
              True, "ok")]
    problems = lib.structural_check(proposal)
    if problems:
        gates[0] = (gates[0][0], False, "; ".join(problems))
        empirical, conformed = [], []
    else:
        empirical, conformed = lib.apply_and_gate(proposal, args.source)
    gates += empirical

    all_ok = all(ok for _, ok, _ in gates)

    lines = ["# Agentic mapping - validation report", ""]
    if meta:
        lines.append(f"Proposal by `{meta.get('model', '?')}` via `{meta.get('backend', '?')}` "
                     f"on {meta.get('created_utc', '?')} "
                     f"({len(meta.get('attempts', []))} attempt(s)).")
        lines.append("")
    lines.append("| Gate | Result | Detail |")
    lines.append("|---|---|---|")
    for name, ok, detail in gates:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines.append("")
    lines.append(f"**Verdict: {'ACCEPTED' if all_ok else 'REJECTED'}** - "
                 f"{'conformed table written' if all_ok else 'nothing lands'}.")
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    for name, ok, detail in gates:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  [{detail}]")

    if all_ok and conformed:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        fields = list(lib.TARGET_FIELDS.keys())
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(conformed)
        print(f"\nACCEPTED -> {args.out} ({len(conformed)} rows)")
        print(f"report   -> {args.report}")
        return 0
    print(f"\nREJECTED -> {args.report}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
