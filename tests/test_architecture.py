"""
ARCHITECTURE.md promises a shape that prose cannot enforce: every import is
stdlib or a sibling module, root scripts couple through files on disk rather
than through imports, and the replayed CI path neither touches the network
nor reads the wall clock or the environment. Each promise is asserted here
over the committed source (ast only, nothing executed), so a change that
bends the shape goes red naming the offending module and line -- instead of
surviving as documentation fiction.

Run:  python -m unittest discover -s tests -v
      (pure static analysis -- no generated directories required, so this
      file also passes on a clean clone)
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_repo():
    """Every committed .py, keyed by the bare name it is imported under."""
    trees, paths = {}, {}
    for sub in ("", "mapper", "tests"):
        folder = os.path.join(ROOT, sub) if sub else ROOT
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".py"):
                continue
            name = fn[:-3]
            if name in trees:
                raise AssertionError(
                    f"two modules share the name {name!r} -- the flat "
                    "sys.path layout cannot serve both")
            path = os.path.join(folder, fn)
            with open(path, encoding="utf-8") as f:
                trees[name] = ast.parse(f.read(), filename=path)
            paths[name] = os.path.relpath(path, ROOT).replace(os.sep, "/")
    return trees, paths


def imported_names(tree):
    """Yield (top-level module name, line) for every import statement.
    Relative imports yield '.' -- the flat, path-based layout has none."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield ".", node.lineno
            else:
                yield node.module.split(".")[0], node.lineno


def unresolved_imports(tree, siblings):
    """Imports that are neither stdlib nor a sibling .py in this repo."""
    return [(name, line) for name, line in imported_names(tree)
            if name == "." or
            (name not in sys.stdlib_module_names and name not in siblings)]


def local_edges(tree, siblings):
    """The sibling modules this tree imports."""
    return {name for name, _ in imported_names(tree) if name in siblings}


def find_cycle(graph):
    """One import cycle as a list of names (first == last), or None."""
    state, path = {}, []

    def visit(node):
        state[node] = "active"
        path.append(node)
        for nxt in sorted(graph.get(node, ())):
            if state.get(nxt) == "active":
                return path[path.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        path.pop()
        state[node] = "done"
        return None

    for node in sorted(graph):
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def closure(graph, roots):
    """roots plus everything transitively imported from them."""
    seen, queue = set(roots), sorted(roots)
    while queue:
        for nxt in sorted(graph.get(queue.pop(), ())):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


# Stdlib modules whose only job is talking to a network. http also covers
# http.client; urllib also covers urllib.request.
NETWORK_MODULES = {"urllib", "http", "socket", "socketserver", "ssl",
                   "ftplib", "poplib", "imaplib", "smtplib", "telnetlib",
                   "xmlrpc"}


def network_imports(tree):
    """Imports of network-capable stdlib modules."""
    return [(name, line) for name, line in imported_names(tree)
            if name in NETWORK_MODULES]


# Reading the clock through any of datetime/date/time defeats the pinned
# simulation window. datetime.strptime and date(...) construction stay legal.
CLOCK_ROOTS = {"datetime", "date", "time"}
CLOCK_ATTRS = {"now", "utcnow", "today", "time", "time_ns", "monotonic",
               "monotonic_ns", "perf_counter", "perf_counter_ns"}


def clock_calls(tree):
    """Call sites like datetime.now(), date.today() or time.time()."""
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in CLOCK_ATTRS):
            continue
        base = node.func.value
        while isinstance(base, ast.Attribute):
            base = base.value
        if isinstance(base, ast.Name) and base.id in CLOCK_ROOTS:
            hits.append((ast.unparse(node.func), node.lineno))
    return hits


def environ_reads(tree):
    """Touches of os.environ / os.getenv, however they are then used."""
    return [(f"os.{node.attr}", node.lineno) for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"environ", "environb", "getenv", "putenv"}
            and isinstance(node.value, ast.Name) and node.value.id == "os"]


MODULES, PATHS = _parse_repo()
GRAPH = {name: local_edges(MODULES[name], set(MODULES)) for name in MODULES}

# Root-level .py files are independent entry points: stages hand off through
# files on disk, and anything shared lives in a mapper/ library.
ROOT_SCRIPTS = frozenset(n for n in MODULES if "/" not in PATHS[n])

# Shared leaves under mapper/: the proposing (live) side and the validating
# (CI) side both import these, so they may import nothing local themselves.
MAPPER_LIBRARIES = frozenset(
    {"contract_lib", "mapping_lib", "public_po_lib", "redact"})

# What CI executes for the replayed deterministic build -- the run: steps of
# build-and-deploy.yml, in order. Deliberately outside the set:
# fetch_external_sources (the continue-on-error reachability probe, the one
# root script allowed to import the network) and the model-calling side
# (propose_mapping, live_run, benchmark, run_external), which CI replays
# rather than runs.
REPLAY_ROOTS = frozenset({"generate_sources", "generate_unknown_source",
                          "validate_mapping", "etl", "build_dashboard",
                          "build_mapping_page"})

# approve.py rides along: validate_mapping --require-approval imports it to
# verify the recorded signature. Its clock and environment reads sit on the
# human --approve signing path, which the replay never takes -- so it is
# exempt from those two rules below, but not from the network rule.
SIGNATURE_CHECKER = frozenset({"approve"})


class TestImportInventory(unittest.TestCase):
    def test_WholeRepo_EveryImport_IsStdlibOrASiblingModule(self):
        problems = [f"{PATHS[name]}:{line} imports {imp!r}"
                    for name in sorted(MODULES)
                    for imp, line in unresolved_imports(MODULES[name],
                                                        set(MODULES))]
        self.assertEqual(problems, [])

    def test_Resolver_WithAThirdPartyImport_NamesTheModule(self):
        bad = unresolved_imports(ast.parse("import pandas"), set(MODULES))
        self.assertEqual(bad, [("pandas", 1)])

    def test_Resolver_WithARelativeImport_FlagsTheFlatLayoutBreak(self):
        bad = unresolved_imports(ast.parse("from . import mapping_lib"),
                                 set(MODULES))
        self.assertEqual(bad, [(".", 1)])


class TestStageAndLibraryBoundaries(unittest.TestCase):
    def test_RootEntryPoints_FromAnywhereInTheRepo_AreNeverImported(self):
        importers = {name: GRAPH[name] & ROOT_SCRIPTS
                     for name in sorted(MODULES) if GRAPH[name] & ROOT_SCRIPTS}
        self.assertEqual(importers, {})

    def test_MapperLibraries_AsSharedLeaves_ImportNothingLocal(self):
        importers = {name: GRAPH[name]
                     for name in sorted(MAPPER_LIBRARIES) if GRAPH[name]}
        self.assertEqual(importers, {})

    def test_LocalImportGraph_AcrossTheWholeRepo_HasNoCycles(self):
        cycle = find_cycle(GRAPH)
        self.assertIsNone(
            cycle, f"import cycle: {' -> '.join(cycle or [])}")

    def test_ProductionModules_WhereverTheyLive_ImportNothingFromTests(self):
        test_modules = {n for n in MODULES if PATHS[n].startswith("tests/")}
        importers = {name: GRAPH[name] & test_modules
                     for name in sorted(MODULES)
                     if name not in test_modules and GRAPH[name] & test_modules}
        self.assertEqual(importers, {})

    def test_CycleFinder_WithATwoModuleLoop_NamesBothMembers(self):
        cycle = find_cycle({"a": {"b"}, "b": {"a"}, "c": set()})
        self.assertIsNotNone(cycle)
        self.assertEqual(set(cycle), {"a", "b"})


class TestReplayPathDeterminism(unittest.TestCase):
    def test_ReplayClosure_FromItsSixRoots_IsRootsLibrariesAndChecker(self):
        self.assertEqual(closure(GRAPH, REPLAY_ROOTS),
                         REPLAY_ROOTS | MAPPER_LIBRARIES | SIGNATURE_CHECKER)

    def test_ReplayClosure_IncludingTransitiveImports_StaysOffTheNetwork(self):
        problems = [f"{PATHS[name]}:{line} imports {imp!r}"
                    for name in sorted(closure(GRAPH, REPLAY_ROOTS))
                    for imp, line in network_imports(MODULES[name])]
        self.assertEqual(problems, [])

    def test_ReplayClosure_ExceptTheChecker_NeverReadsTheClock(self):
        # approve.py's datetime.now stamps new signatures -- the --approve
        # path, which the replay never takes (see SIGNATURE_CHECKER above).
        scope = closure(GRAPH, REPLAY_ROOTS) - SIGNATURE_CHECKER
        problems = [f"{PATHS[name]}:{line} calls {call}"
                    for name in sorted(scope)
                    for call, line in clock_calls(MODULES[name])]
        self.assertEqual(problems, [])

    def test_ReplayClosure_ExceptRedactorAndChecker_NeverReadsTheEnv(self):
        # Two deliberate exceptions: redact.py's HMAC key is env-tunable
        # (MAPPER_REDACTION_KEY) with a fixed local default, so with nothing
        # set -- which is how CI runs -- it stays deterministic; approve.py
        # reads USER/USERNAME only to default --by on the signing path.
        scope = closure(GRAPH, REPLAY_ROOTS) - SIGNATURE_CHECKER - {"redact"}
        problems = [f"{PATHS[name]}:{line} touches {what}"
                    for name in sorted(scope)
                    for what, line in environ_reads(MODULES[name])]
        self.assertEqual(problems, [])

    def test_NetworkScanner_WithAUrllibRequestImport_NamesTheLine(self):
        hits = network_imports(ast.parse("import urllib.request"))
        self.assertEqual(hits, [("urllib", 1)])

    def test_ClockScanner_WithADatetimeNowCall_NamesTheCallSite(self):
        src = "from datetime import datetime\nstamp = datetime.now()\n"
        self.assertEqual(clock_calls(ast.parse(src)), [("datetime.now", 2)])

    def test_ClockScanner_WithStrptimeParsing_StaysQuiet(self):
        src = ("from datetime import datetime\n"
               "d = datetime.strptime('14.03.2025', '%d.%m.%Y')\n")
        self.assertEqual(clock_calls(ast.parse(src)), [])

    def test_EnvironScanner_WithAGetenvCall_NamesTheCallSite(self):
        src = "import os\nkey = os.getenv('MAPPER_API_KEY')\n"
        self.assertEqual(environ_reads(ast.parse(src)), [("os.getenv", 2)])


if __name__ == "__main__":
    unittest.main()
