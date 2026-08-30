"""
Renders the agentic-mapping evidence into a static page: the raw unknown
file, the model's recorded proposal, and the 11 deterministic gates -- all
regenerated from the actual artifacts at build time, so the page can never
drift from the truth.

Run:  python build_mapping_page.py   (after generate_unknown_source.py; a
      recorded proposal must exist in mapper/recorded/)
Output: output/mapping.html
"""
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "mapper"))
import mapping_lib as lib

SOURCE = os.path.join(ROOT, "incoming", "warranty_registrations.txt")
RECORDED = os.path.join(ROOT, "mapper", "recorded", "proposal.json")
OUT = os.path.join(ROOT, "output", "mapping.html")
REPO = "https://github.com/bgard68/bi-simulator"

E = html.escape

with open(RECORDED, encoding="utf-8") as f:
    recorded = json.load(f)
proposal, meta = recorded["proposal"], recorded.get("meta", {})

with open(SOURCE, encoding="utf-8") as f:
    lines = [ln.rstrip("\n") for ln in f]
sample = lines[:11]
canary_no, canary_txt = next(
    ((i + 1, ln) for i, ln in enumerate(lines) if "IGNORE ALL PREVIOUS" in ln),
    (None, None))

gates = []
problems = lib.structural_check(proposal)
gates.append(("S1-S4 structural: shape, coverage, whitelist, canonical maps",
              not problems, "; ".join(problems) if problems else "ok"))
if not problems:
    gates += lib.apply_and_gate(proposal, SOURCE)[0]
all_ok = all(ok for _, ok, _ in gates)

model = str(meta.get("model", "?"))
model_chips = [m for m in model.split("/") if m]  # CLI may report >1 model used
attempts = meta.get("attempts", [])


def chips(items, cls="chip"):
    return "".join(f'<span class="{cls}">{E(str(i))}</span>' for i in items)


map_rows = ""
for c in proposal["columns"]:
    tr = " ".join(f'<span class="tf">{E(t)}</span><span class="sep">&rarr;</span>'
                  for t in c.get("transforms", []))
    map_rows += (f'<tr><td class="mono">{E(c["source"])}</td>'
                 f'<td class="tfs">{tr}</td>'
                 f'<td class="mono strong">{E(c["target"])}</td></tr>')

vm_html = ""
for field, mapping in proposal.get("value_maps", {}).items():
    pairs = "".join(f'<div class="pair"><span class="mono">{E(k)}</span>'
                    f'<span class="sep">&rarr;</span><span>{E(v)}</span></div>'
                    for k, v in mapping.items())
    vm_html += f'<div class="vmap"><div class="vmt">{E(field)}</div>{pairs}</div>'

gate_rows = ""
for name, ok, detail in gates:
    pill = '<span class="pill pass">PASS</span>' if ok else '<span class="pill fail">FAIL</span>'
    gate_rows += (f'<tr><td>{pill}</td><td>{E(name)}</td>'
                  f'<td class="detail">{E(str(detail))}</td></tr>')

verdict = ('<span class="pill pass big">ACCEPTED</span>' if all_ok
           else '<span class="pill fail big">REJECTED</span>')

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gated Mapping Evidence</title>
<style>
  :root {{
    color-scheme: light;
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
    --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
    --border:rgba(11,11,11,.10); --s1:#2a78d6; --good:#006300; --bad:#d03b3b;
    --goodbg:rgba(12,163,12,.12); --badbg:rgba(208,59,59,.12);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
      --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
      --muted:#898781; --grid:#2c2c2a; --axis:#383835;
      --border:rgba(255,255,255,.10); --s1:#3987e5; --good:#0ca30c; --bad:#e66767;
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835;
    --border:rgba(255,255,255,.10); --s1:#3987e5; --good:#0ca30c; --bad:#e66767;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--page); color:var(--ink);
         font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .wrap {{ max-width: 880px; margin: 0 auto; padding: 26px 20px 48px; }}
  h1 {{ font-size: 21px; margin: 0; letter-spacing: -0.01em; }}
  h2 {{ font-size: 15px; margin: 0 0 4px; }}
  .sub {{ color: var(--ink2); margin: 6px 0 0; max-width: 64ch; }}
  .nav {{ display:flex; gap:16px; margin-top:10px; font-size:13px; flex-wrap:wrap; }}
  .nav a {{ color: var(--s1); text-decoration: none; }}
  .nav a:hover {{ text-decoration: underline; }}
  .card {{ background:var(--surface); border:1px solid var(--border);
          border-radius:10px; padding:16px 18px; margin-top:16px; }}
  .csub {{ color:var(--muted); font-size:12.5px; margin:2px 0 10px; }}
  .mono {{ font-family: ui-monospace, Consolas, monospace; font-size: 12.5px; }}
  .strong {{ font-weight: 650; }}
  pre {{ background:var(--page); border:1px solid var(--grid); border-radius:8px;
        padding:10px 12px; overflow-x:auto; font-size:12px; line-height:1.5;
        font-family: ui-monospace, Consolas, monospace; margin: 0; }}
  .chips {{ display:flex; gap:7px; flex-wrap:wrap; margin-top:10px; }}
  .chip {{ border:1px solid var(--border); border-radius:6px; padding:2px 8px;
          font-size:12px; color:var(--ink2); }}
  .canary {{ margin-top:12px; border:1px solid var(--bad); background:var(--badbg);
            border-radius:8px; padding:9px 12px; font-size:12.5px; }}
  .canary .mono {{ display:block; margin-top:5px; overflow-x:auto; white-space:nowrap; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th {{ text-align:left; color:var(--ink2); font-size:11.5px; font-weight:600;
       border-bottom:1px solid var(--axis); padding:5px 12px 5px 0; }}
  td {{ border-bottom:1px solid var(--grid); padding:6px 12px 6px 0; vertical-align:top; }}
  tr:last-child td {{ border-bottom:0; }}
  .tf {{ display:inline-block; border:1px solid var(--border); border-radius:5px;
        padding:1px 6px; font-family:ui-monospace,Consolas,monospace; font-size:11.5px;
        margin:1px 0; }}
  .sep {{ color:var(--muted); padding:0 4px; }}
  .tfs .sep:last-child {{ display:none; }}
  .pill {{ display:inline-block; border-radius:6px; padding:1px 8px; font-size:11.5px;
          font-weight:700; }}
  .pill.pass {{ color:var(--good); background:var(--goodbg); }}
  .pill.fail {{ color:var(--bad); background:var(--badbg); }}
  .pill.big {{ font-size:13px; padding:3px 11px; }}
  .detail {{ color:var(--ink2); font-size:12px; font-variant-numeric:tabular-nums; }}
  .vmaps {{ display:flex; gap:24px; flex-wrap:wrap; margin-top:12px; }}
  .vmt {{ font-size:11.5px; font-weight:600; color:var(--ink2); margin-bottom:4px; }}
  .pair {{ display:flex; gap:4px; font-size:12.5px; padding:1px 0; }}
  .meta {{ display:flex; gap:18px; flex-wrap:wrap; color:var(--ink2); font-size:12.5px; }}
  .meta b {{ color: var(--ink); font-weight:600; }}
  details {{ margin-top: 10px; }}
  summary {{ cursor: pointer; color: var(--s1); font-size: 13px; }}
  footer {{ margin-top:22px; color:var(--muted); font-size:12px; }}
  a {{ color: var(--s1); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>The model proposed. The gates decided. {verdict}</h1>
    <p class="sub">A source file this pipeline was never taught, integrated by an
    LLM whose only power is choosing from a closed transform vocabulary &mdash;
    and a set of deterministic gates that measured the proposal against all
    {len(lines) - 1:,} rows before anything landed. Rebuilt and re-verified by CI
    on every push.</p>
    <nav class="nav">
      <a href="index.html">&larr; The dashboard</a>
      <a href="{REPO}">Repository</a>
      <a href="{REPO}/blob/main/docs/AGENTIC_MAPPING.md">How it works</a>
    </nav>
  </header>

  <section class="card">
    <h2>1 &mdash; The unknown source</h2>
    <p class="csub">incoming/warranty_registrations.txt &middot; {len(lines) - 1:,} rows &middot;
    conventions the ETL was never taught</p>
    <pre>{E(chr(10).join(sample))}</pre>
    <div class="chips">
      {chips(["pipe-delimited .txt", "dates DD.MM.YYYY", "SKU- prefixed products",
              "zones AMER / APJ / LATM", "codes WEB / SHOP / BULK / MKT",
              "~2% unknown customers", "padded + shouty values"])}
    </div>
    {"" if canary_no is None else f'''<div class="canary"><b>Line {canary_no} of the file is a prompt-injection canary</b> &mdash;
    hostile text sitting in a data field. It gets no special treatment: it is just a
    value that fails the customer join, absorbed by the coverage slack. Content cannot vote.
    <span class="mono">{E(canary_txt)}</span></div>'''}
  </section>

  <section class="card">
    <h2>2 &mdash; The proposal (the voice)</h2>
    <p class="csub">Proposed via {E(str(meta.get("backend", "?")))} &middot;
    accepted on attempt {len(attempts)} of 3 &middot; {E(str(meta.get("created_utc", "")))}
    &middot; models in the CLI session: {chips(model_chips)}</p>
    <table>
      <tr><th>Source column</th><th>Transforms (whitelist only)</th><th>Target field</th></tr>
      {map_rows}
    </table>
    <div class="vmaps">{vm_html}</div>
    <details><summary>Full recorded proposal JSON</summary>
    <pre>{E(json.dumps(recorded, indent=2))}</pre></details>
  </section>

  <section class="card">
    <h2>3 &mdash; The gates (the vote)</h2>
    <p class="csub">Deterministic, dependency-free Python &mdash; applied to the full file,
    not the sample the model saw. Recomputed live when this page was built.</p>
    <table>
      <tr><th></th><th>Gate</th><th>Measured</th></tr>
      {gate_rows}
    </table>
  </section>

  <section class="card">
    <h2>Run it yourself</h2>
    <p class="csub">No API key needed: the default backend shells out to the Claude Code CLI
    on an existing subscription; any OpenAI-compatible endpoint (including a local Ollama)
    works via environment variables. CI never calls a model &mdash; it replays this recorded
    decision on every push.</p>
<pre>git clone {REPO}
python generate_sources.py
python generate_unknown_source.py
python mapper/propose_mapping.py     # live model call, records on success
python mapper/validate_mapping.py    # the gates, and the verdict</pre>
  </section>

  <footer>Part of <a href="{REPO}">bi-simulator</a> &mdash; 18 simulated sources flattened
  into one model by an AI agent, with this 19th integrated by AI <i>inside</i> the
  pipeline, gated. Simulated data throughout.</footer>
</div>
</body>
</html>
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(page)
print(f"built {OUT} ({os.path.getsize(OUT) // 1024} KB) - verdict: {'ACCEPTED' if all_ok else 'REJECTED'}")
