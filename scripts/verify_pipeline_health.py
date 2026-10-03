#!/usr/bin/env python3
"""
verify_pipeline_health.py — post-repair smoke test for the SOoL pipeline.

Checks, in order:
  1. No retired Claude model IDs remain in the source tree.
  2. Every Sonnet-5 call site disables thinking (else max_tokens is consumed
     by reasoning and the JSON response truncates).
  3. The Anthropic API actually answers for the configured model.
  4. The annotation backlog is visible to the pipeline.
  5. Database freshness — how stale is each store.

Run:
    source ~/.sool_env && ./venv/bin/python3 verify_pipeline_health.py

Exit code 0 = healthy, 1 = something still broken.
"""
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
RETIRED = ["claude-sonnet-4-20250514", "claude-3-5-sonnet", "claude-3-opus"]
# Call sites that must pin thinking off (they emit JSON under a tight budget).
THINKING_SENSITIVE = [
    "annotate_pipeline.py",
    "annotate_criminal.py",
    "daily_case.py",
    "followup_study.py",
]

ok = True


def report(passed, label, detail=""):
    global ok
    if not passed:
        ok = False
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


print("=" * 64)
print("SOoL pipeline health check")
print("=" * 64)

# ── 1. No retired model IDs ──────────────────────────────────────────────────
print("\n1. Retired model IDs")
hits = []
for py in sorted(BASE.glob("*.py")):
    if py.name == Path(__file__).name:
        continue
    try:
        text = py.read_text(errors="ignore")
    except OSError:
        continue
    for bad in RETIRED:
        if bad in text:
            hits.append(f"{py.name}:{bad}")
report(not hits, "no retired model IDs in source", ", ".join(hits))

# ── 2. Thinking disabled on tight-budget JSON call sites ─────────────────────
print("\n2. Adaptive-thinking guard (Sonnet 5 thinks by default)")
for name in THINKING_SENSITIVE:
    p = BASE / name
    if not p.exists():
        report(False, name, "file missing")
        continue
    text = p.read_text(errors="ignore")
    if "claude-sonnet-5" not in text:
        report(True, name, "no Sonnet 5 call site; skipped")
        continue
    n_disabled = len(re.findall(r'thinking["\']?\s*[:=]\s*\{\s*["\']type["\']\s*:\s*["\']disabled', text))
    report(n_disabled > 0, name, f"{n_disabled} call site(s) pin thinking=disabled")

# ── 3. Live API check ────────────────────────────────────────────────────────
print("\n3. Anthropic API reachability")
key = os.environ.get("SOOL_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
if not key:
    report(False, "API key present", "set SOOL_ANTHROPIC_KEY (source ~/.sool_env)")
else:
    try:
        import requests

        model = "claude-sonnet-5"
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": 64,
                "thinking": {"type": "disabled"},
                "messages": [{"role": "user",
                              "content": 'Reply with exactly this JSON and nothing else: {"ok":true}'}],
            },
            timeout=60,
        )
        if r.status_code == 404:
            report(False, f"model {model} reachable",
                   "404 — model ID not recognised by this account")
        elif r.status_code != 200:
            report(False, f"model {model} reachable",
                   f"HTTP {r.status_code}: {r.text[:180]}")
        else:
            body = r.json()
            text = "".join(b.get("text", "") for b in body.get("content", [])
                           if b.get("type") == "text")
            stop = body.get("stop_reason")
            report("ok" in text.lower(), f"model {model} returned usable text",
                   f"stop_reason={stop} text={text.strip()[:60]!r}")
            report(stop != "max_tokens", "response not truncated",
                   f"stop_reason={stop}")
    except Exception as e:
        report(False, "API call", f"{type(e).__name__}: {e}")

# ── 4. Annotation backlog ────────────────────────────────────────────────────
print("\n4. Annotation backlog")
try:
    n_cases = sqlite3.connect(BASE / "sool_corpus.db").execute(
        "SELECT COUNT(*) FROM cases").fetchone()[0]
    n_annot = sqlite3.connect(BASE / "sool_annotations.db").execute(
        "SELECT COUNT(*) FROM annotations").fetchone()[0]
    backlog = n_cases - n_annot
    print(f"       cases={n_cases:,}  annotations={n_annot:,}  backlog={backlog:,}")
    report(True, "backlog measured",
           "run annotate_pipeline.py to drain it" if backlog > 0 else "fully annotated")
except Exception as e:
    report(False, "backlog query", str(e))

# ── 5. Freshness ─────────────────────────────────────────────────────────────
print("\n5. Data freshness (days since last write)")
now = datetime.now(timezone.utc)
checks = [
    ("sool_corpus.db",              "cases",                "collected_at"),
    ("sool_annotations.db",         "annotations",          "annotation_date"),
    ("sool_criminal.db",            "criminal_cases",       "collected_at"),
    ("sool_criminal_annotations.db", "criminal_annotations", "annotation_date"),
]
for db, table, col in checks:
    try:
        v = sqlite3.connect(BASE / db).execute(
            f'SELECT MAX("{col}") FROM "{table}"').fetchone()[0]
        if not v:
            print(f"       {db:<32} {table:<22} (empty)")
            continue
        ts = datetime.fromisoformat(str(v))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (now - ts).days
        flag = "  <-- STALE" if age > 7 else ""
        print(f"       {db:<32} {table:<22} {age:>4}d ago{flag}")
    except Exception as e:
        print(f"       {db:<32} {table:<22} error: {e}")

print("\n" + "=" * 64)
print("RESULT:", "HEALTHY" if ok else "PROBLEMS FOUND")
print("=" * 64)
sys.exit(0 if ok else 1)
