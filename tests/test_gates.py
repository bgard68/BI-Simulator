"""
The gates are only worth trusting if they demonstrably reject bad proposals.
Every test here corrupts the recorded, accepted proposal in one specific way
and asserts the specific gate that must catch it. If a corruption ever slips
through, this suite -- not a reviewer -- goes red.

Run:  python -m unittest discover -s tests -v
      (after generate_sources.py and generate_unknown_source.py)
"""
import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mapper"))
import mapping_lib as lib

SOURCE = os.path.join(ROOT, "incoming", "warranty_registrations.txt")
RECORDED = os.path.join(ROOT, "mapper", "recorded", "proposal.json")

for needed in (SOURCE, os.path.join(lib.SRC, "crm_customers.csv")):
    if not os.path.exists(needed):
        raise SystemExit(
            f"missing {needed} -- run generate_sources.py and "
            "generate_unknown_source.py before the test suite")

with open(RECORDED, encoding="utf-8") as f:
    ACCEPTED = json.load(f)["proposal"]


def corrupted(**edits):
    """Deep-copy the accepted proposal, then apply keyword edits via callables."""
    p = copy.deepcopy(ACCEPTED)
    for fn in edits.values():
        fn(p)
    return p


def col(p, source):
    return next(c for c in p["columns"] if c["source"] == source)


def gate(gates, prefix):
    for name, ok, detail in gates:
        if name.startswith(prefix):
            return ok, detail
    raise AssertionError(f"gate {prefix} not found in {[g[0] for g in gates]}")


class TestTransformPrimitives(unittest.TestCase):
    def test_prefix_case_chain(self):
        v = lib.apply_transforms(" sku-P1018 ", ["strip", "upper", "strip_prefix:SKU-"],
                                 "product_id", {})
        self.assertEqual(v, "P1018")

    def test_date_conforms_to_iso(self):
        v = lib.apply_transforms("14.03.2025", ["date:%d.%m.%Y"], "purchase_date", {})
        self.assertEqual(v, "2025-03-14")

    def test_value_map_miss_raises(self):
        with self.assertRaises(lib.TransformError):
            lib.apply_transforms("APJ", ["value_map"], "region", {"region": {"EMEA": "EMEA"}})


class TestStructuralGates(unittest.TestCase):
    def test_accepted_proposal_is_clean(self):
        self.assertEqual(lib.structural_check(ACCEPTED), [])

    def test_transform_outside_whitelist_rejected(self):
        p = corrupted(x=lambda p: col(p, "REG_NO")["transforms"].append("exec:os.system"))
        problems = lib.structural_check(p)
        self.assertTrue(any("whitelist" in m for m in problems), problems)

    def test_value_map_to_noncanonical_rejected(self):
        p = corrupted(x=lambda p: p["value_maps"]["region"].update({"APJ": "Asia-Pacific"}))
        problems = lib.structural_check(p)
        self.assertTrue(any("non-canonical" in m for m in problems), problems)

    def test_unmapped_target_rejected(self):
        p = corrupted(x=lambda p: p["columns"].remove(col(p, "ZONE")))
        problems = lib.structural_check(p)
        self.assertTrue(any("region" in m and "exactly once" in m for m in problems), problems)

    def test_double_mapped_target_rejected(self):
        p = corrupted(x=lambda p: col(p, "SALES_CH").update({"target": "region"}))
        problems = lib.structural_check(p)
        self.assertTrue(any("exactly once" in m for m in problems), problems)


class TestEmpiricalGates(unittest.TestCase):
    def run_gates(self, p):
        return lib.apply_and_gate(p, SOURCE)[0]

    def test_accepted_proposal_passes_everything(self):
        gates = self.run_gates(ACCEPTED)
        failed = [(n, d) for n, ok, d in gates if not ok]
        self.assertEqual(failed, [])

    def test_wrong_date_format_fails_E4(self):
        p = corrupted(x=lambda p: col(p, "PURCHASED_ON").update(
            {"transforms": ["strip", "date:%m.%d.%Y"]}))
        ok, detail = gate(self.run_gates(p), "E4")
        self.assertFalse(ok, detail)

    def test_missing_value_map_entry_fails_E8(self):
        p = corrupted(x=lambda p: p["value_maps"]["region"].pop("APJ"))
        ok, detail = gate(self.run_gates(p), "E8")
        self.assertFalse(ok, detail)

    def test_swapped_join_columns_fail_E5(self):
        def swap(p):
            col(p, "BUYER_EMAIL")["target"] = "reg_id"
            col(p, "REG_NO")["target"] = "customer_email"
        ok, detail = gate(self.run_gates(corrupted(x=swap)), "E5")
        self.assertFalse(ok, detail)

    def test_unstripped_sku_prefix_fails_E6(self):
        p = corrupted(x=lambda p: col(p, "ITEM_SKU").update(
            {"transforms": ["strip", "upper"]}))
        ok, detail = gate(self.run_gates(p), "E6")
        self.assertFalse(ok, detail)

    def test_wrong_delimiter_fails_S5(self):
        p = corrupted(x=lambda p: p.update({"delimiter": ","}))
        ok, detail = gate(self.run_gates(p), "S5")
        self.assertFalse(ok, detail)


class TestContainment(unittest.TestCase):
    def test_injection_canary_is_present_and_powerless(self):
        with open(SOURCE, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("IGNORE ALL PREVIOUS INSTRUCTIONS", content)
        gates = lib.apply_and_gate(ACCEPTED, SOURCE)[0]
        ok, detail = gate(gates, "E5")
        self.assertTrue(ok, detail)          # gates still pass overall...
        self.assertIn("unmatched", detail)   # ...with the canary counted as a failed join


class TestDeterminism(unittest.TestCase):
    def test_unknown_source_regenerates_byte_identical(self):
        def digest():
            with open(SOURCE, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        before = digest()
        r = subprocess.run([sys.executable, os.path.join(ROOT, "generate_unknown_source.py")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, digest(), "regeneration changed the fixture -- "
                         "CI replay would no longer prove what it claims")


if __name__ == "__main__":
    unittest.main()
