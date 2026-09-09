"""
Unit coverage for etl.py's conforming primitives.

etl.py runs its pipeline on import, so the module is loaded from a throwaway
directory with its own generated sources: the import's side effects land in that
directory's warehouse/ and are discarded. The assertions below are true unit
tests - one function, fixed input, exact output - even though loading costs a run.

Deliberately no exec/eval of a truncated source to dodge that cost. It would be
faster and would also be the kind of cleverness that outlives the person who
understood it.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_work = None
etl = None


def setUpModule():
    global _work, etl
    _work = tempfile.mkdtemp(prefix="bi-prim-")
    shutil.copytree(os.path.join(REPO, "mapper"), os.path.join(_work, "mapper"))
    for name in os.listdir(REPO):
        if name.endswith(".py"):
            shutil.copy(os.path.join(REPO, name), os.path.join(_work, name))

    generated = subprocess.run(
        [sys.executable, "generate_sources.py"], cwd=_work,
        capture_output=True, text=True)
    assert generated.returncode == 0, generated.stderr

    spec = importlib.util.spec_from_file_location(
        "etl_under_test", os.path.join(_work, "etl.py"))
    etl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(etl)


def tearDownModule():
    shutil.rmtree(_work, ignore_errors=True)


class TestConformRegion(unittest.TestCase):
    """Region codes arrive from the CRM with inconsistent case and padding."""

    def test_ConformRegion_WithACanonicalCode_ReturnsTheFullName(self):
        result = etl.conform_region("NA")

        self.assertEqual("North America", result)

    def test_ConformRegion_WithALowercaseCode_UppercasesBeforeLookup(self):
        result = etl.conform_region("emea")

        self.assertEqual("EMEA", result)

    def test_ConformRegion_WithSurroundingWhitespace_StripsBeforeLookup(self):
        result = etl.conform_region("  apac  ")

        self.assertEqual("APAC", result)

    def test_ConformRegion_WithMixedCaseAndPadding_ReturnsTheFullName(self):
        result = etl.conform_region(" LaTaM ")

        self.assertEqual("LATAM", result)

    def test_ConformRegion_WithAnUnknownCode_RaisesKeyErrorNamingTheValue(self):
        with self.assertRaises(KeyError) as caught:
            etl.conform_region("MARS")

        self.assertEqual("MARS", caught.exception.args[0])

    def test_ConformRegion_WithAnEmptyString_RaisesKeyError(self):
        with self.assertRaises(KeyError):
            etl.conform_region("")

    def test_ConformRegion_WithAFullNameInsteadOfACode_RaisesKeyError(self):
        # "North America" is the output vocabulary, not the input one. Accepting it
        # would make the function quietly non-idempotent.
        with self.assertRaises(KeyError):
            etl.conform_region("North America")

    def test_ConformRegion_WithANonString_RaisesAttributeError(self):
        with self.assertRaises(AttributeError):
            etl.conform_region(None)


class TestParseDate(unittest.TestCase):
    """Each source exports dates its own way; all of them must land on ISO."""

    def test_ParseDate_WithUsSlashFormat_ReturnsIsoDate(self):
        result = etl.parse_date("03/04/2026", "%m/%d/%Y")

        self.assertEqual("2026-03-04", result)

    def test_ParseDate_WithSingleDigitMonthAndDay_ReturnsZeroPaddedIso(self):
        result = etl.parse_date("3/4/2026", "%m/%d/%Y")

        self.assertEqual("2026-03-04", result)

    def test_ParseDate_WithSurroundingWhitespace_StripsBeforeParsing(self):
        result = etl.parse_date("  03/04/2026  ", "%m/%d/%Y")

        self.assertEqual("2026-03-04", result)

    def test_ParseDate_WithDayFirstFormat_ReadsTheDayAsTheDay(self):
        # The same string under a different declared format is a different date.
        # This is the swap that silently corrupts the first twelve days of a month.
        result = etl.parse_date("03/04/2026", "%d/%m/%Y")

        self.assertEqual("2026-04-03", result)

    def test_ParseDate_WithAnIsoStringUnderTheSlashFormat_RaisesValueError(self):
        with self.assertRaises(ValueError):
            etl.parse_date("2026-03-04", "%m/%d/%Y")

    def test_ParseDate_WithNonDateText_RaisesValueError(self):
        with self.assertRaises(ValueError):
            etl.parse_date("not-a-date", "%m/%d/%Y")

    def test_ParseDate_WithAnImpossibleCalendarDate_RaisesValueError(self):
        with self.assertRaises(ValueError):
            etl.parse_date("02/30/2026", "%m/%d/%Y")

    def test_ParseDate_WithAnEmptyString_RaisesValueError(self):
        with self.assertRaises(ValueError):
            etl.parse_date("   ", "%m/%d/%Y")

    def test_ParseDate_WithTrailingContentAfterAValidDate_RaisesValueError(self):
        with self.assertRaises(ValueError):
            etl.parse_date("03/04/2026 09:15", "%m/%d/%Y")


class TestSourceReaders(unittest.TestCase):
    """The readers are thin, but a silent empty read would empty the warehouse."""

    def test_ReadCsv_OverTheGeneratedCrmExtract_ReturnsDictRowsWithKnownColumns(self):
        rows = etl.read_csv("crm_customers.csv")

        self.assertGreater(len(rows), 0)
        self.assertIn("customer_id", rows[0])
        self.assertIn("region", rows[0])
        self.assertIn("signup_date", rows[0])

    def test_ReadJsonl_OverTheGeneratedGatewayExtract_ReturnsOneDictPerLine(self):
        records = etl.read_jsonl("payment_gateway.jsonl")

        self.assertGreater(len(records), 0)
        self.assertIsInstance(records[0], dict)

    def test_ReadJson_OverTheGeneratedCatalog_ReturnsTheParsedDocument(self):
        catalog = etl.read_json("product_catalog.json")

        self.assertGreater(len(catalog), 0)

    def test_ReadCsv_ForAFileThatIsNotThere_RaisesFileNotFoundError(self):
        with self.assertRaises(FileNotFoundError):
            etl.read_csv("no_such_source.csv")

    def test_ReadJson_ForAFileThatIsNotThere_RaisesFileNotFoundError(self):
        with self.assertRaises(FileNotFoundError):
            etl.read_json("no_such_source.json")

    def test_ReadJsonl_ForAFileThatIsNotThere_RaisesFileNotFoundError(self):
        with self.assertRaises(FileNotFoundError):
            etl.read_jsonl("no_such_source.jsonl")


if __name__ == "__main__":
    unittest.main()
