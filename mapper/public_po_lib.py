"""
A SECOND contract, for real public purchase-order data.

The warranty contract (mapping_lib) gates against Cobalt's own CRM and
catalog. Real files from real governments have none of that -- their vendors
and products don't exist in a simulated world -- so this contract gates on
what is *independently knowable* about purchase orders:

  * US state codes are a fixed, external fact (not something we invent)
  * a purchase-order number must carry a consistent vendor across its lines
  * dates must be real dates in a plausible window; money must be money

Same interface as mapping_lib (TARGET_FIELDS / TRANSFORMS_DOC /
structural_check / apply_and_gate), so propose_mapping.py and
validate_mapping.py drive it with --contract public_po.

The model must also identify the *container* here: delimited, json, or xml.
"""
import csv
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- the contract -------------------------------------------------------
TARGET_FIELDS = {
    "po_id":       {"type": "text",   "required": True,  "desc": "purchase order / contract number"},
    "po_date":     {"type": "date",   "required": True,  "desc": "date of the order, conformed to ISO"},
    "vendor_name": {"type": "text",   "required": True,  "desc": "supplier / vendor name"},
    "amount":      {"type": "number", "required": True,  "desc": "monetary value on the line, in the file's own currency"},
    "region":      {"type": "state",  "required": True,  "desc": "US state/territory code of the vendor (2 letters)"},
    "line_no":     {"type": "int",    "required": False, "desc": "line number within the order"},
    "quantity":    {"type": "number", "required": False, "desc": "units ordered"},
    "description": {"type": "text",   "required": False, "desc": "what was ordered"},
    "city":        {"type": "text",   "required": False, "desc": "vendor city"},
}
REQUIRED = [k for k, v in TARGET_FIELDS.items() if v["required"]]

TRANSFORMS_DOC = """Allowed transforms (applied left to right; nothing else exists):
  strip                stripped of surrounding whitespace
  lower / upper        case folded
  int                  parsed as an integer
  number               parsed as a decimal number
  money                currency text -> number ("$49,500.00" -> 49500.0)
  date:<FMT>           parsed with a Python strptime format, emitted as ISO
                       (e.g. date:%Y-%m-%dT%H:%M:%S.%f  or  date:%m/%d/%Y)
  strip_prefix:<P>     leading <P> removed
  value_map            replaced via this proposal's value_maps for the target"""

_TRANSFORM_RE = re.compile(
    r"^(strip|lower|upper|int|number|money|value_map|strip_prefix:.+|date:.+)$")

# Independent ground truth: the actual US postal codes. Not derived from any
# file we were given, so a mapping cannot satisfy it by accident.
US_STATES = set("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD
MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA
WA WV WI WY DC AS GU MP PR VI""".split())

DATE_MIN, DATE_MAX = "1990-01-01", "2035-12-31"


class TransformError(ValueError):
    pass


def apply_transforms(value, transforms, target, value_maps):
    v = "" if value is None else str(value)
    for t in transforms:
        if t == "strip":
            v = v.strip()
        elif t == "lower":
            v = v.lower()
        elif t == "upper":
            v = v.upper()
        elif t == "int":
            try:
                v = int(float(v))
            except ValueError:
                raise TransformError(f"not an integer: {v!r}")
        elif t == "number":
            try:
                v = float(v)
            except ValueError:
                raise TransformError(f"not a number: {v!r}")
        elif t == "money":
            cleaned = re.sub(r"[^0-9.\-]", "", v)
            try:
                v = float(cleaned)
            except ValueError:
                raise TransformError(f"not money: {v!r}")
        elif t.startswith("strip_prefix:"):
            p = t.split(":", 1)[1]
            v = v[len(p):] if v.startswith(p) else v
        elif t.startswith("date:"):
            fmt = t.split(":", 1)[1]
            try:
                v = datetime.strptime(v, fmt).date().isoformat()
            except ValueError:
                raise TransformError(f"date {v!r} does not match {fmt}")
        elif t == "value_map":
            m = value_maps.get(target, {})
            if v not in m:
                raise TransformError(f"no value_map entry for {v!r}")
            v = m[v]
        else:
            raise TransformError(f"transform not in whitelist: {t}")
    return v


# --- structural checks (no file access) ---------------------------------
def structural_check(proposal):
    problems = []
    fmt = proposal.get("format")
    if fmt not in ("delimited", "json", "xml"):
        problems.append(f"format must be delimited|json|xml, got {fmt!r}")
    if fmt == "delimited" and not proposal.get("delimiter"):
        problems.append("delimited format requires a delimiter")
    cols = proposal.get("columns")
    if not isinstance(cols, list) or not cols:
        problems.append("columns must be a non-empty list")
        return problems

    seen = {}
    for c in cols:
        if not isinstance(c, dict) or "source" not in c or "target" not in c:
            problems.append(f"malformed column entry: {c!r}")
            continue
        tgt = c["target"]
        if tgt not in TARGET_FIELDS:
            problems.append(f"unknown target field {tgt!r}")
            continue
        seen[tgt] = seen.get(tgt, 0) + 1
        for t in c.get("transforms", []):
            if not _TRANSFORM_RE.match(t):
                problems.append(f"transform not in whitelist: {t!r}")
    for tgt in REQUIRED:
        if seen.get(tgt, 0) != 1:
            problems.append(f"required target {tgt!r} must be mapped exactly "
                            f"once (mapped {seen.get(tgt, 0)}x)")
    for tgt, n in seen.items():
        if n > 1:
            problems.append(f"target {tgt!r} mapped {n}x")
    for tgt, m in (proposal.get("value_maps") or {}).items():
        if tgt == "region":
            bad = [v for v in m.values() if v not in US_STATES]
            if bad:
                problems.append(f"region value_map targets non-state codes: {bad[:4]}")
    return problems


# --- readers: the model must identify the container ---------------------
def read_records(proposal, path):
    """Return a list of dicts, whatever the container is."""
    fmt = proposal.get("format")
    if fmt == "delimited":
        delim = proposal["delimiter"]
        delim = {"\\t": "\t", "TAB": "\t", "tab": "\t"}.get(delim, delim)
        skip = int(proposal.get("skip_lines", 0) or 0)
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for _ in range(skip):
                f.readline()
            rows = list(csv.reader(f, delimiter=delim))
        if not rows:
            return [], []
        header = [h.strip().strip('"') for h in rows[0]]
        out = []
        for r in rows[1:]:
            if len(r) != len(header):
                out.append(None)          # malformed, counted by G1
            else:
                out.append(dict(zip(header, r)))
        return out, header
    if fmt == "json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in ("data", "rows", "results", "records"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            return [], []
        recs = [d if isinstance(d, dict) else None for d in data]
        header = sorted({k for d in recs if d for k in d})
        return recs, header
    if fmt == "xml":
        tree = ET.parse(path)
        root = tree.getroot()
        tag = proposal.get("record_tag")
        if tag:
            nodes = root.iter(tag)
        else:                              # deepest repeating element
            nodes = list(root)
            while len(nodes) == 1 and len(list(nodes[0])):
                nodes = list(nodes[0])
        recs, header = [], []
        for n in nodes:
            d = {c.tag: (c.text or "") for c in n}
            d.update({k: v for k, v in n.attrib.items() if not k.startswith("_")})
            if d:
                recs.append(d)
                for k in d:
                    if k not in header:
                        header.append(k)
        return recs, header
    return [], []


# --- empirical gates (the whole file) -----------------------------------
def apply_and_gate(proposal, source_path):
    gates = []
    try:
        records, header = read_records(proposal, source_path)
    except Exception as e:
        return [("G0 file parses in the proposed format", False, f"{type(e).__name__}: {e}")], []
    gates.append(("G0 file parses in the proposed format", bool(records),
                  f"{len(records)} record(s), {len(header)} field(s)"))
    if not records:
        return gates, []

    proposed = {c["source"] for c in proposal["columns"]}
    missing = sorted(proposed - set(header))
    gates.append(("G1 proposed source fields exist in the file", not missing,
                  f"missing: {missing[:5]}" if missing else f"header: {header[:8]}"))
    if missing:
        return gates, []

    vmaps = proposal.get("value_maps") or {}
    conformed, errors = [], []
    malformed = sum(1 for r in records if r is None)
    for rec in records:
        if rec is None:
            continue
        row, bad = {}, False
        for c in proposal["columns"]:
            try:
                row[c["target"]] = apply_transforms(
                    rec.get(c["source"]), c.get("transforms", []), c["target"], vmaps)
            except TransformError as e:
                errors.append(str(e))
                bad = True
        if not bad:
            conformed.append(row)
    n = len(records) - malformed
    gates.append(("G2 every record maps without transform errors",
                  len(conformed) == n,
                  f"{len(conformed)}/{n} mapped"
                  + (f"; e.g. {errors[0][:60]}" if errors else "")
                  + (f"; {malformed} malformed rows" if malformed else "")))
    if not conformed:
        return gates, []

    def col(name):
        return [r.get(name) for r in conformed if r.get(name) not in (None, "")]

    ids = col("po_id")
    gates.append(("G3 po_id present on every record", len(ids) == len(conformed),
                  f"{len(ids)}/{len(conformed)} present, {len(set(ids))} distinct"))

    dates = col("po_date")
    in_win = [d for d in dates if isinstance(d, str) and DATE_MIN <= d <= DATE_MAX]
    ok_d = len(dates) == len(conformed) and len(in_win) >= 0.99 * len(conformed)
    gates.append((f"G4 dates ISO and within {DATE_MIN[:4]}-{DATE_MAX[:4]}", ok_d,
                  f"{len(dates)} parsed, {len(in_win)} in window"))

    amts = [a for a in col("amount") if isinstance(a, (int, float))]
    sane = [a for a in amts if 0 <= a < 1e10]
    ok_a = len(amts) >= 0.99 * len(conformed) and len(sane) == len(amts)
    gates.append(("G5 amount numeric, non-negative, plausible", ok_a,
                  f"{len(amts)}/{len(conformed)} numeric"
                  + (f", max {max(amts):,.2f}" if amts else "")))

    regions = col("region")
    bad_r = sorted({r for r in regions if r not in US_STATES})
    ok_r = regions and not bad_r and len(regions) >= 0.99 * len(conformed)
    gates.append(("G6 region is a real US state/territory code", bool(ok_r),
                  f"offenders: {bad_r[:5]}" if bad_r else
                  f"{len(set(regions))} distinct, all valid (e.g. {sorted(set(regions))[:5]})"))

    # cross-row consistency: one PO number cannot belong to two vendors.
    by_po = {}
    for r in conformed:
        by_po.setdefault(r.get("po_id"), set()).add(r.get("vendor_name"))
    conflicts = {k: v for k, v in by_po.items() if len(v) > 1}
    ok_c = len(conflicts) <= 0.01 * max(len(by_po), 1)
    gates.append(("G7 each po_id carries one consistent vendor", ok_c,
                  f"{len(by_po)} orders, {len(conflicts)} with conflicting vendors"))

    names = col("vendor_name")
    numeric_names = [v for v in names if str(v).replace(".", "").isdigit()]
    ok_n = names and len(numeric_names) <= 0.01 * len(names)
    gates.append(("G8 vendor_name reads as a name, not an id", bool(ok_n),
                  f"{len(numeric_names)}/{len(names)} purely numeric"))

    return gates, conformed
