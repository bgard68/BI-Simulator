"""
The gates are only worth trusting if they demonstrably reject bad proposals.
Every test here corrupts the recorded, accepted proposal in one specific way
and asserts the specific gate that must catch it. If a corruption ever slips
through, this suite -- not a reviewer -- goes red.

Run:  python -m unittest discover -s tests -v
      (after generate_sources.py and generate_unknown_source.py)
"""
import copy
import re
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

    def test_wrong_but_canonical_channel_map_fails_E7(self):
        # every mapped value stays canonical, so membership passes -- only
        # the ERP ground-truth agreement catches the swap
        def swap(p):
            vm = p["value_maps"]["channel"]
            vm["BULK"], vm["MKT"] = vm["MKT"], vm["BULK"]
        ok, detail = gate(self.run_gates(corrupted(x=swap)), "E7")
        self.assertFalse(ok, detail)
        self.assertIn("agree", detail)

    def test_wrong_but_canonical_region_map_fails_E8(self):
        # both targets are canonical values, so a membership check alone
        # would pass -- only the CRM ground-truth agreement catches it
        def swap(p):
            vm = p["value_maps"]["region"]
            vm["APJ"], vm["LATM"] = vm["LATM"], vm["APJ"]
        ok, detail = gate(self.run_gates(corrupted(x=swap)), "E8")
        self.assertFalse(ok, detail)
        self.assertIn("agree", detail)

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


class TestQuotedFields(unittest.TestCase):
    def test_split_row_honours_quotes(self):
        line = 'WR-1,"Ortiz, Reyes & Co",a@b.com'
        self.assertEqual(lib.split_row(line, ","),
                         ["WR-1", "Ortiz, Reyes & Co", "a@b.com"])

    def test_split_row_matches_naive_split_when_unquoted(self):
        line = "a|b|c"
        self.assertEqual(lib.split_row(line, "|"), line.split("|"))

    def test_quoted_variant_rows_stay_well_formed(self):
        seed, path = 908, os.path.join(ROOT, "incoming", "variant_908.txt")
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "generate_unknown_source.py"),
                            "--seed", str(seed), "--mode", "quoted"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(path, encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        delim = "," if "," in lines[0] else ";"
        width = len(lib.split_row(lines[0], delim))
        widths = {len(lib.split_row(ln, delim)) for ln in lines[1:]}
        self.assertEqual(widths, {width},
                         "quoted fields must not change the column count")
        # and the naive parser WOULD have broken on this file
        naive = {len(ln.split(delim)) for ln in lines[1:]}
        self.assertNotEqual(naive, {width},
                            "fixture should contain delimiter-in-quotes cases")
        os.remove(path)


class TestUnmappableIsRejected(unittest.TestCase):
    def test_no_proposal_can_satisfy_a_missing_column(self):
        seed, path = 907, os.path.join(ROOT, "incoming", "variant_907.txt")
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "generate_unknown_source.py"),
                            "--seed", str(seed), "--mode", "unmappable"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(path, encoding="utf-8") as f:
            header = f.readline().rstrip("\n")
        # best-effort proposal: map every real column, invent nothing
        delim = next(d for d in "^~|;\t," if d in header)
        names = lib.split_row(header, delim)
        # whatever a model proposes, region has no source column -- either it
        # omits the target (structural fail) or points at a bogus source (S5)
        p = {"delimiter": delim, "has_header": True, "columns": [
            {"source": n, "target": t, "transforms": ["strip"]}
            for n, t in zip(names, lib.TARGET_FIELDS)], "value_maps": {}}
        problems = lib.structural_check(p)
        if not problems:
            gates = lib.apply_and_gate(p, path)[0]
            self.assertTrue(any(not ok for _, ok, _ in gates),
                            "an unmappable file must not pass the gates")
        os.remove(path)


class TestVariants(unittest.TestCase):
    def test_variant_deterministic_per_seed_and_unlike_canonical(self):
        path = os.path.join(ROOT, "incoming", "variant_77.txt")
        def gen():
            r = subprocess.run([sys.executable,
                                os.path.join(ROOT, "generate_unknown_source.py"),
                                "--seed", "77"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        h1, h2 = gen(), gen()
        self.assertEqual(h1, h2, "same seed must produce identical bytes")
        with open(path, encoding="utf-8") as f:
            variant_header = f.readline()
        with open(SOURCE, encoding="utf-8") as f:
            canonical_header = f.readline()
        self.assertNotEqual(variant_header, canonical_header,
                            "variant conventions should differ from the fixture")
        os.remove(path)


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


class TestPublicPOContract(unittest.TestCase):
    """The second contract's gates must reject semantically wrong mappings
    even though no CRM or catalog exists to check against."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "mapper"))
        import public_po_lib
        cls.lib = public_po_lib
        cls.rec = os.path.join(ROOT, "mapper", "recorded", "external.json")

    def test_state_list_is_real_ground_truth(self):
        self.assertIn("VT", self.lib.US_STATES)
        self.assertIn("PR", self.lib.US_STATES)
        self.assertNotIn("EMEA", self.lib.US_STATES)
        self.assertNotIn("ZZ", self.lib.US_STATES)
        self.assertEqual(len(self.lib.US_STATES), 56)

    def test_money_transform(self):
        f = self.lib.apply_transforms
        self.assertEqual(f("$49,500.00", ["money"], "amount", {}), 49500.0)
        with self.assertRaises(self.lib.TransformError):
            f("n/a", ["money"], "amount", {})

    def test_missing_required_target_is_structural_failure(self):
        p = {"format": "delimited", "delimiter": ",",
             "columns": [{"source": "a", "target": "po_id", "transforms": []}]}
        problems = self.lib.structural_check(p)
        for field in ("po_date", "vendor_name", "amount", "region"):
            self.assertTrue(any(field in m for m in problems), f"{field}: {problems}")

    def test_region_map_to_non_state_rejected(self):
        p = {"format": "delimited", "delimiter": ",", "columns": [
                {"source": c, "target": t, "transforms": []} for c, t in
                [("a", "po_id"), ("b", "po_date"), ("c", "vendor_name"),
                 ("d", "amount"), ("e", "region")]],
             "value_maps": {"region": {"X": "EMEA"}}}
        self.assertTrue(any("non-state" in m for m in self.lib.structural_check(p)))

    def test_unknown_format_rejected(self):
        p = {"format": "parquet", "columns": [{"source": "a", "target": "po_id"}]}
        self.assertTrue(any("format must be" in m for m in self.lib.structural_check(p)))

    def test_recorded_external_run_is_all_correct(self):
        if not os.path.exists(self.rec):
            self.skipTest("no recorded external run")
        with open(self.rec, encoding="utf-8") as f:
            ex = json.load(f)
        wrong = [r["file"] for r in ex["results"] if not r["correct"]]
        self.assertEqual(wrong, [], f"wrong outcomes: {wrong}")
        self.assertGreaterEqual(ex["refused"], 1, "a run with no refusals proves nothing")


class TestRedaction(unittest.TestCase):
    """Nothing sensitive may reach a model. These tests fail if it does."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "mapper"))
        import redact, propose_mapping
        cls.redact, cls.pm = redact, propose_mapping
        cls.ext = os.path.join(ROOT, "incoming", "external",
                               "providence_purchase_orders.csv")

    def test_emails_are_replaced_with_shape_preserving_surrogates(self):
        out = self.redact.redact_value("christine.martinez@wbmason.com")
        self.assertNotIn("wbmason", out)
        self.assertNotIn("christine", out.lower())
        self.assertIn("@", out)                    # still reads as an email

    def test_surrogates_are_deterministic(self):
        a = self.redact.redact_value("a.person@example.com")
        b = self.redact.redact_value("a.person@example.com")
        c = self.redact.redact_value("other.person@example.com")
        self.assertEqual(a, b)                     # cardinality preserved
        self.assertNotEqual(a, c)

    def test_header_hints_catch_names_and_addresses(self):
        self.assertEqual(self.redact.classify_header("vendor_contct"), "person")
        self.assertEqual(self.redact.classify_header("e_mail_address"), "email")
        self.assertEqual(self.redact.classify_header("address1"), "address")
        self.assertIsNone(self.redact.classify_header("po_number"))

    def test_values_needed_for_mapping_are_untouched(self):
        for keep in ("2026-07-31T00:00:00.000", "4000", "MA", "WB MASON CO.   INC"):
            self.assertEqual(self.redact.redact_value(keep), keep)

    def test_no_raw_pii_reaches_the_prompt(self):
        if not os.path.exists(self.ext):
            self.skipTest("external file not fetched")
        import public_po_lib
        self.pm.lib = public_po_lib
        prompt = self.pm.build_prompt(self.ext)
        with open(self.ext, encoding="utf-8") as f:
            raw = f.read()
        emails = set(re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", raw))
        leaked = [e for e in emails if e in prompt]
        self.assertEqual(leaked, [], f"raw emails reached the prompt: {leaked[:3]}")
        self.assertIn("example.invalid", prompt)   # surrogates are present

    def test_opting_out_is_explicit_and_visible(self):
        if not os.path.exists(self.ext):
            self.skipTest("external file not fetched")
        import public_po_lib
        self.pm.lib = public_po_lib
        self.pm.build_prompt(self.ext, no_redact=True)
        self.assertTrue(self.pm.LAST_REDACTION.get("skipped"))


class TestHumanApproval(unittest.TestCase):
    """Passing the gates makes a mapping eligible, not approved."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "mapper"))
        import approve
        cls.approve = approve

    def test_recorded_proposal_is_signed(self):
        with open(RECORDED, encoding="utf-8") as f:
            doc = json.load(f)
        appr = doc.get("approval") or {}
        self.assertEqual(appr.get("status"), "approved", "recorded run is unsigned")
        self.assertTrue(appr.get("by"), "an approval must name a person")

    def test_fingerprint_binds_approval_to_the_exact_proposal(self):
        with open(RECORDED, encoding="utf-8") as f:
            doc = json.load(f)
        fp = self.approve.fingerprint(doc["proposal"])
        self.assertEqual(fp, doc["approval"]["proposal_fingerprint"])
        tampered = copy.deepcopy(doc["proposal"])
        tampered["columns"][0]["target"] = "region"
        self.assertNotEqual(self.approve.fingerprint(tampered),
                            doc["approval"]["proposal_fingerprint"],
                            "editing a proposal must invalidate its approval")

    def test_ci_refuses_an_unapproved_mapping(self):
        import tempfile, shutil
        with open(RECORDED, encoding="utf-8") as f:
            doc = json.load(f)
        doc.pop("approval", None)
        tmp = os.path.join(tempfile.gettempdir(), "unapproved_proposal.json")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "mapper", "validate_mapping.py"),
             "--proposal", tmp, "--require-approval",
             "--report", os.path.join(tempfile.gettempdir(), "r.md"),
             "--out", os.path.join(tempfile.gettempdir(), "o.csv")],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 1, "unapproved mapping was allowed to land")
        self.assertIn("H1", r.stdout)
        os.remove(tmp)


class TestContractRegistry(unittest.TestCase):
    """A contract is configuration. Adding a domain must need no Python."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "mapper"))
        import contract_lib
        cls.cl = contract_lib
        cls.ext = os.path.join(ROOT, "incoming", "external")
        cls.runs = os.path.join(ROOT, "mapper", "runs")

    def test_contracts_are_discovered_from_disk(self):
        found = self.cl.available()
        self.assertIn("public_po", found)
        self.assertIn("invoice_register", found)

    def test_every_contract_declares_required_fields_and_gates(self):
        for name in self.cl.available():
            c = self.cl.Contract(self.cl.load(name))
            self.assertTrue(c.REQUIRED, f"{name} declares no required fields")
            self.assertTrue(c.gates, f"{name} declares no gates")
            for g in c.gates:
                self.assertIn("check", g, f"{name}: gate without a check type")

    def test_config_contract_matches_the_python_one(self):
        """The TOML public_po must reach the same verdicts as public_po_lib."""
        import public_po_lib
        toml = self.cl.Contract(self.cl.load("public_po"))
        for stem, src in [("providence_purchase_orders",
                           "providence_purchase_orders.csv"),
                          ("vermont_purchase_orders",
                           "vermont_purchase_orders.json")]:
            p = os.path.join(self.runs, stem + ".json")
            s = os.path.join(self.ext, src)
            if not (os.path.exists(p) and os.path.exists(s)):
                self.skipTest("external run artifacts not present")
            proposal = json.load(open(p, encoding="utf-8"))["proposal"]
            py_ok = all(ok for _, ok, _ in public_po_lib.apply_and_gate(proposal, s)[0])
            tm_ok = all(ok for _, ok, _ in toml.apply_and_gate(proposal, s)[0])
            self.assertEqual(py_ok, tm_ok, f"{stem}: config and code disagree")

    def test_a_new_domain_needs_only_a_file(self):
        """LA City is refused by public_po and accepted by invoice_register --
        two contracts, one file, and no Python written for either outcome."""
        src = os.path.join(self.ext, "lacity_invoices.tsv")
        prop = os.path.join(self.runs, "lacity_invoice.json")
        if not (os.path.exists(src) and os.path.exists(prop)):
            self.skipTest("invoice run artifacts not present")
        proposal = json.load(open(prop, encoding="utf-8"))["proposal"]
        inv = self.cl.Contract(self.cl.load("invoice_register"))
        self.assertEqual(inv.structural_check(proposal), [])
        gates, conformed = inv.apply_and_gate(proposal, src)
        self.assertTrue(all(ok for _, ok, _ in gates),
                        [g for g in gates if not g[1]])
        self.assertGreater(len(conformed), 0)
        # ... and the PO contract still refuses the same file
        po = self.cl.Contract(self.cl.load("public_po"))
        self.assertTrue(any("amount" in m or "region" in m
                            for m in po.structural_check(proposal)))
