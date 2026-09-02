"""
Downloads REAL purchase-order exports from public government data portals.

Nothing here is fabricated: each file is fetched from its publisher's own
endpoint, in whatever format that publisher natively serves. The repo does not
redistribute the data -- it records where the data lives, so anyone can fetch
the same bytes and verify the mapping runs against genuinely external files.

Run:  python fetch_external_sources.py
Output: incoming/external/ (5 files, ~500 KB)
"""
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "incoming", "external")
# SEC requires a descriptive agent with a contact address and rejects the
# parenthesised-URL form; the open-data portals accept anything.
UA = "BI-Simulator research bgard68@gmail.com"
ROWS = 400

# (filename, publisher, url, native format, what it is)
SOURCES = [
    ("providence_purchase_orders.csv", "City of Providence, RI",
     f"https://data.providenceri.gov/resource/425y-pm5m.csv?$limit={ROWS}",
     "CSV", "city + school department purchase order lines"),
    ("vermont_purchase_orders.json", "State of Vermont",
     f"https://data.vermont.gov/resource/8ewu-igdm.json?$limit={ROWS}",
     "JSON", "state purchase orders with vendor detail"),
    ("edmonton_purchase_orders.xml", "City of Edmonton, Canada",
     f"https://data.edmonton.ca/resource/y9rm-5xha.xml?$limit={ROWS}",
     "XML", "purchase orders over $10,000"),
    ("lacity_invoices.tsv", "Los Angeles City Controller",
     f"https://controllerdata.lacity.org/resource/5ru3-n8sy.tsv?$limit={ROWS}",
     "TSV", "invoices and purchase orders for city goods"),
    ("sec_edgar_filings.txt", "U.S. Securities and Exchange Commission",
     "https://www.sec.gov/Archives/edgar/full-index/2025/QTR1/master.idx",
     "pipe-delimited TXT", "EDGAR filing index (deliberately NOT order data)"),
]


def fetch(url, dest, trim_to=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if trim_to:                      # SEC ships the whole quarter; keep a slice
        lines = data.decode("utf-8", "replace").splitlines()
        data = "\n".join(lines[:11] + lines[11:11 + trim_to]).encode("utf-8")
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"fetching {len(SOURCES)} real external files -> incoming/external/\n")
    failures = 0
    for name, publisher, url, fmt, what in SOURCES:
        dest = os.path.join(OUT, name)
        try:
            n = fetch(url, dest, trim_to=ROWS if name.startswith("sec_") else None)
            print(f"  {name:36s} {fmt:19s} {n // 1024:4d} KB   {publisher}")
        except Exception as e:
            failures += 1
            print(f"  {name:36s} FAILED: {type(e).__name__}: {e}")
    print("\nSources are public open-data endpoints; see docs/EXTERNAL_SOURCES.md "
          "for publishers and terms.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
