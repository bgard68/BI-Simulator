"""
Coverage for generate_sources.py, which fabricates all 18 source systems.

The seed is the contract. Every figure asserted anywhere else in this suite -
7,670 rows, $3,056,034.74 - only holds because random.seed(42) makes generation
reproducible. If that breaks, every other pinned number becomes noise, so it is
tested first and directly.

Like the rest of the pipeline this is a script: it writes sources/ on import.
It is therefore loaded from a throwaway directory whose output is discarded.
"""
import datetime
import filecmp
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECTED_SOURCE_FILES = {
    "ad_spend_daily.csv", "crm_customers.csv", "email_stats.json",
    "erp_sales.db", "finance_targets.csv", "fx_rates.csv",
    "hr_sales_reps.csv", "inventory_snapshot.csv", "marketing_campaigns.csv",
    "nps_surveys.csv", "payment_gateway.jsonl", "product_catalog.json",
    "returns_rma.csv", "shipping_tracking.csv", "store_locations.json",
    "supplier_pricelist.xml", "support_tickets.csv", "web_analytics.jsonl",
}

_work = None
gen = None


def _copy_pipeline(dest):
    shutil.copytree(os.path.join(REPO, "mapper"), os.path.join(dest, "mapper"))
    for name in os.listdir(REPO):
        if name.endswith(".py"):
            shutil.copy(os.path.join(REPO, name), os.path.join(dest, name))


def setUpModule():
    global _work, gen
    _work = tempfile.mkdtemp(prefix="bi-gen-")
    _copy_pipeline(_work)

    spec = importlib.util.spec_from_file_location(
        "generate_under_test", os.path.join(_work, "generate_sources.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)


def tearDownModule():
    shutil.rmtree(_work, ignore_errors=True)


def _sources_dir(root):
    return os.path.join(root, "sources")


class TestMonthsBetween(unittest.TestCase):
    """The month spine every monthly aggregate is built on."""

    def test_MonthsBetween_AcrossOneYear_ReturnsEveryMonthInclusive(self):
        result = gen.months_between(datetime.date(2026, 1, 15),
                                    datetime.date(2026, 4, 2))

        self.assertEqual(["2026-01", "2026-02", "2026-03", "2026-04"], result)

    def test_MonthsBetween_WithinASingleMonth_ReturnsThatMonthOnce(self):
        result = gen.months_between(datetime.date(2026, 7, 1),
                                    datetime.date(2026, 7, 31))

        self.assertEqual(["2026-07"], result)

    def test_MonthsBetween_AcrossAYearBoundary_RollsTheYearOver(self):
        result = gen.months_between(datetime.date(2025, 11, 30),
                                    datetime.date(2026, 2, 1))

        self.assertEqual(["2025-11", "2025-12", "2026-01", "2026-02"], result)

    def test_MonthsBetween_IgnoresTheDayComponentEntirely(self):
        first = gen.months_between(datetime.date(2026, 3, 1),
                                   datetime.date(2026, 5, 1))
        last = gen.months_between(datetime.date(2026, 3, 31),
                                  datetime.date(2026, 5, 31))

        self.assertEqual(first, last)

    def test_MonthsBetween_WithAReversedRange_ReturnsNothing(self):
        result = gen.months_between(datetime.date(2026, 6, 1),
                                    datetime.date(2026, 1, 1))

        self.assertEqual([], result)

    def test_MonthsBetween_WithTheEndOneMonthBeforeTheStart_ReturnsNothing(self):
        result = gen.months_between(datetime.date(2026, 6, 1),
                                    datetime.date(2026, 5, 31))

        self.assertEqual([], result)

    def test_MonthsBetween_ZeroPadsSingleDigitMonths(self):
        result = gen.months_between(datetime.date(2026, 1, 1),
                                    datetime.date(2026, 1, 1))

        self.assertEqual(["2026-01"], result)


class TestGeneratedSourceSet(unittest.TestCase):
    """All 18 systems must appear; etl.py hard-codes every filename."""

    def test_Generate_AfterARun_WritesExactlyTheEighteenExpectedSources(self):
        produced = set(os.listdir(_sources_dir(_work)))

        self.assertEqual(EXPECTED_SOURCE_FILES, produced)

    def test_Generate_AfterARun_LeavesNoEmptySourceFile(self):
        directory = _sources_dir(_work)

        empty = [n for n in os.listdir(directory)
                 if os.path.getsize(os.path.join(directory, n)) == 0]

        self.assertEqual([], empty)

    def test_Generate_AfterARun_WritesTheCatalogAsParseableJson(self):
        path = os.path.join(_sources_dir(_work), "product_catalog.json")

        with open(path, encoding="utf-8") as f:
            catalog = json.load(f)

        self.assertGreater(len(catalog), 0)

    def test_Generate_AfterARun_WritesTheGatewayFeedAsOneJsonObjectPerLine(self):
        path = os.path.join(_sources_dir(_work), "payment_gateway.jsonl")

        with open(path, encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]

        self.assertGreater(len(records), 0)
        self.assertIsInstance(records[0], dict)


class TestGenerationIsSeeded(unittest.TestCase):
    """
    Determinism is the contract the rest of the suite's pinned figures rest on.
    Two independent processes, same seed, byte-identical text sources.
    """

    def setUp(self):
        self.a = tempfile.mkdtemp(prefix="bi-seed-a-")
        self.b = tempfile.mkdtemp(prefix="bi-seed-b-")
        self.addCleanup(shutil.rmtree, self.a, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.b, ignore_errors=True)
        _copy_pipeline(self.a)
        _copy_pipeline(self.b)

    def _generate(self, root):
        return subprocess.run([sys.executable, "generate_sources.py"], cwd=root,
                              capture_output=True, text=True)

    def test_Generate_RunTwiceInSeparateProcesses_ProducesIdenticalTextSources(self):
        self.assertEqual(0, self._generate(self.a).returncode)
        self.assertEqual(0, self._generate(self.b).returncode)
        text_sources = sorted(n for n in EXPECTED_SOURCE_FILES if not n.endswith(".db"))

        matched, mismatched, errors = filecmp.cmpfiles(
            _sources_dir(self.a), _sources_dir(self.b), text_sources, shallow=False)

        self.assertEqual([], mismatched)
        self.assertEqual([], errors)
        self.assertEqual(len(text_sources), len(matched))

    def test_Generate_RunTwiceInSeparateProcesses_ProducesTheSameCustomerRoster(self):
        self.assertEqual(0, self._generate(self.a).returncode)
        self.assertEqual(0, self._generate(self.b).returncode)

        with open(os.path.join(_sources_dir(self.a), "crm_customers.csv"),
                  encoding="utf-8") as f:
            first = f.read()
        with open(os.path.join(_sources_dir(self.b), "crm_customers.csv"),
                  encoding="utf-8") as f:
            second = f.read()

        self.assertEqual(first, second)


class TestMonthsBetweenRejectsBadInput(unittest.TestCase):
    """The spine is built from dates; anything else must fail at the call, not later."""

    def test_MonthsBetween_WithANullStart_RaisesAttributeError(self):
        with self.assertRaises(AttributeError):
            gen.months_between(None, datetime.date(2026, 1, 1))

    def test_MonthsBetween_WithANullEnd_RaisesAttributeError(self):
        with self.assertRaises(AttributeError):
            gen.months_between(datetime.date(2026, 1, 1), None)

    def test_MonthsBetween_WithAnIsoStringInsteadOfADate_RaisesAttributeError(self):
        # A string that looks like a date is the likeliest wrong argument, and it
        # must not silently produce a plausible-looking spine.
        with self.assertRaises(AttributeError):
            gen.months_between("2026-01-01", datetime.date(2026, 3, 1))


class TestWeightedChoiceRejectsBadInput(unittest.TestCase):
    """
    wchoice drives most of the fabricated distributions. A silent wrong answer
    here would skew the whole dataset without failing anything.
    """

    def test_WChoice_WithNoItems_RaisesIndexError(self):
        with self.assertRaises(IndexError):
            gen.wchoice([], [])

    def test_WChoice_WithFewerWeightsThanItems_RaisesValueError(self):
        with self.assertRaises(ValueError):
            gen.wchoice(["a", "b"], [1])

    def test_WChoice_WithMoreWeightsThanItems_RaisesValueError(self):
        with self.assertRaises(ValueError):
            gen.wchoice(["a"], [1, 1])

    def test_WChoice_WithAllZeroWeights_RaisesValueError(self):
        with self.assertRaises(ValueError):
            gen.wchoice(["a", "b"], [0, 0])

    def test_WChoice_WithASingleItem_AlwaysReturnsThatItem(self):
        result = gen.wchoice(["only"], [1])

        self.assertEqual("only", result)


class TestGeneratedSourcesAreWellFormed(unittest.TestCase):
    """A file that exists but is unreadable is worse than one that is missing."""

    def test_ErpDatabase_AfterARun_IsAReadableSqliteFileWithBothTables(self):
        path = os.path.join(_sources_dir(_work), "erp_sales.db")

        con = sqlite3.connect(path)
        self.addCleanup(con.close)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

        self.assertIn("orders", tables)
        self.assertIn("order_items", tables)

    def test_SupplierPricelist_AfterARun_IsParseableXml(self):
        path = os.path.join(_sources_dir(_work), "supplier_pricelist.xml")

        root = ElementTree.parse(path).getroot()

        self.assertGreater(len(list(root)), 0)

    def test_GeneratedSources_AfterARun_ContainNoStraySetReprLeakage(self):
        # A set that reached a CSV cell would serialise as "{'a', 'b'}" and also be
        # order-unstable - the same class of defect as the list({...}) fix.
        path = os.path.join(_sources_dir(_work), "crm_customers.csv")

        with open(path, encoding="utf-8") as f:
            body = f.read()

        self.assertNotIn("{'", body)
        self.assertNotIn("set()", body)


if __name__ == "__main__":
    unittest.main()
