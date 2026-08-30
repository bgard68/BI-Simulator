"""
Generates 18 simulated data sources for a fictional outdoor-gear retailer
("Cobalt Outfitters"), each in the format a real source system would export:
CSV, JSON, JSONL, SQLite, and XML -- with per-source date formats and the
kind of light messiness (mixed casing, padded whitespace) real exports have.

Run:  python generate_sources.py
Output: ./sources/  (18 files)
"""
import csv
import json
import math
import os
import random
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, timedelta

random.seed(42)

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "sources")
os.makedirs(SRC, exist_ok=True)

START = date(2025, 1, 1)
END = date(2026, 8, 30)
DAYS = (END - START).days + 1

REGIONS = ["NA", "EMEA", "APAC", "LATAM"]
REGION_WEIGHTS = [0.40, 0.30, 0.18, 0.12]
REGION_CURRENCY = {"NA": "USD", "EMEA": "EUR", "APAC": "AUD", "LATAM": "BRL"}
SEGMENTS = ["Consumer", "Outdoor Pro", "Corporate & Team", "Reseller"]
SEGMENT_WEIGHTS = [0.55, 0.20, 0.15, 0.10]
CHANNELS = ["Online", "Retail", "Wholesale", "Marketplace"]

SEASON = {1: 0.85, 2: 0.80, 3: 0.95, 4: 1.00, 5: 1.10, 6: 1.25,
          7: 1.30, 8: 1.15, 9: 1.00, 10: 1.00, 11: 1.50, 12: 1.45}


def months_between(a, b):
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


MONTHS = months_between(START, END)


def wchoice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]


# ---------------------------------------------------------------- products
BRANDS = ["Cobalt", "NorthCrag", "Peak & Pine", "TrailForge", "Aurora Gear"]
MODEL_WORDS = ["Ridgeline", "Basecamp", "Alpenglow", "Stormfront", "Cascade",
               "Sierra", "Halcyon", "Meridian", "Zephyr", "Torrent", "Granite",
               "Ember", "Solstice", "Vanguard", "Drift", "Summit", "Nomad",
               "Kestrel", "Onyx", "Juniper", "Tundra", "Fjord", "Mesa",
               "Cinder", "Atlas", "Vertex", "Pinnacle", "Rapid", "Sable", "Lark"]
SUBCATS = [
    ("Camping & Hiking", "Tents", 8, (180, 700), ["2P", "3P", "4P", "UL"]),
    ("Camping & Hiking", "Backpacks", 10, (90, 320), ["38L", "50L", "65L", "80L"]),
    ("Camping & Hiking", "Sleeping Bags", 8, (80, 400), ["0C", "-7C", "-18C"]),
    ("Camping & Hiking", "Stoves", 6, (40, 150), ["Micro", "Duo", "XL"]),
    ("Apparel", "Jackets", 10, (120, 450), ["Shell", "Down", "Hybrid"]),
    ("Apparel", "Base Layers", 8, (30, 90), ["Merino", "Synth"]),
    ("Apparel", "Pants", 7, (60, 160), ["Trek", "Softshell"]),
    ("Footwear", "Hiking Boots", 8, (110, 280), ["GTX", "Mid", "Low"]),
    ("Footwear", "Trail Runners", 7, (90, 180), ["X2", "Speed"]),
    ("Footwear", "Sandals", 5, (40, 90), ["Sport", "Camp"]),
    ("Climbing", "Harnesses", 5, (50, 130), ["Sport", "Alpine"]),
    ("Climbing", "Ropes", 5, (120, 300), ["9.5mm", "9.8mm", "10.2mm"]),
    ("Climbing", "Carabiners", 5, (15, 40), ["Screw", "Wire", "Auto"]),
    ("Water Sports", "Kayaks", 5, (400, 1200), ["Solo", "Tandem"]),
    ("Water Sports", "Paddles", 5, (60, 200), ["Carbon", "Alloy"]),
    ("Water Sports", "Dry Bags", 5, (20, 80), ["10L", "20L", "40L"]),
    ("Navigation & Electronics", "GPS Units", 4, (180, 600), ["Mini", "Pro"]),
    ("Navigation & Electronics", "Headlamps", 5, (25, 90), ["400lm", "900lm"]),
    ("Navigation & Electronics", "Watches", 4, (200, 800), ["Solar", "Ti"]),
]

products = []
used_names = set()
pid = 1000
for cat, sub, count, (lo, hi), suffixes in SUBCATS:
    for _ in range(count):
        while True:
            name = (f"{random.choice(BRANDS)} {random.choice(MODEL_WORDS)} "
                    f"{random.choice(suffixes)}")
            if name not in used_names:
                used_names.add(name)
                break
        brand = name.split(" ")[0] if not name.startswith("Peak") else "Peak & Pine"
        if name.startswith("Aurora"):
            brand = "Aurora Gear"
        launch = START - timedelta(days=random.randint(60, 1400))
        products.append({
            "product_id": f"P{pid}", "name": name, "category": cat,
            "subcategory": sub, "brand": brand,
            "list_price": round(random.uniform(lo, hi), 2),
            "launch_date": launch.isoformat(),
        })
        pid += 1

CAT_SEASON = {
    "Water Sports": {5: 1.8, 6: 2.2, 7: 2.2, 8: 1.8},
    "Camping & Hiking": {5: 1.4, 6: 1.6, 7: 1.6, 8: 1.4},
    "Apparel": {11: 1.6, 12: 1.8, 1: 1.6, 2: 1.4},
    "Navigation & Electronics": {11: 1.4, 12: 1.6},
}


def pick_product(month):
    weights = []
    for p in products:
        w = 1.0 * CAT_SEASON.get(p["category"], {}).get(month, 1.0)
        weights.append(w)
    return random.choices(products, weights=weights, k=1)[0]


# ---------------------------------------------------------------- customers
FIRST = ["Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Ines", "Hugo", "Sofia",
         "Mateo", "Freya", "Anders", "Yuki", "Kenji", "Priya", "Arjun", "Lena",
         "Marco", "Elsa", "Tomas", "Nadia", "Felix", "Clara", "Diego", "Aisha",
         "Owen", "Mia", "Lucas", "Emma", "Jonas", "Sara", "Kai", "Nora", "Leo",
         "Isla", "Ruben", "Tara", "Viktor", "Lucia", "Sam"]
LAST = ["Hartley", "Nguyen", "Okafor", "Silva", "Berg", "Tanaka", "Kowalski",
        "Marchetti", "Dubois", "Svensson", "Reyes", "Novak", "Fischer", "Ito",
        "Andersen", "Costa", "Moreau", "Weber", "Lindqvist", "Ortiz", "Haddad",
        "Petrov", "Keller", "Sato", "Jensen", "Romero", "Bauer", "Vargas",
        "Nilsson", "Fontaine", "Klein", "Barros", "Meyer", "Larsen", "Quinn",
        "Duarte", "Holm", "Ferreira", "Voss", "Egan"]
COMPANY_BITS = ["Trailways", "Peaks", "Outfitting", "Expeditions", "Basecamp",
                "Adventure Co", "Gear Collective", "Trek Supply"]

customers = []
for i in range(800):
    seg = wchoice(SEGMENTS, SEGMENT_WEIGHTS)
    region = wchoice(REGIONS, REGION_WEIGHTS)
    if seg in ("Corporate & Team", "Reseller"):
        name = f"{random.choice(LAST)} {random.choice(COMPANY_BITS)}"
        email = f"orders@{name.split(' ')[0].lower()}{i}.example.com"
    else:
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        email = f"{name.split(' ')[0].lower()}.{name.split(' ')[1].lower()}{i}@example.com"
    signup = START - timedelta(days=random.randint(0, 1100))
    # CRM export messiness: some regions lowercase / padded
    r = region
    roll = random.random()
    if roll < 0.08:
        r = region.lower()
    elif roll < 0.13:
        r = f" {region} "
    customers.append({
        "customer_id": f"C{20000 + i}", "full_name": name, "email": email,
        "segment": seg, "region": r,
        "signup_date": f"{signup.month}/{signup.day}/{signup.year}",  # m/d/Y
        "marketing_opt_in": random.random() < 0.62,
        "_region": region,  # internal only, not exported
    })

cust_by_seg = {s: [c for c in customers if c["segment"] == s] for s in SEGMENTS}

# ---------------------------------------------------------------- stores / reps
CITY_MAP = {
    "NA": [("Denver", "USA"), ("Seattle", "USA"), ("Portland", "USA"),
           ("Boulder", "USA"), ("Austin", "USA"), ("Toronto", "Canada"),
           ("Vancouver", "Canada"), ("Minneapolis", "USA"), ("Salt Lake City", "USA")],
    "EMEA": [("London", "UK"), ("Munich", "Germany"), ("Stockholm", "Sweden"),
             ("Amsterdam", "Netherlands"), ("Zurich", "Switzerland"),
             ("Chamonix", "France"), ("Barcelona", "Spain")],
    "APAC": [("Sydney", "Australia"), ("Melbourne", "Australia"),
             ("Auckland", "New Zealand"), ("Tokyo", "Japan"), ("Singapore", "Singapore")],
    "LATAM": [("Santiago", "Chile"), ("Sao Paulo", "Brazil"), ("Mexico City", "Mexico")],
}
stores = []
sid = 1
for region, cities in CITY_MAP.items():
    for city, country in cities:
        opened = START - timedelta(days=random.randint(200, 3000))
        stores.append({
            "store_id": f"S{sid:02d}", "name": f"Cobalt {city}", "city": city,
            "country": country, "region": region, "opened": opened.isoformat(),
            "sqft": random.randint(2200, 9500),
        })
        sid += 1
stores_by_region = {r: [s for s in stores if s["region"] == r] for r in REGIONS}

reps = []
rid = 1
for region in REGIONS:
    for _ in range(4):
        hire = START - timedelta(days=random.randint(100, 2500))
        reps.append({
            "rep_id": f"R{rid:02d}",
            "name": f"{random.choice(FIRST)} {random.choice(LAST)}",
            "team": f"{region} Sales", "region": region,
            "hire_date": hire.isoformat(),
            "annual_quota_usd": random.choice([600, 750, 900, 1100]) * 1000,
        })
        rid += 1
reps_by_region = {r: [x for x in reps if x["region"] == r] for r in REGIONS}

# ---------------------------------------------------------------- campaigns
campaigns = [
    ("CMP01", "Spring Trailhead 25", "Paid Search", "2025-03-01", "2025-04-20", 120),
    ("CMP02", "Gear Up Affiliate Push", "Affiliate", "2025-05-01", "2025-05-31", 45),
    ("CMP03", "Summit Days 25", "Social", "2025-06-05", "2025-07-15", 150),
    ("CMP04", "Back to Trail", "Email", "2025-08-10", "2025-09-20", 30),
    ("CMP05", "Monsoon Ready APAC", "Social", "2025-09-01", "2025-09-30", 40),
    ("CMP06", "Black Friday Blitz", "Paid Search", "2025-11-05", "2025-12-02", 260),
    ("CMP07", "Holiday Basecamp", "Social", "2025-12-01", "2025-12-24", 180),
    ("CMP08", "New Year New Peaks", "Email", "2026-01-02", "2026-01-31", 35),
    ("CMP09", "Alpine Preview", "Email", "2026-02-05", "2026-02-28", 30),
    ("CMP10", "Spring Trailhead 26", "Paid Search", "2026-03-01", "2026-04-20", 140),
    ("CMP11", "Trail Fest 26", "Affiliate", "2026-05-01", "2026-05-31", 55),
    ("CMP12", "Summit Days 26", "Social", "2026-06-05", "2026-07-15", 170),
]
campaigns = [{"campaign_id": c[0], "name": c[1], "channel": c[2],
              "start_date": c[3], "end_date": c[4], "budget_usd": c[5] * 1000}
             for c in campaigns]


def active_campaigns(d):
    ds = d.isoformat()
    return [c for c in campaigns if c["start_date"] <= ds <= c["end_date"]]


# ---------------------------------------------------------------- FX (monthly)
fx_rows = []
rates = {"USD": 1.0, "EUR": 1.08, "AUD": 0.66, "BRL": 0.19}
fx_lookup = {}
for m in MONTHS:
    for cur in rates:
        if cur != "USD":
            rates[cur] *= 1 + random.uniform(-0.015, 0.015)
        fx_rows.append({"month": m, "currency": cur,
                        "usd_rate": round(rates[cur], 4)})
        fx_lookup[(m, cur)] = round(rates[cur], 4)

# ---------------------------------------------------------------- orders + items
orders, items = [], []
oid, lid = 10000, 1
for dnum in range(DAYS):
    d = START + timedelta(days=dnum)
    growth = 1.0 + 0.38 * dnum / DAYS
    lam = 4.6 * SEASON[d.month] * growth
    n = max(0, round(random.gauss(lam, math.sqrt(lam))))
    for _ in range(n):
        seg = wchoice(SEGMENTS, [0.56, 0.20, 0.14, 0.10])
        cust = random.choice(cust_by_seg[seg])
        region = cust["_region"]
        if seg == "Reseller":
            channel = wchoice(CHANNELS, [0.05, 0.0, 0.90, 0.05])
        elif seg == "Corporate & Team":
            channel = wchoice(CHANNELS, [0.35, 0.05, 0.55, 0.05])
        else:
            channel = wchoice(CHANNELS, [0.52, 0.28, 0.0, 0.20])
        if channel == "Wholesale" and d.weekday() >= 5:
            channel = "Online"
        store = random.choice(stores_by_region[region])["store_id"] if channel == "Retail" else None
        rep = None
        if channel == "Wholesale" or (seg == "Corporate & Team" and random.random() < 0.7):
            rep = random.choice(reps_by_region[region])["rep_id"]
        camp = None
        if channel in ("Online", "Marketplace") and random.random() < 0.45:
            act = active_campaigns(d)
            if act:
                camp = random.choice(act)["campaign_id"]
        age = (END - d).days
        if age <= 3:
            status = random.choice(["processing", "processing", "shipped"])
        elif age <= 8:
            status = random.choice(["shipped", "delivered", "delivered"])
        else:
            status = "cancelled" if random.random() < 0.02 else "delivered"
        order = {"order_id": f"SO{oid}", "customer_id": cust["customer_id"],
                 "order_date": d.isoformat(), "channel": channel,
                 "store_id": store, "rep_id": rep, "campaign_id": camp,
                 "currency": REGION_CURRENCY[region], "status": status}
        orders.append(order)
        n_lines = random.randint(2, 6) if channel == "Wholesale" else wchoice([1, 2, 3, 4], [0.45, 0.3, 0.17, 0.08])
        total = 0.0
        for _ in range(n_lines):
            p = pick_product(d.month)
            qty = random.randint(3, 12) if channel == "Wholesale" else wchoice([1, 2, 3], [0.7, 0.22, 0.08])
            price = round(p["list_price"] * random.uniform(0.98, 1.02), 2)
            if channel == "Wholesale":
                disc = round(random.uniform(0.20, 0.40), 2)
            elif camp:
                disc = round(random.uniform(0.10, 0.25), 2)
            else:
                disc = round(random.choice([0, 0, 0, 0.05, 0.10]), 2)
            items.append({"line_id": f"L{lid:06d}", "order_id": order["order_id"],
                          "product_id": p["product_id"], "qty": qty,
                          "unit_price": price, "discount_pct": disc})
            total += qty * price * (1 - disc)
            lid += 1
        order["_total"] = round(total, 2)
        order["_region"] = region
        oid += 1

# ---------------------------------------------------------------- shipping
shipments = []
CARRIERS = {"NA": ["UPS", "FedEx", "USPS"], "EMEA": ["DHL", "DPD", "GLS"],
            "APAC": ["AusPost", "DHL", "Toll"], "LATAM": ["Correios", "DHL", "Estafeta"]}
ship_by_order = {}
for o in orders:
    if o["channel"] == "Retail" or o["status"] in ("cancelled", "processing"):
        continue
    od = date.fromisoformat(o["order_date"])
    promised = random.randint(2, 5) if o["channel"] != "Wholesale" else random.randint(4, 9)
    late = random.random() < 0.12
    actual = promised + (random.randint(1, 6) if late else random.randint(-1, 0))
    actual = max(1, actual)
    ship = od + timedelta(days=random.randint(1, 2))
    delivered = ship + timedelta(days=actual)
    s = {"shipment_id": f"SHP{len(shipments)+1:05d}", "order_id": o["order_id"],
         "carrier": random.choice(CARRIERS[o["_region"]]),
         "ship_date": ship.isoformat(), "promised_days": promised,
         "actual_days": actual,
         "delivered_date": delivered.isoformat() if o["status"] == "delivered" else "",
         "status": "delivered" if o["status"] == "delivered" else "in_transit"}
    shipments.append(s)
    ship_by_order[o["order_id"]] = s

# ---------------------------------------------------------------- returns
orders_by_id = {o["order_id"]: o for o in orders}
prod_by_id = {p["product_id"]: p for p in products}
RETURN_BASE = {"Footwear": 0.11, "Apparel": 0.09}
REASONS = ["Wrong size", "Changed mind", "Not as described", "Damaged in transit"]
returns = []
returned_lines = set()
for it in items:
    o = orders_by_id[it["order_id"]]
    if o["status"] != "delivered" or o["channel"] == "Wholesale":
        continue
    cat = prod_by_id[it["product_id"]]["category"]
    if random.random() < RETURN_BASE.get(cat, 0.05):
        od = date.fromisoformat(o["order_date"])
        rd = od + timedelta(days=random.randint(6, 32))
        if rd > END:
            continue
        if cat in RETURN_BASE:
            reason = wchoice(REASONS, [0.45, 0.22, 0.16, 0.17])
        else:
            reason = wchoice(REASONS, [0.10, 0.38, 0.27, 0.25])
        refund = round(it["qty"] * it["unit_price"] * (1 - it["discount_pct"]), 2)
        returns.append({"rma_id": f"RMA{len(returns)+1:05d}", "line_id": it["line_id"],
                        "order_id": o["order_id"], "return_date": rd.isoformat(),
                        "reason": reason, "refund_amount_local": refund,
                        "condition": random.choice(["resellable", "resellable", "damaged"])})
        returned_lines.add(it["line_id"])

# ---------------------------------------------------------------- payments (JSONL)
payments = []
for o in orders:
    if o["status"] == "cancelled":
        continue
    if o["channel"] == "Wholesale":
        method = wchoice(["Invoice", "Wire"], [0.7, 0.3])
    else:
        method = wchoice(["Card", "PayPal", "Apple Pay", "Gift Card"], [0.58, 0.2, 0.17, 0.05])
    attempts = 1 if random.random() > 0.03 else 2
    for a in range(1, attempts + 1):
        ok = (a == attempts)
        payments.append({
            "txn_id": f"TXN{len(payments)+1:06d}", "order_id": o["order_id"],
            "ts": o["order_date"] + f"T{random.randint(8,22):02d}:{random.randint(0,59):02d}:00Z",
            "method": method, "amount": o["_total"],
            "currency": o["currency"].lower(),  # gateway exports lowercase
            "status": "captured" if ok else "failed", "attempt": a})

# ---------------------------------------------------------------- support tickets
TICKET_CATS = ["Shipping delay", "Return help", "Product question", "Warranty claim", "Website issue"]
late_or_returned = [o for o in orders if
                    (o["order_id"] in ship_by_order and
                     ship_by_order[o["order_id"]]["actual_days"] > ship_by_order[o["order_id"]]["promised_days"])]
returned_orders = list({r["order_id"] for r in returns})
ticket_pool = late_or_returned * 3 + [orders_by_id[x] for x in returned_orders] * 2 + orders
tickets = []
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
for i in range(900):
    linked = random.random() < 0.72
    o = random.choice(ticket_pool) if linked else None
    if o is not None:
        od = date.fromisoformat(o["order_date"])
        created = od + timedelta(days=random.randint(1, 14))
        if created > END:
            created = END
        cust_id = o["customer_id"]
        if o["order_id"] in ship_by_order and ship_by_order[o["order_id"]]["actual_days"] > ship_by_order[o["order_id"]]["promised_days"]:
            cat = wchoice(TICKET_CATS, [0.55, 0.15, 0.15, 0.1, 0.05])
        elif o["order_id"] in returned_orders:
            cat = wchoice(TICKET_CATS, [0.1, 0.55, 0.15, 0.15, 0.05])
        else:
            cat = wchoice(TICKET_CATS, [0.15, 0.15, 0.4, 0.2, 0.1])
    else:
        created = START + timedelta(days=random.randint(0, DAYS - 1))
        cust_id = random.choice(customers)["customer_id"]
        cat = wchoice(TICKET_CATS, [0.1, 0.1, 0.45, 0.15, 0.2])
    closed = random.random() < 0.88
    tickets.append({
        "ticket_id": f"TK{4000+i}",
        "created_date": f"{created.day:02d}-{MON[created.month-1]}-{created.year}",  # 14-Mar-2026
        "customer_id": cust_id,
        "order_id": o["order_id"] if o is not None else "",
        "category": cat, "priority": wchoice(["low", "medium", "high"], [0.5, 0.35, 0.15]),
        "status": "closed" if closed else "open",
        "csat": random.randint(1, 5) if closed and random.random() < 0.6 else ""})

# ---------------------------------------------------------------- NPS surveys
cust_with_orders = list({o["customer_id"] for o in orders})
late_custs = {o["customer_id"] for o in late_or_returned}
ret_custs = {orders_by_id[x]["customer_id"] for x in returned_orders}
COMMENTS_HI = ["Great gear, fast delivery.", "The tent survived a storm. Sold.",
               "Best boots I have owned.", "Support sorted me out quickly.", ""]
COMMENTS_LO = ["Shipping took way too long.", "Sizing runs small, had to return.",
               "Arrived damaged.", "Hard to reach support.", ""]
nps = []
cust_lookup = {c["customer_id"]: c for c in customers}
for i in range(1100):
    cid = random.choice(cust_with_orders)
    seg = cust_lookup[cid]["segment"]
    base = {"Consumer": 8.1, "Outdoor Pro": 8.6, "Corporate & Team": 7.9, "Reseller": 7.6}[seg]
    if cid in late_custs:
        base -= 2.6
    if cid in ret_custs:
        base -= 1.4
    score = max(0, min(10, round(random.gauss(base, 1.6))))
    sd = START + timedelta(days=random.randint(0, DAYS - 1))
    nps.append({"response_id": f"NPS{5000+i}", "survey_date": sd.isoformat(),
                "customer_id": cid, "score": score,
                "comment": random.choice(COMMENTS_HI if score >= 8 else COMMENTS_LO)})

# ---------------------------------------------------------------- web analytics (JSONL)
WEB_CHANNELS = ["Organic", "Paid Search", "Social", "Email", "Direct", "Referral"]
WEB_BASE = {"Organic": 1900, "Paid Search": 1100, "Social": 900,
            "Email": 500, "Direct": 700, "Referral": 300}
web_rows = []
for dnum in range(DAYS):
    d = START + timedelta(days=dnum)
    growth = 1.0 + 0.45 * dnum / DAYS
    camp_channels = {c["channel"] for c in active_campaigns(d)}
    for ch in WEB_CHANNELS:
        lift = 1.55 if ch in camp_channels else 1.0
        sessions = int(WEB_BASE[ch] * SEASON[d.month] * growth * lift * random.uniform(0.85, 1.15))
        conv = round(sessions * random.uniform(0.012, 0.03) * (1.15 if ch in ("Email", "Direct") else 1.0))
        web_rows.append({"date": d.isoformat(), "channel_grouping": ch,
                         "sessions": sessions, "conversions": conv,
                         "bounce_rate": round(random.uniform(0.32, 0.58), 3)})

# ---------------------------------------------------------------- ad spend
PLATFORM = {"Paid Search": ["Google Ads", "Bing Ads"], "Social": ["Meta", "TikTok"],
            "Affiliate": ["PartnerStack"], "Email": ["Klaviyo"]}
ad_rows = []
for c in campaigns:
    s, e = date.fromisoformat(c["start_date"]), date.fromisoformat(c["end_date"])
    span = (e - s).days + 1
    daily = c["budget_usd"] / span
    for i in range(span):
        d = s + timedelta(days=i)
        for plat in PLATFORM[c["channel"]]:
            spend = daily / len(PLATFORM[c["channel"]]) * random.uniform(0.7, 1.3)
            clicks = int(spend / random.uniform(0.8, 2.4))
            ad_rows.append({"date": d.isoformat(), "campaign_id": c["campaign_id"],
                            "platform": plat, "spend_usd": round(spend, 2),
                            "impressions": clicks * random.randint(18, 40),
                            "clicks": clicks})

# ---------------------------------------------------------------- email stats
email_rows = []
for c in campaigns:
    if c["channel"] != "Email":
        continue
    for m in MONTHS:
        if c["start_date"][:7] <= m <= c["end_date"][:7]:
            sends = random.randint(60000, 140000)
            deliv = int(sends * random.uniform(0.965, 0.99))
            opens = int(deliv * random.uniform(0.28, 0.44))
            email_rows.append({"campaign_id": c["campaign_id"], "month": m,
                               "audience": "engaged-24mo", "sends": sends,
                               "delivered": deliv, "opens": opens,
                               "clicks": int(opens * random.uniform(0.09, 0.2)),
                               "unsubs": int(sends * random.uniform(0.001, 0.004))})
for m in MONTHS:
    sends = random.randint(90000, 130000)
    deliv = int(sends * 0.975)
    opens = int(deliv * random.uniform(0.24, 0.36))
    email_rows.append({"campaign_id": "NEWSLETTER", "month": m,
                       "audience": "all-subscribers", "sends": sends,
                       "delivered": deliv, "opens": opens,
                       "clicks": int(opens * random.uniform(0.07, 0.15)),
                       "unsubs": int(sends * random.uniform(0.001, 0.005))})

# ---------------------------------------------------------------- inventory
WAREHOUSES = ["NA-East", "NA-West", "EMEA-Hub", "APAC-Hub", "LATAM-Hub"]
inv_rows = []
for p in products:
    for wh in WAREHOUSES:
        inv_rows.append({"product_id": p["product_id"], "warehouse": wh,
                         "on_hand": random.randint(0, 480),
                         "reorder_point": random.randint(20, 80),
                         "inbound_units": random.choice([0, 0, 0, 50, 120, 200]),
                         "snapshot_date": END.isoformat()})

# ---------------------------------------------------------------- supplier XML
SUPPLIER = {"Cobalt": "Cobalt Mfg Co", "NorthCrag": "NorthCrag Industrial",
            "Peak & Pine": "P&P Sourcing Ltd", "TrailForge": "TrailForge Works",
            "Aurora Gear": "Aurora Gear Supply"}
root = ET.Element("pricelist", {"issued": END.isoformat(), "currency": "USD"})
for p in products:
    ET.SubElement(root, "product", {
        "id": p["product_id"], "supplier": SUPPLIER[p["brand"]],
        "unit_cost_usd": str(round(p["list_price"] * random.uniform(0.42, 0.62), 2)),
        "lead_time_days": str(random.randint(14, 60))})

# ---------------------------------------------------------------- finance targets
actual = {}
for it in items:
    o = orders_by_id[it["order_id"]]
    if o["status"] == "cancelled":
        continue
    m = o["order_date"][:7]
    rev = it["qty"] * it["unit_price"] * (1 - it["discount_pct"]) * fx_lookup[(m, o["currency"])]
    key = (m, o["_region"])
    actual[key] = actual.get(key, 0) + rev
target_rows = [{"month": m, "region": r,
                "revenue_target_usd": int(round(actual.get((m, r), 0) * random.uniform(0.92, 1.12), -3))}
               for m in MONTHS for r in REGIONS]

# ================================================================ WRITERS
def write_csv(fname, rows, fields):
    with open(os.path.join(SRC, fname), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def write_json(fname, data):
    with open(os.path.join(SRC, fname), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return len(data)


def write_jsonl(fname, rows):
    with open(os.path.join(SRC, fname), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return len(rows)


counts = {}
counts["crm_customers.csv"] = write_csv(
    "crm_customers.csv", customers,
    ["customer_id", "full_name", "email", "segment", "region", "signup_date", "marketing_opt_in"])

db_path = os.path.join(SRC, "erp_sales.db")
if os.path.exists(db_path):
    os.remove(db_path)
con = sqlite3.connect(db_path)
con.execute("CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_id TEXT, "
            "order_date TEXT, channel TEXT, store_id TEXT, rep_id TEXT, "
            "campaign_id TEXT, currency TEXT, status TEXT)")
con.execute("CREATE TABLE order_items (line_id TEXT PRIMARY KEY, order_id TEXT, "
            "product_id TEXT, qty INTEGER, unit_price REAL, discount_pct REAL)")
con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
                [(o["order_id"], o["customer_id"], o["order_date"], o["channel"],
                  o["store_id"], o["rep_id"], o["campaign_id"], o["currency"],
                  o["status"]) for o in orders])
con.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)",
                [(i["line_id"], i["order_id"], i["product_id"], i["qty"],
                  i["unit_price"], i["discount_pct"]) for i in items])
con.commit()
con.close()
counts["erp_sales.db"] = f"{len(orders)} orders / {len(items)} items"

counts["product_catalog.json"] = write_json("product_catalog.json", products)
counts["inventory_snapshot.csv"] = write_csv(
    "inventory_snapshot.csv", inv_rows,
    ["product_id", "warehouse", "on_hand", "reorder_point", "inbound_units", "snapshot_date"])
counts["web_analytics.jsonl"] = write_jsonl("web_analytics.jsonl", web_rows)
counts["marketing_campaigns.csv"] = write_csv(
    "marketing_campaigns.csv", campaigns,
    ["campaign_id", "name", "channel", "start_date", "end_date", "budget_usd"])
counts["ad_spend_daily.csv"] = write_csv(
    "ad_spend_daily.csv", ad_rows,
    ["date", "campaign_id", "platform", "spend_usd", "impressions", "clicks"])
counts["email_stats.json"] = write_json("email_stats.json", email_rows)
counts["support_tickets.csv"] = write_csv(
    "support_tickets.csv", tickets,
    ["ticket_id", "created_date", "customer_id", "order_id", "category", "priority", "status", "csat"])
counts["nps_surveys.csv"] = write_csv(
    "nps_surveys.csv", nps,
    ["response_id", "survey_date", "customer_id", "score", "comment"])
counts["shipping_tracking.csv"] = write_csv(
    "shipping_tracking.csv", shipments,
    ["shipment_id", "order_id", "carrier", "ship_date", "promised_days",
     "actual_days", "delivered_date", "status"])
counts["returns_rma.csv"] = write_csv(
    "returns_rma.csv", returns,
    ["rma_id", "line_id", "order_id", "return_date", "reason", "refund_amount_local", "condition"])
counts["payment_gateway.jsonl"] = write_jsonl("payment_gateway.jsonl", payments)
counts["hr_sales_reps.csv"] = write_csv(
    "hr_sales_reps.csv", reps,
    ["rep_id", "name", "team", "region", "hire_date", "annual_quota_usd"])
counts["store_locations.json"] = write_json("store_locations.json", stores)
counts["fx_rates.csv"] = write_csv("fx_rates.csv", fx_rows, ["month", "currency", "usd_rate"])
counts["finance_targets.csv"] = write_csv(
    "finance_targets.csv", target_rows, ["month", "region", "revenue_target_usd"])
ET.ElementTree(root).write(os.path.join(SRC, "supplier_pricelist.xml"),
                           encoding="utf-8", xml_declaration=True)
counts["supplier_pricelist.xml"] = len(products)

print(f"Generated {len(counts)} sources in {SRC}\n")
for k, v in counts.items():
    print(f"  {k:28s} {v}")
