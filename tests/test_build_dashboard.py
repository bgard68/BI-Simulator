"""
Coverage for build_dashboard.py, which injects the warehouse payload into the
HTML template and emits both the standalone page and the artifact body.

The load-bearing line is the "</" escape. dashboard_data.json contains product
and campaign names straight from the sources, so a "</script>" anywhere in that
data would close the block it is embedded in and drop the rest of the payload
into the document as markup. That is a script-injection sink, and it is the one
thing here worth a test that fails loudly.

Like etl.py this is a script, so it is run rather than imported.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLACEHOLDERS = ("__DATA_JSON__", "__MAPPING_LINK__", "__HAS_MAPPING_PAGE__")


def _run(script, cwd):
    return subprocess.run(
        [sys.executable, script], cwd=cwd, capture_output=True, text=True)


class TestBuildDashboard(unittest.TestCase):
    """Each test gets its own pipeline directory so payloads can be rewritten."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="bi-dash-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

        shutil.copytree(os.path.join(REPO, "mapper"), os.path.join(self.work, "mapper"))
        for name in os.listdir(REPO):
            if name.endswith(".py") or name.endswith(".html"):
                shutil.copy(os.path.join(REPO, name), os.path.join(self.work, name))

        generated = _run("generate_sources.py", self.work)
        self.assertEqual(0, generated.returncode, generated.stderr)
        extracted = _run("etl.py", self.work)
        self.assertEqual(0, extracted.returncode, extracted.stderr)

        self.payload_path = os.path.join(self.work, "warehouse", "dashboard_data.json")
        self.dashboard_path = os.path.join(self.work, "output", "dashboard.html")
        self.artifact_path = os.path.join(self.work, "output", "artifact.html")

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _inject_into_payload(self, hostile_value):
        """Puts a hostile string into a real payload field the template embeds."""
        with open(self.payload_path, encoding="utf-8") as f:
            payload = json.load(f)
        payload["meta"]["company"] = hostile_value
        with open(self.payload_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))

    # ---- the escape ------------------------------------------------------------

    def test_Build_WithAClosingScriptTagInThePayload_EscapesItSoTheBlockSurvives(self):
        self._inject_into_payload("Cobalt</script><img src=x onerror=alert(1)>")

        result = _run("build_dashboard.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        page = self._read(self.dashboard_path)
        self.assertNotIn("</script><img", page)
        self.assertIn("<\\/script><img", page)

    def test_Build_WithAClosingScriptTagInThePayload_EscapesItInTheArtifactToo(self):
        self._inject_into_payload("Cobalt</script><img src=x onerror=alert(1)>")

        result = _run("build_dashboard.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        artifact = self._read(self.artifact_path)
        self.assertNotIn("</script><img", artifact)
        self.assertIn("<\\/script><img", artifact)

    def test_Build_WithAnyClosingTagInThePayload_EscapesEverySlashNotJustTheFirst(self):
        self._inject_into_payload("a</b>c</i>d</script>e")

        result = _run("build_dashboard.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        page = self._read(self.dashboard_path)
        self.assertIn("a<\\/b>c<\\/i>d<\\/script>e", page)

    def test_Build_WithAnEscapedPayload_StillParsesBackToTheOriginalValue(self):
        # The escape must be reversible: "<\/" is valid JSON for "</", so the
        # browser sees the original string. An escape that corrupted the data
        # would be no better than the injection.
        hostile = "Cobalt</script>"
        self._inject_into_payload(hostile)

        result = _run("build_dashboard.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(hostile, json.loads('"Cobalt<\\/script>"'))

    # ---- the two outputs -------------------------------------------------------

    def test_Build_AfterAFullRun_WritesBothTheStandalonePageAndTheArtifact(self):
        result = _run("build_dashboard.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(os.path.exists(self.dashboard_path))
        self.assertTrue(os.path.exists(self.artifact_path))

    def test_Build_AfterAFullRun_LeavesNoUnreplacedPlaceholderInTheStandalonePage(self):
        _run("build_dashboard.py", self.work)

        page = self._read(self.dashboard_path)

        self.assertNotIn(PLACEHOLDERS[0], page)
        self.assertNotIn(PLACEHOLDERS[1], page)
        self.assertNotIn(PLACEHOLDERS[2], page)

    def test_Build_AfterAFullRun_LeavesNoUnreplacedPlaceholderInTheArtifact(self):
        _run("build_dashboard.py", self.work)

        artifact = self._read(self.artifact_path)

        self.assertNotIn(PLACEHOLDERS[0], artifact)
        self.assertNotIn(PLACEHOLDERS[1], artifact)
        self.assertNotIn(PLACEHOLDERS[2], artifact)

    def test_Build_AfterAFullRun_GivesTheStandalonePageAFullHtmlDocumentShell(self):
        _run("build_dashboard.py", self.work)

        page = self._read(self.dashboard_path)

        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn('<html lang="en">', page)
        self.assertIn("</body>\n</html>", page)

    def test_Build_AfterAFullRun_LeavesTheArtifactAsBodyContentWithNoDoctype(self):
        # The artifact is embedded in a host page, so its own document shell would
        # nest a second <html> inside the host's body.
        _run("build_dashboard.py", self.work)

        artifact = self._read(self.artifact_path)

        self.assertNotIn("<!doctype html>", artifact.lower())

    def test_Build_AfterAFullRun_EnablesTheMappingLinkOnlyOnTheStandalonePage(self):
        _run("build_dashboard.py", self.work)

        page = self._read(self.dashboard_path)
        artifact = self._read(self.artifact_path)

        self.assertIn('href="mapping.html"', page)
        self.assertNotIn('href="mapping.html"', artifact)

    # ---- negatives -------------------------------------------------------------

    def test_Build_WithNoWarehousePayload_FailsInsteadOfEmittingAnEmptyDashboard(self):
        os.remove(self.payload_path)

        result = _run("build_dashboard.py", self.work)

        self.assertEqual(1, result.returncode)
        self.assertIn("FileNotFoundError", result.stderr)

    def test_Build_WithNoTemplate_FailsInsteadOfWritingABareDocument(self):
        os.remove(os.path.join(self.work, "dashboard_template.html"))

        result = _run("build_dashboard.py", self.work)

        self.assertEqual(1, result.returncode)
        self.assertIn("FileNotFoundError", result.stderr)

    def test_Build_WithNoWarehousePayload_WritesNoStandalonePage(self):
        os.remove(self.payload_path)

        _run("build_dashboard.py", self.work)

        self.assertFalse(os.path.exists(self.dashboard_path))

    def test_Build_WithAMalformedPayload_EmbedsItUnvalidatedAndStillSucceeds(self):
        # Documents a real gap rather than the behaviour we would want. The payload
        # is read with f.read() and never json.loads()'d, so a corrupt warehouse file
        # is injected verbatim and the dashboard renders broken with a zero exit.
        # Naming this as a "fails loudly" test would have asserted a fiction.
        # Fixing it means parsing before injecting, which is a change to
        # build_dashboard.py, not to its tests.
        with open(self.payload_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        result = _run("build_dashboard.py", self.work)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(os.path.exists(self.dashboard_path))
        self.assertIn("{not valid json", self._read(self.dashboard_path))


if __name__ == "__main__":
    unittest.main()
