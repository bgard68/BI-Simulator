"""
Contracts as configuration.

`public_po_lib.py` proved the pattern but hard-coded one domain in Python:
onboarding a second source meant writing code and shipping a deploy. This
module makes a contract a **data file** -- `contracts/<name>.toml` -- and
keeps only the *gate primitives* in code.

The split is the point. Generic, reusable checks live here and are
parameterised by the contract:

    present / unique      a field is populated, optionally distinct
    date_window           parses to ISO and lands inside a plausible range
    numeric_range         parses as a number inside declared bounds
    value_set             every value belongs to a declared set (US states,
                          currency codes, statuses ...)
    lookup_coverage       >= N% of values join a reference file (a catalog,
                          a customer master) -- the "does this exist" gate
    reference_agreement   values agree with what a reference already knows
                          for that key -- the "wrong but plausible" gate
    row_consistency       one key carries one value across its own rows

Everything domain-specific -- field names, thresholds, canonical values,
which reference file to check against -- is declared, not compiled. Adding a
domain is a TOML file and no Python at all.

Exposes the same interface as the hand-written contracts (TARGET_FIELDS,
TRANSFORMS_DOC, structural_check, apply_and_gate) so propose_mapping.py and
validate_mapping.py drive it unchanged.
"""
import csv
import json
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_DIR = os.path.join(ROOT, "contracts")

_TRANSFORM_RE = re.compile(
    r"^(strip|lower|upper|int|number|money|value_map|strip_prefix:.+|date:.+)$")


class TransformError(ValueError):
    pass


# ---------------------------------------------------------------- loading
def available():
    if not os.path.isdir(CONTRACT_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(CONTRACT_DIR) if f.endswith(".toml"))


def load(name):
    path = os.path.join(CONTRACT_DIR, f"{name}.toml")
    with open(path, "rb") as f:
        spec = tomllib.load(f)
    spec["_name"] = name
    return spec


class Contract:
    """A contract loaded from TOML, presenting the hand-written lib interface."""

    def __init__(self, spec):
        self.spec = spec
        self.name = spec.get("_name", "?")
        self.meta = spec.get("contract", {})
        self.fields = spec.get("fields", {})
        self.gates = spec.get("gates", [])
        self.sets = spec.get("value_sets", {})
        self.TARGET_FIELDS = {
            k: {"type": v.get("type", "text"),
                "required": bool(v.get("required", False)),
                "desc": v.get("desc", "")}
            for k, v in self.fields.items()
        }
        self.REQUIRED = [k for k, v in self.TARGET_FIELDS.items() if v["required"]]
        self.TRANSFORMS_DOC = self.meta.get("transforms_doc", DEFAULT_TRANSFORMS_DOC)

    # ---------------- transforms
    def apply_transforms(self, value, transforms, target, value_maps):
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
                try:
                    v = float(re.sub(r"[^0-9.\-]", "", v))
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

    # ---------------- structural
    def structural_check(self, proposal):
        problems = []
        fmt = proposal.get("format")
        allowed = self.meta.get("formats", ["delimited", "json", "xml"])
        if fmt not in allowed:
            problems.append(f"format must be one of {allowed}, got {fmt!r}")
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
            if tgt not in self.TARGET_FIELDS:
                problems.append(f"unknown target field {tgt!r}")
                continue
            seen[tgt] = seen.get(tgt, 0) + 1
            for t in c.get("transforms", []):
                if not _TRANSFORM_RE.match(t):
                    problems.append(f"transform not in whitelist: {t!r}")
        for tgt in self.REQUIRED:
            if seen.get(tgt, 0) != 1:
                problems.append(f"required target {tgt!r} must be mapped exactly "
                                f"once (mapped {seen.get(tgt, 0)}x)")
        for tgt, n in seen.items():
            if n > 1:
                problems.append(f"target {tgt!r} mapped {n}x")
        # a declared value_set is also a constraint on the proposal's own maps
        for tgt, m in (proposal.get("value_maps") or {}).items():
            spec = self.fields.get(tgt, {})
            setname = spec.get("value_set")
            if setname and setname in self.sets:
                allowed_vals = set(self.sets[setname])
                bad = sorted({v for v in m.values() if v not in allowed_vals})
                if bad:
                    problems.append(
                        f"value_map for {tgt!r} targets values outside "
                        f"'{setname}': {bad[:4]}")
        return problems

    # ---------------- readers
    def read_records(self, proposal, path):
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
                out.append(dict(zip(header, r)) if len(r) == len(header) else None)
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
            return recs, sorted({k for d in recs if d for k in d})
        if fmt == "xml":
            root = ET.parse(path).getroot()
            tag = proposal.get("record_tag")
            nodes = root.iter(tag) if tag else list(root)
            if not tag:
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

    # ---------------- references (ground truth)
    _ref_cache = {}

    def _reference(self, refname):
        if refname in self._ref_cache:
            return self._ref_cache[refname]
        spec = (self.spec.get("references") or {}).get(refname)
        if not spec:
            raise KeyError(f"contract declares no reference {refname!r}")
        path = os.path.join(ROOT, spec["path"])
        key, value = spec["key"], spec.get("value")
        rows = {}
        if path.endswith(".json"):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for d in data:
                k = str(d.get(key, "")).strip().lower()
                rows[k] = str(d.get(value, "")).strip() if value else None
        else:
            with open(path, newline="", encoding="utf-8") as f:
                for d in csv.DictReader(f):
                    k = str(d.get(key, "")).strip().lower()
                    rows[k] = str(d.get(value, "")).strip() if value else None
        for tf in spec.get("value_transforms", []):
            if tf == "upper":
                rows = {k: (v.upper() if v else v) for k, v in rows.items()}
            elif tf.startswith("map:"):
                mapping = self.sets.get(tf.split(":", 1)[1], {})
                if isinstance(mapping, dict):
                    rows = {k: mapping.get(v, v) for k, v in rows.items()}
        self._ref_cache[refname] = rows
        return rows

    # ---------------- gates
    def apply_and_gate(self, proposal, source_path):
        gates = []
        try:
            records, header = self.read_records(proposal, source_path)
        except Exception as e:
            return [("G0 file parses in the proposed format", False,
                     f"{type(e).__name__}: {e}")], []
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
                    row[c["target"]] = self.apply_transforms(
                        rec.get(c["source"]), c.get("transforms", []),
                        c["target"], vmaps)
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

        for i, g in enumerate(self.gates, start=3):
            gates.append(self._run_gate(g, conformed, f"G{i}"))
        return gates, conformed

    def _run_gate(self, g, rows, tag):
        kind, field = g["check"], g.get("field")
        label = f"{tag} {g.get('label', kind)}"
        total = len(rows)
        vals = [r.get(field) for r in rows if r.get(field) not in (None, "")]

        if kind == "present":
            uniq = g.get("unique", False)
            ok = len(vals) == total and (not uniq or len(set(vals)) == len(vals))
            return (label, ok, f"{len(vals)}/{total} present, "
                              f"{len(set(vals))} distinct")

        if kind == "date_window":
            lo, hi = g.get("min", "1900-01-01"), g.get("max", "2100-12-31")
            inw = [v for v in vals if isinstance(v, str) and lo <= v <= hi]
            ok = len(vals) >= g.get("min_rate", 0.99) * total and len(inw) == len(vals)
            return (label, ok, f"{len(vals)} parsed, {len(inw)} within {lo[:4]}-{hi[:4]}")

        if kind == "numeric_range":
            nums = [v for v in vals if isinstance(v, (int, float))]
            lo, hi = g.get("min", float("-inf")), g.get("max", float("inf"))
            inr = [v for v in nums if lo <= v <= hi]
            ok = len(nums) >= g.get("min_rate", 0.99) * total and len(inr) == len(nums)
            return (label, ok, f"{len(nums)}/{total} numeric"
                             + (f", max {max(nums):,.2f}" if nums else ""))

        if kind == "value_set":
            allowed = set(self.sets.get(g["value_set"], []))
            bad = sorted({v for v in vals if v not in allowed})
            ok = bool(vals) and not bad and len(vals) >= g.get("min_rate", 0.99) * total
            return (label, ok, f"offenders: {bad[:5]}" if bad else
                              f"{len(set(vals))} distinct, all valid "
                              f"(e.g. {sorted(set(vals))[:5]})")

        if kind == "lookup_coverage":
            ref = self._reference(g["reference"])
            hits = [v for v in vals if str(v).strip().lower() in ref]
            rate = len(hits) / total if total else 0
            ok = rate >= g.get("min_rate", 0.95)
            return (label, ok, f"{len(hits)}/{total} = {rate:.1%} "
                              f"({total - len(hits)} unmatched)")

        if kind == "reference_agreement":
            ref = self._reference(g["reference"])
            keyf = g["key_field"]
            pairs = [(str(r.get(keyf, "")).strip().lower(), r.get(field))
                     for r in rows if r.get(field) not in (None, "")]
            joined = [(k, v) for k, v in pairs if k in ref]
            agree = sum(1 for k, v in joined if ref[k] == v)
            rate = agree / len(joined) if joined else 0
            ok = bool(joined) and rate >= g.get("min_rate", 0.95)
            return (label, ok, f"{agree}/{len(joined)} = {rate:.1%} agree with "
                              f"{g['reference']}")

        if kind == "row_consistency":
            groups = {}
            for r in rows:
                groups.setdefault(r.get(g["key_field"]), set()).add(r.get(field))
            bad = {k: v for k, v in groups.items() if len(v) > 1}
            ok = len(bad) <= g.get("max_conflict_rate", 0.01) * max(len(groups), 1)
            return (label, ok, f"{len(groups)} groups, {len(bad)} with "
                              f"conflicting {field}")

        if kind == "not_numeric":
            numeric = [v for v in vals if str(v).replace(".", "").isdigit()]
            ok = bool(vals) and len(numeric) <= g.get("max_rate", 0.01) * len(vals)
            return (label, ok, f"{len(numeric)}/{len(vals)} purely numeric")

        return (label, False, f"unknown check type {kind!r}")


DEFAULT_TRANSFORMS_DOC = """Allowed transforms (applied left to right; nothing else exists):
  strip                stripped of surrounding whitespace
  lower / upper        case folded
  int                  parsed as an integer
  number               parsed as a decimal number
  money                currency text -> number ("$49,500.00" -> 49500.0)
  date:<FMT>           parsed with a Python strptime format, emitted as ISO
                       (e.g. date:%Y-%m-%dT%H:%M:%S.%f  or  date:%m/%d/%Y)
  strip_prefix:<P>     leading <P> removed
  value_map            replaced via this proposal's value_maps for the target"""
