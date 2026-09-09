# Testing — what is covered, and what writing the tests found

_[← Back to the main README](../README.md)_

124 tests over the whole pipeline. This page is the map, plus a record of the
defects the tests surfaced, how each was found, and what would stop the next one.

---

## Running the suite

The suite is `unittest`, not pytest — there is no `pytest.ini`, no
`requirements.txt`, and pytest need not be installed.

```bash
python generate_sources.py         # prerequisite: test_gates.py reads sources/
python generate_unknown_source.py  # prerequisite: the variant fixtures
python -m unittest discover -s tests
```

**The first two lines are not optional on a fresh clone.** `sources/` and
`warehouse/` are gitignored, and `tests/test_gates.py` raises `SystemExit` with
an explanatory message if `sources/crm_customers.csv` is missing. A clean clone
that skips them reports 83 tests and an import error rather than 124 and `OK`.

Everything added later builds its own throwaway directory under `tempfile`, so
only `test_gates.py` carries that prerequisite.

Expect ~45 seconds. Most of it is the pipeline running end to end inside the
tests, not the assertions.

---

## What each file covers

| File | Level | Cases | Covers |
| --- | --- | --- | --- |
| `test_gates.py` | unit + subprocess | 42 | mapping gates, redaction, contracts, approval signing, the injection canary |
| `test_etl_primitives.py` | unit | 23 | `conform_region`, `parse_date`, the three source readers |
| `test_etl.py` | functional + integration | 18 | grain, reconciliation, conformance, dashboard agreement, determinism |
| `test_build_dashboard.py` | integration | 16 | the `</` script-injection escape, both outputs, payload validation |
| `test_generate_sources.py` | unit + integration | 13 | `months_between`, the 18-file source set, cross-process determinism |
| `test_build_mapping_page.py` | integration | 12 | the `html.escape` sink on model-supplied and untrusted external content |

`etl.py`, `build_dashboard.py`, `build_mapping_page.py` and `generate_sources.py`
are scripts, not modules — most of their work happens in top-level statements
that run on import. They are therefore exercised the way they are actually used:
generated into a throwaway directory and run as a subprocess. `test_gates.py`
already shelled out this way, so this is the existing pattern rather than a new
one.

Where a true unit test is wanted, the module is loaded from that throwaway
directory with `importlib`, so the import's side effects land there and are
discarded. Deliberately **not** `exec()` over a truncated source: faster, but the
kind of cleverness that outlives whoever understood it, and a needless
static-analysis finding.

---

## Defects found while writing the tests

### 1. Generation was not deterministic, despite `random.seed(42)`

**Severity:** high — every pinned figure in the project depended on a claim that
was not true.

**How it was found.** Writing a cross-process determinism test: generate into two
separate temp directories in two separate subprocesses, then `filecmp.cmpfiles`
the results. `nps_surveys.csv` and `support_tickets.csv` came back mismatched.

An in-process test would have passed. So would running `generate_sources.py`
twice and diffing by eye, if both runs happened to hash alike.

**Root cause.**

```python
returned_orders  = list({r["order_id"] for r in returns})     # order varies
cust_with_orders = list({o["customer_id"] for o in orders})   # order varies
```

Python randomises string hashing per process, so set iteration order differs
between runs. Both lists feed `random.choice`, so an unstable order consumed the
seeded random stream in a different sequence — every row of `nps_surveys.csv`
differed between runs.

Confirmed by re-running both processes under `PYTHONHASHSEED=0`, which made the
output identical.

**Why it mattered more than it looks.** `7,670 rows`, `$3,056,034.74`, and every
other figure asserted in this suite rest on generation reproducing. It held only
because the affected fields feed `customer_nps` and `tickets_on_order`, which
change neither row counts nor revenue. A later change touching an ordered field
would have made the pinned numbers flap for no visible reason.

**Fix.** `sorted()` in place of `list()` in both spots, with a comment saying why.

**Prevention.**
- Never `list(<set>)` where the result feeds randomness, output order, or
  anything asserted. Use `sorted()`.
- Test determinism **across processes**, not within one. Same-process repetition
  shares a hash seed and proves nothing about reproducibility.
- `PYTHONHASHSEED=0` is the quickest way to confirm a hash-order suspicion.

### 2. `build_dashboard.py` embedded its payload without parsing it

**Severity:** medium — silent wrong output, which is worse than a crash.

**How it was found.** Writing a negative test for a corrupt
`warehouse/dashboard_data.json`. The test to write was
`..._FailsRatherThanEmbeddingBrokenJson`, but the run exited `0` and wrote a
page. The name asserted a fiction, so the behaviour — not the name — was wrong.

**Root cause.** The payload was read with `f.read()` and injected as text. It was
never `json.loads()`d, so a corrupt warehouse file was passed straight into the
`<script>` block. The build succeeded, the dashboard rendered broken, and nothing
said so.

A hint was sitting in plain sight: `import json` at the top of the file was
**unused**.

**Fix.** `json.loads(payload)` before injection — which also gives that import
its only use.

**Prevention.**
- Validate at trust boundaries. Reading a file is one; "we wrote it ourselves
  upstream" is not a guarantee that it is intact.
- An unused import in a small script is a smell: something the author intended
  to do and did not.
- When a negative test's honest name contradicts the behaviour, the code is
  usually wrong. Do not rename the test to match the bug.

### 3. Documentation drift: the flat table is 45 columns, not 43

**How it was found.** Pinning the column count in an assertion forced a real
number to be looked up, which disagreed with three places in the docs
(`README.md`, `docs/ARCHITECTURE.md`, and `etl.py`'s own docstring).

**Fix.** Corrected all three.

**Prevention.** Assert the number in a test. `test_FlatTable_AfterAFullRun_
HasTheExactSeededRowAndColumnCount` now fails if the shape moves, which is the
prompt to update the prose.

### 4. Process defect: tests pushed without the fixes they assert

**How it was found.** Verifying `main` after the push, rather than assuming.

**Root cause.** The mutation sweep ended each case with `git checkout -- <file>`
to undo the mutation. The source fixes were still uncommitted, so that reverted
them too. The commit landed the tests and not the code, and `main` had four
failing tests for about a minute.

**Fix.** Restored in the follow-up commit.

**Prevention.** Commit the fix **before** running a mutation sweep over the same
file. A harness that cleans up with `git checkout` cannot tell a mutation from
work in progress. Verify the remote after pushing, not the working tree.

---

## Mutation testing

Assertions are only worth what they catch, so each new file was checked by
breaking the code it covers and confirming the right tests failed.

| Mutation | Failures |
| --- | --- |
| `sorted()` reverted to `list()` in `generate_sources.py` | 1 |
| `json.loads(payload)` removed from `build_dashboard.py` | 4 |
| `E = html.escape` replaced with `E = str` | 8 |
| `</` escape removed from `build_dashboard.py` | 3 |
| cancelled-order filter disabled in `etl.py` | 6 |
| `conform_region` stops stripping whitespace | 14 + 2 errors |
| `parse_date` stops stripping | 1 error |
| ownership of `Touch()` reordered before `SetTitle()` *(ToDoApp)* | 2 |

One caveat worth carrying forward: a mutation applied with `sed` **silently did
not match** an escaped-backslash line, and the suite reported `OK`. A mutation
that never applied looks exactly like a test suite that passes. Always echo the
mutated line back before trusting the result.

---

## The two injection sinks

Both published pages embed untrusted content, and both have a single line
standing between the data and the document.

**`build_dashboard.py`** — `payload.replace("</", "<\\/")`. Product and campaign
names reach `dashboard_data.json` straight from the sources, so a `</script>` in
that data would close the block it is embedded in and drop the remainder into the
document as markup. The escape is reversible: `<\/` is valid JSON for `</`, so
the browser still sees the original string.

**`build_mapping_page.py`** — `E = html.escape`. Column names and transforms are
whatever a model proposed, and the sample block is raw external text carrying a
deliberate prompt-injection canary. If that escaping lapses, a model proposal
becomes stored XSS on the page whose entire purpose is demonstrating that
untrusted input is handled safely.

Both are covered with script tags, `img`/`onerror`, and attribute-breakout
payloads, and both are mutation-verified above.

---

## Still uncovered

- `fetch_external_sources.py`, `record_run.py`, `mapper/live_run.py`,
  `mapper/benchmark.py`, `mapper/run_external.py`
- `generate_unknown_source.py` beyond the byte-identical regeneration check in
  `test_gates.py`
