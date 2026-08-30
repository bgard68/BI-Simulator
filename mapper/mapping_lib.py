"""
Shared contract, transform whitelist, and gate logic for the agentic mapping
stage. Everything here is deterministic, dependency-free Python: the model
proposes; this module decides.
"""
import csv
import json
import os
import re
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "sources")

CANONICAL_REGIONS = ["North America", "EMEA", "APAC", "LATAM"]
CANONICAL_CHANNELS = ["Online", "Retail", "Wholesale", "Marketplace"]
DATE_MIN, DATE_MAX = date(2025, 1, 1), date(2026, 9, 30)

# The warehouse contract the proposal must satisfy. This is what the model
# is shown; it is also what the gates enforce.
TARGET_FIELDS = {
    "reg_id": {"type": "string", "unique": True,
               "desc": "registration identifier, unique per row"},
    "product_id": {"type": "string", "ref": "products.product_id",
                   "desc": "catalog product id in the form P1234"},
    "customer_email": {"type": "string", "ref": "customers.email",
                       "desc": "customer email address, lowercase"},
    "purchase_date": {"type": "date",
                      "desc": "purchase date, ISO YYYY-MM-DD after conforming"},
    "channel": {"type": "enum", "values": CANONICAL_CHANNELS,
                "desc": "sales channel, canonical"},
    "warranty_years": {"type": "int", "min": 1, "max": 5,
                       "desc": "warranty coverage in years"},
    "region": {"type": "enum", "values": CANONICAL_REGIONS,
               "desc": "customer region, canonical"},
}

TRANSFORMS_DOC = """Allowed transforms (applied left to right; nothing else exists):
  "strip"              trim surrounding whitespace
  "lower" / "upper"    case fold
  "strip_prefix:<P>"   remove leading literal prefix P if present
  "date:<FMT>"         parse with Python strptime FMT, output ISO YYYY-MM-DD
  "int"                parse base-10 integer
  "value_map"          replace via the proposal's value_maps[<target field>]"""

_TRANSFORM_RE = re.compile(r"^(strip|lower|upper|int|value_map|strip_prefix:.+|date:.+)$")


class TransformError(Exception):
    pass


def apply_transforms(value, transforms, target, value_maps):
    v = value
    for t in transforms:
        if t == "strip":
            v = v.strip()
        elif t == "lower":
            v = v.lower()
        elif t == "upper":
            v = v.upper()
        elif t == "int":
            v = int(v)
        elif t.startswith("strip_prefix:"):
            p = t[len("strip_prefix:"):]
            if isinstance(v, str) and v.startswith(p):
                v = v[len(p):]
        elif t.startswith("date:"):
            v = datetime.strptime(v, t[len("date:"):]).date().isoformat()
        elif t == "value_map":
            vm = value_maps.get(target, {})
            if v not in vm:
                raise TransformError(f"value {v!r} not in value_maps[{target!r}]")
            v = vm[v]
        else:
            raise TransformError(f"unknown transform {t!r}")
    return v


def structural_check(proposal):
    """Gate S: is the proposal even well-formed against the contract?"""
    problems = []
    if not isinstance(proposal, dict):
        return ["proposal is not a JSON object"]
    delim = proposal.get("delimiter")
    if not isinstance(delim, str) or len(delim) != 1:
        problems.append("delimiter must be a single character")
    cols = proposal.get("columns")
    if not isinstance(cols, list) or not cols:
        return problems + ["columns missing or empty"]
    targets = [c.get("target") for c in cols if isinstance(c, dict)]
    for field in TARGET_FIELDS:
        if targets.count(field) != 1:
            problems.append(f"target {field!r} must be mapped exactly once "
                            f"(mapped {targets.count(field)}x)")
    for c in cols:
        if not isinstance(c.get("source"), str):
            problems.append(f"column entry missing source: {c!r}")
        for t in c.get("transforms", []):
            if not isinstance(t, str) or not _TRANSFORM_RE.match(t):
                problems.append(f"transform not in whitelist: {t!r}")
    vm = proposal.get("value_maps", {})
    if not isinstance(vm, dict):
        problems.append("value_maps must be an object")
    else:
        for field, mapping in vm.items():
            spec = TARGET_FIELDS.get(field, {})
            allowed = set(spec.get("values", []))
            if allowed and not set(mapping.values()) <= allowed:
                bad = set(mapping.values()) - allowed
                problems.append(f"value_maps[{field!r}] maps to non-canonical {sorted(bad)}")
    return problems


def load_lookups():
    emails = set()
    with open(os.path.join(SRC, "crm_customers.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            emails.add(r["email"].strip().lower())
    with open(os.path.join(SRC, "product_catalog.json"), encoding="utf-8") as f:
        products = {p["product_id"] for p in json.load(f)}
    return emails, products


def apply_and_gate(proposal, source_path):
    """Gate E: apply the proposal to the FULL file and measure the result.

    Returns (gates, conformed_rows) where gates is a list of
    (gate_name, passed, detail) and conformed_rows are dicts (only meaningful
    when every gate passed).
    """
    gates = []
    emails, products = load_lookups()
    vm = proposal.get("value_maps", {})
    delim = proposal["delimiter"]
    colmap = {c["source"]: c for c in proposal["columns"]}

    with open(source_path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    header = lines[0].split(delim) if proposal.get("has_header", True) else None
    body = lines[1:] if header else lines

    missing = [s for s in colmap if header is not None and s not in header]
    gates.append(("S5 proposed source columns exist in header", not missing,
                  f"missing: {missing}" if missing else f"header: {header}"))
    if missing:
        return gates, []

    n_fields = len(header)
    bad_split = sum(1 for ln in body if len(ln.split(delim)) != n_fields)
    gates.append(("E1 every row splits into the header's column count",
                  bad_split == 0, f"{bad_split} of {len(body)} rows malformed"))

    conformed, transform_errors = [], []
    for i, ln in enumerate(body):
        parts = ln.split(delim)
        if len(parts) != n_fields:
            continue
        row = {}
        for src_name, raw in zip(header, parts):
            c = colmap.get(src_name)
            if c is None:
                continue
            try:
                row[c["target"]] = apply_transforms(
                    raw, c.get("transforms", []), c["target"], vm)
            except (TransformError, ValueError) as e:
                row[c["target"]] = None
                transform_errors.append((i + 2, c["target"], str(e)[:80]))
        conformed.append(row)

    n = len(conformed)
    gates.append(("E2 row count preserved", n == len(body), f"{n} of {len(body)}"))

    ids = [r.get("reg_id") for r in conformed]
    ok_ids = all(ids) and len(set(ids)) == n
    gates.append(("E3 reg_id present and unique", ok_ids,
                  f"{len(set(ids))} distinct of {n}"))

    dates = [r.get("purchase_date") for r in conformed]
    parsed = [d for d in dates if d]
    in_window = [d for d in parsed if DATE_MIN.isoformat() <= d <= DATE_MAX.isoformat()]
    date_rate = len(parsed) / n if n else 0
    gates.append(("E4 dates parse (>=99%) and fall in the business window",
                  date_rate >= 0.99 and len(in_window) == len(parsed),
                  f"parsed {len(parsed)}/{n}, in-window {len(in_window)}/{len(parsed)}"))

    em = [r.get("customer_email") for r in conformed]
    matched_e = sum(1 for e in em if e and e in emails)
    e_cov = matched_e / n if n else 0
    gates.append(("E5 customer join coverage >= 95% (email -> CRM)",
                  e_cov >= 0.95, f"{matched_e}/{n} = {e_cov:.1%} "
                  f"({n - matched_e} unmatched, incl. any injection canary)"))

    pr = [r.get("product_id") for r in conformed]
    matched_p = sum(1 for p in pr if p and p in products)
    p_cov = matched_p / n if n else 0
    gates.append(("E6 product join coverage >= 97% (sku -> catalog)",
                  p_cov >= 0.97, f"{matched_p}/{n} = {p_cov:.1%}"))

    bad_ch = {r.get("channel") for r in conformed} - set(CANONICAL_CHANNELS)
    bad_rg = {r.get("region") for r in conformed} - set(CANONICAL_REGIONS)
    gates.append(("E7 channels 100% canonical", not bad_ch, f"offenders: {sorted(map(str, bad_ch))[:5]}" if bad_ch else "all canonical"))
    gates.append(("E8 regions 100% canonical", not bad_rg, f"offenders: {sorted(map(str, bad_rg))[:5]}" if bad_rg else "all canonical"))

    wy = [r.get("warranty_years") for r in conformed]
    ok_wy = all(isinstance(w, int) and 1 <= w <= 5 for w in wy)
    gates.append(("E9 warranty_years all integers in 1..5", ok_wy,
                  f"sample: {sorted({str(w) for w in wy})[:6]}"))

    if transform_errors:
        sample = "; ".join(f"line {l} {t}: {m}" for l, t, m in transform_errors[:3])
        gates.append(("E10 transform errors stay within join-coverage slack",
                      len(transform_errors) <= 0.05 * n,
                      f"{len(transform_errors)} errors, e.g. {sample}"))

    return gates, conformed
