# Real external sources

Everything else in this repo is simulated on purpose: seeded, reproducible,
and honest about being fabricated. That invites one fair objection — *the same
project wrote both the exam and the student.*

These files answer it. They are real purchase-order exports published by real
governments, fetched from their own endpoints, in whatever format each
publisher natively serves. Nothing about them was authored here.

## The files

`python fetch_external_sources.py` downloads all five into `incoming/external/`
(~500 KB). They are **not committed** — the repo records where the data lives
rather than redistributing it, so anyone can fetch the same bytes and confirm
they are genuine.

| Format | Publisher | Endpoint | What it is |
|---|---|---|---|
| CSV | City of Providence, RI | `data.providenceri.gov/resource/425y-pm5m.csv` | city + school purchase order lines |
| JSON | State of Vermont | `data.vermont.gov/resource/8ewu-igdm.json` | state purchase orders with vendor detail |
| XML | City of Edmonton, Canada | `data.edmonton.ca/resource/y9rm-5xha.xml` | purchase orders over $10,000 |
| TSV | Los Angeles City Controller | `controllerdata.lacity.org/resource/5ru3-n8sy.tsv` | invoices and purchase orders |
| TXT (pipe) | U.S. SEC | `sec.gov/Archives/edgar/full-index/2025/QTR1/master.idx` | EDGAR filing index — deliberately *not* order data |

The first four are Socrata open-data portals, which serve the same dataset in
several formats; the format of each file above is the publisher's own, not a
conversion. The SEC index is a US Government work in the public domain. Each
portal's terms are its own — treat the data as reference material, not as part
of this project's MIT license.

**No JSONL.** No public portal surveyed (data.gov's catalogue, the Socrata
network, the Open Contracting registry) publishes newline-delimited JSON, so
rather than convert a file and call it external, JSONL is left to the
simulated variant classes, which cover it honestly.

## The second contract

Real files cannot be gated the way the warranty file is: Providence's vendors
do not exist in Cobalt's CRM, so the join-coverage gates would (correctly)
reject them. `mapper/public_po_lib.py` therefore defines a **second contract**
whose ground truth is external fact rather than a local master:

| Gate | What it enforces |
|---|---|
| S | format identified (delimited / json / xml), required targets each mapped exactly once, transforms from the whitelist |
| G0–G1 | the file actually parses in the proposed container; proposed fields exist |
| G2 | every record maps without a transform error |
| G3 | `po_id` present on every record |
| G4 | dates parse to ISO and land in 1990–2035 |
| G5 | amounts numeric, non-negative, plausible |
| G6 | **`region` is a real US state or territory code** — an independent fact, not something this repo defines |
| G7 | **one `po_id` carries one consistent vendor** — cross-row consistency a wrong mapping breaks |
| G8 | `vendor_name` reads as a name, not an id |

G6 and G7 are the interesting ones. A model that maps the wrong column to
`region` produces values that are not real states; a model that grabs the
wrong column for `vendor_name` produces a purchase order whose vendor changes
between its own line items. Neither needs a warehouse to catch.

The model must also identify the **container** here — delimited, JSON or XML —
not just the columns.

## Results

`python mapper/run_external.py --publish` scores each file by whether the
*outcome* was right, not whether it was accepted:

| Format | Publisher | Outcome | Correct? |
|---|---|---|---|
| CSV | Providence, RI | **accepted** — 400 rows conformed, attempt 1 | ✅ |
| JSON | State of Vermont | **accepted** — 400 rows conformed, attempt 1 | ✅ |
| TSV | LA City Controller | **refused** — no line amount, no vendor state | ✅ |
| XML | Edmonton, Canada | **refused** — dollar buckets, no PO id, no US state | ✅ |
| TXT | SEC EDGAR | **refused** — not order data at all | ✅ |

**5/5 correct outcomes.** Providence cleared every gate with 28 distinct real
state codes and 347 purchase orders carrying zero vendor conflicts; Vermont
cleared it with 26 states across 192 orders.

The three refusals matter more than the two acceptances. Each of those files
genuinely lacks something the contract requires, and in every case the model
left the field unmapped and said so rather than inventing a mapping to satisfy
the instruction. The system declining real data it cannot honestly conform is
the same property the simulated `unmappable` class tests — here it is
demonstrated on files nobody in this project wrote.
