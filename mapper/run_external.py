"""
Runs the agentic mapper against the REAL external files, scoring each by
whether the outcome was correct -- not merely whether it was accepted.

Two of these files are purchase-order line data that can satisfy the public-PO
contract. Three cannot: LA City's extract carries no line amounts or state,
Edmonton publishes dollar *buckets* instead of amounts, and the SEC index is
not order data at all. For those, refusal is the correct answer.

Run:  python mapper/run_external.py [--publish]
Writes: mapper/runs/external.json  (+ mapper/recorded/external.json with --publish)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import propose_mapping as pm
import public_po_lib
import validate_mapping  # noqa: F401  (kept importable for parity)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "incoming", "external")
RUNS = os.path.join(ROOT, "mapper", "runs")

CASES = [
    ("providence_purchase_orders.csv", "City of Providence, RI", "CSV", True,
     "purchase order lines with quantities, unit prices and vendor states"),
    ("vermont_purchase_orders.json", "State of Vermont", "JSON", True,
     "state purchase orders with vendor city/state"),
    ("lacity_invoices.tsv", "Los Angeles City Controller", "TSV", False,
     "invoice register: no line amount and no vendor state"),
    ("edmonton_purchase_orders.xml", "City of Edmonton, Canada", "XML", False,
     "dollar-value buckets instead of amounts; no PO id, no US state"),
    ("sec_edgar_filings.txt", "U.S. SEC EDGAR", "TXT (pipe)", False,
     "securities filing index - not purchase orders at all"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="claude-cli")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()

    pm.lib = public_po_lib               # drive the public-PO contract
    os.makedirs(RUNS, exist_ok=True)
    results = []

    for fname, publisher, fmt, should_accept, why in CASES:
        src = os.path.join(EXT, fname)
        if not os.path.exists(src):
            print(f"  {fname}: missing -- run fetch_external_sources.py first")
            continue
        out = os.path.join(RUNS, os.path.splitext(fname)[0] + ".json")
        print(f"[{fmt:11s}] {publisher} ...", flush=True)
        accepted, attempts = pm.run_propose(src, out, args.backend,
                                            args.max_attempts, quiet=True)
        gates = []
        if accepted:
            with open(out, encoding="utf-8") as f:
                proposal = json.load(f)["proposal"]
            g, conformed = public_po_lib.apply_and_gate(proposal, src)
            gates = [{"gate": n, "ok": ok, "detail": str(d)} for n, ok, d in g]
            rows = len(conformed)
        else:
            rows = 0
        correct = accepted == should_accept
        reasons = []
        if not accepted and attempts:
            last = attempts[-1]
            reasons = (last.get("structural_problems", []) +
                       last.get("failed_gates", []))
        print(f"   -> {'ACCEPTED' if accepted else 'REFUSED'} after {len(attempts)} "
              f"attempt(s) - {'correct' if correct else 'WRONG OUTCOME'}"
              f"{f' ({rows} rows)' if rows else ''}")
        results.append({
            "file": fname, "publisher": publisher, "format": fmt, "why": why,
            "should_accept": should_accept, "accepted": accepted,
            "correct": correct, "attempts": len(attempts), "rows": rows,
            "gates": gates, "refusal_reasons": reasons[:4],
        })

    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": args.backend,
        "files": len(results),
        "correct_outcomes": sum(1 for r in results if r["correct"]),
        "accepted": sum(1 for r in results if r["accepted"]),
        "refused": sum(1 for r in results if not r["accepted"]),
        "results": results,
    }
    path = os.path.join(RUNS, "external.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    if args.publish:
        pub = os.path.join(ROOT, "mapper", "recorded", "external.json")
        os.makedirs(os.path.dirname(pub), exist_ok=True)
        with open(pub, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1)
        print(f"\npublished -> {pub}")

    print(f"\n=== {summary['correct_outcomes']}/{summary['files']} correct outcomes "
          f"({summary['accepted']} accepted, {summary['refused']} refused)")
    return 0 if summary["correct_outcomes"] == summary["files"] else 1


if __name__ == "__main__":
    sys.exit(main())
