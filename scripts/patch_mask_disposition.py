#!/usr/bin/env python3
"""
patch_mask_disposition.py
=========================
Patches annotate_pipeline.py to add --mask-disposition flag.

What it does:
  1. Adds strip_disposition() function after OPINION_CHARS constant
  2. Adds masking call inside build_user_prompt() after truncation
  3. Adds --mask-disposition argument to argparse
  4. Passes mask flag through annotate_domain() → build_user_prompt()
  5. Adds masked annotation logging for comparison study

Usage:
    python3 patch_mask_disposition.py
    python3 patch_mask_disposition.py --dry-run   # preview only

Then run masked annotation:
    python3 annotate_pipeline.py --mask-disposition --domain 1 --limit 200
"""

import re
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime

TARGET = Path("annotate_pipeline.py")
BACKUP = Path(f"annotate_pipeline.py.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

# ── PATCH 1: strip_disposition() function ─────────────────────────────────────
# Insert after RATE_LIMIT constant line

STRIP_FUNCTION = '''
# ─────────────────────────────────────────────────────────────────────────────
# DISPOSITION MASKING (equipoise / blind annotation)
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that signal dispositional outcome — visible in the opinion tail
_DISP_PATTERNS = [
    # Explicit holding phrases
    r"we\\s+(?:therefore\\s+)?affirm(?:ed|s)?\\b",
    r"we\\s+(?:therefore\\s+)?revers(?:e|ed|es)\\b",
    r"we\\s+(?:therefore\\s+)?remand\\b",
    r"judgment\\s+(?:of\\s+the\\s+district\\s+court\\s+)?(?:is\\s+)?affirmed\\b",
    r"judgment\\s+(?:is\\s+)?reversed\\b",
    r"(?:is\\s+)?reversed\\s+and\\s+remanded\\b",
    r"\\bAFFIRMED\\b",
    r"\\bREVERSED\\b",
    r"\\bREMANDED\\b",
    r"(?:petition|appeal)\\s+(?:is\\s+)?(?:granted|denied)\\b",
    r"\\bprotection\\s+(?:granted|denied)\\b",
    # Outcome-signalling conclusion phrases
    r"for\\s+the\\s+(?:foregoing\\s+)?reasons[,.]?\\s+we\\s+(?:affirm|reverse|remand)",
    r"the\\s+(?:district\\s+court['\\u2019]?s?\\s+)?(?:judgment|order)\\s+is",
    r"we\\s+(?:vacate|set\\s+aside|dismiss|grant|deny)",
]

_DISP_RE = re.compile(
    "|".join(_DISP_PATTERNS),
    re.IGNORECASE,
)

# How many chars from the tail to mask
MASK_TAIL_CHARS = 2000

# Replacement text shown to annotator
MASK_PLACEHOLDER = (
    "\\n\\n[DISPOSITION REDACTED — annotate the structural chain from the "
    "opinion reasoning only. Do not infer the outcome from any redacted text.]"
)


def strip_disposition(text: str, tail_chars: int = MASK_TAIL_CHARS) -> tuple[str, bool]:
    """
    Remove dispositional language from opinion text for blind annotation.

    Strategy:
      1. Search the final `tail_chars` of the text for known outcome phrases.
      2. If found, truncate the text at the earliest match in that window
         and append MASK_PLACEHOLDER.
      3. Also remove any all-caps AFFIRMED / REVERSED / REMANDED tokens
         anywhere in the text (they often appear in headers too).
      4. Returns (masked_text, was_masked: bool).

    The function is conservative: it only removes text from the tail,
    leaving the opinion's structural reasoning intact.
    """
    if not text:
        return text, False

    tail_start = max(0, len(text) - tail_chars)
    tail       = text[tail_start:]

    # Find earliest disposition signal in tail
    earliest_match = None
    for m in _DISP_RE.finditer(tail):
        if earliest_match is None or m.start() < earliest_match.start():
            earliest_match = m

    was_masked = False
    if earliest_match:
        # Truncate at the sentence boundary before the match if possible
        cut = tail_start + earliest_match.start()
        # Back up to last sentence end before cut
        preceding = text[:cut]
        last_period = max(
            preceding.rfind(". "),
            preceding.rfind(".\\n"),
            preceding.rfind("\\n\\n"),
        )
        if last_period > 0 and (cut - last_period) < 400:
            cut = last_period + 1
        text = text[:cut] + MASK_PLACEHOLDER
        was_masked = True

    # Secondary pass: remove all-caps outcome tokens anywhere
    # (they appear in headers like "AFFIRMED IN PART, REVERSED IN PART")
    cleaned = re.sub(
        r"\\b(AFFIRMED|REVERSED|REMANDED|VACATED|DISMISSED)\\b(?:[^.\\n]{0,60})?",
        "[REDACTED]",
        text,
    )
    if cleaned != text:
        was_masked = True
        text = cleaned

    return text, was_masked

'''

# ── PATCH 2: masking call inside build_user_prompt ────────────────────────────
# After the truncation block, before building the prompt string

OLD_TRUNCATE = (
    '    if len(text) > OPINION_CHARS:\n'
    '        text = text[:OPINION_CHARS] + "\\n\\n[... opinion truncated for length ...]"'
)

NEW_TRUNCATE = (
    '    if len(text) > OPINION_CHARS:\n'
    '        text = text[:OPINION_CHARS] + "\\n\\n[... opinion truncated for length ...]"\n'
    '\n'
    '    # ── Outcome masking (equipoise / blind annotation) ──────────────────\n'
    '    masked_flag = False\n'
    '    if mask_disposition:\n'
    '        text, masked_flag = strip_disposition(text)\n'
    '        if masked_flag:\n'
    '            log.debug(f"  Masked disposition in {case.get(\'case_name\', \'?\')[:40]}")'
)

# ── PATCH 3: build_user_prompt signature ─────────────────────────────────────
OLD_BUILD_SIG = 'def build_user_prompt(case: dict, domain_id: int) -> str:'
NEW_BUILD_SIG = 'def build_user_prompt(case: dict, domain_id: int, mask_disposition: bool = False) -> str:'

# ── PATCH 4: annotate_domain signature and call-through ──────────────────────
OLD_DOMAIN_SIG = (
    'def annotate_domain(db: AnnotationDB, domain_id: int,\n'
    '                    limit: int = None, dry_run: bool = False):'
)
NEW_DOMAIN_SIG = (
    'def annotate_domain(db: AnnotationDB, domain_id: int,\n'
    '                    limit: int = None, dry_run: bool = False,\n'
    '                    mask_disposition: bool = False):'
)

OLD_BUILD_CALL = '        user_prompt = build_user_prompt(case, domain_id)'
NEW_BUILD_CALL = '        user_prompt = build_user_prompt(case, domain_id, mask_disposition=mask_disposition)'

# ── PATCH 5: argparse --mask-disposition ─────────────────────────────────────
OLD_ARGPARSE_TAIL = (
    '    parser.add_argument("--dry-run", action="store_true",\n'
    '                        help="Show what would be annotated without calling API")'
)
NEW_ARGPARSE_TAIL = (
    '    parser.add_argument("--dry-run", action="store_true",\n'
    '                        help="Show what would be annotated without calling API")\n'
    '    parser.add_argument("--mask-disposition", action="store_true",\n'
    '                        help=(\n'
    '                            "Strip dispositional outcome language from opinion tail "\n'
    '                            "before annotation (blind/equipoise mode). Enables "\n'
    '                            "comparison study: run on a 200-case sample and compare "\n'
    '                            "CD distributions against unmasked annotations. "\n'
    '                            "Masked annotations are logged to masked_annotations.jsonl."\n'
    '                        ))'
)

# ── PATCH 6: pass mask flag into annotate_domain calls in main() ──────────────
OLD_DOMAIN_CALL = '            annotate_domain(db, did, limit=args.limit, dry_run=args.dry_run)'
NEW_DOMAIN_CALL = (
    '            annotate_domain(db, did, limit=args.limit, dry_run=args.dry_run,\n'
    '                            mask_disposition=args.mask_disposition)'
)

# ── ANCHOR for PATCH 1 (insert strip_disposition after RATE_LIMIT line) ───────
RATE_LIMIT_LINE = 'RATE_LIMIT     = 3.0     # seconds between API calls'


def apply_patches(src: str, dry_run: bool = False) -> str:
    changes = []

    def replace(old, new, label):
        nonlocal src
        count = src.count(old)
        if count == 0:
            print(f"  ✗  {label}: not found — skipping")
            return
        if count > 1:
            print(f"  ⚠  {label}: found {count} times — replacing first only")
        src = src.replace(old, new, 1)
        changes.append(label)
        print(f"  ✓  {label}")

    # Patch 1: insert strip_disposition() after RATE_LIMIT constant
    if RATE_LIMIT_LINE in src:
        idx = src.index(RATE_LIMIT_LINE) + len(RATE_LIMIT_LINE)
        src = src[:idx] + STRIP_FUNCTION + src[idx:]
        changes.append("strip_disposition() function")
        print("  ✓  strip_disposition() function")
    else:
        print("  ✗  RATE_LIMIT anchor not found — strip_disposition() not inserted")

    replace(OLD_BUILD_SIG,       NEW_BUILD_SIG,       "build_user_prompt() signature")
    replace(OLD_TRUNCATE,        NEW_TRUNCATE,         "masking call in build_user_prompt()")
    replace(OLD_DOMAIN_SIG,      NEW_DOMAIN_SIG,       "annotate_domain() signature")
    replace(OLD_BUILD_CALL,      NEW_BUILD_CALL,       "build_user_prompt call in annotate_domain()")
    replace(OLD_ARGPARSE_TAIL,   NEW_ARGPARSE_TAIL,    "--mask-disposition argparse entry")
    replace(OLD_DOMAIN_CALL,     NEW_DOMAIN_CALL,      "annotate_domain() call in main()")

    return src, changes


def main():
    parser = argparse.ArgumentParser(description="Patch annotate_pipeline.py with --mask-disposition")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not write")
    parser.add_argument("--target", default=str(TARGET), help="Path to annotate_pipeline.py")
    args = parser.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"Error: {target} not found")
        sys.exit(1)

    src = target.read_text(encoding="utf-8")
    print(f"Patching {target} ({len(src):,} chars)")
    print()

    result, changes = apply_patches(src, dry_run=args.dry_run)

    print(f"\n{len(changes)} patches applied.")

    if args.dry_run:
        print("\nDRY RUN — no files written.")
        return

    # Backup original
    shutil.copy(target, BACKUP)
    print(f"Backup: {BACKUP}")

    # Write patched file
    target.write_text(result, encoding="utf-8")
    print(f"Written: {target}")

    # Syntax check
    import subprocess
    r = subprocess.run(["python3", "-c", f"import ast; ast.parse(open('{target}').read())"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("Syntax check: ✓ OK")
    else:
        print(f"Syntax check: ✗ FAILED\n{r.stderr[:400]}")
        print(f"Restoring backup...")
        shutil.copy(BACKUP, target)
        sys.exit(1)

    print(f"\nUsage:")
    print(f"  # Blind re-annotation sample (200 cases, domain 1):")
    print(f"  python3 annotate_pipeline.py --mask-disposition --domain 1 --limit 200")
    print(f"  # Then compare CD distributions:")
    print(f"  python3 compare_masked_cd.py")


if __name__ == "__main__":
    main()
