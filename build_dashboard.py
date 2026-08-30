"""
Injects warehouse/dashboard_data.json into dashboard_template.html and writes:

  output/dashboard.html   standalone page (open locally, share, etc.)
  output/artifact.html    body-content variant for hosted-artifact publishing

Run:  python build_dashboard.py   (after etl.py)
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

with open(os.path.join(ROOT, "dashboard_template.html"), encoding="utf-8") as f:
    template = f.read()
with open(os.path.join(ROOT, "warehouse", "dashboard_data.json"), encoding="utf-8") as f:
    payload = f.read()

# keep any "</" inside JSON strings from terminating the <script> block
payload = payload.replace("</", "<\\/")
page = template.replace("__DATA_JSON__", payload, 1)

artifact_path = os.path.join(OUT, "artifact.html")
with open(artifact_path, "w", encoding="utf-8") as f:
    f.write(page)

m = re.match(r"\s*<title>(.*?)</title>\s*", page, re.S)
title = m.group(1) if m else "Dashboard"
body = page[m.end():] if m else page
standalone = (
    "<!doctype html>\n<html lang=\"en\">\n<head>\n"
    "<meta charset=\"utf-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
    f"<title>{title}</title>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
)
dash_path = os.path.join(OUT, "dashboard.html")
with open(dash_path, "w", encoding="utf-8") as f:
    f.write(standalone)

print(f"built {dash_path} ({os.path.getsize(dash_path)//1024} KB)")
print(f"built {artifact_path} ({os.path.getsize(artifact_path)//1024} KB)")
