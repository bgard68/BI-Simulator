"""
The human step.

Passing the gates makes a proposal *eligible*, not *approved*. Gates are a
safety net -- they prove a mapping is consistent with data we already trust.
They cannot know that a vendor's "AMT" column means net rather than gross, or
that this supplier's file is the one legal signed off on. A person decides
that, once, per source.

So an accepted proposal carries an `approval` block. `validate_mapping.py
--require-approval` (which CI uses) refuses to let an unapproved mapping land,
and this script is how a named human signs one off.

Run:  python mapper/approve.py --show
      python mapper/approve.py --approve --by "Burt Gardner" --note "checked AMT is net"
      python mapper/approve.py --revoke --by "Burt Gardner" --note "vendor changed format"
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDED = os.path.join(ROOT, "mapper", "recorded", "proposal.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)


def status_of(doc):
    a = doc.get("approval") or {}
    return a.get("status", "pending"), a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", default=RECORDED)
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--revoke", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--by", default=os.environ.get("USER") or os.environ.get("USERNAME"))
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    doc = load(args.proposal)
    state, block = status_of(doc)

    if args.show or not (args.approve or args.revoke):
        print(f"proposal : {os.path.relpath(args.proposal, ROOT)}")
        print(f"source   : {doc.get('meta', {}).get('source_file', '?')}")
        print(f"status   : {state.upper()}")
        for k in ("by", "at", "note"):
            if block.get(k):
                print(f"{k:9s}: {block[k]}")
        cols = doc.get("proposal", {}).get("columns", [])
        print(f"\nmapping ({len(cols)} columns) awaiting your judgement:")
        for c in cols:
            tf = " -> ".join(c.get("transforms", [])) or "(none)"
            print(f"  {c['source']:24s} {tf:44s} => {c['target']}")
        vm = doc.get("proposal", {}).get("value_maps") or {}
        for field, m in vm.items():
            print(f"  value_map {field}: {m}")
        if state != "approved":
            print("\nnot approved: CI with --require-approval will refuse this.")
            print('approve with: python mapper/approve.py --approve --by "Your Name"')
        return 0

    if not args.by:
        print("--by is required: an approval needs a name attached to it")
        return 1

    doc["approval"] = {
        "status": "approved" if args.approve else "revoked",
        "by": args.by,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": args.note,
        # what was approved -- so an edited proposal loses its approval
        "proposal_fingerprint": fingerprint(doc.get("proposal", {})),
    }
    save(args.proposal, doc)
    print(f"{doc['approval']['status'].upper()} by {args.by} "
          f"at {doc['approval']['at']}")
    return 0


def fingerprint(proposal):
    import hashlib
    blob = json.dumps(proposal, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


if __name__ == "__main__":
    sys.exit(main())
