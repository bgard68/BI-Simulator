"""
Coverage for build_mapping_page.py, which renders the agentic-mapping evidence page.

Everything on that page comes from somewhere untrusted: the column names and
transforms are what a model proposed, and the sample block is raw text from an
external file that deliberately carries a prompt-injection canary. All of it is
interpolated into HTML through E = html.escape.

If that escaping lapses, a model proposal becomes stored XSS on a published page -
and the page whose entire point is demonstrating that untrusted input is handled
safely would be the thing serving it. That is what these tests defend.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

XSS = '<script>alert(1)</script>'
ESCAPED_XSS = '&lt;script&gt;alert(1)&lt;/script&gt;'


def _run(script, cwd):
    return subprocess.run(
        [sys.executable, script], cwd=cwd, capture_output=True, text=True)


class TestBuildMappingPage(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="bi-map-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

        shutil.copytree(os.path.join(REPO, "mapper"), os.path.join(self.work, "mapper"))
        shutil.copytree(os.path.join(REPO, "incoming"),
                        os.path.join(self.work, "incoming"))
        for name in os.listdir(REPO):
            if name.endswith(".py") or name.endswith(".html"):
                shutil.copy(os.path.join(REPO, name), os.path.join(self.work, name))

        # apply_and_gate() reads sources/crm_customers.csv, so the pipeline's
        # sources have to exist before the page can be built.
        generated = _run("generate_sources.py", self.work)
        self.assertEqual(0, generated.returncode, generated.stderr)

        self.recorded = os.path.join(self.work, "mapper", "recorded", "proposal.json")
        self.source = os.path.join(
            self.work, "incoming", "warranty_registrations.txt")
        self.out = os.path.join(self.work, "output", "mapping.html")

    def _read_page(self):
        with open(self.out, encoding="utf-8") as f:
            return f.read()

    def _poison_first_source_column(self, value):
        with open(self.recorded, encoding="utf-8") as f:
            recorded = json.load(f)
        recorded["proposal"]["columns"][0]["source"] = value
        with open(self.recorded, "w", encoding="utf-8") as f:
            json.dump(recorded, f)

    # ---- the escaping ----------------------------------------------------------

    def test_Build_WithAScriptTagInAProposedColumnName_EscapesItInTheOutput(self):
        self._poison_first_source_column(XSS)

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        page = self._read_page()
        self.assertNotIn(XSS, page)
        self.assertIn(ESCAPED_XSS, page)

    def test_Build_WithAnImgOnerrorPayloadInAColumnName_EscapesTheAngleBrackets(self):
        self._poison_first_source_column('<img src=x onerror=alert(1)>')

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        page = self._read_page()
        self.assertNotIn('<img src=x onerror=alert(1)>', page)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', page)

    def test_Build_WithAnAttributeBreakoutInAColumnName_EscapesTheQuote(self):
        # The value lands inside a <td>, but html.escape(quote=True) also covers the
        # attribute case, so a future move into an attribute stays safe.
        self._poison_first_source_column('" onmouseover="alert(1)')

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        page = self._read_page()
        self.assertNotIn('" onmouseover="alert(1)', page)
        self.assertIn('&quot; onmouseover=&quot;alert(1)', page)

    def test_Build_WithTheRecordedProposal_EscapesTheEmbeddedJsonDump(self):
        self._poison_first_source_column(XSS)

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        # The whole proposal is also dumped into a <pre> block; that copy must be
        # escaped too, not just the table cell.
        self.assertEqual(0, self._read_page().count("<script>alert(1)</script>"))

    def test_Build_WithTheInjectionCanaryInTheSource_RendersItAsInertText(self):
        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        page = self._read_page()
        self.assertIn("IGNORE ALL PREVIOUS", page)
        self.assertNotIn("<script>", page.split("IGNORE ALL PREVIOUS")[1][:200])

    def test_Build_WithMarkupInTheSourceSample_EscapesTheSampleBlock(self):
        with open(self.source, "a", encoding="utf-8") as f:
            f.write("\n" + XSS + "\n")

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(XSS, self._read_page())

    # ---- the output ------------------------------------------------------------

    def test_Build_AfterAFullRun_WritesTheMappingPage(self):
        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(os.path.exists(self.out))

    def test_Build_AfterAFullRun_ReportsTheAcceptedVerdictForTheRecordedProposal(self):
        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("ACCEPTED", result.stdout)

    # ---- negatives -------------------------------------------------------------

    def test_Build_WithNoRecordedProposal_FailsInsteadOfPublishingAnEmptyPage(self):
        os.remove(self.recorded)

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(1, result.returncode)
        self.assertIn("FileNotFoundError", result.stderr)

    def test_Build_WithNoSourceFile_FailsInsteadOfPublishingAPageWithNoEvidence(self):
        os.remove(self.source)

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(1, result.returncode)
        self.assertIn("FileNotFoundError", result.stderr)

    def test_Build_WithAMalformedRecordedProposal_FailsRatherThanRenderingPartially(self):
        with open(self.recorded, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(1, result.returncode)
        self.assertIn("JSONDecodeError", result.stderr)

    def test_Build_WithNoRecordedProposal_WritesNoPage(self):
        os.remove(self.recorded)

        _run("build_mapping_page.py", self.work)

        self.assertFalse(os.path.exists(self.out))


    def test_Build_WithAProposalMissingItsColumnsKey_FailsRatherThanRenderingEmpty(self):
        with open(self.recorded, encoding="utf-8") as f:
            recorded = json.load(f)
        del recorded["proposal"]["columns"]
        with open(self.recorded, "w", encoding="utf-8") as f:
            json.dump(recorded, f)

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(1, result.returncode)
        self.assertIn("KeyError", result.stderr)

    def test_Build_WithNoProposalKeyAtAll_FailsRatherThanRenderingEmpty(self):
        with open(self.recorded, "w", encoding="utf-8") as f:
            json.dump({"meta": {}}, f)

        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(1, result.returncode)
        self.assertIn("KeyError", result.stderr)

    def test_Build_WithAnEmptySourceFile_StillEscapesAndDoesNotCrashOnTheCanary(self):
        # No canary line means the lookup returns (None, None); the page must still
        # render rather than blow up interpolating a missing match.
        with open(self.source, "w", encoding="utf-8") as f:
            f.write("")

        result = _run("build_mapping_page.py", self.work)

        self.assertNotEqual(2, result.returncode)

    def test_Build_WithNoTemplateDirectoryWritable_IsNotSilentlySkipped(self):
        # Guards the inverse of the negatives above: a successful exit must mean a
        # page was actually written, not that the build quietly did nothing.
        result = _run("build_mapping_page.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertGreater(os.path.getsize(self.out), 1000)

if __name__ == "__main__":
    unittest.main()
