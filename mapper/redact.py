"""
Redaction for anything that goes to a model.

The split this module enforces: **the model sees a redacted sample; the
deterministic layer processes the real file.** A schema mapping only needs
the *shape* of a value -- is this an email, which date format, what prefix --
never the value itself. So sensitive values are replaced with type-preserving
surrogates before sampling, and nothing sensitive leaves the machine.

Surrogates are deterministic (keyed hash), so a value that repeats in the file
still repeats in the sample -- the model can see that a column is unique or
low-cardinality without seeing what is in it.

Detection is deliberately blunt: content patterns plus column-name hints, both
conservative in the direction of over-redacting. A missed pattern is a
disclosure; an over-redacted column costs nothing but a slightly duller sample.

WHAT THIS DOES NOT CATCH -- stated plainly, because a redactor whose limits
are undocumented is worse than none:

  * Person names with no telling column name. `contact`, `buyer`, `attn` are
    caught by hint; `signed_by`, `owner`, `requested_by` are not. There is no
    NER here -- names are unbounded strings and pattern matching cannot find
    them. A real deployment pairs this with a classifier (Azure AI Language,
    Presidio) or an allow-list of columns cleared for sampling.
  * PII embedded in free text. A `description` column reading "call Jane at
    the Elm St site" keeps the name and the street; only the standalone
    patterns below (email, phone, SSN, card, IP) are found inside prose.
  * Non-US formats. Phone, postal and government-id patterns are US-shaped;
    a UK NIN or an IBAN in an unhinted column passes through.
  * Structured formats get content matching only. For JSON and XML the
    positional column-hint pass does not apply, so a `contactName` key is
    redacted only if its *value* matches a pattern.
  * Indirect identifiers. A rare job title plus a small city can identify
    someone without any single field looking sensitive. Nothing here reasons
    about combinations.
  * Anything encoded. Base64, URL-encoded or hashed payloads are opaque to
    regexes.

The mitigation for all of the above is the same and is architectural rather
than clever: only a *sample* is ever sent, the sample is redacted, and the
full file never leaves the machine. Where that is still not acceptable --
health data, anything under contractual data-residency terms -- the
`openai-compatible` backend points at a model inside your own perimeter
(Azure OpenAI in your tenant, or a local Ollama), and nothing leaves at all.
"""
import hashlib
import os
import re

KEY = os.environ.get("MAPPER_REDACTION_KEY", "bi-simulator-local").encode()

# --- content detectors --------------------------------------------------
PATTERNS = [
    ("email",   re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("ssn",     re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card",    re.compile(r"\b(?:\d[ \-]?){13,19}\b")),
    ("phone",   re.compile(r"(?:\+?\d{1,2}[ .\-]?)?\(?\d{3}\)?[ .\-]?\d{3}[ .\-]?\d{4}\b")),
    ("ip",      re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
]

# --- column-name hints (checked against the header, case-insensitive) ---
HEADER_HINTS = [
    ("email",   re.compile(r"e[_\-]?mail|email", re.I)),
    ("person",  re.compile(r"\b(contact|buyer|purchaser|customer[_\-]?name|"
                           r"full[_\-]?name|first[_\-]?name|last[_\-]?name|"
                           r"employee|rep[_\-]?name|attn)\b|contct", re.I)),
    ("address", re.compile(r"address|addr\d?|street|addr[_\-]?line", re.I)),
    ("phone",   re.compile(r"phone|tel|mobile|fax", re.I)),
    ("ssn",     re.compile(r"\bssn\b|social[_\-]?security|tax[_\-]?id|\bein\b", re.I)),
    ("card",    re.compile(r"card[_\-]?(no|num|number)|account[_\-]?(no|number)|iban", re.I)),
]

FAKE_NAMES = ["A. Rivera", "B. Chen", "C. Okonkwo", "D. Larsen", "E. Moreau",
              "F. Bianchi", "G. Haddad", "H. Novak", "I. Yamada", "J. Silva"]
FAKE_STREETS = ["Maple", "Cedar", "Juniper", "Alder", "Birch", "Willow"]


def _h(value, n=6):
    return hashlib.blake2b(str(value).encode("utf-8", "replace"),
                           key=KEY, digest_size=8).hexdigest()[:n]


def surrogate(value, kind):
    """A stand-in that preserves shape and cardinality, not content."""
    v = str(value)
    if kind == "email":
        return f"user{_h(v)}@example.invalid"
    if kind == "person":
        return FAKE_NAMES[int(_h(v, 4), 16) % len(FAKE_NAMES)]
    if kind == "address":
        num = int(_h(v, 4), 16) % 9000 + 100
        return f"{num} {FAKE_STREETS[int(_h(v, 3), 16) % len(FAKE_STREETS)]} St"
    if kind == "phone":
        return f"555-01{int(_h(v, 4), 16) % 100:02d}"
    if kind in ("ssn", "card", "ip"):
        return "[redacted]"
    return f"[redacted:{_h(v, 4)}]"


def classify_header(name):
    """Return a redaction kind for a column name, or None."""
    for kind, rx in HEADER_HINTS:
        if rx.search(name or ""):
            return kind
    return None


def redact_value(value, kind=None):
    """Redact one value: by declared column kind, else by content sniffing."""
    if value is None:
        return value
    v = str(value)
    if kind:
        return surrogate(v, kind) if v.strip() else v
    for k, rx in PATTERNS:
        if rx.search(v):
            return rx.sub(lambda m: surrogate(m.group(0), k), v)
    return v


def redact_text(text, header_kinds=None):
    """Redact a raw text sample (delimited, JSON or XML alike).

    Content patterns are applied everywhere. Column-name hints cannot be
    applied positionally to arbitrary text, so they are handled by
    redact_records() when structure is available.
    """
    out = text
    for kind, rx in PATTERNS:
        out = rx.sub(lambda m, k=kind: surrogate(m.group(0), k), out)
    return out


def redact_records(records, header):
    """Redact parsed records using column-name hints plus content sniffing."""
    kinds = {h: classify_header(h) for h in header}
    hits = {}
    out = []
    for rec in records:
        if rec is None:
            out.append(rec)
            continue
        row = {}
        for k, v in rec.items():
            kind = kinds.get(k)
            new = redact_value(v, kind)
            if new != v:
                hits[k] = hits.get(k, 0) + 1
            row[k] = new
        out.append(row)
    return out, kinds, hits


def report(kinds, hits, total):
    """A short, auditable summary of what was withheld from the model."""
    redacted = {k: v for k, v in kinds.items() if v}
    lines = []
    for col, kind in sorted(redacted.items()):
        lines.append(f"  {col:28s} {kind:8s} {hits.get(col, 0)}/{total} values")
    for col, n in sorted(hits.items()):
        if col not in redacted:
            lines.append(f"  {col:28s} {'content':8s} {n}/{total} values")
    return lines
