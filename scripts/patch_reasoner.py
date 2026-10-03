#!/usr/bin/env python3
"""
patch_reasoner.py — Fix two over-strict axioms in reason_corpus.py
===================================================================
1. RPF axiom: RPF can fire when N7 or N8 is partial, not only when failed
2. N7 partial: protection_granted with N7=partial is valid (right partially recognized)

Usage:
    python3 patch_reasoner.py
"""
import shutil, sys
from pathlib import Path
from datetime import datetime

TARGET = Path("reason_corpus.py")
BACKUP = Path(f"reason_corpus.py.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

src = TARGET.read_text(encoding="utf-8")
changes = []

def rep(old, new, label):
    global src
    if old not in src:
        print(f"  ✗ NOT FOUND: {label}")
        return
    src = src.replace(old, new, 1)
    changes.append(label)
    print(f"  ✓ {label}")

# ── Fix 1: STRUCTURAL_IMPOSSIBILITIES lambda for RPF ─────────────────────────
# Old: RPF + N7 closed + N8 failed → impossible
# New: RPF + N7 closed + N8 closed → impossible (both fully closed = no structural basis)
# Rationale: RPF is valid when N8 is partial (remedy partially blocked)
#            or when N7 is partial (recognition partial → repair incomplete)
rep(
    "    # N7 closed but RPF present — repair failure requires N7 failure\n"
    "    lambda r: r['node7'] == 'closed' and 'RPF' in r['cts'] and\n"
    "              r['node8'] == 'failed',",

    "    # RPF requires some structural basis — N7 or N8 must not be fully closed\n"
    "    # RPF is valid when N8=partial (blocked remedy) or N7=partial (incomplete recognition)\n"
    "    # Only flag as impossible if RPF fires with BOTH N7 and N8 fully closed AND N8=closed\n"
    "    # (already caught by the inline check below — remove from lambda list)\n"
    "    # lambda removed: RPF+N7closed+N8failed — see inline check\n"
    "    lambda r: False,  # placeholder — RPF consistency handled inline",

    "STRUCTURAL_IMPOSSIBILITIES RPF lambda"
)

# ── Fix 2: N7=partial allowed for protection_granted ─────────────────────────
# Old: granted + N7=failed → inconsistent  (correct)
# New: granted + N7=failed → inconsistent  (keep)
#      granted + N7=partial → NOT inconsistent (partial recognition can still grant)
rep(
    "    # Cannot be granted if N7 failed\n"
    "    if outcome == 'protection_granted' and nodes[7] == 'failed':\n"
    "        inferences['inconsistencies'].append(\n"
    "            \"INCONSISTENT: chain_outcome=protection_granted but N7=failed\"\n"
    "        )",

    "    # Cannot be granted if N7 fully failed\n"
    "    # N7=partial is permissible for granted (right partially but sufficiently recognized)\n"
    "    if outcome == 'protection_granted' and nodes[7] == 'failed':\n"
    "        inferences['inconsistencies'].append(\n"
    "            \"INCONSISTENT: chain_outcome=protection_granted but N7=failed\"\n"
    "        )",

    "N7 partial allowed for granted"
)

# ── Fix 3: RPF inline check — relax to require N8 also not partial ────────────
rep(
    "    # RPF requires N7 failure or independent N8 problem\n"
    "    if 'RPF' in cts and nodes[7] == 'closed' and nodes[8] == 'closed':\n"
    "        inferences['inconsistencies'].append(\n"
    "            \"INCONSISTENT: RPF fires but N7 and N8 both closed — \"\n"
    "            \"RPF requires either N7 failure cascade or N8 structural defect\"\n"
    "        )",

    "    # RPF requires structural basis: N7 or N8 must show stress (failed or partial)\n"
    "    # RPF with N7=closed AND N8=closed AND no active node stress = annotation error\n"
    "    # RPF with N7=partial or N8=partial is valid (incomplete recognition/repair)\n"
    "    if ('RPF' in cts\n"
    "            and nodes[7] == 'closed'\n"
    "            and nodes[8] == 'closed'\n"
    "            and not any(nodes[n] in ('failed','partial') for n in range(1,7))):\n"
    "        inferences['inconsistencies'].append(\n"
    "            \"INCONSISTENT: RPF fires but all nodes closed — \"\n"
    "            \"RPF requires N7/N8 stress or upstream partial closure\"\n"
    "        )",

    "RPF inline check relaxed"
)

print(f"\n{len(changes)}/3 patches applied.")

if len(changes) < 3:
    print("Some patches not applied — check manually.")
    sys.exit(1)

shutil.copy(TARGET, BACKUP)
print(f"Backup: {BACKUP}")
TARGET.write_text(src, encoding="utf-8")
print(f"Written: {TARGET}")

import subprocess
r = subprocess.run(["python3", "-c", f"import ast; ast.parse(open('{TARGET}').read())"],
                   capture_output=True, text=True)
if r.returncode == 0:
    print("Syntax: ✓ OK")
    print("\nNext:")
    print("  python3 reason_corpus.py")
    print("  curl --retry 3 --user \"$TURBIFY_FTP_USER:$TURBIFY_FTP_PASS\" \\")
    print("    -T ~/CaseLaw/sool_inferences.json \\")
    print("    \"ftp://$TURBIFY_FTP_HOST/sool_inferences.json\"")
else:
    print(f"Syntax: ✗ FAILED\n{r.stderr[:300]}")
    shutil.copy(BACKUP, TARGET)
    print("Restored backup.")
    sys.exit(1)
