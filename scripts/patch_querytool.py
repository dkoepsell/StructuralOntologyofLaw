#!/usr/bin/env python3
"""
patch_querytool.py — Patch SOoL_QueryTool.html in place
=========================================================
Adds Case of the Day banner, fixes ID type bug, updates stale numbers.
Run from ~/CaseLaw/, then FTP the result.

Usage:
    python3 patch_querytool.py
    # Then:
    # curl --retry 3 --user "$TURBIFY_FTP_USER:$TURBIFY_FTP_PASS" \
    #   -T ~/CaseLaw/SOoL_QueryTool.html \
    #   "ftp://$TURBIFY_FTP_HOST/SOoL_QueryTool.html"
"""

import shutil, sys
from pathlib import Path
from datetime import datetime

SRC  = Path.home() / "CaseLaw" / "SOoL_QueryTool.html"
BAK  = Path.home() / "CaseLaw" / f"SOoL_QueryTool.html.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

src = SRC.read_text(encoding="utf-8", errors="replace")
print(f"Input: {SRC} ({len(src):,} chars)")

changes = []
def rep(old, new, label):
    global src
    if old not in src:
        print(f"  SKIP (not found): {label}")
        return
    src = src.replace(old, new, 1)
    changes.append(label)
    print(f"  OK: {label}")

# ── 1. Case of the Day banner ─────────────────────────────────────────────────
HEADER_OLD = '''  <div style="border-bottom:2px solid var(--gold);padding-bottom:.75rem;margin-bottom:1.5rem">
    <div style="font-size:.7rem;letter-spacing:.25em;text-transform:uppercase;color:var(--gold);margin-bottom:.3rem">SOoL Structural Analysis</div>
    <h2 style="font-size:1.5rem;font-weight:600;color:var(--navy);margin:0">Case Analyzer</h2>
    <p style="font-size:.95rem;color:var(--muted);margin:.4rem 0 0">Paste any legal text — opinion, oral argument transcript, brief — and receive a full SOoL structural annotation: MLC node closures, active Contradiction Types, CD score, and outcome prediction.</p>
  </div>'''

HEADER_NEW = '''  <div style="border-bottom:2px solid var(--gold);padding-bottom:.75rem;margin-bottom:1.5rem">
    <div style="font-size:.7rem;letter-spacing:.25em;text-transform:uppercase;color:var(--gold);margin-bottom:.3rem">SOoL Structural Analysis</div>
    <h2 style="font-size:1.5rem;font-weight:600;color:var(--navy);margin:0">Case Analyzer</h2>
    <p style="font-size:.95rem;color:var(--muted);margin:.4rem 0 0">Paste any legal text — opinion, oral argument transcript, brief — and receive a full SOoL structural annotation: MLC node closures, active Contradiction Types, CD score, and outcome prediction.</p>
  </div>

  <!-- ── CASE OF THE DAY ─────────────────────────────────────────────── -->
  <div id="cotd-banner" style="display:none;background:var(--navy2);border:1px solid var(--gold);
       border-radius:var(--r);padding:1rem 1.25rem;margin-bottom:1.25rem">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap">
      <div style="flex:1;min-width:200px">
        <div style="font-size:.65rem;letter-spacing:.22em;text-transform:uppercase;
                    color:var(--gold);margin-bottom:.3rem">&#9878; Case of the Day</div>
        <div id="cotd-name" style="font-size:1rem;font-weight:600;color:var(--gold-light);
                                   line-height:1.35;margin-bottom:.25rem"></div>
        <div id="cotd-meta" style="font-size:.78rem;color:var(--muted)"></div>
        <div id="cotd-preview" style="font-size:.82rem;color:#c8b898;margin-top:.4rem;
                                       line-height:1.55;font-style:italic"></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:.5rem;align-items:flex-end;flex-shrink:0">
        <button id="cotd-load-btn" onclick="cotdLoad()"
          style="font-family:Inconsolata,monospace;font-size:.8rem;padding:.4rem .9rem;
                 background:var(--gold);color:var(--navy2);border:none;
                 border-radius:var(--r);cursor:pointer;font-weight:700;white-space:nowrap">
          Load Today&#39;s Case &#8594;
        </button>
        <a id="cotd-cl-link" href="#" target="_blank"
          style="font-family:Inconsolata,monospace;font-size:.72rem;color:var(--muted);
                 text-decoration:none">View on CourtListener &#8599;</a>
      </div>
    </div>
  </div>
  <div id="cotd-error" style="display:none;font-size:.82rem;color:var(--muted);
       font-style:italic;margin-bottom:1rem"></div>'''

rep(HEADER_OLD, HEADER_NEW, "Case of the Day banner")

# ── 2. Case of the Day JS + onTabAnalyzer override ───────────────────────────
AZSAVEKEY = 'function azSaveKey() {'

COTD_JS = '''// ── CASE OF THE DAY ──────────────────────────────────────────────────────────
var _cotdData = null;

async function cotdInit() {
  try {
    var r = await fetch('case_of_the_day.json?_=' + new Date().toDateString().replace(/ /g,'_'));
    if (!r.ok) throw new Error('not found');
    _cotdData = await r.json();
    var banner = document.getElementById('cotd-banner');
    if (!banner) return;
    document.getElementById('cotd-name').textContent = _cotdData.case_name || 'Unknown';
    var ann = _cotdData.annotation || {};
    document.getElementById('cotd-meta').textContent =
      (_cotdData.court || '') + '  \u00b7  ' + (_cotdData.date || '') +
      '  \u00b7  CD = ' + (ann.contradiction_debt || '\u2014') +
      '  \u00b7  ' + (ann.chain_outcome || '').replace('_',' ');
    document.getElementById('cotd-preview').textContent =
      (_cotdData.opinion_excerpt || '').substring(0, 180) + '\u2026';
    var link = document.getElementById('cotd-cl-link');
    if (_cotdData.cl_url) { link.href = _cotdData.cl_url; link.style.display = 'inline'; }
    else { link.style.display = 'none'; }
    banner.style.display = 'block';
  } catch(e) {
    var err = document.getElementById('cotd-error');
    if (err) { err.textContent = 'No case of the day available yet.'; err.style.display = 'block'; }
  }
}

function cotdLoad() {
  if (!_cotdData) return;
  var ann = _cotdData.annotation || {};
  var nameEl = document.getElementById('az-casename');
  if (nameEl) nameEl.value = _cotdData.case_name || '';
  var textEl = document.getElementById('az-text');
  if (textEl) textEl.value = _cotdData.opinion_excerpt || '';
  if (typeof azRenderResults === 'function') {
    azRenderResults(ann);
    document.getElementById('az-results').style.display = 'block';
    document.getElementById('az-results').scrollIntoView({behavior:'smooth', block:'start'});
  }
  var btn = document.getElementById('cotd-load-btn');
  if (btn) { btn.textContent = '\u2713 Loaded'; btn.style.background = 'var(--green, #1a6438)'; }
}

function onTabAnalyzer(btn) {
  document.querySelectorAll('.tab-panel').forEach(function(p){p.classList.remove('active');});
  document.querySelectorAll('.tab-btn').forEach(function(b){b.classList.remove('active');});
  document.getElementById('tab-analyzer').classList.add('active');
  if (btn) btn.classList.add('active');
  cotdInit();
}

function azSaveKey() {'''

rep(AZSAVEKEY, COTD_JS, "cotdInit/cotdLoad/onTabAnalyzer JS")

# ── 3. ID type fix — onclick ──────────────────────────────────────────────────
rep('onclick="openDetail(${c.id})">',
    "onclick=\"openDetail('${c.id}')\">",
    "onclick ID quote fix")

# ── 4. ID type fix — find() strict equality ───────────────────────────────────
rep('const c = DB.cases.find(x=>x.id===cid);',
    'const c = DB.cases.find(x=>String(x.id)===String(cid));',
    "find() String cast fix")

# ── 5. Stale numbers ──────────────────────────────────────────────────────────
rep('id="pl-auc">0.9985</div>', 'id="pl-auc">0.9848</div>', "pl-auc 0.9985->0.9848")
rep('id="pl-ratio">14.8\u00d7</div>', 'id="pl-ratio">14.0\u00d7</div>', "pl-ratio 14.8->14.0")
rep('>15.5:1</strong>', '>14.0:1</strong>', "footer ratio")
rep('<span id="dash-footer-den">0.263</span>', '<span id="dash-footer-den">0.252</span>', "footer CD")
rep("_corpusStats={avgDenied:0.263,avgGranted:0.017,ratio:'15.5'",
    "_corpusStats={avgDenied:0.252,avgGranted:0.018,ratio:'14.0'", "_corpusStats")
rep('predicting reversal with 99.85% accuracy across this corpus.',
    'predicting reversal with 98.48% accuracy (masked annotation, n=4,934).', "99.85%")
rep('AUC 0.9985</strong> \u2014 CD alone\n          predicts appellate outcome with 99.85% discriminatory accuracy (5-fold CV).',
    'AUC 0.9848</strong> \u2014 CD alone\n          predicts appellate outcome with 98.48% discriminatory accuracy under masked (blind) annotation (n=4,934).', "prose AUC")
rep('the empirical 14.8:1 CD/outcome ratio is a validation',
    'the empirical 14.0:1 CD/outcome ratio is a validation', "weights prose")
rep('data:[0.5518,0.9966,0.9977,0.9920,0.9985]',
    'data:[0.5518,0.9848,0.9977,0.9920,0.9848]', "chart data")
rep('The SOoL CD measure predicts appellate outcomes at AUC = 0.9985 across the full civil corpus.',
    'The SOoL CD measure predicts appellate outcomes at AUC = 0.9848 under masked annotation (n=4,934).', "JS dynamic AUC")
rep('"protection_denied": "DENIED: Claimant\'s right not recognized. Corpus avg CD: 0.263"',
    '"protection_denied": "DENIED: Claimant\'s right not recognized. Corpus avg CD: 0.252 (masked)"', "denied tooltip")
rep('ratio 15.5:1 vs denied.', 'ratio 14.0:1 vs denied.', "granted tooltip")
rep('16.9\u00d7 CD ratio</strong> \u2014 reversed\n          cases carry nearly 17\u00d7 more structural stress than affirmed cases.',
    '14.0\u00d7 CD ratio</strong> \u2014 denied\n          cases carry 14\u00d7 more structural stress than granted cases (masked).',
    "detail panel ratio")
rep('CD (denied) = 0.355; mean CD (granted) = 0.021; CD ratio = 16.9\u00d7. AUC of CD as outcome predictor = 0.9985.',
    'CD (denied) = 0.252; mean CD (granted) = 0.018; CD ratio = 14.0\u00d7. AUC of CD as outcome predictor = 0.9848 (masked).',
    "likelihood panel")
rep('AUC \u2014 Predictive Accuracy', 'AUC \u2014 Structural Consistency (masked, internal)', "AUC label")
rep('>AUC = 0.9966</div>\n      <p style="font-size:1rem;color:var(--muted);margin-top:.3rem;line-height:1.6">Trained on 80% of cases, tested on 20% the model had never seen. The AUC drops by only 0.0019 from the cross-validated result. This is not overfitting.</p>',
    '>AUC = 0.9848</div>\n      <p style="font-size:1rem;color:var(--muted);margin-top:.3rem;line-height:1.6">Masked re-annotation of full corpus (n=4,934, disposition language stripped). AUC under blind annotation \u2014 primary non-circular validation figure. Chain_outcome agreement with unmasked: 96.1%.</p>',
    "holdout card")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{len(changes)} changes applied.")

# Verify key fixes
ok = all([
    'cotdInit' in src,
    'cotd-banner' in src,
    "openDetail('" in src,
    'String(x.id)===String(cid)' in src,
    '0.9985' not in src,
    '14.8\u00d7' not in src,
])
print("All key checks:", "PASS" if ok else "FAIL")
for s in ['0.9985', '14.8\u00d7', '15.5:1', '16.9\u00d7', '99.85%']:
    if s in src:
        print(f"  STILL PRESENT: {s}")

# Write
shutil.copy(SRC, BAK)
SRC.write_text(src, encoding="utf-8")
print(f"\nBackup: {BAK}")
print(f"Written: {SRC} ({len(src):,} chars)")
print("\nNext:")
print('  curl --retry 3 --user "$TURBIFY_FTP_USER:$TURBIFY_FTP_PASS" \\')
print('    -T ~/CaseLaw/SOoL_QueryTool.html \\')
print('    "ftp://$TURBIFY_FTP_HOST/SOoL_QueryTool.html"')
