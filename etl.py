"""
ETL: extracts all 18 simulated sources, conforms them (date formats, region
codes, casing), joins everything onto the order-line grain, and writes:

  warehouse/flat_sales.csv        the full flattened wide table (43 cols)
  warehouse/dashboard_data.json   trimmed rows + aggregates for the dashboard

Run:  python etl.py   (after generate_sources.py)
"""
import csv
import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "sources")
WH = os.path.join(ROOT, "warehouse")
os.makedirs(WH, exist_ok=True)

lineage = []


def track(file, system, fmt, rows, role):
    lineage.append({"file": file, "system": system, "format": fmt,
                    "rows": rows, "role": role})


def read_csv(fname):
    with open(os.path.join(SRC, fname), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_json(fname):
    with open(os.path.join(SRC, fname), encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(fname):
    with open(os.path.join(SRC, fname), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- conformance
REGION_NAMES = {"NA": "North America", "EMEA": "EMEA", "APAC": "APAC", "LATAM": "LATAM"}
_region_fixes = 0


def conform_region(raw):
    global _region_fixes
    clean = raw.strip().upper()
    if clean != raw:
        _region_fixes += 1
    return REGION_NAMES[clean]


def parse_date(raw, fmt):
    """Each source exports dates its own way; conform to ISO."""
    return datetime.strptime(raw.strip(), fmt).date().isoformat()


# ============================================================ EXTRACT (18)
# 1. CRM customers (CSV, m/d/Y dates, messy region codes)
customers = {}
for r in read_csv("crm_customers.csv"):
    customers[r["customer_id"]] = {
        "name": r["full_name"], "segment": r["segment"],
        "region": conform_region(r["region"]),
        "signup": parse_date(r["signup_date"], "%m/%d/%Y")}
track("crm_customers.csv", "CRM", "CSV", len(customers), "customer dim")

# 2. ERP orders + line items (SQLite)
con = sqlite3.connect(os.path.join(SRC, "erp_sales.db"))
con.row_factory = sqlite3.Row
orders = {r["order_id"]: dict(r) for r in con.execute("SELECT * FROM orders")}
items = [dict(r) for r in con.execute("SELECT * FROM order_items")]
con.close()
track("erp_sales.db", "ERP", "SQLite", f"{len(orders)}+{len(items)}",
      "fact grain: order lines")

# 3. Product catalog (JSON, from the PIM)
products = {p["product_id"]: p for p in read_json("product_catalog.json")}
track("product_catalog.json", "PIM", "JSON", len(products), "product dim")

# 4. Inventory snapshot (CSV, WMS)
stock = {}
inv = read_csv("inventory_snapshot.csv")
for r in inv:
    stock[r["product_id"]] = stock.get(r["product_id"], 0) + int(r["on_hand"])
track("inventory_snapshot.csv", "WMS", "CSV", len(inv), "stock on hand")

# 5. Web analytics (JSONL) -> monthly sessions/conversions
web = read_jsonl("web_analytics.jsonl")
sessions_m = {}
for r in web:
    m = r["date"][:7]
    agg = sessions_m.setdefault(m, {"sessions": 0, "conversions": 0})
    agg["sessions"] += r["sessions"]
    agg["conversions"] += r["conversions"]
track("web_analytics.jsonl", "Web analytics", "JSONL", len(web), "traffic agg")

# 6. Marketing campaigns (CSV)
campaigns = {c["campaign_id"]: c for c in read_csv("marketing_campaigns.csv")}
track("marketing_campaigns.csv", "Marketing", "CSV", len(campaigns), "campaign dim")

# 7. Ad spend daily (CSV) -> monthly spend by campaign channel
ads = read_csv("ad_spend_daily.csv")
spend_m = {}
for r in ads:
    ch = campaigns[r["campaign_id"]]["channel"]
    key = (r["date"][:7], ch)
    spend_m[key] = spend_m.get(key, 0) + float(r["spend_usd"])
track("ad_spend_daily.csv", "Ad platforms", "CSV", len(ads), "spend agg")

# 8. Email stats (JSON)
email = read_json("email_stats.json")
email_m = {}
for r in email:
    agg = email_m.setdefault(r["month"], {"sends": 0, "clicks": 0})
    agg["sends"] += r["sends"]
    agg["clicks"] += r["clicks"]
track("email_stats.json", "Email platform", "JSON", len(email), "email agg")

# 9. Support tickets (CSV, DD-Mon-YYYY dates)
tickets = read_csv("support_tickets.csv")
tickets_per_order = {}
for r in tickets:
    parse_date(r["created_date"], "%d-%b-%Y")  # validate/conform
    if r["order_id"]:
        tickets_per_order[r["order_id"]] = tickets_per_order.get(r["order_id"], 0) + 1
track("support_tickets.csv", "Helpdesk", "CSV", len(tickets), "tickets per order")

# 10. NPS surveys (CSV) -> latest score per customer
nps_rows = read_csv("nps_surveys.csv")
nps_latest = {}
for r in sorted(nps_rows, key=lambda x: x["survey_date"]):
    nps_latest[r["customer_id"]] = int(r["score"])
track("nps_surveys.csv", "Survey tool", "CSV", len(nps_rows), "NPS per customer")

# 11. Shipping tracking (CSV)
ship = {}
ship_rows = read_csv("shipping_tracking.csv")
for r in ship_rows:
    ship[r["order_id"]] = r
track("shipping_tracking.csv", "Carrier feeds", "CSV", len(ship_rows), "delivery perf")

# 12. Returns / RMA (CSV)
returns = {r["line_id"]: r for r in read_csv("returns_rma.csv")}
track("returns_rma.csv", "Returns portal", "CSV", len(returns), "returned lines")

# 13. Payment gateway (JSONL, lowercase currencies) -> captured txn per order
pay = {}
pay_rows = read_jsonl("payment_gateway.jsonl")
for r in pay_rows:
    r["currency"] = r["currency"].upper()  # conform
    if r["status"] == "captured":
        pay[r["order_id"]] = r
track("payment_gateway.jsonl", "Payments", "JSONL", len(pay_rows), "payment method")

# 14. HR sales reps (CSV)
reps = {r["rep_id"]: r for r in read_csv("hr_sales_reps.csv")}
track("hr_sales_reps.csv", "HRIS", "CSV", len(reps), "rep dim")

# 15. Store locations (JSON)
stores = {s["store_id"]: s for s in read_json("store_locations.json")}
track("store_locations.json", "Store master", "JSON", len(stores), "store dim")

# 16. FX rates (CSV)
fx = {(r["month"], r["currency"]): float(r["usd_rate"]) for r in read_csv("fx_rates.csv")}
track("fx_rates.csv", "Treasury", "CSV", len(fx), "currency conversion")

# 17. Finance targets (CSV)
targets = [{"m": r["month"], "rg": REGION_NAMES[r["region"]],
            "t": int(r["revenue_target_usd"])} for r in read_csv("finance_targets.csv")]
track("finance_targets.csv", "Finance plan", "CSV", len(targets), "revenue targets")

# 18. Supplier price list (XML) -> unit cost per product
costs = {}
tree = ET.parse(os.path.join(SRC, "supplier_pricelist.xml"))
for el in tree.getroot():
    costs[el.get("id")] = float(el.get("unit_cost_usd"))
track("supplier_pricelist.xml", "Procurement", "XML", len(costs), "unit costs")

# ============================================================ TRANSFORM: flatten
flat = []
skipped_cancelled = 0
for it in items:
    o = orders[it["order_id"]]
    if o["status"] == "cancelled":
        skipped_cancelled += 1
        continue
    cust = customers[o["customer_id"]]
    prod = products[it["product_id"]]
    month = o["order_date"][:7]
    rate = fx[(month, o["currency"])]
    qty = int(it["qty"])
    rev_local = qty * it["unit_price"] * (1 - it["discount_pct"])
    rev_usd = rev_local * rate
    cost_usd = qty * costs[it["product_id"]]
    s = ship.get(it["order_id"])
    ret = returns.get(it["line_id"])
    p = pay.get(it["order_id"], {})
    rep = reps.get(o["rep_id"]) if o["rep_id"] else None
    store = stores.get(o["store_id"]) if o["store_id"] else None
    late = bool(s and int(s["actual_days"]) > int(s["promised_days"]))
    flat.append({
        "line_id": it["line_id"], "order_id": it["order_id"],
        "order_date": o["order_date"], "month": month,
        "customer_id": o["customer_id"], "customer_name": cust["name"],
        "segment": cust["segment"], "region": cust["region"],
        "channel": o["channel"],
        "store_id": o["store_id"] or "", "store_name": store["name"] if store else "Digital",
        "rep_id": o["rep_id"] or "", "rep_name": rep["name"] if rep else "House",
        "rep_team": rep["team"] if rep else "",
        "campaign_id": o["campaign_id"] or "",
        "campaign_name": campaigns[o["campaign_id"]]["name"] if o["campaign_id"] else "",
        "campaign_channel": campaigns[o["campaign_id"]]["channel"] if o["campaign_id"] else "",
        "product_id": it["product_id"], "product_name": prod["name"],
        "category": prod["category"], "subcategory": prod["subcategory"],
        "brand": prod["brand"], "qty": qty,
        "unit_price": it["unit_price"], "discount_pct": it["discount_pct"],
        "currency": o["currency"], "fx_usd_rate": rate,
        "revenue_local": round(rev_local, 2), "revenue_usd": round(rev_usd, 2),
        "unit_cost_usd": costs[it["product_id"]], "cost_usd": round(cost_usd, 2),
        "margin_usd": round(rev_usd - cost_usd, 2),
        "carrier": s["carrier"] if s else "", "promised_days": s["promised_days"] if s else "",
        "actual_days": s["actual_days"] if s else "", "late_delivery": late,
        "returned": bool(ret), "return_reason": ret["reason"] if ret else "",
        "payment_method": p.get("method", "In-store"),
        "tickets_on_order": tickets_per_order.get(it["order_id"], 0),
        "customer_nps": nps_latest.get(o["customer_id"], ""),
        "stock_on_hand": stock.get(it["product_id"], 0),
        "order_status": o["status"],
    })

# ============================================================ LOAD
fields = list(flat[0].keys())
with open(os.path.join(WH, "flat_sales.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(flat)

# Compact rows for the dashboard (array-of-arrays keeps the embed small)
cols = ["d", "rg", "ch", "sg", "ca", "br", "pr", "st", "cp", "q",
        "rv", "mg", "rt", "lt", "pm", "np", "tk", "o", "sh", "rr"]
rows = [[r["order_date"], r["region"], r["channel"], r["segment"], r["category"],
         r["brand"], r["product_name"], r["store_name"],
         r["campaign_name"] or None, r["qty"], round(r["revenue_usd"], 2),
         round(r["margin_usd"], 2), 1 if r["returned"] else 0,
         1 if r["late_delivery"] else 0, r["payment_method"],
         r["customer_nps"] if r["customer_nps"] != "" else None,
         r["tickets_on_order"], int(r["order_id"][2:]),
         1 if r["carrier"] else 0, r["return_reason"] or None] for r in flat]

dashboard = {
    "meta": {"company": "Cobalt Outfitters", "grain": "order line",
             "span": [flat[0]["order_date"][:10], max(r["order_date"] for r in flat)],
             "sources": len(lineage), "orders": len({r["order_id"] for r in flat})},
    "cols": cols,
    "rows": rows,
    "targets": targets,
    "spend": [{"m": m, "ch": ch, "s": round(v)} for (m, ch), v in sorted(spend_m.items())],
    "sessions": [{"m": m, "s": v["sessions"], "c": v["conversions"]}
                 for m, v in sorted(sessions_m.items())],
    "email": [{"m": m, "sends": v["sends"], "clicks": v["clicks"]}
              for m, v in sorted(email_m.items())],
    "lineage": lineage,
}
with open(os.path.join(WH, "dashboard_data.json"), "w", encoding="utf-8") as f:
    json.dump(dashboard, f, separators=(",", ":"))

total_rev = sum(r["revenue_usd"] for r in flat)
total_margin = sum(r["margin_usd"] for r in flat)
print(f"Extracted 18 sources -> conformed -> flattened")
print(f"  region codes normalized : {_region_fixes} messy values fixed")
print(f"  cancelled orders dropped: {skipped_cancelled} lines")
print(f"  flat table              : {len(flat)} rows x {len(fields)} cols -> warehouse/flat_sales.csv")
print(f"  dashboard payload       : warehouse/dashboard_data.json "
      f"({os.path.getsize(os.path.join(WH, 'dashboard_data.json'))//1024} KB)")
print(f"  total revenue (USD)     : {total_rev:,.0f}")
print(f"  blended margin          : {100*total_margin/total_rev:.1f}%")
print(f"  return rate (lines)     : {100*sum(r['returned'] for r in flat)/len(flat):.1f}%")
